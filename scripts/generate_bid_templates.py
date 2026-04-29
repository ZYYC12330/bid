from __future__ import annotations

import argparse
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from docx import Document
from docx.document import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph

try:
    from scripts.platform_file_client import upload_docx_to_platform
except ModuleNotFoundError:
    from platform_file_client import upload_docx_to_platform

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_PATH = (
    REPO_ROOT
    / "4.15测试-箱室类"
    / "招标文件"
    / "GKZH-25ZXH856-401.88项目箱室设备采购-招标文件-发布版1128.docx"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "4.15测试-箱室类" / "输出模版"
DEFAULT_UPLOAD_BASE_URL = "https://demo.langcore.cn/"
DEFAULT_PLATFORM_KEY = ""

BUSINESS_LABELS = (
    "商务标",
    "商务文件",
    "商务部分",
    "商务册",
)
TECHNICAL_LABELS = (
    "技术标",
    "技术文件",
    "技术部分",
    "技术册",
)
BUSINESS_MARKERS = (
    "法定代表人(单位负责人)身份证明",
    "法定代表人（单位负责人）身份证明",
    "法定代表人身份证明",
    "授权委托书",
    "投标函",
    "商务偏离表",
    "商务偏差表",
)
TECHNICAL_MARKERS = (
    "质量保证",
    "供货方案",
    "技术服务方案",
    "技术方案",
    "项目组织与进度",
    "技术偏离表",
    "技术偏差表",
)
PROJECT_TITLE_MARKERS = ("(项目名称)", "（项目名称）")


@dataclass(frozen=True)
class BodyBlock:
    index: int
    text: str


@dataclass(frozen=True)
class TemplateRange:
    business_start: int
    business_end: int
    technical_start: int
    technical_end: int


@dataclass(frozen=True)
class CoverCandidate:
    position: int
    score: int
    label: str
    has_directory: bool
    matched_markers: tuple[str, ...]
    cover_text: str


@dataclass(frozen=True)
class DetectionReport:
    business_candidates: tuple[CoverCandidate, ...]
    technical_candidates: tuple[CoverCandidate, ...]
    selected_business: CoverCandidate
    selected_technical: CoverCandidate
    business_start: int
    technical_start: int


def normalize_text(text: str) -> str:
    return " ".join(text.replace("\u3000", " ").split())


def normalize_for_match(text: str) -> str:
    normalized = normalize_text(text)
    return (
        normalized.replace("：", ":")
        .replace("（", "(")
        .replace("）", ")")
        .replace(" ", "")
    )


def contains_any_marker(text: str, markers: tuple[str, ...]) -> bool:
    normalized = normalize_for_match(text)
    return any(normalize_for_match(marker) in normalized for marker in markers)


def contains_any_label(text: str, labels: tuple[str, ...]) -> bool:
    normalized = normalize_for_match(text)
    return any(normalize_for_match(label) == normalized for label in labels)


def matched_markers(text: str, markers: tuple[str, ...]) -> tuple[str, ...]:
    normalized = normalize_for_match(text)
    hits: list[str] = []
    for marker in markers:
        if normalize_for_match(marker) in normalized and marker not in hits:
            hits.append(marker)
    return tuple(hits)


def iter_block_items(parent: DocxDocument) -> Iterable[Paragraph | Table]:
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P

    parent_elm = parent.element.body
    for child in parent_elm.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield Table(child, parent)


def block_text(block: Paragraph | Table) -> str:
    if isinstance(block, Paragraph):
        return normalize_text(block.text)

    rows: list[str] = []
    for row in block.rows:
        cell_values = [normalize_text(cell.text) for cell in row.cells]
        joined = " | ".join(value for value in cell_values if value)
        if joined:
            rows.append(joined)
    return normalize_text("\n".join(rows))


def collect_body_blocks(document: DocxDocument) -> list[BodyBlock]:
    blocks: list[BodyBlock] = []
    for index, block in enumerate(iter_block_items(document)):
        text = block_text(block)
        if text:
            blocks.append(BodyBlock(index=index, text=text))
    return blocks


def _find_cover_start(blocks: list[BodyBlock], cover_position: int) -> int:
    start = cover_position
    lower_bound = max(0, cover_position - 8)
    for index in range(cover_position - 1, lower_bound - 1, -1):
        block_text = blocks[index].text
        normalized = normalize_for_match(block_text)
        if normalized in PROJECT_TITLE_MARKERS or "项目名称" in normalized:
            start = index
            break
    return start


def _score_cover_candidate(
    blocks: list[BodyBlock],
    cover_position: int,
    labels: tuple[str, ...],
    expected_markers: tuple[str, ...],
) -> CoverCandidate | None:
    cover_text = blocks[cover_position].text
    if not contains_any_label(cover_text, labels):
        return None

    score = 3
    window = blocks[cover_position + 1 : cover_position + 26]
    has_directory = any(normalize_for_match(block.text) == "目录" for block in window[:8])
    if has_directory:
        score += 2

    marker_hits: list[str] = []
    for block in window:
        for marker in matched_markers(block.text, expected_markers):
            if marker not in marker_hits:
                marker_hits.append(marker)

    if not marker_hits:
        return None

    return CoverCandidate(
        position=cover_position,
        score=score + len(marker_hits),
        label=cover_text,
        has_directory=has_directory,
        matched_markers=tuple(marker_hits),
        cover_text=cover_text,
    )


def _collect_cover_candidates(
    blocks: list[BodyBlock],
    start_position: int,
    labels: tuple[str, ...],
    markers: tuple[str, ...],
) -> tuple[CoverCandidate, ...]:
    candidates: list[CoverCandidate] = []

    for position in range(start_position, len(blocks)):
        candidate = _score_cover_candidate(blocks, position, labels, markers)
        if candidate is not None:
            candidates.append(candidate)

    candidates.sort(key=lambda item: (-item.score, item.position))
    return tuple(candidates)


def _find_best_cover(
    blocks: list[BodyBlock],
    start_position: int,
    labels: tuple[str, ...],
    markers: tuple[str, ...],
) -> CoverCandidate | None:
    candidates = _collect_cover_candidates(blocks, start_position, labels, markers)
    if not candidates:
        return None
    return candidates[0]


def detect_template_ranges(
    blocks: list[BodyBlock], include_report: bool = False
) -> TemplateRange | tuple[TemplateRange, DetectionReport]:
    business_candidates = _collect_cover_candidates(blocks, 0, BUSINESS_LABELS, BUSINESS_MARKERS)
    business_cover = business_candidates[0] if business_candidates else None

    if business_cover is None:
        raise ValueError("未找到商务标模板封面。")

    technical_candidates = _collect_cover_candidates(
        blocks, business_cover.position + 1, TECHNICAL_LABELS, TECHNICAL_MARKERS
    )
    technical_cover = technical_candidates[0] if technical_candidates else None

    if technical_cover is None:
        raise ValueError("未找到技术标模板封面。")

    business_start = _find_cover_start(blocks, business_cover.position)
    technical_start = _find_cover_start(blocks, technical_cover.position)

    template_range = TemplateRange(
        business_start=blocks[business_start].index,
        business_end=blocks[technical_start].index - 1,
        technical_start=blocks[technical_start].index,
        technical_end=blocks[-1].index,
    )
    if not include_report:
        return template_range

    report = DetectionReport(
        business_candidates=business_candidates,
        technical_candidates=technical_candidates,
        selected_business=business_cover,
        selected_technical=technical_cover,
        business_start=blocks[business_start].index,
        technical_start=blocks[technical_start].index,
    )
    return template_range, report


def format_detection_report(report: DetectionReport, blocks: list[BodyBlock]) -> str:
    lines = ["识别日志：", ""]

    def append_section(
        title: str,
        candidates: tuple[CoverCandidate, ...],
        selected: CoverCandidate,
        start_index: int,
    ) -> None:
        lines.append(f"[{title}]")
        for candidate in candidates:
            selected_tag = " [选中]" if candidate.position == selected.position else ""
            lines.append(
                f"- 候选块#{blocks[candidate.position].index} 文本=\"{candidate.cover_text}\" "
                f"score={candidate.score} 目录={'是' if candidate.has_directory else '否'}{selected_tag}"
            )
            lines.append(f"  命中特征: {', '.join(candidate.matched_markers)}")
        lines.append(
            f"  最终判定: 选择块#{blocks[selected.position].index}，"
            f"因为它是有效{title}封面且得分最高；回溯起点为块#{start_index}。"
        )
        lines.append("")

    append_section("商务标", report.business_candidates, report.selected_business, report.business_start)
    append_section("技术标", report.technical_candidates, report.selected_technical, report.technical_start)
    return "\n".join(lines).rstrip()


def trim_document_to_range(document: DocxDocument, start_index: int, end_index: int) -> None:
    body = document.element.body
    content_elements = [
        child
        for child in body.iterchildren()
        if child.tag.endswith("}p") or child.tag.endswith("}tbl")
    ]

    for index, child in enumerate(content_elements):
        if start_index <= index <= end_index:
            continue
        body.remove(child)


def export_template(source_path: Path, output_path: Path, start_index: int, end_index: int) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, output_path)
    document = Document(output_path)
    trim_document_to_range(document, start_index, end_index)
    document.save(output_path)


