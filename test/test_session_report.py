import json
import hashlib
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
if len(args) > 1 and args[1] == "queue":
    json.dump(args, open(os.environ["FAKE_QUEUE_ARGS"], "w"))
    sys.exit(1 if os.environ.get("FAKE_QUEUE_FAIL") == "1" else 0)
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
        self.env = {**os.environ, "SESSION_REPORT_DIR": str(self.reports), "SESSION_REPORT_NOTIFY": "0", "SESSION_REPORT_DELAY": "0", "SESSION_REPORT_COOLDOWN": "0", "CLAUDE_CODE_SESSION_ID": SID, "FAKE_QUEUE_ARGS": str(self.base / "queue-args.json"), "SESSION_REPORT_CHAT": "1"}
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

    def track(self, tool_name, tool_input, sid=SID, event="PostToolUse"):
        result = self.run_script("track.py", {"session_id": sid, "cwd": str(self.repo), "hook_event_name": event, "tool_name": tool_name, "tool_input": tool_input})
        self.assertEqual(result.returncode, 0, result.stderr)

    def gate(self, harness="claude", **fields):
        payload = {"session_id": SID, "cwd": str(self.repo), "hook_event_name": "Stop", "stop_hook_active": False, "permission_mode": "default", **fields}
        result = self.run_script("gate.py", payload, "--harness", harness, *(["--check"] if harness == "claude" else []))
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def meta(self, sid=SID):
        path = self.reports / ".state" / f"{sid}.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def journal(self, sid=SID):
        path = self.reports / ".state" / f"{sid}.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def edit_login(self):
        self.track("Edit", {"file_path": str(self.repo / "auth" / "login.go")}, event="PreToolUse")
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
        self.assertEqual(output, {"ready": True})
        self.track("Agent", {"description": "session-report", "subagent_type": "fork", "run_in_background": True, "prompt": f"Read {SCRIPTS.parent / 'SKILL.md'}. Session id: {SID}"})
        self.assertEqual(self.gate(), {})
        self.track("Edit", {"file_path": str(self.repo / "auth" / "login.go")})
        self.assertEqual(self.gate(), {"ready": True})

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

    def test_read_only_git_text_does_not_capture_old_commit(self):
        self.track("Bash", {"command": 'rg "git commit" README.md'}, event="PreToolUse")
        self.track("Bash", {"command": 'rg "git commit" README.md'})
        self.assertEqual(self.journal(), [])
        self.assertEqual(self.gate(), {})
        self.assertEqual(self.meta()["repos"][str(self.repo)]["commits"], [])


    def test_track_counts_review_findings(self):
        self.track("ReportFindings", {"findings": []})
        self.assertEqual(self.journal()[0]["kind"], "review")
        self.assertEqual(self.gate(), {"ready": True})

    def test_render_full_report(self):
        self.edit_login()
        self.track("Bash", {"command": "git commit"}, event="PreToolUse")
        self.git("commit", "-qam", "feat(auth): return a challenge at sign-in")
        self.track("Bash", {"command": "git commit -am 'feat(auth): return a challenge at sign-in'"})
        (self.repo / "auth" / "mfa.go").write_text("package auth\n\nfunc challenge() error { return nil }\n")
        self.track("Write", {"file_path": str(self.repo / "auth" / "mfa.go")})
        result = self.render(self.write_report())
        self.assertEqual(result.returncode, 0, result.stderr)
        html_path = Path(result.stdout.strip())
        self.assertEqual(html_path, self.reports / f"SI-ISPO-BE-{hashlib.sha256(SID.encode()).hexdigest()[:12]}.html")
        page = html_path.read_text()
        for anchor in ("ringkasan", "keputusan", "dibuat", "arsitektur", "alur", "siklus", "implementasi", "file", "review", "pengujian", "e2e", "tradeoff", "luar", "lanjut"):
            self.assertIn(f'<section id="{anchor}">', page)
        self.assertLess(page.index('id="ringkasan"'), page.index('id="keputusan"'))
        self.assertLess(page.index('id="keputusan"'), page.index('id="dibuat"'))
        self.assertEqual(page.count('src="data:image/png;base64,'), 1)
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
        self.assertNotIn('src="data:image', page)

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
        self.assertIn(hashlib.sha256(SID.encode()).hexdigest()[:12], result.stdout)

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
        self.assertTrue((self.reports / f"SI-ISPO-BE-{hashlib.sha256(SID.encode()).hexdigest()[:12]}.html").exists())
        self.assertEqual(self.meta()["spawned_count"], 1)
        self.assertEqual(self.gate("codex"), {})

    def test_codex_report_is_queued_to_original_chat(self):
        self.run_codex(skip=False)
        queue = json.loads((self.base / "queue-args.json").read_text())
        self.assertEqual(queue[1], "queue")
        self.assertEqual(queue[queue.index("--thread")+1], SID)
        message = queue[queue.index("--message")+1]
        self.assertIn("[session-report:completed]", message)
        self.assertIn("Laporan sesi: [Buka laporan]", message)
        self.assertIn(self.meta()["html"], message)
        self.assertEqual(self.meta()["chat_delivered_report"], self.meta()["report"])

    def test_same_report_is_not_queued_twice(self):
        self.run_codex(skip=False)
        queued = self.base / "queue-args.json"
        before = queued.stat().st_mtime_ns
        code = "import sys;sys.path.insert(0,sys.argv[1]);import delivery;delivery.codex(sys.argv[2],sys.argv[3],sys.argv[4])"
        result = subprocess.run([sys.executable,"-c",code,str(SCRIPTS),SID,self.meta()["html"],str(self.base/"codex")], env=self.env,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(queued.stat().st_mtime_ns,before)

    def test_chat_can_be_disabled_independently(self):
        self.env["SESSION_REPORT_CHAT"] = "0"
        self.run_codex(skip=False)
        self.assertTrue(Path(self.meta()["html"]).exists())
        self.assertFalse((self.base / "queue-args.json").exists())

    def test_skip_has_no_chat_notification(self):
        self.run_codex(skip=True)
        self.assertFalse((self.base / "queue-args.json").exists())
        self.run_claude(skip=True)
        self.assertNotIn("session-report:completed", self.last_claude_gate.stderr)

    def test_failed_chat_delivery_keeps_html(self):
        self.env["FAKE_QUEUE_FAIL"] = "1"
        self.run_codex(skip=False)
        self.assertTrue(Path(self.meta()["html"]).exists())
        self.assertTrue(self.meta()["chat_delivery_error"])
        self.assertNotIn("chat_delivered_report", self.meta())

    def test_codex_skip_rearms_the_gate(self):
        self.run_codex(skip=True)
        self.assertFalse((self.reports / f"SI-ISPO-BE-{hashlib.sha256(SID.encode()).hexdigest()[:12]}.html").exists())
        self.assertEqual(self.meta()["spawned_count"], 0)

    def run_claude(self, skip=False, invalid=False):
        fake = self.base / "claude"
        args_path = self.base / "claude-args.json"
        fake.write_text("#!/usr/bin/python3\nimport json,os,sys\nargs=sys.argv\njson.dump(args,open(os.environ['FAKE_ARGS'],'w'))\nr=json.load(open(os.environ['FAKE_REPORT']))\nr['skip']=os.environ.get('FAKE_SKIP')=='1'\nprint(json.dumps({'is_error':False,'structured_output':r} if os.environ.get('FAKE_INVALID')!='1' else {'is_error':True}))\n")
        fake.chmod(0o755)
        self.env.update({"SESSION_REPORT_CLAUDE_BIN": str(fake), "FAKE_REPORT": str(FIXTURE),
                         "FAKE_ARGS": str(args_path), "FAKE_SKIP": "1" if skip else "0",
                         "FAKE_INVALID": "1" if invalid else "0", "CLAUDECODE": "1"})
        self.edit_login()
        result = self.run_script("gate.py", {"session_id":SID,"cwd":str(self.repo),"model":"claude-parent-test"}, "--harness", "claude")
        self.assertEqual(result.returncode, 0 if skip or invalid else 2, result.stderr)
        self.last_claude_gate = result
        self.assertTrue(wait_for(lambda: args_path.exists() and "worker_pid" not in self.meta()))
        return json.loads(args_path.read_text())

    def test_claude_worker_keeps_model_and_forces_low_effort(self):
        args = self.run_claude()
        self.assertEqual(args[args.index("--model")+1], "claude-parent-test")
        self.assertEqual(args[args.index("--effort")+1], "low")
        self.assertEqual(args[args.index("--resume")+1], SID)
        for flag in ("--fork-session", "--no-session-persistence", "--json-schema"):
            self.assertIn(flag,args)
        self.assertEqual(args[args.index("--tools")+1], "Read")
        self.assertEqual(self.meta()["harness"], "claude")
        self.assertTrue(Path(self.meta()["html"]).exists())
        self.assertIn("Laporan sesi: [Buka laporan]", self.last_claude_gate.stderr)
        self.assertEqual(self.gate(), {})

    def test_claude_skip_and_failed_output_rearm_without_report(self):
        self.run_claude(skip=True)
        self.assertNotIn("html", self.meta())
        self.assertEqual(self.meta()["spawned_count"], 0)
        self.run_claude(invalid=True)
        self.assertNotIn("html", self.meta())
        self.assertEqual(self.meta()["spawned_count"], 0)

    def test_claude_model_falls_back_to_transcript(self):
        transcript=self.base/"session.jsonl"
        transcript.write_text(json.dumps({"type":"assistant","message":{"model":"claude-original-test"}})+"\n")
        sys.path.insert(0,str(SCRIPTS))
        import gate
        self.assertEqual(gate.original_model({"transcript_path":str(transcript)}),"claude-original-test")
        self.assertEqual(gate.original_model({"model":"override-test","transcript_path":str(transcript)}),"override-test")

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
        self.assertTrue(claude["hooks"]["Stop"][1]["hooks"][0]["asyncRewake"])
        self.assertEqual(claude["hooks"]["Stop"][1]["hooks"][0]["timeout"], 1900)
        self.assertEqual(len(claude["hooks"]["PostToolUse"]), 1)
        self.assertEqual(json.loads((home / ".claude" / "settings.json.bak-session-report").read_text()), original)
        codex = json.loads((home / ".codex" / "hooks.json").read_text())
        self.assertIn("--harness codex", codex["hooks"]["Stop"][0]["hooks"][0]["command"])
        self.assertEqual(codex["hooks"]["PostToolUse"][0]["matcher"], "apply_patch|Edit|Write|Bash|exec_command|shell|local_shell")


    def test_manual_render_covers_changes_without_duplicate(self):
        self.edit_login()
        self.assertEqual(self.render(self.write_report()).returncode, 0)
        self.assertEqual(self.gate(), {})
        self.edit_login()
        self.assertEqual(self.gate(), {"ready": True})

    def commit_change(self, filename, contents, message):
        self.track("Bash", {"command": "git commit"}, event="PreToolUse")
        (self.repo / filename).write_text(contents)
        self.git("add", filename)
        self.git("commit", "-qm", message)
        self.track("Bash", {"command": "git commit"})

    def facts(self):
        sys.path.insert(0, str(SCRIPTS))
        import common
        import render
        previous = os.environ.get("SESSION_REPORT_DIR")
        os.environ["SESSION_REPORT_DIR"] = str(self.reports)
        try:
            return render.repo_facts(str(self.repo), self.meta().get("repos", {}).get(str(self.repo), {}), ["auth/login.go", "café.txt"])
        finally:
            if previous is None:
                os.environ.pop("SESSION_REPORT_DIR", None)
            else:
                os.environ["SESSION_REPORT_DIR"] = previous

    def test_initial_commit_is_session_work(self):
        self.repo = self.base / "unborn"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "test")
        self.git("config", "user.email", "test@example.com")
        self.commit_change("first.txt", "first\n", "feat(first): add first file")
        facts = self.facts()
        self.assertEqual(len(facts["commits"]), 1)
        self.assertEqual([f["path"] for f in facts["files"]], ["first.txt"])

    def test_merge_and_switch_do_not_claim_other_commits(self):
        self.git("switch", "-c", "upstream")
        (self.repo / "foreign.txt").write_text("foreign\n")
        self.git("add", "foreign.txt")
        self.git("commit", "-qm", "feat(other): foreign work")
        self.git("switch", "develop")
        self.edit_login()
        self.commit_change("own.txt", "own\n", "feat(own): add own file")
        self.track("Bash", {"command": "git switch upstream"}, event="PreToolUse")
        self.git("switch", "upstream")
        self.track("Bash", {"command": "git switch upstream"})
        self.assertEqual(self.facts()["commits"], [])
        self.git("switch", "develop")
        self.track("Bash", {"command": "git merge upstream"}, event="PreToolUse")
        self.git("merge", "--no-edit", "upstream")
        self.track("Bash", {"command": "git merge upstream"})
        facts = self.facts()
        self.assertEqual([c[1] for c in facts["commits"]], ["feat(own): add own file"])
        self.assertNotIn("foreign.txt", [f["path"] for f in facts["files"]])


    def test_rebase_keeps_only_session_patches(self):
        self.git("switch", "-c", "upstream")
        (self.repo / "foreign.txt").write_text("foreign\n")
        self.git("add", "foreign.txt")
        self.git("commit", "-qm", "feat(other): upstream change")
        self.git("switch", "develop")
        self.commit_change("own.txt", "mine\n", "feat(own): local change")
        self.track("Bash", {"command": "git rebase upstream"}, event="PreToolUse")
        self.git("rebase", "upstream")
        self.track("Bash", {"command": "git rebase upstream"})
        self.assertEqual([c[1] for c in self.facts()["commits"]], ["feat(own): local change"])
        self.assertNotIn("foreign.txt", [f["path"] for f in self.facts()["files"]])

    def test_shell_edit_in_known_other_repo_is_recorded(self):
        first = self.repo
        second = self.base / "other-repo"
        second.mkdir()
        self.repo = second
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "test")
        self.git("config", "user.email", "test@example.com")
        target = second / "existing.txt"
        target.write_text("before\n")
        self.git("add", "existing.txt")
        self.git("commit", "-qm", "feat(base): add file")
        self.track("Bash", {"command": "git status"}, event="PreToolUse")
        self.track("Bash", {"command": "git status"})
        self.repo = first
        self.track("Bash", {"command": "python3 writer.py"}, event="PreToolUse")
        target.write_text("after\n")
        self.track("Bash", {"command": "python3 writer.py"})
        edits = [e for e in self.journal() if e.get("kind") == "edit"]
        self.assertIn(str(target), [e["path"] for e in edits])
        self.assertEqual(self.gate(), {"ready": True})

    def test_shell_literal_discovers_other_repo_before_first_write(self):
        first = self.repo
        other = self.base / "new-other-repo"
        other.mkdir()
        self.repo = other
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "test")
        self.git("config", "user.email", "test@example.com")
        target = other / "changed.txt"
        target.write_text("before\n")
        self.git("add", "changed.txt")
        self.git("commit", "-qm", "feat(base): add file")
        self.repo = first
        command = "python3 - <<'PY'\nfrom pathlib import Path\np=Path('../new-other-repo')/'changed.txt'\np.write_text('after')\nPY"
        self.track("Bash", {"command": command}, event="PreToolUse")
        target.write_text("after\n")
        self.track("Bash", {"command": command})
        self.assertIn(str(target), [e.get("path") for e in self.journal()])

    def test_shell_mode_change_refreshes_already_modified_file(self):
        self.edit_login()
        self.render(self.write_report())
        before = len(self.journal())
        self.track("Bash", {"command": "chmod +x auth/login.go"}, event="PreToolUse")
        (self.repo / "auth/login.go").chmod(0o755)
        self.track("Bash", {"command": "chmod +x auth/login.go"})
        self.assertGreater(len(self.journal()), before)
        self.assertEqual(self.gate(), {"ready": True})

    def test_shell_overwrites_and_new_files_are_captured(self):
        for content in ("first\n", "second\n"):
            before = len(self.journal())
            self.track("Bash", {"command": "python3 writer.py"}, event="PreToolUse")
            (self.repo / "shell.txt").write_text(content)
            self.track("Bash", {"command": "python3 writer.py"})
            self.assertGreater(len(self.journal()), before)
            paths = [e["path"] for e in self.journal() if e.get("kind") == "edit"]
            self.assertIn(str(self.repo / "shell.txt"), paths)
        result = self.render(self.write_report(repos=[]))
        self.assertEqual(result.returncode, 0, result.stderr)
        page = Path(result.stdout.strip()).read_text()
        self.assertTrue('class="path">shell.txt' in page)
        self.assertTrue('+second' in page)

    def test_git_am_counts_local_application(self):
        self.git("switch", "-c", "mail-source")
        (self.repo / "mailed.txt").write_text("mail\n")
        self.git("add", "mailed.txt")
        self.git("commit", "-qm", "feat(mail): add mailed file")
        patch = self.git("format-patch", "-1", "--stdout")
        self.git("switch", "develop")
        self.track("Bash", {"command": "git am"}, event="PreToolUse")
        subprocess.run(["git", "am"], cwd=self.repo, input=patch, text=True, capture_output=True, check=True)
        self.track("Bash", {"command": "git am"})
        self.assertEqual(len(self.facts()["commits"]), 1)
        self.assertEqual([f["path"] for f in self.facts()["files"]], ["mailed.txt"])

    def test_failed_commit_does_not_capture_history(self):
        self.track("Bash", {"command": "git commit"}, event="PreToolUse")
        subprocess.run(["git", "commit", "-m", "nothing"], cwd=self.repo, capture_output=True)
        self.track("Bash", {"command": "git commit"})
        self.assertEqual(self.gate(), {})
        self.assertEqual(self.meta()["repos"][str(self.repo)]["commits"], [])

    def test_deleted_sql_comment_is_a_deletion(self):
        sys.path.insert(0, str(SCRIPTS))
        import render
        page = render.diff_html({"diff": ["--- a/x.sql", "+++ b/x.sql", "@@ -1 +1 @@", "--- drop me", "+++ add me"], "truncated": False})
        self.assertIn('<span class="d">--- drop me</span>', page)
        self.assertIn('<span class="a">+++ add me</span>', page)

    def test_unicode_and_special_paths_survive(self):
        for name in ("café.txt", "tab\tline\n.txt"):
            self.track("Write", {"file_path": str(self.repo / name)}, event="PreToolUse")
            (self.repo / name).write_text("hello\n")
            self.track("Write", {"file_path": str(self.repo / name)})
        self.track("Bash", {"command": "git commit"}, event="PreToolUse")
        self.git("add", "café.txt", "tab\tline\n.txt")
        self.git("commit", "-qm", "feat(names): add files")
        self.track("Bash", {"command": "git commit"})
        names = [f["path"] for f in self.facts()["files"]]
        self.assertIn("café.txt", names)
        self.assertIn("tab\tline\n.txt", names)

    def test_auto_uses_current_harness_id_not_other_journal(self):
        self.edit_login()
        other = "codex-thread-unique"
        env = {**self.env, "CODEX_THREAD_ID": other}
        result = self.run_script("render.py", None, "auto", str(self.write_report()), "--harness", "codex", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.meta()["repos"].keys(), {str(self.repo)})
        self.assertNotIn("html", self.meta())
        self.assertEqual(self.meta(other)["harness"], "codex")
        sys.path.insert(0, str(SCRIPTS))
        import render
        from unittest.mock import patch
        with patch.dict(os.environ, {}, clear=True):
            first = render.resolve_session("auto", "/a/backend")
            second = render.resolve_session("auto", "/b/backend")
            self.assertNotEqual(first, second)

    def test_same_session_prefix_does_not_overwrite_html(self):
        report = self.write_report()
        first = self.render(report, session="manual-shared-prefix-a")
        second = self.render(report, session="manual-shared-prefix-b")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertNotEqual(first.stdout.strip(), second.stdout.strip())
        self.assertTrue(Path(first.stdout.strip()).exists())
        self.assertTrue(Path(second.stdout.strip()).exists())

    def test_push_refreshes_report_state(self):
        remote = self.base / "remote.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        self.git("remote", "add", "origin", str(remote))
        self.git("push", "-qu", "origin", "develop")
        self.commit_change("pushed.txt", "x\n", "feat(push): add file")
        self.render(self.write_report())
        self.track("Bash", {"command": "git push"}, event="PreToolUse")
        self.git("push", "-q")
        self.track("Bash", {"command": "git push"})
        self.assertEqual(self.gate(), {"ready": True})
        self.assertEqual(self.facts()["ahead"], 0)

    def test_bad_session_and_unreadable_report_are_not_schema_errors(self):
        for sid, path in (("${CLAUDE_SESSION_ID}", self.write_report()), (SID, self.base / "absent.json")):
            result = self.render(path, session=sid)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn("fix these", result.stderr)

    def test_raw_patch_and_shell_workdir_use_correct_repo(self):
        patch = "*** Begin Patch\n*** Add File: raw.txt\n+x\n*** End Patch"
        self.track("apply_patch", patch, event="PreToolUse")
        (self.repo / "raw.txt").write_text("x\n")
        self.track("apply_patch", patch)
        self.assertEqual(self.journal()[0]["path"], str(self.repo / "raw.txt"))
        payload = {"session_id": SID, "cwd": str(self.base), "tool_name": "exec_command", "tool_input": {"cmd": "git commit", "workdir": str(self.repo)}}
        self.run_script("track.py", {**payload, "hook_event_name": "PreToolUse"})
        self.git("add", "raw.txt")
        self.git("commit", "-qm", "feat(raw): add raw file")
        result = self.run_script("track.py", {**payload, "hook_event_name": "PostToolUse"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.facts()["commits"]), 1)

    def test_unrelated_report_agent_does_not_consume_changes(self):
        self.edit_login()
        self.track("Agent", {"description": "review session-report skill", "subagent_type": "fork"})
        self.track("Agent", {"description": "session-report", "subagent_type": "Explore"})
        self.assertEqual(self.gate(), {"ready": True})

    def test_offline_bundle_and_no_network_policy(self):
        self.edit_login()
        result = self.render(self.write_report())
        page = Path(result.stdout.strip()).read_text()
        self.assertTrue('https://cdn.jsdelivr.net/npm/mermaid@11/' not in page)
        self.assertIn("connect-src 'none'", page)
        self.assertIn('window.mermaid', page)
        self.assertNotIn('src="https://', page)

    def test_report_root_and_lock_reject_symlinks(self):
        target = self.base / "target"
        target.mkdir()
        self.reports.symlink_to(target, target_is_directory=True)
        result = self.run_script("track.py", {"session_id": SID, "tool_name": "ReportFindings"})
        self.assertNotEqual(result.returncode, 0)
        self.reports.unlink()
        self.edit_login()
        victim = self.base / "victim.txt"
        victim.write_text("keep")
        lock = self.reports / ".state" / f"{SID}.lock"
        lock.unlink()
        lock.symlink_to(victim)
        result = self.run_script("track.py", {"session_id": SID, "tool_name": "Bash", "cwd": str(self.repo), "hook_event_name": "PreToolUse", "tool_input": {"command": "git status"}})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(victim.read_text(), "keep")
        self.assertEqual(self.reports.stat().st_mode & 0o777, 0o700)

    def test_installer_updates_matcher_and_keeps_first_backup(self):
        home = self.base / "home"
        env = {**self.env, "HOME": str(home)}
        settings = home / ".claude/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text('{"original":true}')
        self.assertEqual(self.run_script("install.py", env=env).returncode, 0)
        old = json.loads(settings.read_text())
        old["hooks"]["PostToolUse"][0]["matcher"] = "Edit"
        settings.write_text(json.dumps(old))
        self.assertEqual(self.run_script("install.py", env=env).returncode, 0)
        installed = json.loads(settings.read_text())
        self.assertIn("Bash", installed["hooks"]["PostToolUse"][0]["matcher"])
        self.assertEqual(json.loads(settings.with_name("settings.json.bak-session-report").read_text()), {"original": True})
        self.assertEqual(len(installed["hooks"]["PostToolUse"]), 1)

    def test_known_repo_post_edits_do_not_rewrite_meta(self):
        self.edit_login()
        path = self.reports / ".state" / f"{SID}.json"
        before = path.stat().st_mtime_ns
        for _ in range(3):
            self.track("Edit", {"file_path": str(self.repo / "auth/login.go")}, event="PreToolUse")
            self.track("Edit", {"file_path": str(self.repo / "auth/login.go")})
        self.assertEqual(path.stat().st_mtime_ns, before)

    def test_cooldown_keeps_unreported_changes(self):
        self.edit_login()
        self.render(self.write_report())
        self.edit_login()
        result = self.run_script("gate.py", {"session_id": SID, "cwd": str(self.repo)}, env={**self.env, "SESSION_REPORT_COOLDOWN": "300"})
        self.assertEqual(json.loads(result.stdout), {})
        self.assertEqual(self.gate(), {"ready": True})

    def test_report_coverage_does_not_consume_newer_changes(self):
        self.edit_login()
        self.edit_login()
        result = self.run_script("render.py", None, SID, str(self.write_report()), "--covered-count", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.gate(), {"ready": True})


if __name__ == "__main__":
    unittest.main()
