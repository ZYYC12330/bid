from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


MODEL = os.getenv("LLM_MODEL", "qwen3.6-flash")
BASE_URL = os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATE_ITEMS_PATH = (
    REPO_ROOT
    / "4.15测试-箱室类"
    / "输出模版"
    / "GKZH-25ZXH856-401.88项目箱室设备采购-招标文件-发布版1128_商务标模版.待填项清单.json"
)
DEFAULT_OUTPUT_PATH = DEFAULT_TEMPLATE_ITEMS_PATH.with_name(
    DEFAULT_TEMPLATE_ITEMS_PATH.name.replace(".待填项清单.json", ".qwen请求包.json")
)
DEFAULT_ANSWERS_OUTPUT_PATH = DEFAULT_TEMPLATE_ITEMS_PATH.with_name(
    DEFAULT_TEMPLATE_ITEMS_PATH.name.replace(".待填项清单.json", ".AI填充结果.json")
)


def load_optional_json(path: Path | None) -> Any:
    if path is None:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_env_file(path: Path = REPO_ROOT / ".env", *, env: dict[str, str] | None = None) -> None:
    target_env = env if env is not None else os.environ
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in target_env:
            target_env[key] = value


def get_api_key(*, env: dict[str, str] | None = None) -> str:
    target_env = env if env is not None else os.environ
    api_key = target_env.get("LLM_API_KEY") or target_env.get("DASHSCOPE_API_KEY") or target_env.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("缺少 LLM_API_KEY、DASHSCOPE_API_KEY 或 OPENAI_API_KEY，无法调用模型。")
    return api_key


def build_user_payload(
    items_payload: dict[str, Any],
    *,
    bidder_profile_path: Path | None = None,
    credential_index_path: Path | None = None,
    tender_requirements_path: Path | None = None,
    quotation_path: Path | None = None,
    writing_rules_path: Path | None = None,
) -> dict[str, Any]:
    return {
        "task": "根据待填项清单逐项生成商务标填充值，必须保留 item_id。",
        "template_items": items_payload.get("items", []),
        "bidder_profile": load_optional_json(bidder_profile_path),
        "credential_index": load_optional_json(credential_index_path),
        "tender_requirements": load_optional_json(tender_requirements_path),
        "quotation": load_optional_json(quotation_path),
        "writing_rules": load_optional_json(writing_rules_path)
        or {
            "no_fabrication": "没有来源证据的字段不要编造，status 返回 missing 或 needs_review。",
            "evidence_required": "每个 filled 字段必须给出 evidence.source 和 evidence.quote。",
            "bid_deadline_date_rule": (
                "所有带 fill_rule.type=tender_bid_deadline 的字段，都必须从 tender_requirements "
                "里的投标截止时间取值。component=year 只填年份数字，component=month 只填月份数字，"
                "component=day 只填日期数字，component=full_date 填完整投标截止日期/时间。"
                "找不到投标截止时间时返回 needs_review，不要使用当前日期或自行编造。"
            ),
            "output_only_json": "只返回 JSON，不要返回 Markdown、解释文字或代码块。",
        },
        "output_schema": {
            "answers": [
                {
                    "item_id": "business_001",
                    "value": "填充值",
                    "status": "filled | missing | needs_review",
                    "confidence": 0.0,
                    "evidence": [{"source": "来源文件", "quote": "证据原文"}],
                    "note": "缺失或需人工确认时说明原因",
                }
            ]
        },
    }


def build_qwen_request(
    items_payload: dict[str, Any],
    *,
    bidder_profile_path: Path | None = None,
    credential_index_path: Path | None = None,
    tender_requirements_path: Path | None = None,
    quotation_path: Path | None = None,
    writing_rules_path: Path | None = None,
) -> dict[str, Any]:
    user_payload = build_user_payload(
        items_payload,
        bidder_profile_path=bidder_profile_path,
        credential_index_path=credential_index_path,
        tender_requirements_path=tender_requirements_path,
        quotation_path=quotation_path,
        writing_rules_path=writing_rules_path,
    )
    return {
        "base_url": BASE_URL,
        "endpoint": "/chat/completions",
        "model": MODEL,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是商务标填充助手。只返回 JSON。"
                    "必须按输入的 template_items 逐项输出 answers，不能新增、删除或改写 item_id。"
                    "没有证据时不要编造，返回 missing 或 needs_review。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False, indent=2),
            },
        ],
    }


def extract_answers_from_response(response_payload: dict[str, Any]) -> dict[str, Any]:
    content = response_payload["choices"][0]["message"]["content"]
    if not isinstance(content, str):
        raise RuntimeError("Qwen 响应 message.content 不是字符串。")

    cleaned = content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    answers = json.loads(cleaned)
    if not isinstance(answers, dict) or not isinstance(answers.get("answers"), list):
        raise RuntimeError("Qwen 响应缺少 answers 数组，不能用于回填。")
    return answers


def call_qwen_request(request_payload: dict[str, Any], *, api_key: str) -> dict[str, Any]:
    base_url = str(request_payload.get("base_url") or BASE_URL).rstrip("/")
    endpoint = str(request_payload.get("endpoint") or "/chat/completions")
    body = {
        key: value
        for key, value in request_payload.items()
        if key not in {"base_url", "endpoint"}
    }
    request = urllib.request.Request(
        f"{base_url}{endpoint}",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Qwen 请求失败: HTTP {exc.code}: {error_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Qwen 请求失败: {exc}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="生成发给 qwen3.6-plus 的 OpenAI 兼容请求包 JSON。"
    )
    parser.add_argument("items", nargs="?", type=Path, default=DEFAULT_TEMPLATE_ITEMS_PATH)
    parser.add_argument("--bidder-profile", type=Path)
    parser.add_argument("--credential-index", type=Path)
    parser.add_argument("--tender-requirements", type=Path)
    parser.add_argument("--quotation", type=Path)
    parser.add_argument("--writing-rules", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="保存 OpenAI 兼容请求包 JSON")
    parser.add_argument(
        "--answers-output",
        type=Path,
        default=DEFAULT_ANSWERS_OUTPUT_PATH,
        help="保存 Qwen 返回的 AI 填充结果 JSON",
    )
    parser.add_argument("--no-call", action="store_true", help="只生成请求包，不调用 Qwen")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    load_env_file()
    items_payload = json.loads(args.items.read_text(encoding="utf-8"))
    request = build_qwen_request(
        items_payload,
        bidder_profile_path=args.bidder_profile,
        credential_index_path=args.credential_index,
        tender_requirements_path=args.tender_requirements,
        quotation_path=args.quotation,
        writing_rules_path=args.writing_rules,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Qwen 请求包: {args.output}")
    print(f"base_url: {BASE_URL}")
    print(f"model: {MODEL}")
    if args.no_call:
        return 0

    response_payload = call_qwen_request(request, api_key=get_api_key())
    answers = extract_answers_from_response(response_payload)
    args.answers_output.parent.mkdir(parents=True, exist_ok=True)
    args.answers_output.write_text(json.dumps(answers, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"AI 填充结果: {args.answers_output}")
    print(f"填充项数量: {len(answers['answers'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
