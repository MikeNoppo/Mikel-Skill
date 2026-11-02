import os
import hashlib
from pathlib import Path
import re
import shlex
import sys
import time

import common

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
SHELL_TOOLS = {"Bash", "exec_command", "shell", "local_shell"}
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
        return PATCH_FILE.findall(text_of(tool_input.get("command") or tool_input.get("input") or tool_input.get("patch")))
    return []


def shell_dirs(command, cwd):
    targets = {cwd}
    for literal in re.findall(r"[\"']((?:\.\.?/|/|~/)[^\"'\n]+)[\"']", command):
        candidate = os.path.abspath(os.path.join(cwd, os.path.expanduser(literal)))
        if Path(candidate).exists():
            targets.add(candidate)
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return targets
    segments, segment = [], []
    for token in tokens + [";"]:
        if token and all(c in ";&|\n" for c in token):
            if segment:
                segments.append(segment)
                segment = []
        else:
            segment.append(token)
    for tokens in segments:
        if tokens[0] == "cd" and len(tokens) == 2:
            cwd = os.path.abspath(os.path.join(cwd, os.path.expanduser(tokens[1])))
            targets.add(cwd)
        elif tokens[0] == "git":
            target = cwd
            for index, token in enumerate(tokens[:-1]):
                if token == "-C":
                    target = os.path.abspath(os.path.join(target, tokens[index + 1]))
            targets.add(target)
    return targets


def discover(sid, paths):
    meta = common.load_meta(sid)
    cache = meta.get("directories", {})
    found, additions = {}, {}
    for path in paths:
        directory = common.existing_dir(path)
        if directory is None:
            continue
        directory = os.path.realpath(directory)
        repo = cache.get(directory)
        if repo is None:
            repo = common.repo_root(directory)
            if repo:
                additions[directory] = repo
        if repo:
            found[path] = repo
    if additions:
        with common.locked_meta(sid) as meta:
            meta.setdefault("directories", {}).update(additions)
    return found


def working_files(repo):
    status = common.git(repo, "status", "--porcelain=v1", "--no-renames", "--untracked-files=all", "-z") or ""
    result = {}
    for item in status.split("\0"):
        if len(item) < 4:
            continue
        rel = item[3:]
        path = Path(repo) / rel
        digest = hashlib.sha256()
        try:
            if path.exists() or path.is_symlink():
                digest.update(str(path.lstat().st_mode & 0o111).encode())
            if path.is_symlink():
                digest.update(os.readlink(path).encode())
            elif path.is_file():
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
            elif path.exists():
                digest.update(str(path.stat().st_mtime_ns).encode())
            else:
                digest.update(b"deleted")
            result[rel] = [item[:2], digest.hexdigest()]
        except OSError:
            result[rel] = [item[:2], "unreadable"]
    return result


def snapshot(repo, entries=None):
    entries = common.reflog(repo) if entries is None else entries
    return {**common.repo_state(repo, entries), "head": common.git(repo, "rev-parse", "--verify", "-q", "HEAD"),
            "branch": common.git(repo, "symbolic-ref", "--short", "-q", "HEAD"),
            "files": working_files(repo)}


def main():
    if common.is_child():
        return 0
    data = common.read_hook_input()
    sid = data.get("session_id")
    if not common.valid_sid(sid):
        return 0
    name = data.get("tool_name") or ""
    raw_input = data.get("tool_input")
    tool_input = raw_input if isinstance(raw_input, dict) else {"input": text_of(raw_input)}
    cwd = tool_input.get("workdir") or tool_input.get("cwd") or data.get("cwd") or os.getcwd()
    cwd = os.path.abspath(os.path.join(data.get("cwd") or os.getcwd(), cwd))
    pre = data.get("hook_event_name") == "PreToolUse"
    if name == "Agent":
        if not pre and tool_input.get("description") == "session-report" and tool_input.get("subagent_type") == "fork" and tool_input.get("run_in_background") is True and f"Session id: {sid}" in tool_input.get("prompt", "") and str(common.SKILL_DIR / "SKILL.md") in tool_input.get("prompt", ""):
            common.update_meta(sid, spawned_count=common.change_count(sid), spawned_at=time.time())
        return 0
    if name == "ReportFindings":
        if not pre:
            common.append_event(sid, {"kind": "review"})
        return 0
    paths = [os.path.abspath(os.path.join(cwd, p)) for p in edited_paths(name, tool_input)]
    paths = [p for p in paths if not common.is_under(p, common.root())]
    if name in SHELL_TOOLS:
        targets = shell_dirs(text_of(tool_input.get("command") or tool_input.get("cmd")), cwd)
    else:
        targets = paths
    locations = discover(sid, targets)
    repos = set(locations.values())
    if name in SHELL_TOOLS:
        repos.update(repo for repo in common.load_meta(sid).get("repos", {}) if Path(repo).is_dir())
    key = str(data.get("tool_use_id") or name)
    if pre and name not in SHELL_TOOLS:
        missing = repos - common.load_meta(sid).get("repos", {}).keys()
        if missing:
            with common.locked_meta(sid) as meta:
                for repo in missing:
                    meta.setdefault("repos", {})[repo] = {"base": common.git(repo, "rev-parse", "--verify", "-q", "HEAD") or common.EMPTY_TREE, "commits": []}
        return 0
    if pre:
        states = {repo: snapshot(repo) for repo in repos}
        with common.locked_meta(sid) as meta:
            for repo, state in states.items():
                meta.setdefault("repos", {}).setdefault(repo, {"base": state["head"] or common.EMPTY_TREE, "commits": []})
            meta.setdefault("pending", {})[key] = states
        return 0
    meta = common.load_meta(sid)
    before = meta.get("pending", {}).get(key, {})
    if before or repos - meta.get("repos", {}).keys():
        with common.locked_meta(sid) as meta:
            meta.setdefault("pending", {}).pop(key, None)
            for repo in repos:
                entry = meta.setdefault("repos", {}).setdefault(repo, {"base": common.git(repo, "rev-parse", "--verify", "-q", "HEAD") or common.EMPTY_TREE, "commits": []})
                if repo in before:
                    entries = common.reflog(repo)
                    after = snapshot(repo, entries)
                    old = before[repo]
                    recent = entries[:max(0, len(entries) - old["reflog"])]
                    commits = entry.setdefault("commits", [])
                    count_before = len(commits)
                    for sha, _, subject in reversed(recent):
                        rewritten = subject.startswith("rebase (") and any(common.patch_id(repo, sha) == common.patch_id(repo, old_sha) is not None for old_sha in commits)
                        if (subject.startswith(common.SESSION_REFLOG) or rewritten) and sha not in commits:
                            commits.append(sha)
                            common.append_event(sid, {"kind": "commit", "repo": repo, "sha": sha})
                    if name in SHELL_TOOLS:
                        for rel in sorted(old["files"].keys() | after["files"].keys()):
                            if old["files"].get(rel) != after["files"].get(rel):
                                common.append_event(sid, {"kind": "edit", "path": os.path.join(repo, rel), "repo": repo})
                    if name in SHELL_TOOLS and after != old and len(commits) == count_before:
                        common.append_event(sid, {"kind": "git", "repo": repo})
    response = data.get("tool_response")
    if not isinstance(response, dict) or not response.get("is_error", False):
        for path in paths:
            repo = locations.get(path)
            common.append_event(sid, {"kind": "edit", "path": path, "repo": repo})
    return 0


if __name__ == "__main__":
    sys.exit(main())
