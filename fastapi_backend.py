from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles

REPO_ROOT = Path(__file__).resolve().parent
SCRIPT_DIR = REPO_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from scripts.extract_bid_template_items import extract_template_items
from scripts.extract_bid_template_items_ai import (
    extract_template_items_ai,
)
from scripts.extract_tender_metadata_ai import extract_tender_metadata
from scripts.fill_bid_template import fill_template
from scripts.generate_bid_templates import (
    DEFAULT_PLATFORM_KEY,
    DEFAULT_UPLOAD_BASE_URL,
    generate_template_links,
)
from scripts import knowledge_store
from scripts.platform_file_client import download_file, upload_docx_to_platform


TemplateType = Literal["business", "technical", "price"]


app = FastAPI(title="标书生成后端", version="2.0.0")
RUNTIME_ROOT = REPO_ROOT / "runtime" / "fastapi_jobs"
KNOWLEDGE_IMAGE_DIR = REPO_ROOT / "runtime" / "knowledge_images"
logger = logging.getLogger("bid_fill")


def _to_path(value: Optional[str]) -> Optional[Path]:
    if not value or value.strip() == "string":
        return None
    return Path(value).expanduser().resolve()


def _required_path(value: Optional[str], field_name: str) -> Path:
    path = _to_path(value)
    if path is None:
        raise HTTPException(status_code=400, detail=f"{field_name} 不能为空。")
    return path


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _fill_log(
    logs: list[dict[str, Any]],
    job_id: str,
    step: str,
    message: str,
    start_time: float,
    **extra: Any,
) -> None:
    entry: dict[str, Any] = {
        "step": step,
        "message": message,
        "elapsed_ms": round((time.perf_counter() - start_time) * 1000),
    }
    entry.update({key: value for key, value in extra.items() if value is not None})
    logs.append(entry)
    logger.info("[fill:%s] %s - %s %s", job_id, step, message, json.dumps(extra, ensure_ascii=False))


def _new_job_dir(prefix: str) -> Path:
    path = RUNTIME_ROOT / f"{prefix}_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    return path


async def _save_uploaded_docx(file: UploadFile, target_dir: Path, fallback_name: str) -> Path:
    filename = Path(file.filename or fallback_name).name
    if not filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="仅支持上传 .docx 文件。")
    target_path = target_dir / filename
    target_path.write_bytes(await file.read())
    return target_path


def _default_rule_output_path(template_path: Path) -> Path:
    return template_path.with_suffix(".待填项清单.json")


def _default_ai_output_paths(template_path: Path) -> dict[str, Path]:
    return {
        "output": template_path.with_suffix(".AI待填项清单.json"),
        "request": template_path.with_suffix(".AI抽取请求.json"),
        "response": template_path.with_suffix(".AI抽取响应.json"),
    }


def _default_metadata_output_paths(input_path: Path) -> dict[str, Path]:
    return {
        "output": input_path.with_suffix(".元信息.json"),
        "request": input_path.with_suffix(".元信息请求.json"),
        "response": input_path.with_suffix(".元信息响应.json"),
    }


def _default_filled_output_path(template_path: Path) -> Path:
    return template_path.parent / f"{template_path.stem}_已填充.docx"


def _get_platform_key() -> str:
    platform_key = os.getenv("PLATFORM_KEY") or os.getenv("PLATFORM_API_KEY") or DEFAULT_PLATFORM_KEY
    if not platform_key:
        raise RuntimeError("缺少 PLATFORM_KEY 或 PLATFORM_API_KEY，无法上传到平台。")
    return platform_key


def _knowledge_payload(payload: dict[str, Any]) -> dict[str, str]:
    name = str(payload.get("name") or "").strip()
    item_type = str(payload.get("type") or payload.get("item_type") or "TEXT").strip() or "TEXT"
    content = str(payload.get("content") or "").strip()
    image_url = str(payload.get("image_url") or payload.get("imageUrl") or "").strip()
    file_name = str(payload.get("file_name") or payload.get("fileName") or "").strip()
    if not name and not content and not image_url:
        raise HTTPException(status_code=400, detail="知识库条目名称、内容或图片 URL 至少填写一个。")
    if not name:
        name = "未命名资料"
    return {
        "name": name,
        "item_type": item_type,
        "content": content,
        "image_url": image_url,
        "file_name": file_name,
    }


def _copy_item_payload(item_payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(item_payload, ensure_ascii=False))


def _filtered_item_payload(
    item_payload: dict[str, Any],
    selected_item_ids: Optional[list[str]],
) -> dict[str, Any]:
    if not selected_item_ids:
        return _copy_item_payload(item_payload)
    selected = {str(item_id) for item_id in selected_item_ids}
    payload = _copy_item_payload(item_payload)
    payload["items"] = [
        item
        for item in payload.get("items", [])
        if str(item.get("item_id") or "") in selected
    ]
    return payload


