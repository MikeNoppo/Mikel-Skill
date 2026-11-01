import os
import re
import sys
import time

import common

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
SHELL_TOOLS = {"Bash", "exec_command", "shell", "local_shell"}
GIT_HISTORY = re.compile(r"\bgit\b(?:\s+-C\s+(\"[^\"]+\"|'[^']+'|\S+))?(?:\s+-{1,2}[\w-]+(?:=\S+)?)*\s+(commit|merge|rebase|cherry-pick|am|revert|pull|reset)\b")
PATCH_FILE = re.compile(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+?)\s*$", re.M)


def text_of(value):
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return value if isinstance(value, str) else ""


def edited_paths(name, tool_input):
    if name in EDIT_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("notebook_path")
        return [path] if isinstance(path, str) else []
    if name == "apply_patch":
        patch = text_of(tool_input.get("command") or tool_input.get("input") or tool_input.get("patch"))
        return PATCH_FILE.findall(patch)
    return []


def record_edits(sid, paths, cwd):
    report_root = common.root()
    for raw in paths:
        path = os.path.normpath(raw if os.path.isabs(raw) else os.path.join(cwd, raw))
        if common.is_under(path, report_root):
            continue
        repo = common.repo_root(path)
        if repo:
            common.remember_repo(sid, repo)
        common.append_event(sid, {"kind": "edit", "path": path, "repo": repo})


def record_git(sid, command, cwd):
    match = GIT_HISTORY.search(command)
    if not match:
        return
    target = (match.group(1) or ".").strip("\"'")
    repo = common.repo_root(target if os.path.isabs(target) else os.path.join(cwd, target))
    if repo:
        previous = common.git(repo, "rev-parse", "--verify", "-q", "HEAD@{1}") if match.group(2) == "commit" else None
        common.remember_repo(sid, repo, previous)
    common.append_event(sid, {"kind": "git", "action": match.group(2), "repo": repo})


def main():
    if common.is_child():
        return 0
    data = common.read_hook_input()
    sid = data.get("session_id")
    if not common.valid_sid(sid):
        return 0
    name = data.get("tool_name") or ""
    tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    cwd = data.get("cwd") or os.getcwd()
    if name == "Agent":
        if "session-report" in text_of(tool_input.get("description")):
            common.update_meta(sid, spawned_count=common.change_count(sid), spawned_at=time.time())
        return 0
    if name == "ReportFindings":
        common.append_event(sid, {"kind": "review"})
        return 0
    if name in SHELL_TOOLS:
        record_git(sid, text_of(tool_input.get("command")), cwd)
        return 0
    record_edits(sid, edited_paths(name, tool_input), cwd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
