import json
import shlex
import sys
from pathlib import Path

import common

SCRIPTS = Path(__file__).resolve().parent
LEGACY_SCRIPTS = {str(SCRIPTS / name) for name in ("track.py", "gate.py", "worker.py", "delivery.py")}


def owned(command):
    try:
        return any(part in LEGACY_SCRIPTS for part in shlex.split(command))
    except ValueError:
        return False


def migrate(path):
    if not path.exists():
        return False
    config = json.loads(path.read_text())
    changed = False
    for event, groups in list(config.get("hooks", {}).items()):
        kept = []
        for group in groups:
            handlers = group.get("hooks", [])
            remaining = [hook for hook in handlers if not owned(hook.get("command", ""))]
            if remaining != handlers:
                changed = True
            if remaining:
                kept.append({**group, "hooks": remaining})
        if kept:
            config["hooks"][event] = kept
        else:
            config["hooks"].pop(event, None)
    allow = config.get("permissions", {}).get("allow", [])
    legacy = {"Edit(//tmp/session-reports/**)", f"Bash(python3 {SCRIPTS / 'render.py'} *)"}
    remaining = [rule for rule in allow if rule not in legacy]
    if remaining != allow:
        config["permissions"]["allow"] = remaining
        changed = True
    if changed:
        backup = path.with_name(path.name + ".bak-session-report-manual")
        if not backup.exists():
            with backup.open("xb") as handle:
                handle.write(path.read_bytes())
            backup.chmod(0o600)
        common.write_atomic(path, json.dumps(config, indent=2, ensure_ascii=False) + "\n")
    return changed


def link_skill(destination):
    source = SCRIPTS.parent
    if destination.is_symlink():
        if destination.resolve() == source:
            return False
        raise ValueError(f"{destination} points elsewhere; keep or move it before installing")
    if destination.exists():
        if destination.resolve() == source:
            return False
        raise ValueError(f"{destination} already exists; keep or move it before installing")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.symlink_to(source, target_is_directory=True)
    return True


def main():
    home = Path.home()
    for destination in (home / ".agents/skills/session-report", home / ".claude/skills/session-report"):
        try:
            changed = link_skill(destination)
        except (OSError, ValueError) as error:
            print(str(error), file=sys.stderr)
            return 1
        print(f"{destination}: " + ("linked skill" if changed else "skill already available"))
    for path in (Path.home() / ".claude/settings.json", Path.home() / ".codex/hooks.json"):
        print(f"{path}: " + ("removed session-report automation" if migrate(path) else "no session-report automation"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
