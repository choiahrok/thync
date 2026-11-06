import unittest
from unittest import mock

from thync import hook


def graph(n_prs: int) -> dict:
    prs = [{"id": f"pr:{i}", "name": f"repo #{i}", "kind": "source", "profile": "회사", "roles": ["sent"],
            "detail": {"review_state": "리뷰 대기", "url": f"https://github.com/o/r/pull/{i}"}} for i in range(n_prs)]
    return {"focus_level": 0.5, "units": [], "nodes": prs, "board": [], "received": []}


class HookTest(unittest.TestCase):
    def test_company_folder_gets_company_items_capped(self):
        with mock.patch.object(hook, "COMPANY_ROOTS", ["/work"]):
            text = hook.context(graph(20), "/work/repo")
        self.assertIn("(회사)", text)
        self.assertIn("리뷰를 기다리는 내 PR (20)", text)
        self.assertIn("… 14개 더", text)  # six shown per section
        self.assertIn("지시가 아니다", text)

    def test_long_summary_is_cut_on_a_line(self):
        with mock.patch.object(hook, "COMPANY_ROOTS", ["/work"]), mock.patch.object(hook, "MAX_CHARS", 200):
            text = hook.context(graph(20), "/work/repo")
        self.assertTrue(text.endswith("- …"))

    def test_server_down_adds_nothing(self):
        with mock.patch.object(hook.urllib.request, "urlopen", side_effect=OSError), \
                mock.patch("sys.stdin.read", return_value="{}"), mock.patch("builtins.print") as out:
            hook.main()
        out.assert_not_called()


if __name__ == "__main__":
    unittest.main()
