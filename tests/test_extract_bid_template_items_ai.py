from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from docx import Document

from scripts import extract_bid_template_items_ai


class ExtractBidTemplateItemsAiTest(unittest.TestCase):
    def test_ai_request_keeps_full_xml_out_of_prompt(self) -> None:
        blocks = [
            {
                "block_index": 0,
                "block_type": "paragraph",
                "paragraph_index": 0,
                "text": "投标人名称：",
                "xml": "<w:p>" + ("x" * 100_000) + "</w:p>",
            }
        ]

        request_payload = extract_bid_template_items_ai.build_ai_request(
            blocks,
            template_path=Path("template.docx"),
            template_type="business",
        )

        prompt = request_payload["messages"][1]["content"]
        self.assertLess(len(prompt), 30_720)
        self.assertIn("投标人名称", prompt)
        self.assertNotIn("x" * 1000, prompt)

    def test_ai_selected_paragraph_is_returned_with_xml_and_placeholder(self) -> None:
        with TemporaryDirectory() as tmpdir:
            template_path = Path(tmpdir) / "template.docx"
            document = Document()
            document.add_paragraph("投标人名称：")
            document.save(template_path)

            raw_response = {
                "choices": [
                    {
                        "message": {
                            "content": """
                            {
                              "items": [
                                {
                                  "block_index": 0,
                                  "field_name": "投标人名称",
                                  "placeholder_text": "投标人名称：",
                                  "locator": {
                                    "block_type": "paragraph_colon",
                                    "label_text": "投标人名称"
                                  }
                                }
                              ]
                            }
                            """
                        }
                    }
                ]
            }

            with (
                patch.object(extract_bid_template_items_ai, "load_env_file"),
                patch.object(extract_bid_template_items_ai, "get_api_key", return_value="fake-key"),
                patch.object(extract_bid_template_items_ai, "call_ai", return_value=raw_response) as call_mock,
            ):
                payload = extract_bid_template_items_ai.extract_template_items_ai(
                    template_path,
                    template_type="business",
                )

        self.assertEqual(len(payload["items"]), 1)
        item = payload["items"][0]
        self.assertEqual(item["item_id"], "business_001")
        self.assertEqual(item["field_name"], "投标人名称")
        self.assertEqual(item["placeholder_text"], "投标人名称：")
        self.assertEqual(item["locator"]["block_type"], "paragraph_colon")
        self.assertEqual(item["locator"]["paragraph_index"], 0)
        self.assertIn("投标人名称", item["locator"]["xml"])
        call_mock.assert_called_once()
        request_payload = call_mock.call_args.args[0]
        self.assertEqual(request_payload["model"], extract_bid_template_items_ai.MODEL)
        self.assertIn("messages", request_payload)


if __name__ == "__main__":
    unittest.main()
