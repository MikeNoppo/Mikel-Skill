import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import zlib
import struct
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL / "scripts"
FIXTURE = SKILL / "test" / "fixtures" / "report.json"
SID = "11111111-2222-3333-4444-555555555555"
FAKE_CODEX = """#!/usr/bin/python3
import json, os, sys
args = sys.argv
report = json.load(open(os.environ["FAKE_REPORT"]))
report["skip"] = os.environ.get("FAKE_SKIP") == "1"
json.dump(report, open(args[args.index("-o") + 1], "w"))
json.dump(args, open(os.environ["FAKE_ARGS"], "w"))
"""


def png():
    rows = b"".join(b"\x00" + b"\x12\x7a\x4a" * 4 for _ in range(4))
    chunk = lambda kind, data: struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def wait_for(check, seconds=20):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if check():
            return True
        time.sleep(0.1)
    return False


class SessionReportTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sr-test.")
        self.base = Path(self.temporary.name)
        self.assertTrue(str(self.base).startswith(tempfile.gettempdir() + "/sr-test."))
        self.reports = self.base / "reports"
        self.repo = self.base / "SI-ISPO-BE"
        (self.repo / "auth").mkdir(parents=True)
        self.env = {**os.environ, "SESSION_REPORT_DIR": str(self.reports), "SESSION_REPORT_NOTIFY": "0", "SESSION_REPORT_DELAY": "0"}
        self.env.pop("SESSION_REPORT_CHILD", None)
        self.git("init", "-q", "-b", "develop")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "test")
        (self.repo / "auth" / "login.go").write_text("package auth\n\nfunc Login() {}\n")
        self.git("add", ".")
        self.git("commit", "-qm", "feat: base")
        (self.repo / "shot.png").write_bytes(png())

    def tearDown(self):
        self.temporary.cleanup()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True, text=True).stdout.strip()

    def run_script(self, name, payload=None, *args, env=None, cwd=None):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / name), *args],
            input=json.dumps(payload) if payload is not None else "",
            capture_output=True,
            text=True,
            env=env or self.env,
            cwd=cwd or self.repo,
        )

    def track(self, tool_name, tool_input, sid=SID):
        result = self.run_script("track.py", {"session_id": sid, "cwd": str(self.repo), "tool_name": tool_name, "tool_input": tool_input})
        self.assertEqual(result.returncode, 0, result.stderr)

    def gate(self, harness="claude", **fields):
        payload = {"session_id": SID, "cwd": str(self.repo), "hook_event_name": "Stop", "stop_hook_active": False, "permission_mode": "default", **fields}
        result = self.run_script("gate.py", payload, "--harness", harness)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def meta(self, sid=SID):
        path = self.reports / ".state" / f"{sid}.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def journal(self, sid=SID):
        path = self.reports / ".state" / f"{sid}.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def edit_login(self):
        (self.repo / "auth" / "login.go").write_text("package auth\n\nfunc Login() error { return challenge() }\n")
        self.track("Edit", {"file_path": str(self.repo / "auth" / "login.go")})

    def write_report(self, **changes):
        report = json.loads(FIXTURE.read_text())
        report.update(changes)
        path = self.base / f"report-{len(list(self.base.glob('report-*')))}.json"
        path.write_text(json.dumps(report))
        return path

    def render(self, report_path, session=SID):
        return self.run_script("render.py", None, session, str(report_path))

    def test_gate_stays_quiet_without_changes(self):
        self.assertEqual(self.gate(), {})

    def test_gate_ignores_plan_mode_hook_reentry_and_child(self):
        self.edit_login()
        self.assertEqual(self.gate(permission_mode="plan"), {})
        self.assertEqual(self.gate(stop_hook_active=True), {})
        result = self.run_script("gate.py", {"session_id": SID, "cwd": str(self.repo)}, env={**self.env, "SESSION_REPORT_CHILD": "1"})
        self.assertEqual(json.loads(result.stdout), {})

    def test_gate_rejects_unsafe_session_ids(self):
        self.edit_login()
        result = self.run_script("gate.py", {"session_id": "../../etc", "cwd": str(self.repo)})
        self.assertEqual(json.loads(result.stdout), {})

    def test_gate_blocks_once_per_new_change(self):
        self.edit_login()
        output = self.gate()
        self.assertEqual(output["decision"], "block")
        self.assertIn(SID, output["reason"])
        self.assertIn('subagent_type "fork"', output["reason"])
        self.track("Agent", {"description": "session-report", "subagent_type": "fork", "prompt": "..."})
        self.assertEqual(self.gate(), {})
        self.track("Edit", {"file_path": str(self.repo / "auth" / "login.go")})
        self.assertEqual(self.gate()["decision"], "block")

    def test_gate_waits_while_a_report_agent_runs(self):
        self.edit_login()
        self.assertEqual(self.gate(background_tasks=[{"description": "session-report", "status": "running"}]), {})

    def test_track_ignores_report_files_and_other_agents(self):
        self.track("Write", {"file_path": str(self.reports / SID / "report-1.json")})
        self.track("Agent", {"description": "explore auth", "subagent_type": "Explore"})
        self.assertEqual(self.journal(), [])

    def test_track_reads_apply_patch_paths(self):
        patch = "*** Begin Patch\n*** Update File: auth/login.go\n@@\n-x\n+y\n*** Add File: auth/mfa.go\n+package auth\n*** End Patch"
        self.track("apply_patch", {"command": patch})
        paths = [event["path"] for event in self.journal()]
        self.assertEqual(paths, [str(self.repo / "auth" / "login.go"), str(self.repo / "auth" / "mfa.go")])
        self.assertIn(str(self.repo), self.meta()["repos"])

    def test_track_commit_in_unknown_repo_uses_previous_head(self):
        base = self.git("rev-parse", "HEAD")
        (self.repo / "auth" / "login.go").write_text("package auth\n")
        self.git("commit", "-qam", "feat(auth): change")
        self.track("Bash", {"command": "git -C . commit -am 'feat(auth): change'"})
        self.assertEqual(self.journal()[0]["kind"], "git")
        self.assertEqual(self.meta()["repos"][str(self.repo)]["base"], base)

    def test_track_counts_review_findings(self):
        self.track("ReportFindings", {"findings": []})
        self.assertEqual(self.journal()[0]["kind"], "review")
        self.assertEqual(self.gate()["decision"], "block")

    def test_render_full_report(self):
        self.edit_login()
        self.git("commit", "-qam", "feat(auth): return a challenge at sign-in")
        self.track("Bash", {"command": "git commit -am 'feat(auth): return a challenge at sign-in'"})
        (self.repo / "auth" / "mfa.go").write_text("package auth\n\nfunc challenge() error { return nil }\n")
        self.track("Write", {"file_path": str(self.repo / "auth" / "mfa.go")})
        result = self.render(self.write_report())
        self.assertEqual(result.returncode, 0, result.stderr)
        html_path = Path(result.stdout.strip())
        self.assertEqual(html_path, self.reports / f"SI-ISPO-BE-{SID[:8]}.html")
        page = html_path.read_text()
        for anchor in ("ringkasan", "keputusan", "dibuat", "arsitektur", "alur", "siklus", "implementasi", "file", "review", "pengujian", "e2e", "tradeoff", "luar", "lanjut"):
            self.assertIn(f'<section id="{anchor}">', page)
        self.assertLess(page.index('id="ringkasan"'), page.index('id="keputusan"'))
        self.assertLess(page.index('id="keputusan"'), page.index('id="dibuat"'))
        self.assertEqual(page.count("data:image/png;base64,"), 1)
        self.assertIn("feat(auth): return a challenge at sign-in", page)
        self.assertIn('<span class="a">+func Login() error { return challenge() }</span>', page)
        self.assertIn('<span class="a">+func challenge() error { return nil }</span>', page)
        self.assertIn("1 file belum di-commit", page)
        self.assertIn("2 keputusan menunggu kamu", page)
        self.assertIn("Alur lama", page)
        self.assertEqual(os.readlink(self.reports / "latest.html"), html_path.name)
        self.assertIn(html_path.name, (self.reports / "index.html").read_text())
        self.assertEqual(self.meta()["decisions"], 2)

    def test_render_hides_optional_sections_and_flags_missing_evidence(self):
        self.edit_login()
        report = self.write_report(
            decisions=[],
            architecture=None,
            flows=[],
            lifecycle=[],
            e2e=None,
            tests=[],
            code_review={"ran": False, "source": "", "findings": []},
        )
        page = Path(self.render(report).stdout.strip()).read_text()
        for anchor in ("arsitektur", "alur", "siklus", "e2e"):
            self.assertNotIn(f'<section id="{anchor}">', page)
        self.assertIn("Tidak ada keputusan tertunda", page)
        self.assertIn("Belum ada code review di sesi ini", page)
        self.assertIn("Tidak ada test, build, atau lint", page)

    def test_render_api_only_e2e_has_no_screenshot(self):
        self.edit_login()
        fixture = json.loads(FIXTURE.read_text())
        steps = [step for step in fixture["e2e"]["steps"] if not step["screenshot"]]
        report = self.write_report(e2e={**fixture["e2e"], "steps": steps})
        page = Path(self.render(report).stdout.strip()).read_text()
        self.assertIn("POST /cms/auth/mfa/verify dengan kode 000000", page)
        self.assertNotIn("data:image", page)

    def test_render_notifies_through_omarchy_with_a_glyph(self):
        bin_dir = self.base / "bin"
        bin_dir.mkdir()
        log = self.base / "notify.log"
        for name in ("omarchy-notification-send", "omarchy-launch-browser"):
            (bin_dir / name).write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > {log}\n' if name == "omarchy-notification-send" else "#!/bin/sh\n")
            (bin_dir / name).chmod(0o755)
        self.edit_login()
        env = {**self.env, "SESSION_REPORT_NOTIFY": "1", "PATH": f"{bin_dir}:{os.environ['PATH']}"}
        result = self.run_script("render.py", None, SID, str(self.write_report()), env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(wait_for(log.exists, 5))
        args = log.read_text().splitlines()
        self.assertEqual(args[args.index("-g") + 1], "\U000F0219")
        self.assertIn("SI-ISPO-BE: Hampir siap", args)
        self.assertEqual(args[args.index("--exec") + 1:], ["omarchy-launch-browser", Path(result.stdout.strip()).as_uri()])

    def test_render_rejects_invalid_report(self):
        report = self.write_report(status="done")
        data = json.loads(report.read_text())
        del data["tradeoffs"]
        report.write_text(json.dumps(data))
        result = self.render(report)
        self.assertEqual(result.returncode, 2)
        self.assertIn("$.status: 'done' is not one of", result.stderr)
        self.assertIn("$: missing field tradeoffs", result.stderr)

    def test_render_auto_picks_the_session_for_this_repo(self):
        self.edit_login()
        result = self.render(self.write_report(), session="auto")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(SID[:8], result.stdout)

    def run_codex(self, skip):
        fake = self.base / "codex"
        fake.write_text(FAKE_CODEX)
        fake.chmod(0o755)
        args = self.base / "codex-args.json"
        self.env.update({"SESSION_REPORT_CODEX_BIN": str(fake), "FAKE_REPORT": str(FIXTURE), "FAKE_SKIP": "1" if skip else "0", "FAKE_ARGS": str(args)})
        self.edit_login()
        self.assertEqual(self.gate("codex"), {})
        self.assertTrue(wait_for(lambda: args.exists() and "worker_pid" not in self.meta()), (self.reports / SID / "worker.log").read_text())
        return json.loads(args.read_text())

    def test_codex_worker_forks_read_only_and_renders(self):
        args = self.run_codex(skip=False)
        self.assertEqual(args[1:4], ["exec", "fork", SID])
        for flag in ("--ephemeral", 'sandbox_mode="read-only"', "--output-schema"):
            self.assertIn(flag, args)
        self.assertTrue((self.reports / f"SI-ISPO-BE-{SID[:8]}.html").exists())
        self.assertEqual(self.meta()["spawned_count"], 1)
        self.assertEqual(self.gate("codex"), {})

    def test_codex_skip_rearms_the_gate(self):
        self.run_codex(skip=True)
        self.assertFalse((self.reports / f"SI-ISPO-BE-{SID[:8]}.html").exists())
        self.assertEqual(self.meta()["spawned_count"], 0)

    def test_install_merges_hooks_once_and_keeps_settings(self):
        home = self.base / "home"
        settings = home / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        original = {"env": {"A": "1"}, "permissions": {"allow": ["Bash(git *)"]}, "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "other"}]}]}}
        settings.write_text(json.dumps(original))
        settings.chmod(0o600)
        env = {**self.env, "HOME": str(home)}
        for _ in range(2):
            result = self.run_script("install.py", None, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("already installed", result.stdout)
        claude = json.loads(settings.read_text())
        self.assertEqual(settings.stat().st_mode & 0o777, 0o600)
        self.assertEqual(claude["env"], {"A": "1"})
        self.assertEqual(claude["permissions"]["allow"][0], "Bash(git *)")
        self.assertIn("Edit(//tmp/session-reports/**)", claude["permissions"]["allow"])
        self.assertEqual(len(claude["hooks"]["Stop"]), 2)
        self.assertEqual(len(claude["hooks"]["PostToolUse"]), 1)
        self.assertEqual(json.loads((home / ".claude" / "settings.json.bak-session-report").read_text()), original)
        codex = json.loads((home / ".codex" / "hooks.json").read_text())
        self.assertIn("--harness codex", codex["hooks"]["Stop"][0]["hooks"][0]["command"])
        self.assertEqual(codex["hooks"]["PostToolUse"][0]["matcher"], "apply_patch|Edit|Write|Bash")


if __name__ == "__main__":
    unittest.main()
