from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import fastapi_backend
from fastapi.testclient import TestClient


class FastapiBackendRoutesTest(unittest.TestCase):
    def test_backend_only_exposes_three_script_interfaces(self) -> None:
        api_routes = {
            route.path
            for route in fastapi_backend.app.routes
            if hasattr(route, "methods") and "POST" in route.methods
        }

        self.assertEqual(
            api_routes,
            {
                "/api/generate-templates",
                "/api/extract-tender-metadata",
                "/api/extract-items",
                "/api/extract-items-ai",
                "/api/fill-bid-template",
                "/api/knowledge-items",
                "/api/knowledge-images",
            },
        )

    def test_root_serves_frontend_page(self) -> None:
        client = TestClient(fastapi_backend.app)

        response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("AI 标书生成平台", response.text)
        self.assertIn("上传招标文件", response.text)
        self.assertIn("待提取项列表", response.text)
        self.assertIn("下一步", response.text)

    def test_knowledge_items_can_be_created_and_listed(self) -> None:
        client = TestClient(fastapi_backend.app)
        created_item = {
            "id": "kb_001",
            "name": "企业简介",
            "type": "TEXT",
            "content": "航天晨光股份有限公司",
            "image_url": "",
            "file_name": "",
        }
        with (
            patch.object(fastapi_backend.knowledge_store, "create_item", return_value=created_item) as create_mock,
            patch.object(fastapi_backend.knowledge_store, "list_items", return_value=[created_item]) as list_mock,
        ):
            create_response = client.post(
                "/api/knowledge-items",
                json={"name": "企业简介", "type": "TEXT", "content": "航天晨光股份有限公司"},
            )
            list_response = client.get("/api/knowledge-items")

        self.assertEqual(create_response.status_code, 200)
        self.assertTrue(create_response.json()["success"])
        self.assertEqual(create_response.json()["item"], created_item)
        create_mock.assert_called_once_with(
            name="企业简介",
            item_type="TEXT",
            content="航天晨光股份有限公司",
            image_url="",
            file_name="",
        )
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json()["items"], [created_item])
        list_mock.assert_called_once()

    def test_knowledge_images_are_saved_as_renderable_urls(self) -> None:
        client = TestClient(fastapi_backend.app)
        response = client.post(
            "/api/knowledge-images",
            files={"file": ("seal.png", b"\x89PNG\r\n\x1a\nfake", "image/png")},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertTrue(payload["image_url"].startswith("/knowledge-images/"))
        self.assertEqual(payload["file_name"], "seal.png")
        self.assertTrue((fastapi_backend.KNOWLEDGE_IMAGE_DIR / Path(payload["image_url"]).name).exists())

    def test_generate_templates_accepts_uploaded_docx(self) -> None:
        client = TestClient(fastapi_backend.app)
        with patch.object(
            fastapi_backend,
            "generate_template_links",
            return_value={
                "business_template_url": "https://demo.langcore.cn/api/file/business",
                "technical_template_url": "https://demo.langcore.cn/api/file/technical",
            },
        ) as generate_mock:
            response = client.post(
                "/api/generate-templates",
                files={
                    "file": (
                        "招标文件.docx",
                        b"fake-docx",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                },
                data={"verbose": "false"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["business_template_url"],
            "https://demo.langcore.cn/api/file/business",
        )
        generate_mock.assert_called_once()
        self.assertTrue(generate_mock.call_args.kwargs["input_path"].name.endswith(".docx"))
        self.assertIsNone(generate_mock.call_args.kwargs["output_dir"])

    def test_extract_tender_metadata_accepts_uploaded_docx(self) -> None:
        client = TestClient(fastapi_backend.app)
        metadata_payload = {
            "project_info": {
                "bid_number": "QT025WXR818C11506BD/GKZH-25ZXH856",
                "project_name": "401.88项目箱室设备采购",
                "confidence": 0.94,
                "evidence": [{"field": "项目名称", "quote": "401.88项目箱室设备采购"}],
            },
            "request": {"model": "qwen3.6-plus"},
            "raw_response": {"choices": []},
        }
        with patch.object(
            fastapi_backend,
            "extract_tender_metadata",
            return_value=metadata_payload,
        ) as metadata_mock:
            response = client.post(
                "/api/extract-tender-metadata",
                files={
                    "file": (
                        "招标文件.docx",
                        b"fake-docx",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["project_info"]["bid_number"], "QT025WXR818C11506BD/GKZH-25ZXH856")
        self.assertEqual(payload["project_info"]["project_name"], "401.88项目箱室设备采购")
        self.assertTrue(Path(payload["output_path"]).name.endswith(".元信息.json"))
        self.assertTrue(Path(payload["request_output_path"]).name.endswith(".元信息请求.json"))
        self.assertTrue(Path(payload["response_output_path"]).name.endswith(".元信息响应.json"))
        metadata_mock.assert_called_once()
        self.assertTrue(metadata_mock.call_args.args[0].name.endswith(".docx"))

    def test_extract_items_accepts_template_url(self) -> None:
        client = TestClient(fastapi_backend.app)
        with (
            patch.object(fastapi_backend, "download_file") as download_mock,
            patch.object(
                fastapi_backend,
                "extract_template_items",
                return_value={"items": [{"item_id": "business_001"}]},
            ) as extract_mock,
        ):
            response = client.post(
                "/api/extract-items",
                data={
                    "template_url": "https://demo.langcore.cn/api/file/business-template.docx",
                    "template_type": "business",
                    "output_path": "string",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items_count"], 1)
        self.assertEqual(response.json()["items_json"], {"items": [{"item_id": "business_001"}]})
        self.assertEqual(
            response.json()["template_url"],
            "https://demo.langcore.cn/api/file/business-template.docx",
        )
        download_mock.assert_called_once()
        self.assertEqual(
            download_mock.call_args.args[0],
            "https://demo.langcore.cn/api/file/business-template.docx",
        )
        self.assertTrue(download_mock.call_args.args[1].name.endswith(".docx"))
        extract_mock.assert_called_once()
        self.assertTrue(extract_mock.call_args.args[0].name.endswith(".docx"))
        self.assertTrue(Path(response.json()["output_path"]).name.endswith(".待填项清单.json"))
        self.assertNotEqual(Path(response.json()["output_path"]).name, "string")

    def test_extract_items_ai_accepts_template_url_and_preserves_extract_items_shape(self) -> None:
        client = TestClient(fastapi_backend.app)
        items_payload = {
            "items": [{"item_id": "business_001"}],
        }
        with (
            patch.object(fastapi_backend, "download_file") as download_mock,
            patch.object(
                fastapi_backend,
                "extract_template_items_ai",
                return_value=items_payload,
            ) as extract_mock,
        ):
            response = client.post(
                "/api/extract-items-ai",
                data={
                    "template_url": "https://demo.langcore.cn/api/file/business-template.docx",
                    "template_type": "business",
                    "output_path": "string",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items_count"], 1)
        self.assertEqual(response.json()["items_json"], {"items": [{"item_id": "business_001"}]})
        self.assertEqual(
            response.json()["template_url"],
            "https://demo.langcore.cn/api/file/business-template.docx",
        )
        self.assertTrue(Path(response.json()["output_path"]).name.endswith(".AI待填项清单.json"))
        self.assertNotIn("page_count", response.json())
        self.assertNotIn("request_output_path", response.json())
        download_mock.assert_called_once()
        self.assertEqual(
            download_mock.call_args.args[0],
            "https://demo.langcore.cn/api/file/business-template.docx",
        )
        extract_mock.assert_called_once()
        self.assertTrue(extract_mock.call_args.args[0].name.endswith(".docx"))
        self.assertEqual(extract_mock.call_args.kwargs["template_type"], "business")

    def test_fill_bid_template_accepts_items_json_and_user_inputs(self) -> None:
        client = TestClient(fastapi_backend.app)
        with TemporaryDirectory() as tmpdir:
            template_path = Path(tmpdir) / "商务标模版.docx"
            output_path = Path(tmpdir) / "已填充.docx"
            template_path.write_bytes(b"fake-docx")

            items_json = {
                "template_path": str(template_path),
                "items": [
                    {
                        "item_id": "business_001",
                        "field_name": "投标人名称",
                        "locator": {"block_type": "paragraph_colon"},
                    },
                    {
                        "item_id": "business_002",
                        "field_name": "联系人",
                        "locator": {"block_type": "paragraph_colon"},
                    },
                ],
            }

            def fake_fill_template(template_arg, items_arg, answers_arg, output_arg, *, missing_marker):
                Path(output_arg).write_bytes(b"filled")
                return Path(output_arg)

            with (
                patch.object(
                    fastapi_backend,
                    "fill_template",
                    side_effect=fake_fill_template,
                ) as fill_mock,
                patch.object(
                    fastapi_backend,
                    "upload_docx_to_platform",
                    return_value="https://demo.langcore.cn/api/file/filled-business",
                ) as upload_mock,
                patch.dict("os.environ", {"PLATFORM_KEY": "test-platform-key"}),
            ):
                response = client.post(
                    "/api/fill-bid-template",
                    json={
                        "items_json": items_json,
                        "user_inputs": {"business_001": "航天晨光股份有限公司"},
                        "selected_item_ids": ["business_001"],
                        "output_path": str(output_path),
                    },
                )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["items_count"], 1)
        self.assertEqual(payload["answers_count"], 1)
        self.assertEqual(payload["output_path"], str(output_path.resolve()))
        self.assertEqual(
            payload["filled_template_url"],
            "https://demo.langcore.cn/api/file/filled-business",
        )
        self.assertGreaterEqual(len(payload["fill_logs"]), 5)
        self.assertEqual(payload["fill_logs"][-1]["step"], "upload")
        self.assertTrue(Path(payload["items_input_path"]).exists())
        self.assertTrue(Path(payload["answers_input_path"]).exists())

        fill_mock.assert_called_once()
        self.assertEqual(fill_mock.call_args.args[0], template_path.resolve())
        self.assertEqual(
            fill_mock.call_args.args[1]["items"],
            [items_json["items"][0]],
        )
        self.assertEqual(
            fill_mock.call_args.args[2],
            {"answers": [{"item_id": "business_001", "status": "filled", "value": "航天晨光股份有限公司"}]},
        )
        self.assertEqual(fill_mock.call_args.args[3], output_path.resolve())
        self.assertEqual(fill_mock.call_args.kwargs["missing_marker"], "【待确认】")
        upload_mock.assert_called_once_with(
            output_path.resolve(),
            upload_base_url=fastapi_backend.DEFAULT_UPLOAD_BASE_URL,
            platform_key="test-platform-key",
        )

    def test_user_inputs_match_field_names_by_common_suffixes(self) -> None:
        items_json = {
            "items": [
                {"item_id": "business_001", "field_name": "投标人名称"},
                {"item_id": "business_002", "field_name": "备案编号"},
                {"item_id": "business_003", "field_name": "联系人"},
            ]
        }

        answers = fastapi_backend._answers_from_user_inputs(
            items_json,
            {"投标人": "航天晨光股份有限公司", "备案号": "BA-2026-001"},
        )

        self.assertEqual(
            answers,
            {
                "answers": [
                    {"item_id": "business_001", "status": "filled", "value": "航天晨光股份有限公司"},
                    {"item_id": "business_002", "status": "filled", "value": "BA-2026-001"},
                    {"item_id": "business_003", "status": "manual_confirm", "value": ""},
                ]
            },
        )

    def test_user_input_list_with_values_becomes_filled_answers(self) -> None:
        items_json = {
            "items": [
                {"item_id": "business_001", "field_name": "投标人名称"},
                {"item_id": "business_002", "field_name": "联系人"},
            ]
        }

        answers = fastapi_backend._answers_from_user_inputs(
            items_json,
            [
                {"item_id": "business_001", "field_name": "投标人名称", "value": "航天晨光股份有限公司"},
                {"item_id": "business_002", "field_name": "联系人", "value": ""},
            ],
        )

        self.assertEqual(
            answers,
            {
                "answers": [
                    {"item_id": "business_001", "status": "filled", "value": "航天晨光股份有限公司"},
                    {"item_id": "business_002", "status": "manual_confirm", "value": ""},
                ]
            },
        )

    def test_image_placeholder_answers_use_left_right_side_when_names_are_shared(self) -> None:
        items_json = {
            "items": [
                {
                    "item_id": "business_001",
                    "field_name": "法定代表人（单位负责人）身份证复印件",
                    "field_type": "image",
                    "locator": {"block_type": "image_placeholder", "shape_index": 0},
                },
                {
                    "item_id": "business_002",
                    "field_name": "法定代表人（单位负责人）身份证复印件",
                    "field_type": "image",
                    "locator": {"block_type": "image_placeholder", "shape_index": 1},
                },
            ]
        }

        answers = fastapi_backend._answers_from_user_inputs(
            items_json,
            {
                "法定代表人（单位负责人）身份证复印件正面": "front.png",
                "法定代表人（单位负责人）身份证复印件反面": "back.png",
            },
        )

        self.assertEqual(
            answers,
            {
                "answers": [
                    {"item_id": "business_001", "status": "filled", "value": "front.png"},
                    {"item_id": "business_002", "status": "filled", "value": "back.png"},
                ]
            },
        )


if __name__ == "__main__":
    unittest.main()
