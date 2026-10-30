"""Kanban cards as Markdown files: python3 -m unittest discover tests"""
import os
import tempfile
import unittest

os.environ["THYNC_HOME"] = tempfile.mkdtemp()  # before importing thync, so nothing touches the real home

from thync import store  # noqa: E402


class CardFiles(unittest.TestCase):
    def setUp(self):
        for p in store.CARDS_DIR.glob("*.md"):
            p.unlink()

    def test_write_read_and_reset(self):
        store.save_card("jira:ABC-1", {"column": "done", "title": "제목", "note": "메모\n둘째 줄"})
        card = store.read_cards()["jira:ABC-1"]
        self.assertEqual(card["meta"], {"id": "jira:ABC-1", "title": "제목", "column": "done"})
        self.assertEqual(card["note"], "메모\n둘째 줄")
        # Clearing column, title and note removes the file.
        store.save_card("jira:ABC-1", {"reset": True, "title": "", "note": ""})
        self.assertEqual(list(store.CARDS_DIR.glob("*.md")), [])

    def test_hand_made_file_becomes_a_card(self):
        store.CARDS_DIR.mkdir(parents=True, exist_ok=True)
        (store.CARDS_DIR / "hand.md").write_text("---\ntitle: 손으로 만든 카드\ncolumn: doing\n---\n본문\n", encoding="utf-8")
        card = store.read_cards()["manual:hand"]
        self.assertEqual((card["meta"]["column"], card["note"]), ("doing", "본문"))
        store.save_card("manual:hand", {"column": "done"})
        self.assertTrue((store.CARDS_DIR / "hand.md").exists())
        self.assertEqual(store.read_cards()["manual:hand"]["meta"]["column"], "done")


if __name__ == "__main__":
    unittest.main()
