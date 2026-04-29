from __future__ import annotations

import zipfile
import importlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import extract_tender_metadata_ai


def _docx_with_document_xml(path: Path, body_xml: str) -> None:
    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    {body_xml}
  </w:body>
</w:document>
"""
    with zipfile.ZipFile(path, "w") as docx_zip:
        docx_zip.writestr("word/document.xml", document_xml)


class ExtractTenderMetadataAiTest(unittest.TestCase):
    def test_base_url_can_be_configured_by_environment(self) -> None:
        with patch.dict("os.environ", {"LLM_BASE_URL": "http://10.25.1.48/v1"}):
            reloaded = importlib.reload(extract_tender_metadata_ai)

        self.assertEqual(reloaded.BASE_URL, "http://10.25.1.48/v1")
        importlib.reload(extract_tender_metadata_ai)

    def test_read_first_page_prefers_page_breaks(self) -> None:
        with TemporaryDirectory() as tmpdir:
            docx_path = Path(tmpdir) / "招标文件.docx"
            _docx_with_document_xml(
                docx_path,
                """
                <w:p><w:r><w:t>第一页 招标编号：A-001</w:t></w:r></w:p>
                <w:p><w:r><w:lastRenderedPageBreak/><w:t>第二页 项目名称：二号项目</w:t></w:r></w:p>
                <w:p><w:r><w:lastRenderedPageBreak/><w:t>第三页 招标人：中国核电工程有限公司</w:t></w:r></w:p>
                <w:p><w:r><w:lastRenderedPageBreak/><w:t>第四页 不应进入提示词</w:t></w:r></w:p>
                """,
            )

            text = extract_tender_metadata_ai.read_first_page_text(docx_path)

        self.assertIn("第一页 招标编号：A-001", text)
        self.assertNotIn("第二页 项目名称：二号项目", text)
        self.assertNotIn("第三页 招标人：中国核电工程有限公司", text)
        self.assertNotIn("第四页 不应进入提示词", text)

    def test_extract_tender_metadata_normalizes_qwen_response(self) -> None:
        with TemporaryDirectory() as tmpdir:
            docx_path = Path(tmpdir) / "招标文件.docx"
            _docx_with_document_xml(
                docx_path,
                '<w:p><w:r><w:t>招标编号：QT-001 项目名称：箱室设备采购</w:t></w:r></w:p>',
            )
            raw_response = {
                "choices": [
                    {
                        "message": {
                            "content": """
                            {
                              "bid_number": "QT-001",
                              "project_name": "箱室设备采购",
                              "confidence": 0.91,
                              "evidence": [
                                {"field": "招标编号", "quote": "招标编号：QT-001"}
                              ]
                            }
                            """
                        }
                    }
                ]
            }

            with (
                patch.object(extract_tender_metadata_ai, "load_env_file"),
                patch.object(extract_tender_metadata_ai, "get_api_key", return_value="fake-key"),
                patch.object(extract_tender_metadata_ai, "call_qwen_request", return_value=raw_response) as call_mock,
            ):
                payload = extract_tender_metadata_ai.extract_tender_metadata(docx_path)

        self.assertEqual(payload["project_info"]["bid_number"], "QT-001")
        self.assertEqual(payload["project_info"]["project_name"], "箱室设备采购")
        self.assertEqual(payload["project_info"]["confidence"], 0.91)
        self.assertEqual(payload["request"]["model"], "qwen3.6-plus")
        self.assertEqual(payload["raw_response"], raw_response)
        call_mock.assert_called_once()

    def test_call_qwen_request_bypasses_system_proxy_by_default(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self) -> bytes:
                return b'{"choices":[]}'

        class FakeOpener:
            def open(self, request, timeout):
                return FakeResponse()

        request_payload = extract_tender_metadata_ai.build_qwen_request(
            "招标编号：QT-001 项目名称：箱室设备采购",
            docx_path=Path("招标文件.docx"),
        )

        with (
            patch.object(extract_tender_metadata_ai.urllib.request, "ProxyHandler") as proxy_handler,
            patch.object(extract_tender_metadata_ai.urllib.request, "build_opener", return_value=FakeOpener()) as build_opener,
            patch.object(extract_tender_metadata_ai.urllib.request, "urlopen", return_value=FakeResponse()) as urlopen,
            patch.dict("os.environ", {"HTTPS_PROXY": "http://127.0.0.1:8888"}, clear=False),
        ):
            response = extract_tender_metadata_ai.call_qwen_request(request_payload, api_key="fake-key")

        self.assertEqual(response, {"choices": []})
        proxy_handler.assert_called_once_with({})
        build_opener.assert_called_once_with(proxy_handler.return_value)
        urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
