#!/usr/bin/env python3
"""hookify-global 회귀 스모크 테스트.

dist/ 산출물을 대상으로 한다. 실행 전 `python3 build.py`로 dist를 생성하라.
각 테스트는 임시 HOME·임시 cwd를 쓰고 실제 ~/.claude를 건드리지 않는다.
hook 동작은 dist의 실제 hook 스크립트를 subprocess로 실행해 end-to-end로 검증한다.
표준 라이브러리만 사용한다.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DIST = REPO / "dist"
HOOKS = DIST / "hooks"


def make_rule(name, event, action, field, operator, pattern, message):
    """단일 조건 규칙 마크다운을 생성한다."""
    return (
        "---\n"
        f"name: {name}\n"
        "enabled: true\n"
        f"event: {event}\n"
        f"action: {action}\n"
        "conditions:\n"
        f"  - field: {field}\n"
        f"    operator: {operator}\n"
        f"    pattern: {pattern}\n"
        "---\n"
        f"{message}\n"
    )


class Base(unittest.TestCase):
    def setUp(self):
        if not DIST.is_dir():
            self.skipTest("dist/ 없음 — 먼저 'python3 build.py' 실행")
        self.tmp = Path(tempfile.mkdtemp(prefix="hookify-test-"))
        self.home = self.tmp / "home"
        self.proj = self.tmp / "proj"
        (self.home / ".claude").mkdir(parents=True)
        (self.proj / ".claude").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_rule(self, base, fname, content):
        (base / ".claude" / fname).write_text(content, encoding="utf-8", newline="\n")

    def env(self, home=None):
        e = dict(os.environ)
        h = str(home or self.home)
        e["HOME"] = h
        e["USERPROFILE"] = h  # Windows expanduser는 USERPROFILE을 본다
        e["CLAUDE_PLUGIN_ROOT"] = str(DIST)
        e["PYTHONPATH"] = str(DIST)
        e["PYTHONIOENCODING"] = "utf-8"
        return e

    def load_rules(self, event=None, home=None):
        code = (
            "import json\n"
            "from core.config_loader import load_rules\n"
            f"ev = {event!r}\n"
            "rs = load_rules(ev) if ev else load_rules()\n"
            "print(json.dumps([{'name': r.name, 'message': r.message,"
            " 'event': r.event, 'action': r.action} for r in rs]))\n"
        )
        r = subprocess.run([sys.executable, "-c", code], cwd=str(self.proj),
                           env=self.env(home), capture_output=True, text=True,
                           encoding="utf-8")
        self.assertEqual(r.returncode, 0, f"load_rules 실패:\n{r.stderr}")
        return json.loads(r.stdout.strip() or "[]")

    def run_hook(self, script, input_data, home=None):
        r = subprocess.run([sys.executable, str(HOOKS / script)],
                           input=json.dumps(input_data), cwd=str(self.proj),
                           env=self.env(home), capture_output=True, text=True,
                           encoding="utf-8")
        self.assertEqual(r.returncode, 0, f"{script} 실패:\n{r.stderr}")
        out = r.stdout.strip()
        return json.loads(out) if out else {}


class TestEncoding(Base):
    def test_emoji_korean_preserved(self):
        msg = "⚠️ 위험한 명령 감지! 한글 메시지 보존 확인."
        self.write_rule(self.proj, "hookify.emoji.local.md",
                        make_rule("emoji-rule", "bash", "warn",
                                  "command", "contains", "danger", msg))
        rules = self.load_rules()
        self.assertEqual(len(rules), 1)
        self.assertIn("⚠️", rules[0]["message"])
        self.assertIn("한글 메시지 보존", rules[0]["message"])


class TestGlobalDedup(Base):
    def test_global_and_project_both_load(self):
        self.write_rule(self.home, "hookify.glob.global.md",
                        make_rule("global-rule", "all", "warn",
                                  "command", "contains", "g", "global msg"))
        self.write_rule(self.proj, "hookify.proj.local.md",
                        make_rule("project-rule", "all", "warn",
                                  "command", "contains", "p", "project msg"))
        rules = self.load_rules()
        self.assertEqual(sorted(r["name"] for r in rules),
                         ["global-rule", "project-rule"])

    def test_home_local_md_not_loaded(self):
        # 방법 1: 전역 규칙은 ~/.claude/hookify.*.global.md 만 로드한다.
        # 홈의 .local.md(옛 전역 파일명)는 더 이상 로드되지 않는다.
        self.write_rule(self.home, "hookify.old.local.md",
                        make_rule("old-global", "all", "warn",
                                  "command", "contains", "o", "old global msg"))
        self.write_rule(self.home, "hookify.new.global.md",
                        make_rule("new-global", "all", "warn",
                                  "command", "contains", "n", "new global msg"))
        rules = self.load_rules()
        names = [r["name"] for r in rules]
        self.assertIn("new-global", names)
        self.assertNotIn("old-global", names)


class TestReadEvent(Base):
    def setUp(self):
        super().setUp()
        self.write_rule(self.proj, "hookify.file.local.md",
                        make_rule("file-rule", "file", "warn",
                                  "file_path", "contains", "secret", "FILE RULE FIRED"))

    def test_read_does_not_fire(self):
        out = self.run_hook("pretooluse.py", {
            "hook_event_name": "PreToolUse", "tool_name": "Read",
            "tool_input": {"file_path": "/x/secret.txt"},
        })
        self.assertNotIn("systemMessage", out)

    def test_edit_fires(self):
        out = self.run_hook("pretooluse.py", {
            "hook_event_name": "PreToolUse", "tool_name": "Edit",
            "tool_input": {"file_path": "/x/secret.txt",
                           "old_string": "a", "new_string": "b"},
        })
        self.assertIn("systemMessage", out)
        self.assertIn("FILE RULE FIRED", out["systemMessage"])

    def test_glob_no_path_no_fire_no_crash(self):
        out = self.run_hook("pretooluse.py", {
            "hook_event_name": "PreToolUse", "tool_name": "Glob",
            "tool_input": {"pattern": "*.secret"},
        })
        self.assertEqual(out, {})


class TestReadEventExtraction(Base):
    """patch 05가 추가한 read 이벤트 발동 경로와 Glob path 추출 분기를 실제로 실행한다."""

    def setUp(self):
        super().setUp()
        self.write_rule(self.proj, "hookify.read.local.md",
                        make_rule("read-rule", "read", "warn",
                                  "file_path", "contains", "secret", "READ RULE FIRED"))

    def test_read_rule_fires_on_read(self):
        out = self.run_hook("pretooluse.py", {
            "hook_event_name": "PreToolUse", "tool_name": "Read",
            "tool_input": {"file_path": "/x/secret.txt"},
        })
        self.assertIn("systemMessage", out)
        self.assertIn("READ RULE FIRED", out["systemMessage"])

    def test_glob_with_path_fires(self):
        out = self.run_hook("pretooluse.py", {
            "hook_event_name": "PreToolUse", "tool_name": "Glob",
            "tool_input": {"path": "/x/secret", "pattern": "*"},
        })
        self.assertIn("systemMessage", out)

    def test_glob_without_path_no_fire_no_crash(self):
        # path 없는 Glob: _extract_field가 pattern을 경로로 오해하지 않고 None을 반환해
        # read 규칙이 평가는 되지만 미발동한다(분기가 실제 실행됨, NoneType 크래시 없음).
        out = self.run_hook("pretooluse.py", {
            "hook_event_name": "PreToolUse", "tool_name": "Glob",
            "tool_input": {"pattern": "*.secret"},
        })
        self.assertEqual(out, {})


class TestBlockReason(Base):
    def test_pretooluse_permission_decision_reason(self):
        self.write_rule(self.proj, "hookify.block.local.md",
                        make_rule("bash-block", "bash", "block",
                                  "command", "contains", "rm -rf", "BLOCK rm"))
        out = self.run_hook("pretooluse.py", {
            "hook_event_name": "PreToolUse", "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /tmp"},
        })
        self.assertIn("hookSpecificOutput", out)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("permissionDecisionReason", out["hookSpecificOutput"])
        self.assertIn("BLOCK rm", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_posttooluse_top_level_reason(self):
        self.write_rule(self.proj, "hookify.block.local.md",
                        make_rule("bash-block", "bash", "block",
                                  "command", "contains", "rm -rf", "BLOCK rm"))
        out = self.run_hook("posttooluse.py", {
            "hook_event_name": "PostToolUse", "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /tmp"},
        })
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("reason", out)
        self.assertNotIn("hookSpecificOutput", out)

    def test_stop_top_level_reason(self):
        self.write_rule(self.proj, "hookify.stop.local.md",
                        make_rule("stop-block", "stop", "block",
                                  "reason", "contains", "STOPME", "STOP blocked"))
        out = self.run_hook("stop.py", {
            "hook_event_name": "Stop", "reason": "please STOPME now",
        })
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("reason", out)
        self.assertNotIn("hookSpecificOutput", out)

    def test_userpromptsubmit_top_level_reason(self):
        self.write_rule(self.proj, "hookify.prompt.local.md",
                        make_rule("prompt-block", "prompt", "block",
                                  "user_prompt", "contains", "BADWORD", "PROMPT blocked"))
        out = self.run_hook("userpromptsubmit.py", {
            "hook_event_name": "UserPromptSubmit",
            "user_prompt": "this has BADWORD inside",
        })
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("reason", out)
        self.assertNotIn("permissionDecisionReason", json.dumps(out))


class TestHooksJson(Base):
    def test_hooks_json_valid_and_execform(self):
        data = json.loads((HOOKS / "hooks.json").read_text(encoding="utf-8"))
        events = data["hooks"]
        self.assertEqual(set(events),
                         {"PreToolUse", "PostToolUse", "Stop", "UserPromptSubmit"})
        for groups in events.values():
            for group in groups:
                for hook in group["hooks"]:
                    if hook.get("type") == "command":
                        self.assertIn("command", hook)
                        self.assertIn("args", hook)
                        self.assertIsInstance(hook["args"], list)
                        self.assertEqual(hook["command"], "python3")


class TestPy38Import(Base):
    def test_py38_import(self):
        exe = shutil.which("python3.8")
        if not exe:
            self.skipTest("python3.8 미설치")
        env = dict(os.environ)
        env["PYTHONPATH"] = str(DIST)
        env["PYTHONIOENCODING"] = "utf-8"
        r = subprocess.run([exe, "-c", "import core.config_loader"],
                           env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
