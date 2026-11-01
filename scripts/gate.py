import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import common

REASON = (
    "[session-report] This session has changes that are not in a session report yet. "
    "If your last message asks the user something they must answer before the task can continue, end your turn now and do nothing else. "
    "Otherwise launch exactly one background Agent with subagent_type \"fork\", description \"session-report\" and this prompt: "
    "\"Read {skill} and follow its Background mode (Claude fork). Session id: {sid}\". "
    "Then end your turn without writing anything else. When that agent's completion notification arrives, reply with only the one line it returned."
)


def respond(payload=None):
    print(json.dumps(payload or {}))
    return 0


def report_running(data):
    return "session-report" in json.dumps(data.get("background_tasks") or [])


def own_worker(pid, sid):
    try:
        command = Path(f"/proc/{int(pid)}/cmdline").read_bytes().split(b"\0")
    except (OSError, ValueError):
        return False
    return any(part.endswith(b"worker.py") for part in command) and sid.encode() in command


def spawn_worker(sid, cwd, meta, changes):
    previous = meta.get("worker_pid")
    if previous and own_worker(previous, sid):
        try:
            os.killpg(int(previous), signal.SIGTERM)
        except OSError:
            pass
    log = (common.session_dir(sid) / "worker.log").open("ab")
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).with_name("worker.py")), sid, cwd],
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env={**os.environ, "SESSION_REPORT_CHILD": "1"},
    )
    common.update_meta(
        sid,
        spawned_count=changes,
        previous_spawned_count=meta.get("spawned_count", 0),
        worker_pid=process.pid,
        spawned_at=time.time(),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--harness", choices=["claude", "codex"], default="claude")
    args = parser.parse_args()
    data = common.read_hook_input()
    if common.is_child() or data.get("stop_hook_active") or data.get("permission_mode") == "plan":
        return respond()
    sid = data.get("session_id")
    if not common.valid_sid(sid) or report_running(data):
        return respond()
    changes = common.change_count(sid)
    meta = common.load_meta(sid)
    if changes <= meta.get("spawned_count", 0):
        return respond()
    if args.harness == "claude":
        return respond({"decision": "block", "reason": REASON.format(skill=common.SKILL_DIR / "SKILL.md", sid=sid)})
    spawn_worker(sid, data.get("cwd") or os.getcwd(), meta, changes)
    return respond()


if __name__ == "__main__":
    sys.exit(main())