def derive_output_paths(input_path: Path, output_dir: Path | None) -> tuple[Path, Path]:
    if output_dir is not None:
        target_dir = output_dir
    else:
        # 默认输出到输入文档所在目录的同级目录“输出模版”
        base_dir = input_path.parent.parent if input_path.parent.parent != input_path.parent else input_path.parent
        target_dir = base_dir / "输出模版"
    stem = input_path.stem
    return (
        target_dir / f"{stem}_商务标模版.docx",
        target_dir / f"{stem}_技术标模版.docx",
    )


def generate_templates(
    input_path: Path, output_dir: Path | None = None, verbose: bool = False
) -> tuple[Path, Path]:
    document = Document(input_path)
    blocks = collect_body_blocks(document)
    if verbose:
        template_range, report = detect_template_ranges(blocks, include_report=True)
        print(format_detection_report(report, blocks))
    else:
        template_range = detect_template_ranges(blocks)
    business_output, technical_output = derive_output_paths(input_path, output_dir)

    export_template(
        input_path,
        business_output,
        template_range.business_start,
        template_range.business_end,
    )
    export_template(
        input_path,
        technical_output,
        template_range.technical_start,
        template_range.technical_end,
    )
    return business_output, technical_output


def generate_template_links(
    input_path: Path,
    output_dir: Path | None = None,
    verbose: bool = False,
    upload_base_url: str | None = None,
    platform_key: str | None = None,
) -> dict[str, str]:
    business_output, technical_output = generate_templates(input_path, output_dir, verbose=verbose)
    resolved_upload_base_url = upload_base_url or os.getenv("UPLOAD_BASE_URL") or DEFAULT_UPLOAD_BASE_URL
    resolved_platform_key = (
        platform_key
        or os.getenv("PLATFORM_KEY")
        or os.getenv("PLATFORM_API_KEY")
        or DEFAULT_PLATFORM_KEY
    )
    if not resolved_platform_key:
        raise RuntimeError("缺少 PLATFORM_KEY 或 PLATFORM_API_KEY，无法上传到平台。")
    return {
        "business_template_url": upload_docx_to_platform(
            business_output,
            upload_base_url=resolved_upload_base_url,
            platform_key=resolved_platform_key,
        ),
        "technical_template_url": upload_docx_to_platform(
            technical_output,
            upload_base_url=resolved_upload_base_url,
            platform_key=resolved_platform_key,
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从招标文件 Word 中拆分生成商务标模版和技术标模版。"
    )
    parser.add_argument(
        "input_path",
        nargs="?",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help=f"输入的招标文件 .docx 路径，默认使用 {DEFAULT_INPUT_PATH}",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"输出目录，默认使用 {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="打印模板识别日志，说明为什么判定为商务标/技术标",
    )
    parser.add_argument(
        "--upload-base-url",
        default=None,
        help=f"平台上传地址，默认使用环境变量 UPLOAD_BASE_URL 或 {DEFAULT_UPLOAD_BASE_URL}",
    )
    parser.add_argument(
        "--platform-key",
        default=None,
        help="平台上传密钥，默认使用环境变量 PLATFORM_KEY。",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    links = generate_template_links(
        args.input_path,
        args.output_dir,
        verbose=args.verbose,
        upload_base_url=args.upload_base_url,
        platform_key=args.platform_key,
    )
    print(f"商务标在线文档: {links['business_template_url']}")
    print(f"技术标在线文档: {links['technical_template_url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
