from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from docx import Document
from docx.document import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph


DEFAULT_TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent
    / "4.15测试-箱室类"
    / "输出模版"
    / "GKZH-25ZXH856-401.88项目箱室设备采购-招标文件-发布版1128_商务标模版.docx"
)
DEFAULT_OUTPUT_PATH = DEFAULT_TEMPLATE_PATH.with_suffix(".待填项清单.json")

PLACEHOLDER_PATTERN = re.compile(r"[（(]([^（）()]{1,40})[）)]")
X_PLACEHOLDER_PATTERN = re.compile(r"20XX\s*年\s*XX\s*月\s*XX\s*日|X{2,}")
COLON_LABEL_PATTERN = re.compile(r"([\u4e00-\u9fa5A-Za-z0-9（）()]{1,24})[：:]")
SECTION_PATTERN = re.compile(r"^[一二三四五六七八九十]+[、.．]\s*(.+)$")

EXCLUDED_PLACEHOLDER_WORDS = (
    "盖章",
    "盖单位公章",
    "签字",
    "印章",
    "不适用",
    "单位负责人",
    "以下称",
)
PLACEHOLDER_KEYWORDS = (
    "项目名称",
    "投标人名称",
    "投标人",
    "姓名",
    "金额",
    "大写",
    "小写",
    "交货期",
    "日期",
    "时间",
    "年",
    "月",
    "日",
    "填写",
)
ALLOWED_COLON_LABELS = {
    "招标编号",
    "投标人",
    "投标人名称",
    "姓名",
    "性别",
    "年龄",
    "职务",
    "地址",
    "网址",
    "电话",
    "邮政编码",
    "项目名称",
    "投标总价（小写）",
    "（大写）",
}
EXCLUDED_COLON_LABELS = {
    "注",
    "我方承诺",
    "我方的投标文件包括下列内容",
    "北京国科军友工程咨询有限公司",
    "投标文件报价部分格式要求",
    "人",
}
ALLOWED_SOURCE_PREFERENCES = {
    "case_performance_kb",
    "qualification_materials_kb",
    "company_profile_kb",
    "tender_requirements_kb",
}
MIN_IMAGE_PLACEHOLDER_WIDTH_EMU = 1_000_000
MIN_IMAGE_PLACEHOLDER_HEIGHT_EMU = 500_000


def normalize_text(text: str) -> str:
    return " ".join(text.replace("\u3000", " ").split())


def iter_block_items(document: DocxDocument):
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P

    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def infer_source_preference(field_name: str) -> list[str]:
    if any(word in field_name for word in ("案例", "业绩", "合同", "类似项目")):
        source = "case_performance_kb"
    elif any(word in field_name for word in ("资质", "证书", "认证", "许可证", "注册资金", "身份证", "复印件")):
        source = "qualification_materials_kb"
    elif is_bid_deadline_date_field(field_name):
        source = "tender_requirements_kb"
    elif any(word in field_name for word in ("项目", "招标编号", "交货期", "交付", "工期", "技术", "规格")):
        source = "tender_requirements_kb"
    else:
        source = "company_profile_kb"

    if source not in ALLOWED_SOURCE_PREFERENCES:
        raise ValueError(f"非法 source_preference: {source}")
    return [source]


def infer_field_type(field_name: str) -> str:
    if any(word in field_name for word in ("图片", "照片", "复印件", "身份证")):
        return "image"
    if is_bid_deadline_date_field(field_name):
        return "date_or_period"
    if any(word in field_name for word in ("金额", "报价", "注册资金")):
        return "money"
    if any(word in field_name for word in ("日期", "时间", "期限", "交货期")):
        return "date_or_period"
    if any(word in field_name for word in ("电话", "传真")):
        return "phone"
    return "text"


def clean_field_name(raw: str) -> str:
    cleaned = normalize_text(raw)
    cleaned = cleaned.strip(" ：:()（）")
    if cleaned.startswith("此处请填写"):
        return "交货期响应"
    return cleaned


def clean_x_placeholder_label(raw: str) -> str:
    cleaned = re.sub(r"[（(][^（）()]{0,30}[）)]$", "", raw)
    return clean_field_name(cleaned)


