import json
import shlex
import sys
from pathlib import Path

import common

SCRIPTS = Path(__file__).resolve().parent
PYTHON = "/usr/bin/python3"
TRACK = f"{PYTHON} {shlex.quote(str(SCRIPTS / 'track.py'))}"
CLAUDE_GATE = f"{PYTHON} {shlex.quote(str(SCRIPTS / 'gate.py'))} --harness claude"
CODEX_GATE = f"{PYTHON} {shlex.quote(str(SCRIPTS / 'gate.py'))} --harness codex"
CLAUDE_ALLOW = [
    "Edit(//tmp/session-reports/**)",
    f"Bash(python3 {SCRIPTS / 'render.py'} *)",
]
CLAUDE_HOOKS = {
    "PreToolUse": ("Edit|Write|MultiEdit|NotebookEdit|Bash", TRACK),
    "PostToolUse": ("Edit|Write|MultiEdit|NotebookEdit|Bash|ReportFindings|Agent", TRACK),
    "Stop": (None, CLAUDE_GATE),
}
CODEX_HOOKS = {
    "PreToolUse": ("apply_patch|Edit|Write|Bash|exec_command|shell|local_shell", TRACK),
    "PostToolUse": ("apply_patch|Edit|Write|Bash|exec_command|shell|local_shell", TRACK),
    "Stop": (None, CODEX_GATE),
}


def load(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def ensure_hooks(config, wanted):
    changed = []
    hooks = config.setdefault("hooks", {})
    for event, (matcher, command) in wanted.items():
        groups = hooks.setdefault(event, [])
        handler = {"type": "command", "command": command, "timeout": 1900 if command == CLAUDE_GATE else 10}
        if command == CLAUDE_GATE:
            handler["asyncRewake"] = True
        matches = [(group, hook) for group in groups for hook in group.get("hooks", []) if hook.get("command") == command]
        if len(matches) == 1 and matches[0][0].get("matcher") == matcher and matches[0][1] == handler:
            continue
        for group, hook in matches:
            group["hooks"].remove(hook)
        groups[:] = [group for group in groups if group.get("hooks")]
        group = {"hooks": [handler]}
        if matcher:
            group = {"matcher": matcher, **group}
        groups.append(group)
        changed.append(event)
    return changed


def save(path, config):
    backup = path.with_name(f"{path.name}.bak-session-report")
    if path.exists() and not backup.exists():
        with backup.open("xb") as handle:
            handle.write(path.read_bytes())
        backup.chmod(0o600)
    path.parent.mkdir(parents=True, exist_ok=True)
    common.write_atomic(path, json.dumps(config, indent=2, ensure_ascii=False) + "\n")


def install_claude(home):
    path = home / ".claude" / "settings.json"
    config = load(path, {})
    changed = ensure_hooks(config, CLAUDE_HOOKS)
    allow = config.setdefault("permissions", {}).setdefault("allow", [])
    for rule in CLAUDE_ALLOW:
        if rule not in allow:
            allow.append(rule)
            changed.append(rule)
    if changed:
        save(path, config)
    return path, changed


def install_codex(home):
    path = home / ".codex" / "hooks.json"
    config = load(path, {"hooks": {}})
    changed = ensure_hooks(config, CODEX_HOOKS)
    if changed:
        save(path, config)
    return path, changed


def main():
    home = Path.home()
    for installer in (install_claude, install_codex):
        path, changed = installer(home)
        print(f"{path}: " + (f"added {', '.join(changed)}" if changed else "already installed"))
    print("Codex: open /hooks once in the Codex TUI and trust the new hooks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
