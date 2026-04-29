from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

try:
    from .extract_bid_template_items import infer_field_type, infer_source_preference
    from .prepare_qwen_fill_request import get_api_key, load_env_file
except ImportError:
    from extract_bid_template_items import infer_field_type, infer_source_preference
    from prepare_qwen_fill_request import get_api_key, load_env_file


MODEL = os.getenv("LLM_MODEL", "qwen-max")
BASE_URL = os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATE_PATH = (
    REPO_ROOT
    / "4.15测试-箱室类"
    / "输出模版"
    / "GKZH-25ZXH856-401.88项目箱室设备采购-招标文件-发布版1128_商务标模版.docx"
)
DEFAULT_OUTPUT_PATH = DEFAULT_TEMPLATE_PATH.with_suffix(".AI待填项清单.json")
MAX_PROMPT_CHARS = 28_000
MAX_BLOCK_TEXT_CHARS = 800
MAX_TABLE_CELL_CHARS = 120


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _element_text(element: ElementTree.Element) -> str:
    values = [
        child.text or ""
        for child in element.iter()
        if _local_name(child.tag) == "t"
    ]
    return " ".join("".join(values).replace("\u3000", " ").split())


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}...(已截断，原长度 {len(value)})"


def _table_rows(element: ElementTree.Element) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in element.iter():
        if _local_name(row.tag) != "tr":
            continue
        cells = [
            _truncate(_element_text(cell), MAX_TABLE_CELL_CHARS)
            for cell in row
            if _local_name(cell.tag) == "tc"
        ]
        if cells:
            rows.append(cells)
    return rows


def read_docx_body_blocks(template_path: Path) -> list[dict[str, Any]]:
    with zipfile.ZipFile(template_path) as docx_zip:
        document_xml = docx_zip.read("word/document.xml")

    root = ElementTree.fromstring(document_xml)
    body = next((child for child in root.iter() if _local_name(child.tag) == "body"), root)
    blocks: list[dict[str, Any]] = []
    paragraph_index = 0
    table_index = 0
    for child in body:
        local_name = _local_name(child.tag)
        if local_name not in {"p", "tbl"}:
            continue

        block: dict[str, Any] = {
            "block_index": len(blocks),
            "block_type": "paragraph" if local_name == "p" else "table",
            "text": _element_text(child),
            "xml": ElementTree.tostring(child, encoding="unicode"),
        }
        if local_name == "p":
            block["paragraph_index"] = paragraph_index
            paragraph_index += 1
        else:
            block["table_index"] = table_index
            block["table_rows"] = _table_rows(child)
            table_index += 1
        blocks.append(block)
    return blocks


def _prompt_block(block: dict[str, Any]) -> dict[str, Any]:
    prompt_block: dict[str, Any] = {
        "block_index": block["block_index"],
        "block_type": block["block_type"],
        "text": _truncate(str(block.get("text") or ""), MAX_BLOCK_TEXT_CHARS),
    }
    if "paragraph_index" in block:
        prompt_block["paragraph_index"] = block["paragraph_index"]
    if "table_index" in block:
        prompt_block["table_index"] = block["table_index"]
    if block.get("table_rows"):
        prompt_block["table_rows"] = block["table_rows"]
    return prompt_block


def _fit_prompt_payload(prompt_payload: dict[str, Any]) -> dict[str, Any]:
    content = json.dumps(prompt_payload, ensure_ascii=False)
    if len(content) <= MAX_PROMPT_CHARS:
        return prompt_payload

    compact_blocks = []
    for block in prompt_payload["blocks"]:
        compact_block = {
            "block_index": block["block_index"],
            "block_type": block["block_type"],
            "text": _truncate(str(block.get("text") or ""), 160),
        }
        if "paragraph_index" in block:
            compact_block["paragraph_index"] = block["paragraph_index"]
        if "table_index" in block:
            compact_block["table_index"] = block["table_index"]
        compact_blocks.append(compact_block)
    compact_payload = {**prompt_payload, "blocks": compact_blocks}
    if len(json.dumps(compact_payload, ensure_ascii=False)) <= MAX_PROMPT_CHARS:
        return compact_payload

    fitted_blocks: list[dict[str, Any]] = []
    for block in compact_blocks:
        trial_payload = {**compact_payload, "blocks": [*fitted_blocks, block]}
        if len(json.dumps(trial_payload, ensure_ascii=False)) > MAX_PROMPT_CHARS:
            break
        fitted_blocks.append(block)
    return {**compact_payload, "blocks": fitted_blocks}