FIELD_NAME_SUFFIXES = ("名称", "号码", "编号", "编码", "代码")
IMAGE_FRONT_MARKERS = ("正面", "前面", "首页", "人像面", "front")
IMAGE_BACK_MARKERS = ("反面", "背面", "背页", "国徽", "签发机关", "有效期限", "back")


def _normalize_field_name(name: str) -> str:
    return str(name or "").replace("：", "").replace(":", "").replace(" ", "").strip()


def _canonical_field_name(name: str) -> str:
    normalized = _normalize_field_name(name)
    changed = True
    while changed:
        changed = False
        for suffix in FIELD_NAME_SUFFIXES:
            if len(normalized) > len(suffix) + 1 and normalized.endswith(suffix):
                normalized = normalized[: -len(suffix)]
                changed = True
                break
    if len(normalized) <= 4 and normalized.endswith("号"):
        normalized = normalized[:-1]
    return normalized


def _field_names_match(left: str, right: str) -> bool:
    left_normalized = _normalize_field_name(left)
    right_normalized = _normalize_field_name(right)
    if not left_normalized or not right_normalized:
        return False
    if left_normalized == right_normalized:
        return True
    left_canonical = _canonical_field_name(left_normalized)
    right_canonical = _canonical_field_name(right_normalized)
    if left_canonical and left_canonical == right_canonical:
        return True
    return SequenceMatcher(None, left_normalized, right_normalized).ratio() >= 0.92


def _image_side_from_name(name: str) -> str | None:
    normalized = _normalize_field_name(name).lower()
    if any(marker.lower() in normalized for marker in IMAGE_BACK_MARKERS):
        return "back"
    if any(marker.lower() in normalized for marker in IMAGE_FRONT_MARKERS):
        return "front"
    return None


def _image_side_from_item(item: dict[str, Any]) -> str | None:
    side = _image_side_from_name(str(item.get("field_name") or ""))
    if side is not None:
        return side

    locator = item.get("locator") or {}
    if locator.get("block_type") != "image_placeholder":
        return None
    try:
        shape_index = int(locator.get("shape_index"))
    except (TypeError, ValueError):
        return None
    if shape_index == 0:
        return "front"
    if shape_index == 1:
        return "back"
    return None


def _field_name_without_image_side(name: str) -> str:
    normalized = _normalize_field_name(name)
    for marker in (*IMAGE_FRONT_MARKERS, *IMAGE_BACK_MARKERS):
        normalized = normalized.replace(marker, "")
    return normalized


def _image_side_key_matches(key: str, item: dict[str, Any]) -> bool:
    item_side = _image_side_from_item(item)
    key_side = _image_side_from_name(key)
    if item_side is None or key_side != item_side:
        return False
    key_base = _field_name_without_image_side(key)
    item_base = _field_name_without_image_side(str(item.get("field_name") or ""))
    return _field_names_match(key_base, item_base)


def _value_from_user_inputs(
    user_inputs: Any,
    item: dict[str, Any],
) -> tuple[bool, Any]:
    item_id = str(item.get("item_id") or "")
    field_name = str(item.get("field_name") or "")
    normalized_field_name = _normalize_field_name(field_name)

    if isinstance(user_inputs, dict):
        for key in (item_id, field_name, normalized_field_name):
            if key and key in user_inputs:
                return True, user_inputs[key]
        if str(item.get("field_type") or "").lower() == "image":
            for key, value in user_inputs.items():
                if _image_side_key_matches(str(key), item):
                    return True, value
        for key, value in user_inputs.items():
            if _field_names_match(str(key), field_name):
                return True, value
        return False, None

    if isinstance(user_inputs, list):
        for entry in user_inputs:
            if not isinstance(entry, dict):
                continue
            entry_id = str(entry.get("item_id") or entry.get("id") or "")
            entry_name = str(entry.get("field_name") or entry.get("fieldName") or entry.get("name") or "")
            if entry_id == item_id or _field_names_match(entry_name, field_name):
                for value_key in ("value", "manual_value", "manualValue", "content"):
                    if value_key in entry:
                        return True, entry[value_key]
        return False, None

    return False, None


def _answers_from_user_inputs(
    item_payload: dict[str, Any],
    user_inputs: Any,
) -> dict[str, list[dict[str, Any]]]:
    if isinstance(user_inputs, dict) and isinstance(user_inputs.get("answers"), list):
        user_inputs = user_inputs["answers"]

    answers: list[dict[str, Any]] = []
    for item in item_payload.get("items", []):
        item_id = item.get("item_id")
        if not item_id:
            continue
        has_value, value = _value_from_user_inputs(user_inputs, item)
        answers.append(
            {
                "item_id": item_id,
                "status": "filled" if has_value and str(value or "").strip() else "manual_confirm",
                "value": "" if value is None else value,
            }
        )
    return {"answers": answers}


