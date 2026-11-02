import os
import shutil
import subprocess
import sys
import time
from datetime import datetime

import common
import render

PROMPT = "Read {skill} and follow its Background mode (Codex). Session id: {sid}"


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


def main(sid, cwd, covered_count=None):
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
    print(f"{datetime.now():%H:%M:%S} fork {sid}", flush=True)
    try:
        result = subprocess.run(command, cwd=cwd, stdin=subprocess.DEVNULL, timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"codex exec fork failed: {error}", flush=True)
        release(sid)
        return 1
    if result.returncode != 0 or not output.exists():
        print(f"codex exec fork exited {result.returncode} without {output}", flush=True)
        release(sid)
        return 1
    try:
        path = render.render(sid, output, "codex", cwd=cwd, covered_count=int(covered_count) if covered_count is not None else None)
    except (render.ReportError, OSError, ValueError) as error:
        print(f"report rejected:\n{error}", flush=True)
        release(sid)
        return 1
    if path is None:
        print("skip: the session is waiting on the user", flush=True)
        release(sid)
        return 0
    finish(sid)
    print(f"{datetime.now():%H:%M:%S} wrote {path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
