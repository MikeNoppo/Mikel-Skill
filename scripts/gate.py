import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import common


def respond(payload=None):
    print(json.dumps(payload or {}))
    return 0


def report_running(data):
    return any(isinstance(task, dict) and task.get("description") == "session-report" and task.get("status") == "running" for task in data.get("background_tasks", []))


def own_worker(pid, sid):
    try:
        command = Path(f"/proc/{int(pid)}/cmdline").read_bytes().split(b"\0")
    except (OSError, ValueError):
        return False
    return any(part.endswith(b"worker.py") for part in command) and sid.encode() in command


def original_model(data):
    if data.get("model"):
        return data["model"]
    path = data.get("transcript_path")
    if path:
        try:
            model = None
            with open(path) as handle:
                for line in handle:
                    try:
                        item = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(item, dict) and item.get("type") == "assistant":
                        candidate = (item.get("message") or {}).get("model")
                        if candidate and not candidate.startswith("<"):
                            model = candidate
            return model
        except OSError:
            pass
    return None


def spawn_worker(sid, cwd, meta, changes, harness="codex", model=""):
    previous = meta.get("worker_pid")
    if previous and own_worker(previous, sid):
        try:
            os.killpg(int(previous), signal.SIGTERM)
        except OSError:
            pass
    log = (common.session_dir(sid) / "worker.log").open("ab")
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).with_name("worker.py")), sid, cwd, str(changes), harness, model or ""],
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
    parser.add_argument("--check", action="store_true", help="show whether a report is ready without launching a worker")
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
    if changes <= max(meta.get("spawned_count", 0), meta.get("reported_count", 0)):
        return respond()
    cooldown = max(0, float(os.environ.get("SESSION_REPORT_COOLDOWN", "300")))
    if time.time() - meta.get("updated_at", 0) < cooldown:
        return respond()
    if meta.get("worker_pid") and own_worker(meta["worker_pid"], sid):
        return respond()
    if args.check:
        return respond({"ready": True})
    spawn_worker(sid, data.get("cwd") or os.getcwd(), meta, changes, args.harness, original_model(data) if args.harness == "claude" else "")
    return respond()


if __name__ == "__main__":
    sys.exit(main())
