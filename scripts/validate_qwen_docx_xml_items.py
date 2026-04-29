from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

try:
    from .prepare_qwen_fill_request import get_api_key, load_env_file
except ImportError:
    from prepare_qwen_fill_request import get_api_key, load_env_file


MODEL = "qwen3.6-plus"
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
PROMPT = "找出待填项"


def read_docx_document_xml(docx_path: Path) -> str:
    if not docx_path.exists():
        raise FileNotFoundError(f"找不到 DOCX 文件: {docx_path}")
    if docx_path.suffix.lower() != ".docx":
        raise ValueError(f"仅支持 .docx 文件: {docx_path}")

    try:
        with zipfile.ZipFile(docx_path) as docx_zip:
            return docx_zip.read("word/document.xml").decode("utf-8")
    except KeyError as exc:
        raise RuntimeError(f"DOCX 内缺少 word/document.xml: {docx_path}") from exc
    except zipfile.BadZipFile as exc:
        raise RuntimeError(f"不是有效的 DOCX/ZIP 文件: {docx_path}") from exc


def build_qwen_request(
    docx_xml: str,
    *,
    docx_path: Path,
    model: str = MODEL,
) -> dict[str, Any]:
    user_payload = {
        "prompt": PROMPT,
        "input_file": str(docx_path),
        "docx_xml": docx_xml,
        "output_schema": {
            "items": [
                {
                    "field_name": "待填项名称",
                    "placeholder_text": "原文中的占位文本或字段附近文本",
                    "section": "所在章节或表格",
                    "required": True,
                    "reason": "为什么判定为待填项",
                    "xml_hint": "可定位该待填项的 XML 片段或关键词",
                }
            ]
        },
    }
    return {
        "base_url": BASE_URL,
        "endpoint": "/chat/completions",
        "model": model,
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": "你是 Word 标书模板待填项识别助手。只返回 JSON，不要返回 Markdown 或解释文字。",
            },
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False, indent=2),
            },
        ],
    }


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


def extract_items_json(response_payload: dict[str, Any]) -> dict[str, Any]:
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

    payload = json.loads(cleaned)
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise RuntimeError("Qwen 响应缺少 items 数组。")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def default_output_path(docx_path: Path) -> Path:
    return docx_path.with_suffix(".待填项.json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="把用户输入 DOCX 的 word/document.xml 发给 qwen3.6-plus，提示词为“找出待填项”，输出 JSON。"
    )
    parser.add_argument("docx", type=Path, help="用户输入的 DOCX 文件")
    parser.add_argument("--output", type=Path, help="待填项 JSON 输出路径，默认与 DOCX 同目录")
    parser.add_argument("--request-output", type=Path, help="保存发给 Qwen 的请求包 JSON")
    parser.add_argument("--response-output", type=Path, help="保存 Qwen 原始响应 JSON")
    parser.add_argument("--model", default=MODEL, help=f"模型名，默认 {MODEL}")
    parser.add_argument("--no-call", action="store_true", help="只生成请求包，不调用模型")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    output_path = args.output or default_output_path(args.docx)
    request_output = args.request_output or output_path.with_suffix(".qwen请求包.json")
    response_output = args.response_output or output_path.with_suffix(".qwen响应.json")

    docx_xml = read_docx_document_xml(args.docx)
    request_payload = build_qwen_request(docx_xml, docx_path=args.docx, model=args.model)
    write_json(request_output, request_payload)
    print(f"DOCX XML 字符数: {len(docx_xml)}")
    print(f"Qwen 请求包: {request_output}")
    print(f"model: {args.model}")
    print(f"prompt: {PROMPT}")
    if args.no_call:
        return 0

    load_env_file()
    response_payload = call_qwen_request(request_payload, api_key=get_api_key())
    write_json(response_output, response_payload)
    items_payload = extract_items_json(response_payload)
    write_json(output_path, items_payload)
    print(f"Qwen 原始响应: {response_output}")
    print(f"待填项 JSON: {output_path}")
    print(f"待填项数量: {len(items_payload['items'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
