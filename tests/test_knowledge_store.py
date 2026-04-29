from __future__ import annotations

import json
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from scripts import knowledge_store


class KnowledgeStoreJsonTest(unittest.TestCase):
    def test_items_are_persisted_to_local_json_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / "knowledge_items.json"

            with patch.object(knowledge_store, "DATA_FILE", data_file):
                created = knowledge_store.create_item(
                    name="企业简介",
                    item_type="TEXT",
                    content="航天晨光股份有限公司",
                    image_url="",
                    file_name="",
                )

                self.assertTrue(created["id"].startswith("kb_"))
                self.assertEqual(
                    json.loads(data_file.read_text(encoding="utf-8")),
                    [created],
                )
                self.assertEqual(knowledge_store.list_items(), [created])

                updated = knowledge_store.update_item(
                    created["id"],
                    name="企业简介更新",
                    item_type="TEXT",
                    content="更新后的内容",
                    image_url="/knowledge-images/seal.png",
                    file_name="seal.png",
                )

                self.assertEqual(updated["name"], "企业简介更新")
                self.assertEqual(
                    json.loads(data_file.read_text(encoding="utf-8")),
                    [updated],
                )

                knowledge_store.delete_item(created["id"])

                self.assertEqual(json.loads(data_file.read_text(encoding="utf-8")), [])


if __name__ == "__main__":
    unittest.main()
