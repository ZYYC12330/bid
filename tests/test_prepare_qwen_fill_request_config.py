from __future__ import annotations

import importlib
import unittest
from unittest.mock import patch

from scripts import prepare_qwen_fill_request


class PrepareQwenFillRequestConfigTest(unittest.TestCase):
    def test_base_url_can_be_configured_by_environment(self) -> None:
        with patch.dict("os.environ", {"LLM_BASE_URL": "http://10.25.1.48/v1"}):
            reloaded = importlib.reload(prepare_qwen_fill_request)

        self.assertEqual(reloaded.BASE_URL, "http://10.25.1.48/v1")
        importlib.reload(prepare_qwen_fill_request)

    def test_llm_api_key_is_supported_as_primary_key_name(self) -> None:
        self.assertEqual(
            prepare_qwen_fill_request.get_api_key(
                env={
                    "LLM_API_KEY": "inner-net-key",
                    "DASHSCOPE_API_KEY": "dashscope-key",
                    "OPENAI_API_KEY": "openai-key",
                }
            ),
            "inner-net-key",
        )
