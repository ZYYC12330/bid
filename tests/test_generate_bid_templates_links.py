from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import generate_bid_templates


class GenerateTemplateLinksTest(unittest.TestCase):
    def test_generate_template_links_uploads_both_generated_templates(self) -> None:
        with TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "招标文件.docx"
            business_path = Path(tmpdir) / "outputs" / "招标文件_商务标模版.docx"
            technical_path = Path(tmpdir) / "outputs" / "招标文件_技术标模版.docx"
            input_path.write_bytes(b"input")
            business_path.parent.mkdir(parents=True)
            business_path.write_bytes(b"business")
            technical_path.write_bytes(b"technical")

            with (
                patch.object(
                    generate_bid_templates,
                    "generate_templates",
                    return_value=(business_path, technical_path),
                ) as generate_mock,
                patch.object(
                    generate_bid_templates,
                    "upload_docx_to_platform",
                    side_effect=[
                        "https://demo.langcore.cn/api/file/business",
                        "https://demo.langcore.cn/api/file/technical",
                    ],
                ) as upload_mock,
            ):
                links = generate_bid_templates.generate_template_links(
                    input_path,
                    output_dir=None,
                    upload_base_url="https://demo.langcore.cn/",
                    platform_key="test-key",
                )

        self.assertEqual(
            links,
            {
                "business_template_url": "https://demo.langcore.cn/api/file/business",
                "technical_template_url": "https://demo.langcore.cn/api/file/technical",
            },
        )
        generate_mock.assert_called_once_with(input_path, None, verbose=False)
        self.assertEqual(upload_mock.call_count, 2)
        self.assertEqual(upload_mock.call_args_list[0].args[0], business_path)
        self.assertEqual(upload_mock.call_args_list[1].args[0], technical_path)

    def test_generate_template_links_requires_platform_key(self) -> None:
        with TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "招标文件.docx"
            business_path = Path(tmpdir) / "outputs" / "招标文件_商务标模版.docx"
            technical_path = Path(tmpdir) / "outputs" / "招标文件_技术标模版.docx"
            input_path.write_bytes(b"input")

            with (
                patch.object(
                    generate_bid_templates,
                    "generate_templates",
                    return_value=(business_path, technical_path),
                ),
                patch.dict("os.environ", {"PLATFORM_KEY": ""}, clear=False),
            ):
                with self.assertRaisesRegex(RuntimeError, "PLATFORM_KEY"):
                    generate_bid_templates.generate_template_links(input_path)


if __name__ == "__main__":
    unittest.main()