def is_bid_deadline_date_field(field_name: str) -> bool:
    normalized = clean_field_name(field_name)
    if normalized in {"年", "月", "日"}:
        return True
    return any(word in normalized for word in ("年月日", "日期", "时间", "投标截止"))


def infer_bid_deadline_component(field_name: str) -> str:
    normalized = clean_field_name(field_name)
    if normalized == "年":
        return "year"
    if normalized == "月":
        return "month"
    if normalized == "日":
        return "day"
    return "full_date"


def is_fillable_colon_label(field_name: str) -> bool:
    if not field_name or field_name in EXCLUDED_COLON_LABELS:
        return False
    return field_name in ALLOWED_COLON_LABELS


def is_fillable_placeholder(raw: str) -> bool:
    value = clean_field_name(raw)
    if not value:
        return False
    if any(word in value for word in EXCLUDED_PLACEHOLDER_WORDS):
        return False
    return any(word in value for word in PLACEHOLDER_KEYWORDS)


def run_text_spans(paragraph: Paragraph) -> list[tuple[int, int, int]]:
    spans = []
    offset = 0
    for index, run in enumerate(paragraph.runs):
        end = offset + len(run.text)
        spans.append((index, offset, end))
        offset = end
    return spans


def find_following_underlined_blank_run(paragraph: Paragraph, char_offset: int) -> int | None:
    spans = run_text_spans(paragraph)
    for run_index, start, end in spans:
        if end <= char_offset:
            continue
        run = paragraph.runs[run_index]
        tail_text = run.text[max(char_offset - start, 0) :]
        if tail_text.strip():
            continue
        if run.underline or "_" in tail_text:
            return run_index
    return None


def infer_x_placeholder_field_name(text: str, match: re.Match[str]) -> str | None:
    placeholder = normalize_text(match.group(0))
    if "XX" in placeholder and any(word in placeholder for word in ("年", "月", "日")):
        return "日期"

    prefix = text[: match.start()]
    colon_matches = list(COLON_LABEL_PATTERN.finditer(prefix))
    if not colon_matches:
        return None

    label = clean_x_placeholder_label(colon_matches[-1].group(1))
    if not label:
        return None
    if any(word in label for word in EXCLUDED_PLACEHOLDER_WORDS):
        return None
    return label


def is_blank_colon_value(text: str, match: re.Match[str], next_match: re.Match[str] | None) -> bool:
    start = match.end()
    end = next_match.start() if next_match else len(text)
    value = normalize_text(text[start:end])
    if not value:
        return True
    return all(word in value for word in ("盖",)) or value in {"（盖章）", "（盖单位公章）"}


def make_item(
    *,
    item_id: str,
    template_type: str,
    section: str,
    field_name: str,
    prompt_hint: str,
    locator: dict[str, Any],
    placeholder_text: str | None = None,
    field_type: str | None = None,
) -> dict[str, Any]:
    item = {
        "item_id": item_id,
        "template_type": template_type,
        "section": section,
        "field_name": field_name,
        "field_type": field_type or infer_field_type(field_name),
        "required": True,
        "placeholder_text": placeholder_text,
        "prompt_hint": prompt_hint,
        "source_preference": infer_source_preference(field_name),
        "locator": locator,
    }
    if is_bid_deadline_date_field(field_name):
        item["fill_rule"] = {
            "type": "tender_bid_deadline",
            "component": infer_bid_deadline_component(field_name),
            "description": "从招标文件投标截止时间取值；单独的年/月/日分别填写对应数字。",
        }
    return item


def xml_local_name(element: Any) -> str:
    return str(element.tag).rsplit("}", 1)[-1]


def first_descendant(element: Any, local_name: str) -> Any | None:
    return next((child for child in element.iter() if xml_local_name(child) == local_name), None)


def descendant_text(element: Any) -> str:
    values = [child.text or "" for child in element.iter() if xml_local_name(child) == "t"]
    return normalize_text("".join(values))


def shape_attr(element: Any, name: str) -> str | None:
    value = element.get(name)
    if value is not None:
        return value
    return next((attr_value for attr_name, attr_value in element.attrib.items() if attr_name.endswith(f"}}{name}")), None)


