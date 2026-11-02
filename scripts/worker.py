import os
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime

import common
import delivery
import render

PROMPT = "Read {skill} and follow its Background mode (CLI worker). Session id: {sid}"


def codex_bin():
    return os.environ.get("SESSION_REPORT_CODEX_BIN") or shutil.which("codex") or "/usr/lib/chatgpt/resources/codex"


def release(sid):
    with common.locked_meta(sid) as meta:
        if meta.get("worker_pid") == os.getpid():
            meta["spawned_count"] = meta.get("previous_spawned_count", 0)
            meta.pop("worker_pid", None)


def finish(sid):
    with common.locked_meta(sid) as meta:
        if meta.get("worker_pid") == os.getpid():
            meta.pop("worker_pid", None)


def main(sid, cwd, covered_count=None, harness="codex", model=""):
    if harness not in {"claude", "codex"}:
        return 2
    if not common.valid_sid(sid):
        return 2
    time.sleep(float(os.environ.get("SESSION_REPORT_DELAY", "3")))
    output = common.session_dir(sid) / f"report-{datetime.now():%Y%m%d-%H%M%S}.json"
    command = [
        codex_bin(), "exec", "fork", sid,
        "--ephemeral",
        "--skip-git-repo-check",
        "--disable", "hooks",
        "-c", 'sandbox_mode="read-only"',
        "-c", 'approval_policy="never"',
        "-c", 'model_reasoning_effort="low"',
        "--output-schema", str(common.SCHEMA),
        "-o", str(output),
        PROMPT.format(skill=common.SKILL_DIR / "SKILL.md", sid=sid),
    ]
    env = {**os.environ, "SESSION_REPORT_CHILD": "1"}
    if harness == "claude":
        if not model:
            print("cannot build Claude report: original session model is missing", flush=True)
            release(sid)
            return 1
        command = [os.environ.get("SESSION_REPORT_CLAUDE_BIN") or shutil.which("claude") or "claude",
                   "--print", "--resume", sid, "--fork-session", "--no-session-persistence",
                   "--model", model, "--effort", "low", "--output-format", "json",
                   "--json-schema", common.SCHEMA.read_text(),
                   "--tools", "Read", "--allowedTools", "Read", "--permission-mode", "dontAsk",
                   "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                   "--settings", '{"disableAllHooks":true}',
                   PROMPT.format(skill=common.SKILL_DIR / "SKILL.md", sid=sid)]
        env.pop("CLAUDECODE", None)
    print(f"{datetime.now():%H:%M:%S} fork {harness} {sid} effort=low", flush=True)
    try:
        result = subprocess.run(command, cwd=cwd, stdin=subprocess.DEVNULL, timeout=1800,
                                env=env, capture_output=harness == "claude", text=True)
        if harness == "claude" and result.returncode == 0:
            envelope = json.loads(result.stdout)
            if envelope.get("is_error") or not isinstance(envelope.get("structured_output"), dict):
                raise ValueError("Claude did not return successful structured output")
            common.write_atomic(output, json.dumps(envelope["structured_output"], ensure_ascii=False))
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"{harness} fork failed: {error}", flush=True)
        release(sid)
        return 1
    if result.returncode != 0 or not output.exists():
        print(f"{harness} fork exited {result.returncode} without valid output", flush=True)
        release(sid)
        return 1
    try:
        path = render.render(sid, output, harness, cwd=cwd, covered_count=int(covered_count) if covered_count is not None else None)
    except (render.ReportError, OSError, ValueError) as error:
        print(f"report rejected:\n{error}", flush=True)
        release(sid)
        return 1
    if path is None:
        print("skip: the session is waiting on the user", flush=True)
        release(sid)
        return 0
    if harness == "codex":
        delivery.codex(sid, path, codex_bin())
    finish(sid)
    print(f"{datetime.now():%H:%M:%S} wrote {path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:6]))