def _template_path_for_fill(payload: dict[str, Any], job_dir: Path) -> Path:
    template_url = payload.get("template_url")
    if template_url:
        template_path = job_dir / "template.docx"
        download_file(str(template_url), template_path)
        return template_path

    template_path = _to_path(payload.get("template_path"))
    if template_path is None:
        items_template_path = payload.get("items_json", {}).get("template_path")
        template_path = _to_path(items_template_path)
    if template_path is None:
        raise HTTPException(status_code=400, detail="template_url、template_path 或 items_json.template_path 必须提供一个。")
    if not template_path.exists():
        raise HTTPException(status_code=400, detail=f"模版文件不存在：{template_path}")
    return template_path


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/health")
def api_health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/knowledge-items")
def list_knowledge_items_route() -> dict[str, Any]:
    try:
        return {"success": True, "items": knowledge_store.list_items()}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"读取知识库失败: {exc}") from exc


@app.post("/api/knowledge-items")
def create_knowledge_item_route(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        item = knowledge_store.create_item(**_knowledge_payload(payload))
        return {"success": True, "item": item}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"保存知识库失败: {exc}") from exc


@app.put("/api/knowledge-items/{item_id}")
def update_knowledge_item_route(item_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        item = knowledge_store.update_item(item_id, **_knowledge_payload(payload))
        return {"success": True, "item": item}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="知识库条目不存在。") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"更新知识库失败: {exc}") from exc


@app.delete("/api/knowledge-items/{item_id}")
def delete_knowledge_item_route(item_id: str) -> dict[str, Any]:
    try:
        knowledge_store.delete_item(item_id)
        return {"success": True}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="知识库条目不存在。") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"删除知识库失败: {exc}") from exc


@app.post("/api/knowledge-images")
async def upload_knowledge_image_route(file: UploadFile = File(...)) -> dict[str, Any]:
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="请选择图片文件。")
    KNOWLEDGE_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}:
        suffix = ".png"
    target_path = KNOWLEDGE_IMAGE_DIR / f"{uuid.uuid4().hex}{suffix}"
    target_path.write_bytes(await file.read())
    return {
        "success": True,
        "image_url": f"/knowledge-images/{target_path.name}",
        "file_name": Path(file.filename or target_path.name).name,
    }


