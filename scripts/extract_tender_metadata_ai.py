from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

try:
    from .prepare_qwen_fill_request import get_api_key, load_env_file
except ImportError:
    from prepare_qwen_fill_request import get_api_key, load_env_file


MODEL = os.getenv("LLM_MODEL", "qwen3.6-plus")
BASE_URL = os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
MAX_CONTEXT_CHARS = 18_000
MAX_FALLBACK_BLOCKS = 120


def _should_bypass_proxy(base_url: str) -> bool:
    if os.getenv("LLM_USE_PROXY", "").strip().lower() in {"1", "true", "yes", "on"}:
        return False
    host = urllib.parse.urlparse(base_url).hostname or ""
    return host.endswith("dashscope.aliyuncs.com")


def _open_request(request: urllib.request.Request, *, timeout: int, base_url: str):
    if _should_bypass_proxy(base_url):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open(request, timeout=timeout)
    return urllib.request.urlopen(request, timeout=timeout)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _normalize_text(value: str) -> str:
    return " ".join(value.replace("\u3000", " ").split())


def _read_document_root(docx_path: Path) -> ElementTree.Element:
    if not docx_path.exists():
        raise FileNotFoundError(f"找不到 DOCX 文件: {docx_path}")
    if docx_path.suffix.lower() != ".docx":
        raise ValueError(f"仅支持 .docx 文件: {docx_path}")
    try:
        with zipfile.ZipFile(docx_path) as docx_zip:
            document_xml = docx_zip.read("word/document.xml")
    except KeyError as exc:
        raise RuntimeError(f"DOCX 内缺少 word/document.xml: {docx_path}") from exc
    except zipfile.BadZipFile as exc:
        raise RuntimeError(f"不是有效的 DOCX/ZIP 文件: {docx_path}") from exc
    return ElementTree.fromstring(document_xml)


def _append_text_by_page(element: ElementTree.Element, pages: list[list[str]], page_index: int) -> int:
    local_name = _local_name(element.tag)
    if local_name in {"br", "lastRenderedPageBreak"}:
        if local_name == "lastRenderedPageBreak" or element.attrib.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}type") == "page":
            page_index += 1
            while len(pages) <= page_index:
                pages.append([])
        return page_index
    if local_name == "t" and element.text:
        text = _normalize_text(element.text)
        if text:
            pages[page_index].append(text)
    for child in element:
        page_index = _append_text_by_page(child, pages, page_index)
    return page_index


def _block_text(element: ElementTree.Element) -> str:
    texts = [
        child.text or ""
        for child in element.iter()
        if _local_name(child.tag) == "t"
    ]
    return _normalize_text("".join(texts))


def read_first_page_text(docx_path: Path) -> str:
    root = _read_document_root(docx_path)
    body = next((child for child in root.iter() if _local_name(child.tag) == "body"), root)
    pages: list[list[str]] = [[]]
    page_index = 0
    for child in body:
        if _local_name(child.tag) not in {"p", "tbl"}:
            continue
        page_index = _append_text_by_page(child, pages, page_index)
        if page_index >= 1:
            break

    text = " ".join(pages[0]).strip()
    if text:
        return text[:MAX_CONTEXT_CHARS]

    fallback_blocks: list[str] = []
    for child in body:
        if _local_name(child.tag) not in {"p", "tbl"}:
            continue
        text = _block_text(child)
        if text:
            fallback_blocks.append(text)
        if len(fallback_blocks) >= MAX_FALLBACK_BLOCKS:
            break
    return "\n".join(fallback_blocks)[:MAX_CONTEXT_CHARS]


def build_qwen_request(first_page_text: str, *, docx_path: Path) -> dict[str, Any]:
    user_payload = {
        "task": "从招标文件第一页提取项目元信息。",
        "input_file": str(docx_path),
        "rules": [
            "只提取招标编号和项目名称两项。",
            "招标编号可能写作招标编号、项目编号、采购编号等，保留原文完整编号。",
            "项目名称只填写项目名称本身，不要带“项目名称：”前缀。",
            "如果无法确认，字段值返回空字符串，并在 evidence 说明原因。",
            "只返回 JSON，不要返回 Markdown。",
        ],
        "output_schema": {
            "bid_number": "招标编号",
            "project_name": "项目名称",
            "confidence": 0.0,
            "evidence": [
                {"field": "招标编号", "quote": "原文证据", "page_hint": "第一页"}
            ],
        },
        "first_page_text": first_page_text,
    }
    return {
        "base_url": BASE_URL,
        "endpoint": "/chat/completions",
        "model": MODEL,
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": "你是招标文件项目信息抽取助手。只返回严格 JSON。",
            },
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False),
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
        with _open_request(request, timeout=180, base_url=base_url) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"项目元信息 AI 请求失败: HTTP {exc.code}: {error_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"项目元信息 AI 请求失败: {exc}") from exc


def _content_json_from_response(response_payload: dict[str, Any]) -> dict[str, Any]:
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
    if not isinstance(payload, dict):
        raise RuntimeError("Qwen 响应不是 JSON 对象。")
    return payload


def normalize_project_info(ai_payload: dict[str, Any]) -> dict[str, Any]:
    source = ai_payload.get("project_info") if isinstance(ai_payload.get("project_info"), dict) else ai_payload
    evidence = source.get("evidence") if isinstance(source.get("evidence"), list) else []
    try:
        confidence = float(source.get("confidence", 0) or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "bid_number": str(source.get("bid_number") or source.get("招标编号") or "").strip(),
        "project_name": str(source.get("project_name") or source.get("项目名称") or "").strip(),
        "confidence": max(0.0, min(1.0, confidence)),
        "evidence": evidence,
    }


def extract_tender_metadata(docx_path: Path) -> dict[str, Any]:
    first_page_text = read_first_page_text(docx_path)
    request_payload = build_qwen_request(first_page_text, docx_path=docx_path)
    load_env_file()
    response_payload = call_qwen_request(request_payload, api_key=get_api_key())
    ai_payload = _content_json_from_response(response_payload)
    return {
        "input_path": str(docx_path),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "first_page_text": first_page_text,
        "project_info": normalize_project_info(ai_payload),
        "request": request_payload,
        "raw_response": response_payload,
    }
