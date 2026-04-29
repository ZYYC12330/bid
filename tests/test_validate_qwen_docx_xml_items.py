from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.validate_qwen_docx_xml_items import build_qwen_request, read_docx_document_xml


class ValidateQwenDocxXmlItemsTest(unittest.TestCase):
    def test_read_docx_document_xml_returns_word_document_xml(self) -> None:
        document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>投标人名称：</w:t></w:r></w:p></w:body>
</w:document>
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            docx_path = Path(tmpdir) / "input.docx"
            with zipfile.ZipFile(docx_path, "w") as docx_zip:
                docx_zip.writestr("word/document.xml", document_xml)

            self.assertEqual(read_docx_document_xml(docx_path), document_xml)

    def test_build_qwen_request_uses_prompt_and_docx_xml(self) -> None:
        request = build_qwen_request(
            "<w:p><w:t>投标人名称：</w:t></w:p>",
            docx_path=Path("input.docx"),
        )

        self.assertEqual(request["model"], "qwen3.6-plus")
        self.assertEqual(request["response_format"], {"type": "json_object"})
        user_payload = request["messages"][1]["content"]
        self.assertIn('"prompt": "找出待填项"', user_payload)
        self.assertIn("投标人名称", user_payload)
        self.assertIn("items", user_payload)


if __name__ == "__main__":
    unittest.main()