def build_ai_request(
    blocks: list[dict[str, Any]],
    *,
    template_path: Path,
    template_type: str,
) -> dict[str, Any]:
    prompt_payload = {
        "task": "识别商务标/技术标模板中真正需要后续填写的项目，输出待填项 JSON。",
        "template_path": str(template_path),
        "template_type": template_type,
        "rules": [
            "只能由大模型判断哪些位置是待填项目，不要套用固定正则、固定白名单或关键词规则。",
            "结合每个 Word XML block 的文本和 XML 判断，不要把签字、盖章、说明文字、固定条款误识别为待填项。",
            "如果是冒号标签后的待填项，locator.block_type 用 paragraph_colon，并给出 label_text。",
            "如果是段落占位符替换，locator.block_type 用 paragraph_placeholder，并给出 placeholder_text。",
            "如果是下划线空白，locator.block_type 用 paragraph_underlined_blank。",
            "如果是表格空单元格，locator.block_type 用 table_cell，并尽量给出 row_index、cell_index、label_text。",
            "只返回 JSON，不要返回 Markdown。",
        ],
        "output_schema": {
            "items": [
                {
                    "block_index": 0,
                    "field_name": "字段名",
                    "field_type": "text | money | date_or_period | phone | image",
                    "required": True,
                    "placeholder_text": "页面或 XML 中的占位文本",
                    "prompt_hint": "给后续填充的提示",
                    "locator": {
                        "block_type": "paragraph_colon",
                        "label_text": "字段标签",
                    },
                }
            ]
        },
        "blocks": [_prompt_block(block) for block in blocks],
    }
    prompt_payload = _fit_prompt_payload(prompt_payload)
    return {
        "base_url": BASE_URL,
        "endpoint": "/chat/completions",
        "model": MODEL,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": "你是标书模板字段抽取助手。只返回严格 JSON。",
            },
            {
                "role": "user",
                "content": json.dumps(prompt_payload, ensure_ascii=False),
            },
        ],
    }


def call_ai(request_payload: dict[str, Any], *, api_key: str) -> dict[str, Any]:
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
        with urllib.request.urlopen(request, timeout=240) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"AI 抽取请求失败: HTTP {exc.code}: {error_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"AI 抽取请求失败: {exc}") from exc


def extract_json_from_response(response_payload: dict[str, Any]) -> dict[str, Any]:
    content = response_payload["choices"][0]["message"]["content"]
    if not isinstance(content, str):
        raise RuntimeError("AI 响应 message.content 不是字符串。")
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
        raise RuntimeError("AI 响应缺少 items 数组，不能作为待填项清单。")
    return payload


def _safe_source_preference(field_name: str) -> list[str]:
    try:
        return infer_source_preference(field_name)
    except ValueError:
        return ["company_profile_kb"]


def normalize_items_payload(
    ai_payload: dict[str, Any],
    *,
    template_path: Path,
    template_type: str,
    blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    blocks_by_index = {block["block_index"]: block for block in blocks}
    items: list[dict[str, Any]] = []
    for index, item in enumerate(ai_payload.get("items", []), start=1):
        if not isinstance(item, dict):
            continue

        try:
            block_index = int(item.get("block_index"))
        except (TypeError, ValueError):
            continue
        block = blocks_by_index.get(block_index)
        if block is None:
            continue

        field_name = str(item.get("field_name") or "").strip()
        if not field_name:
            continue

        locator = item.get("locator") if isinstance(item.get("locator"), dict) else {}
        locator = dict(locator)
        locator.setdefault("block_type", "ai_xml")
        if block["block_type"] == "paragraph":
            locator.setdefault("paragraph_index", block["paragraph_index"])
        elif block["block_type"] == "table":
            locator.setdefault("table_index", block["table_index"])
        locator["block_index"] = block_index
        locator["xml"] = block["xml"]

        placeholder_text = item.get("placeholder_text")
        if placeholder_text is None:
            placeholder_text = locator.get("placeholder_text") or block.get("text") or None

        items.append(
            {
                "item_id": str(item.get("item_id") or f"{template_type}_{len(items) + 1:03d}"),
                "template_type": str(item.get("template_type") or template_type),
                "section": str(item.get("section") or ""),
                "field_name": field_name,
                "field_type": str(item.get("field_type") or infer_field_type(field_name)),
                "required": bool(item.get("required", True)),
                "placeholder_text": placeholder_text,
                "prompt_hint": str(item.get("prompt_hint") or f"填写字段：{field_name}"),
                "source_preference": item.get("source_preference") or _safe_source_preference(field_name),
                "locator": locator,
            }
        )

    return {
        "template_path": str(template_path),
        "template_type": template_type,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "items": items,
        "answer_schema": {
            "answers": [
                {
                    "item_id": "business_001",
                    "value": "待填值",
                    "status": "filled | missing | needs_review",
                    "confidence": 0.0,
                    "evidence": [{"source": "文件名", "quote": "证据原文"}],
                }
            ]
        },
    }


def extract_template_items_ai(
    template_path: Path,
    *,
    template_type: str = "business",
    dry_run_request: bool = False,
) -> dict[str, Any]:
    blocks = read_docx_body_blocks(template_path)
    request_payload = build_ai_request(
        blocks,
        template_path=template_path,
        template_type=template_type,
    )
    if dry_run_request:
        return {
            "template_path": str(template_path),
            "template_type": template_type,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "items": [],
            "request": request_payload,
        }

    load_env_file()
    response_payload = call_ai(request_payload, api_key=get_api_key())
    ai_items_payload = extract_json_from_response(response_payload)
    return normalize_items_payload(
        ai_items_payload,
        template_path=template_path,
        template_type=template_type,
        blocks=blocks,
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="调用大模型从商务标/技术标模版 Word XML 中提取待填项清单 JSON。")
    parser.add_argument("template_path", nargs="?", type=Path, default=DEFAULT_TEMPLATE_PATH)
    parser.add_argument("--template-type", default="business", choices=("business", "technical", "price"))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--dry-run-request", action="store_true", help="只生成请求包，不调用模型")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    payload = extract_template_items_ai(
        args.template_path,
        template_type=args.template_type,
        dry_run_request=args.dry_run_request,
    )
    _write_json(args.output, payload)
    print(f"待填项数量: {len(payload.get('items', []))}")
    print(f"待填项清单: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