@app.post("/api/generate-templates")
async def generate_templates_route(
    file: UploadFile = File(...),
    verbose: bool = Form(False),
) -> dict[str, Any]:
    try:
        job_dir = _new_job_dir("generate")
        input_path = await _save_uploaded_docx(file, job_dir, "tender.docx")
        links = generate_template_links(
            input_path=input_path,
            output_dir=None,
            verbose=verbose,
        )
        return {
            "success": True,
            "job_id": job_dir.name,
            "input_path": str(input_path),
            **links,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/extract-tender-metadata")
async def extract_tender_metadata_route(
    file: UploadFile = File(...),
) -> dict[str, Any]:
    try:
        job_dir = _new_job_dir("metadata")
        input_path = await _save_uploaded_docx(file, job_dir, "tender.docx")
        defaults = _default_metadata_output_paths(input_path)
        payload = extract_tender_metadata(input_path)
        _write_json(defaults["request"], payload.get("request", {}))
        _write_json(defaults["response"], payload.get("raw_response", {}))
        output_payload = {
            key: value
            for key, value in payload.items()
            if key not in {"request", "raw_response"}
        }
        _write_json(defaults["output"], output_payload)
        return {
            "success": True,
            "job_id": job_dir.name,
            "input_path": str(input_path),
            "project_info": output_payload.get("project_info", {}),
            "output_path": str(defaults["output"]),
            "request_output_path": str(defaults["request"]),
            "response_output_path": str(defaults["response"]),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/extract-items")
async def extract_items_route(
    template_url: str = Form(...),
    template_type: TemplateType = Form("business"),
    output_path: Optional[str] = Form(None),
) -> dict[str, Any]:
    try:
        job_dir = _new_job_dir("extract")
        template_path = job_dir / "template.docx"
        download_file(template_url, template_path)
        resolved_output_path = _to_path(output_path) or _default_rule_output_path(template_path)
        payload = extract_template_items(template_path, template_type=template_type)
        _write_json(resolved_output_path, payload)
        return {
            "success": True,
            "job_id": job_dir.name,
            "template_url": template_url,
            "template_path": str(template_path),
            "items_count": len(payload.get("items", [])),
            "output_path": str(resolved_output_path),
            "items_json": payload,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/extract-items-ai")
async def extract_items_ai_route(
    template_url: str = Form(...),
    template_type: TemplateType = Form("business"),
    output_path: Optional[str] = Form(None),
) -> dict[str, Any]:
    try:
        job_dir = _new_job_dir("extract_ai")
        template_path = job_dir / "template.docx"
        download_file(template_url, template_path)
        defaults = _default_ai_output_paths(template_path)
        resolved_output_path = _to_path(output_path) or defaults["output"]

        payload = extract_template_items_ai(
            template_path,
            template_type=template_type,
        )
        _write_json(resolved_output_path, payload)

        return {
            "success": True,
            "job_id": job_dir.name,
            "template_url": template_url,
            "template_path": str(template_path),
            "items_count": len(payload.get("items", [])),
            "output_path": str(resolved_output_path),
            "items_json": payload,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/fill-bid-template")
async def fill_bid_template_route(
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    start_time = time.perf_counter()
    job_id = "pending"
    fill_logs: list[dict[str, Any]] = []
    try:
        _fill_log(fill_logs, job_id, "request", "收到回填请求", start_time, payload_keys=sorted(payload.keys()))
        item_payload = payload.get("items_json")
        if not isinstance(item_payload, dict):
            raise HTTPException(status_code=400, detail="items_json 必须是待填项 JSON 对象。")

        user_inputs = payload.get("user_inputs", payload.get("answers", {}))
        selected_item_ids = payload.get("selected_item_ids")
        if selected_item_ids is not None and not isinstance(selected_item_ids, list):
            raise HTTPException(status_code=400, detail="selected_item_ids 必须是字符串数组。")

        job_dir = _new_job_dir("fill")
        job_id = job_dir.name
        fill_logs.clear()
        _fill_log(
            fill_logs,
            job_id,
            "request",
            "收到回填请求",
            start_time,
            item_count=len(item_payload.get("items", [])),
            selected_count=len(selected_item_ids or []),
        )
        template_path = _template_path_for_fill(payload, job_dir)
        _fill_log(fill_logs, job_id, "template", "模版文件已就绪", start_time, template_path=str(template_path))
        resolved_output_path = _to_path(payload.get("output_path")) or _default_filled_output_path(template_path)
        missing_marker = str(payload.get("missing_marker") or "【待确认】")

        fill_items_json = _filtered_item_payload(item_payload, selected_item_ids)
        answers_json = _answers_from_user_inputs(fill_items_json, user_inputs)
        _fill_log(
            fill_logs,
            job_id,
            "prepare",
            "已生成本次回填输入",
            start_time,
            fill_item_count=len(fill_items_json.get("items", [])),
            answer_count=len(answers_json.get("answers", [])),
        )

        items_output_path = job_dir / "待填项输入.json"
        answers_output_path = job_dir / "用户填充输入.json"
        _write_json(items_output_path, fill_items_json)
        _write_json(answers_output_path, answers_json)
        _fill_log(
            fill_logs,
            job_id,
            "persist",
            "已保存回填中间 JSON",
            start_time,
            items_input_path=str(items_output_path),
            answers_input_path=str(answers_output_path),
        )

        filled_path = fill_template(
            template_path,
            fill_items_json,
            answers_json,
            resolved_output_path,
            missing_marker=missing_marker,
        )
        _fill_log(fill_logs, job_id, "docx", "Word 回填完成，准备上传", start_time, output_path=str(filled_path))
        filled_template_url = upload_docx_to_platform(
            filled_path,
            upload_base_url=os.getenv("UPLOAD_BASE_URL") or DEFAULT_UPLOAD_BASE_URL,
            platform_key=_get_platform_key(),
        )
        _fill_log(fill_logs, job_id, "upload", "平台下载链接已返回", start_time, filled_template_url=filled_template_url)

        return {
            "success": True,
            "job_id": job_dir.name,
            "template_path": str(template_path),
            "items_count": len(fill_items_json.get("items", [])),
            "answers_count": len(answers_json.get("answers", [])),
            "filled_template_url": filled_template_url,
            "output_path": str(filled_path),
            "items_input_path": str(items_output_path),
            "answers_input_path": str(answers_output_path),
            "fill_logs": fill_logs,
        }
    except HTTPException:
        raise
    except Exception as exc:
        _fill_log(fill_logs, job_id, "error", "回填流程失败", start_time, error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc


FRONTEND_DIR = REPO_ROOT / "frontend"
KNOWLEDGE_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/knowledge-images", StaticFiles(directory=KNOWLEDGE_IMAGE_DIR), name="knowledge-images")
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "fastapi_backend:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "18010")),
        reload=True,
    )
