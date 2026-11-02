import fcntl
import json
import os
import re
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SCHEMA = SKILL_DIR / "assets" / "report.schema.json"
TEMPLATE = SKILL_DIR / "assets" / "template.html"
SID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def root():
    value = os.environ.get("SESSION_REPORT_DIR", "/tmp/session-reports")
    path = Path(value)
    if not path.is_absolute() or path in (Path("/"), Path.home()):
        raise ValueError(f"SESSION_REPORT_DIR must be an absolute path other than / and $HOME: {value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError(f"{path} must be a real directory owned by you")
    if stat.S_IMODE(info.st_mode) & 0o077:
        path.chmod(0o700)
    return path


def state_dir():
    path = root() / ".state"
    return private_dir(path)


def private_dir(path):
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError(f"{path} must be a real directory owned by you")
    path.chmod(0o700)
    return path


def session_dir(sid):
    if not valid_sid(sid):
        raise ValueError("invalid session id")
    return private_dir(root() / sid)


def valid_sid(value):
    return isinstance(value, str) and SID_PATTERN.fullmatch(value) is not None


def meta_path(sid):
    return state_dir() / f"{sid}.json"


def load_meta(sid):
    path = meta_path(sid)
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_atomic(path, data):
    path = Path(path)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb" if isinstance(data, bytes) else "w") as handle:
            handle.write(data)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def locked_meta(sid):
    descriptor = os.open(state_dir() / f"{sid}.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        meta = load_meta(sid)
        yield meta
        write_atomic(meta_path(sid), json.dumps(meta, ensure_ascii=False, indent=2))
    finally:
        os.close(descriptor)


def update_meta(sid, **changes):
    with locked_meta(sid) as meta:
        meta.update(changes)
    return meta


def git(cwd, *args, ok=(0,), input_text=None):
    try:
        result = subprocess.run(
            ["git", "-c", "core.quotePath=false", "-C", str(cwd), *args],
            capture_output=True,
            input=input_text,
            text=True,
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode not in ok:
        return None
    return result.stdout.rstrip("\n")


def existing_dir(path):
    path = Path(path)
    while not path.is_dir():
        if path.parent == path:
            return None
        path = path.parent
    return path


def repo_root(path):
    directory = existing_dir(path)
    if directory is None:
        return None
    return git(directory, "rev-parse", "--show-toplevel") or None


def is_under(path, parent):
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
    except ValueError:
        return False
    return True
