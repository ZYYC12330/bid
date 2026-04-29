from __future__ import annotations

import http.client
import json
import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen


def _extract_upload_url(payload: Any) -> str | None:
    if isinstance(payload, str):
        if payload.startswith("http://") or payload.startswith("https://"):
            return payload
        return None
    if isinstance(payload, list):
        for item in payload:
            url = _extract_upload_url(item)
            if url:
                return url
        return None
    if isinstance(payload, dict):
        for key in ("url", "file_url", "fileUrl", "download_url", "downloadUrl"):
            value = payload.get(key)
            if isinstance(value, str) and (value.startswith("http://") or value.startswith("https://")):
                return value
        for value in payload.values():
            url = _extract_upload_url(value)
            if url:
                return url
    return None


def _extract_file_id(payload: Any) -> str | None:
    if isinstance(payload, dict):
        value = payload.get("fileId")
        if isinstance(value, str) and value:
            return value
        for child in payload.values():
            child_id = _extract_file_id(child)
            if child_id:
                return child_id
    if isinstance(payload, list):
        for item in payload:
            item_id = _extract_file_id(item)
            if item_id:
                return item_id
    return None


def upload_docx_to_platform(file_path: Path, upload_base_url: str, platform_key: str) -> str:
    parsed = urlparse(upload_base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("upload_base_url 必须是合法的 http/https URL。")

    filename = file_path.name
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    boundary = "----BidTemplateBoundary7MA4YWxkTrZu0gW"

    chunks: list[bytes] = []
    chunks.append(f"--{boundary}\r\n".encode("utf-8"))
    chunks.append(
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode("utf-8")
    )
    chunks.append(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
    chunks.append(file_path.read_bytes())
    chunks.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    payload = b"".join(chunks)

    conn: http.client.HTTPConnection | http.client.HTTPSConnection
    if parsed.scheme == "https":
        conn = http.client.HTTPSConnection(parsed.netloc)
    else:
        conn = http.client.HTTPConnection(parsed.netloc)
    headers = {
        "Authorization": f"Bearer {platform_key}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(payload)),
    }
    try:
        conn.request("POST", "/api/file", payload, headers)
        response = conn.getresponse()
        body = response.read().decode("utf-8", errors="replace")
    finally:
        conn.close()

    if response.status >= 400:
        raise RuntimeError(f"上传文件失败({response.status})：{body}")

    try:
        payload_obj = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"上传接口返回非 JSON：{body}") from exc

    file_url = _extract_upload_url(payload_obj)
    if not file_url:
        file_id = _extract_file_id(payload_obj)
        if file_id:
            file_url = f"{parsed.scheme}://{parsed.netloc}/api/file/{file_id}"
    if not file_url:
        raise RuntimeError(f"上传接口返回中未找到文件 URL：{body}")
    return file_url


def download_file(template_url: str, target_path: Path) -> None:
    parsed = urlparse(template_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("template_url 必须是合法的 http/https URL。")
    try:
        with urlopen(template_url) as response:
            content = response.read()
    except Exception as exc:
        raise RuntimeError(f"下载模板失败：{exc}") from exc
    if not content:
        raise RuntimeError("下载模板失败：文件内容为空。")
    target_path.write_bytes(content)