def extract_rect_placeholder_metadata(shape: Any) -> dict[str, Any] | None:
    geometry = first_descendant(shape, "prstGeom")
    if geometry is None or geometry.get("prst") != "rect":
        return None
    if descendant_text(shape):
        return None

    extent = first_descendant(shape, "extent")
    if extent is None:
        return None
    try:
        width_emu = int(extent.get("cx") or 0)
        height_emu = int(extent.get("cy") or 0)
    except ValueError:
        return None
    if width_emu < MIN_IMAGE_PLACEHOLDER_WIDTH_EMU or height_emu < MIN_IMAGE_PLACEHOLDER_HEIGHT_EMU:
        return None

    doc_pr = first_descendant(shape, "docPr")
    return {
        "doc_pr_id": shape_attr(doc_pr, "id") if doc_pr is not None else None,
        "doc_pr_name": shape_attr(doc_pr, "name") if doc_pr is not None else None,
        "width_emu": width_emu,
        "height_emu": height_emu,
    }


def image_placeholder_field_name(context_text: str, shape_number: int) -> str:
    context = clean_field_name(context_text.removeprefix("附"))
    context = context.rstrip("。；;")
    if "身份证" in context:
        side = "正面" if shape_number == 1 else "反面" if shape_number == 2 else f"第{shape_number}张"
        return f"{context}{side}"
    if context:
        return f"{context}图片{shape_number}"
    return f"图片占位框{shape_number}"


def _append_image_placeholder_items(
    *,
    items: list[dict[str, Any]],
    template_type: str,
    section: str,
    paragraph: Paragraph,
    paragraph_index: int,
    context_text: str,
) -> None:
    shapes = paragraph._p.xpath(".//*[local-name()='anchor' or local-name()='inline']")
    shape_number = 0
    for shape in shapes:
        metadata = extract_rect_placeholder_metadata(shape)
        if metadata is None:
            continue
        shape_number += 1
        field_name = image_placeholder_field_name(context_text, shape_number)
        item_id = f"{template_type}_{len(items) + 1:03d}"
        items.append(
            make_item(
                item_id=item_id,
                template_type=template_type,
                section=section,
                field_name=field_name,
                field_type="image",
                placeholder_text=None,
                prompt_hint=f"插入图片：{field_name}",
                locator={
                    "block_type": "image_placeholder",
                    "paragraph_index": paragraph_index,
                    "shape_index": shape_number - 1,
                    **metadata,
                },
            )
        )


def _append_paragraph_items(
    *,
    items: list[dict[str, Any]],
    template_type: str,
    section: str,
    paragraph: Paragraph,
    paragraph_index: int,
    previous_text: str = "",
) -> None:
    _append_image_placeholder_items(
        items=items,
        template_type=template_type,
        section=section,
        paragraph=paragraph,
        paragraph_index=paragraph_index,
        context_text=normalize_text(paragraph.text) or previous_text,
    )

    text = paragraph.text
    normalized = normalize_text(text)
    if not normalized:
        return

    for match in PLACEHOLDER_PATTERN.finditer(text):
        placeholder = match.group(0)
        field_name = clean_field_name(match.group(1))
        if not is_fillable_placeholder(match.group(1)):
            continue
        blank_run_index = find_following_underlined_blank_run(paragraph, match.end())
        if blank_run_index is None:
            continue
        item_id = f"{template_type}_{len(items) + 1:03d}"
        items.append(
            make_item(
                item_id=item_id,
                template_type=template_type,
                section=section,
                field_name=field_name,
                placeholder_text=placeholder,
                prompt_hint=f"根据括号提示填写后续下划线：{placeholder}",
                locator={
                    "block_type": "paragraph_underlined_blank",
                    "paragraph_index": paragraph_index,
                    "blank_run_index": blank_run_index,
                    "placeholder_text": placeholder,
                },
            )
        )

    for match in X_PLACEHOLDER_PATTERN.finditer(text):
        placeholder = normalize_text(match.group(0))
        field_name = infer_x_placeholder_field_name(text, match)
        if not field_name:
            continue
        item_id = f"{template_type}_{len(items) + 1:03d}"
        items.append(
            make_item(
                item_id=item_id,
                template_type=template_type,
                section=section,
                field_name=field_name,
                placeholder_text=placeholder,
                prompt_hint=f"填写段落中的占位符：{placeholder}",
                locator={
                    "block_type": "paragraph_placeholder",
                    "paragraph_index": paragraph_index,
                    "placeholder_text": placeholder,
                },
            )
        )

    colon_matches = list(COLON_LABEL_PATTERN.finditer(text))
    for index, match in enumerate(colon_matches):
        next_match = colon_matches[index + 1] if index + 1 < len(colon_matches) else None
        field_name = clean_field_name(match.group(1))
        if not is_fillable_colon_label(field_name) or not is_blank_colon_value(text, match, next_match):
            continue
        item_id = f"{template_type}_{len(items) + 1:03d}"
        items.append(
            make_item(
                item_id=item_id,
                template_type=template_type,
                section=section,
                field_name=field_name,
                placeholder_text=match.group(0),
                prompt_hint=f"填写字段：{field_name}",
                locator={
                    "block_type": "paragraph_colon",
                    "paragraph_index": paragraph_index,
                    "label_text": match.group(1),
                },
            )
        )


