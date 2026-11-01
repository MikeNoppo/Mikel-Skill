import json
import os
import shutil
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
PYTHON = "/usr/bin/python3"
TRACK = f"{PYTHON} {SCRIPTS / 'track.py'}"
CLAUDE_GATE = f"{PYTHON} {SCRIPTS / 'gate.py'} --harness claude"
CODEX_GATE = f"{PYTHON} {SCRIPTS / 'gate.py'} --harness codex"
CLAUDE_ALLOW = [
    "Edit(//tmp/session-reports/**)",
    f"Bash(python3 {SCRIPTS / 'render.py'} *)",
]
CLAUDE_HOOKS = {
    "PostToolUse": ("Edit|Write|MultiEdit|NotebookEdit|Bash|ReportFindings|Agent", TRACK),
    "Stop": (None, CLAUDE_GATE),
}
CODEX_HOOKS = {
    "PostToolUse": ("apply_patch|Edit|Write|Bash", TRACK),
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
        if any(hook.get("command") == command for group in groups for hook in group.get("hooks", [])):
            continue
        group = {"hooks": [{"type": "command", "command": command, "timeout": 10}]}
        if matcher:
            group = {"matcher": matcher, **group}
        groups.append(group)
        changed.append(event)
    return changed


def save(path, config):
    if path.exists():
        shutil.copy2(path, path.with_name(f"{path.name}.bak-session-report"))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")
    if path.exists():
        shutil.copymode(path, temporary)
    os.replace(temporary, path)


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
