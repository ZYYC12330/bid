from __future__ import annotations

from pathlib import Path
import unittest


FRONTEND_HTML = Path(__file__).resolve().parents[1] / "frontend" / "index.html"


class FrontendRealExtractFlowTest(unittest.TestCase):
    def test_upload_flow_calls_real_template_and_extract_endpoints(self) -> None:
        html = FRONTEND_HTML.read_text(encoding="utf-8")

        self.assertIn('fetch("/api/extract-tender-metadata"', html)
        self.assertIn('fetch("/api/generate-templates"', html)
        self.assertIn('fetch("/api/extract-items"', html)
        self.assertIn("business_template_url", html)
        self.assertIn("renderRealExtractItems", html)

    def test_upload_loading_shows_project_info_and_progress(self) -> None:
        html = FRONTEND_HTML.read_text(encoding="utf-8")

        self.assertIn('id="bidNumberValue"', html)
        self.assertIn('id="projectNameValue"', html)
        self.assertIn("AI解析", html)
        self.assertNotIn("AI 解析前三页", html)
        self.assertNotIn("AI解析前三页", html)
        self.assertIn("生成商务标模版", html)
        self.assertIn("提取待填写字段", html)
        self.assertIn("runProjectMetadataFlow", html)

    def test_frontend_no_longer_uses_static_extract_item_fixture(self) -> None:
        html = FRONTEND_HTML.read_text(encoding="utf-8")

        self.assertNotIn("const extractItems = [", html)
        self.assertNotIn('key: "project_name"', html)

    def test_image_fields_render_as_image_upload_controls(self) -> None:
        html = FRONTEND_HTML.read_text(encoding="utf-8")

        self.assertIn("renderManualValueControl", html)
        self.assertIn('accept="image/*"', html)
        self.assertIn("data-manual-image-id", html)
        self.assertIn("readImageFile(file)", html)

    def test_knowledge_items_use_compact_single_row_layout(self) -> None:
        html = FRONTEND_HTML.read_text(encoding="utf-8")

        self.assertIn('class="knowledge-form compact"', html)
        self.assertIn(".knowledge-form.compact", html)
        self.assertIn(".knowledge-item.compact", html)
        self.assertIn('class="form-field knowledge-inline-content"', html)

    def test_knowledge_base_uses_frontend_knowledge_utils_defaults(self) -> None:
        html = FRONTEND_HTML.read_text(encoding="utf-8")

        self.assertNotIn('fetch("/api/knowledge-items"', html)
        self.assertNotIn('fetch(`/api/knowledge-items/${encodeURIComponent(item.id)}`', html)
        self.assertIn("KnowledgeUtils.buildDefaultKnowledgeItems", html)
        self.assertIn("KnowledgeUtils.buildKnowledgeItemsFromFields", html)
        self.assertIn('fetch("/api/knowledge-images"', html)
        self.assertIn("uploadKnowledgeImage(file)", html)
        self.assertIn("item.imageUrl", html)

    def test_knowledge_items_expose_create_delete_and_sync_actions(self) -> None:
        html = FRONTEND_HTML.read_text(encoding="utf-8")

        self.assertIn('id="addKnowledgeButton"', html)
        self.assertIn("data-delete-knowledge", html)
        self.assertIn("data-sync-knowledge", html)
        self.assertIn('aria-label="同步知识库条目"', html)
        self.assertIn('data-icon="save"', html)
        self.assertIn("await saveKnowledgeItem(item)", html)

    def test_generated_knowledge_items_save_without_backend_persistence(self) -> None:
        html = FRONTEND_HTML.read_text(encoding="utf-8")

        self.assertIn("async function saveKnowledgeItem(item)", html)
        self.assertIn("return normalizeKnowledgeItem(item)", html)
        self.assertNotIn("response.status === 404", html)

    def test_project_name_is_applied_from_current_upload_context(self) -> None:
        html = FRONTEND_HTML.read_text(encoding="utf-8")

        self.assertIn("applyProjectNameValue", html)
        self.assertIn("KnowledgeUtils.isProjectNameField", html)
        self.assertIn("projectName: fallbackProjectName()", html)
        self.assertIn('.filter((item) => !KnowledgeUtils.isProjectNameField(item.name))', html)

    def test_source_preference_tags_have_tender_and_company_colors(self) -> None:
        html = FRONTEND_HTML.read_text(encoding="utf-8")

        self.assertIn(".mini-chip.source-tender", html)
        self.assertIn(".mini-chip.source-company", html)
        self.assertIn(".mini-chip.source-qualification", html)
        self.assertIn(".mini-chip.source-case", html)
        self.assertIn("sourcePreferenceClass(source)", html)


if __name__ == "__main__":
    unittest.main()