def _nearest_left_label(row, cell_index: int) -> str | None:
    for index in range(cell_index - 1, -1, -1):
        value = normalize_text(row.cells[index].text)
        if value:
            return value
    return None


def is_line_item_table(table: Table) -> bool:
    if not table.rows:
        return False
    header_text = " ".join(normalize_text(cell.text) for cell in table.rows[0].cells)
    return "序号" in header_text and any(word in header_text for word in ("规格型号", "单位", "数量"))


def is_fillable_table_label(field_name: str) -> bool:
    if not field_name or len(field_name) > 30:
        return False
    if re.fullmatch(r"[0-9]+(?:[.．][0-9…‥]*)?", field_name):
        return False
    if field_name in {"套", "项", "个", "件", "……"}:
        return False
    return True


def _append_table_items(
    *,
    items: list[dict[str, Any]],
    template_type: str,
    section: str,
    table: Table,
    table_index: int,
) -> None:
    if is_line_item_table(table):
        return

    seen_cells: list[Any] = []
    for row_index, row in enumerate(table.rows):
        for cell_index, cell in enumerate(row.cells):
            if any(seen_cell is cell._tc for seen_cell in seen_cells):
                continue
            seen_cells.append(cell._tc)
            if normalize_text(cell.text):
                continue
            label = _nearest_left_label(row, cell_index)
            if not label:
                continue
            field_name = clean_field_name(label)
            if not is_fillable_table_label(field_name):
                continue
            item_id = f"{template_type}_{len(items) + 1:03d}"
            items.append(
                make_item(
                    item_id=item_id,
                    template_type=template_type,
                    section=section,
                    field_name=field_name,
                    placeholder_text=None,
                    prompt_hint=f"填写表格字段：{field_name}",
                    locator={
                        "block_type": "table_cell",
                        "table_index": table_index,
                        "row_index": row_index,
                        "cell_index": cell_index,
                        "label_text": label,
                    },
                )
            )


def extract_template_items(template_path: Path, template_type: str = "business") -> dict[str, Any]:
    document = Document(template_path)
    items: list[dict[str, Any]] = []
    section = "封面"
    paragraph_index = 0
    table_index = 0
    previous_text = ""

    for block in iter_block_items(document):
        if isinstance(block, Paragraph):
            text = normalize_text(block.text)
            section_match = SECTION_PATTERN.match(text)
            if section_match:
                section = text
            _append_paragraph_items(
                items=items,
                template_type=template_type,
                section=section,
                paragraph=block,
                paragraph_index=paragraph_index,
                previous_text=previous_text,
            )
            if text:
                previous_text = text
            paragraph_index += 1
        else:
            _append_table_items(
                items=items,
                template_type=template_type,
                section=section,
                table=block,
                table_index=table_index,
            )
            table_index += 1

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="从商务标/技术标模版 Word 中提取待填项清单 JSON。")
    parser.add_argument("template_path", nargs="?", type=Path, default=DEFAULT_TEMPLATE_PATH)
    parser.add_argument("--template-type", default="business", choices=("business", "technical", "price"))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    payload = extract_template_items(args.template_path, template_type=args.template_type)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"待填项清单: {args.output}")
    print(f"待填项数量: {len(payload['items'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
