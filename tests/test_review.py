import unittest

from thync.review import build_review, commentable

DIFF = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -10,2 +10,3 @@ def f():
 keep = 1
+added = 2
 tail = 3
diff --git a/gone.py b/gone.py
--- a/gone.py
+++ /dev/null
@@ -1 +0,0 @@
-x = 1
"""


class ReviewTest(unittest.TestCase):
    def test_commentable_lines_are_new_side_only(self):
        self.assertEqual(commentable(DIFF), {("app.py", 10): "keep = 1", ("app.py", 11): "added = 2", ("app.py", 12): "tail = 3"})

    def test_lines_outside_the_diff_move_into_the_body(self):
        payload = build_review({"body": "요약", "comments": [
            {"path": "app.py", "line": 11, "body": "🔵 이름"},
            {"path": "app.py", "line": 99, "body": "🟡 밖"},
            {"path": "gone.py", "line": "1", "body": "🔵 지운 파일"}]}, DIFF, False, True)
        self.assertEqual([(c["path"], c["line"]) for c in payload["comments"]], [("app.py", 11)])
        self.assertIn("`app.py:99` 🟡 밖", payload["body"])
        self.assertEqual(payload["event"], "COMMENT")

    def test_approve_only_when_asked_complete_and_clean(self):
        blue = {"body": "지적 없음", "comments": [{"path": "app.py", "line": 10, "body": "🔵 취향"}]}
        self.assertEqual(build_review(blue, DIFF, False, True)["event"], "APPROVE")
        self.assertEqual(build_review(blue, DIFF, False, False)["event"], "COMMENT")
        self.assertEqual(build_review(blue, DIFF, True, True)["event"], "COMMENT")  # diff was cut
        hidden = {"body": "x" * 70_000 + "🔴", "comments": [{"path": "a", "line": 1, "body": "🔵"}] * 30
                  + [{"path": "a", "line": 1, "body": "🟡 31번째"}]}
        self.assertEqual(build_review(hidden, DIFF, False, True)["event"], "COMMENT")

    def test_added_line_that_looks_like_a_header(self):
        diff = "+++ b/a.py\n@@ -1,0 +1,3 @@\n+x\n+++ b/evil\n+y\n+++ b/c d.py\t\n@@ -0,0 +1 @@\n+z\n"
        self.assertEqual(commentable(diff), {("a.py", 1): "x", ("a.py", 2): "++ b/evil", ("a.py", 3): "y", ("c d.py", 1): "z"})


if __name__ == "__main__":
    unittest.main()
