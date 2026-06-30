#!/usr/bin/env python3
"""patch 09 회귀: cwd_path_scope가 편집 도구(Edit/MultiEdit/Write)의 file_path도 인식한다.

기존 test_smoke.TestCwdPathScope는 셸(command) 경로만 검증한다. 본 모듈은
command 키가 없는 편집 도구가 file_path로 cwd 안/밖을 판정받는지(Fix A) 검증한다.
dist/ 산출물을 subprocess hook으로 end-to-end 실행한다.
"""
import unittest

from test_smoke import Base

RULE = (
    "---\nname: fp-block\nenabled: true\nevent: file\naction: block\n"
    "tool_matcher: Edit|MultiEdit\n"
    "cwd_path_scope: true\n"
    "conditions:\n  - field: file_path\n    operator: regex_match\n    pattern: \\.cs$\n"
    "---\nFP SCOPED\n"
)


class TestCwdPathScopeFilePath(Base):
    def _run(self, tool_name, tool_input):
        self.write_rule(self.proj, "hookify.fp.local.md", RULE)
        return self.run_hook("pretooluse.py", {
            "hook_event_name": "PreToolUse", "tool_name": tool_name,
            "tool_input": tool_input, "cwd": str(self.proj),
        })

    def test_edit_inside_cwd_blocks(self):
        out = self._run("Edit", {"file_path": str(self.proj / "Foo.cs"),
                                 "old_string": "a", "new_string": "b"})
        self.assertIn("hookSpecificOutput", out)

    def test_edit_outside_cwd_skips(self):
        out = self._run("Edit", {"file_path": str(self.home / "Foo.cs"),
                                 "old_string": "a", "new_string": "b"})
        self.assertEqual(out, {})

    def test_multiedit_inside_cwd_blocks(self):
        out = self._run("MultiEdit", {"file_path": str(self.proj / "sub" / "Bar.cs"),
                                      "edits": []})
        self.assertIn("hookSpecificOutput", out)

    def test_inside_cwd_but_condition_mismatch_skips(self):
        out = self._run("Edit", {"file_path": str(self.proj / "Foo.txt"),
                                 "old_string": "a", "new_string": "b"})
        self.assertEqual(out, {})


if __name__ == "__main__":
    unittest.main()
