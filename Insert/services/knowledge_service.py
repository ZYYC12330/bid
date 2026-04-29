"""知识库服务模块"""
import json
import os
import uuid
from typing import Optional

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "knowledge.json")


def _ensure_data_file():
    """确保数据文件存在"""
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)


def get_all_knowledge() -> list[dict]:
    """获取所有知识条目"""
    _ensure_data_file()
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def get_knowledge_by_id(knowledge_id: str) -> Optional[dict]:
    """根据ID获取知识条目"""
    items = get_all_knowledge()
    for item in items:
        if item["id"] == knowledge_id:
            return item
    return None


def add_knowledge(field_name: str, content: str, description: str = "") -> dict:
    """添加新的知识条目"""
    items = get_all_knowledge()
    new_item = {
        "id": str(uuid.uuid4()),
        "field_name": field_name,
        "content": content,
        "description": description
    }
    items.append(new_item)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    return new_item


def update_knowledge(knowledge_id: str, field_name: str, content: str, description: str = "") -> Optional[dict]:
    """更新知识条目"""
    items = get_all_knowledge()
    for i, item in enumerate(items):
        if item["id"] == knowledge_id:
            items[i] = {
                "id": knowledge_id,
                "field_name": field_name,
                "content": content,
                "description": description
            }
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
            return items[i]
    return None


def delete_knowledge(knowledge_id: str) -> bool:
    """删除知识条目"""
    items = get_all_knowledge()
    original_len = len(items)
    items = [item for item in items if item["id"] != knowledge_id]
    if len(items) < original_len:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        return True
    return False


def search_knowledge(query: str) -> list[dict]:
    """搜索知识条目"""
    items = get_all_knowledge()
    query_lower = query.lower()
    results = []
    for item in items:
        if (query_lower in item["field_name"].lower() or 
            query_lower in item["content"].lower() or
            query_lower in item.get("description", "").lower()):
            results.append(item)
    return results
