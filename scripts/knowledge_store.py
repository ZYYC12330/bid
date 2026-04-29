from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = REPO_ROOT / "runtime" / "knowledge_items.json"


def _empty_store() -> list[dict[str, Any]]:
    return []


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item.get("id") or f"kb_{uuid.uuid4().hex}"),
        "name": str(item.get("name") or "未命名资料"),
        "type": str(item.get("type") or item.get("item_type") or "TEXT"),
        "content": str(item.get("content") or ""),
        "image_url": str(item.get("image_url") or ""),
        "file_name": str(item.get("file_name") or ""),
    }


def _read_items() -> list[dict[str, Any]]:
    if not DATA_FILE.exists():
        return _empty_store()

    payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("items", [])
    if not isinstance(payload, list):
        raise ValueError(f"知识库 JSON 格式错误：{DATA_FILE}")
    return [_normalize_item(item) for item in payload if isinstance(item, dict)]


def _write_items(items: list[dict[str, Any]]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    normalized_items = [_normalize_item(item) for item in items]
    temp_path = DATA_FILE.with_name(f"{DATA_FILE.name}.{uuid.uuid4().hex}.tmp")
    temp_path.write_text(
        json.dumps(normalized_items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(DATA_FILE)


def ensure_schema() -> None:
    if not DATA_FILE.exists():
        _write_items(_empty_store())


def list_items() -> list[dict[str, Any]]:
    ensure_schema()
    return _read_items()


def create_item(
    *,
    name: str,
    item_type: str,
    content: str = "",
    image_url: str = "",
    file_name: str = "",
) -> dict[str, Any]:
    items = _read_items()
    item = _normalize_item(
        {
            "id": f"kb_{uuid.uuid4().hex}",
            "name": name,
            "type": item_type,
            "content": content,
            "image_url": image_url,
            "file_name": file_name,
        }
    )
    items.insert(0, item)
    _write_items(items)
    return item


def update_item(
    item_id: str,
    *,
    name: str,
    item_type: str,
    content: str = "",
    image_url: str = "",
    file_name: str = "",
) -> dict[str, Any]:
    items = _read_items()
    for index, item in enumerate(items):
        if item.get("id") == item_id:
            updated = _normalize_item(
                {
                    "id": item_id,
                    "name": name,
                    "type": item_type,
                    "content": content,
                    "image_url": image_url,
                    "file_name": file_name,
                }
            )
            items[index] = updated
            _write_items(items)
            return updated
    raise KeyError(item_id)


def delete_item(item_id: str) -> None:
    items = _read_items()
    remaining = [item for item in items if item.get("id") != item_id]
    if len(remaining) == len(items):
        raise KeyError(item_id)
    _write_items(remaining)
