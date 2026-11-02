import os
import subprocess
from pathlib import Path

import common


def announcement(path):
    path = Path(path).absolute()
    if not common.is_under(path, common.root()) or not path.is_file():
        raise ValueError("report link must point to an existing report in SESSION_REPORT_DIR")
    return f"Laporan sesi: [Buka laporan](<{path}>)"


def reminder(path):
    return ("[session-report:completed] Notifikasi otomatis: laporan sesi sudah selesai dibuat. "
            "Tampilkan hanya baris berikut di chat sebagai balasan:\n\n" + announcement(path))


def codex(sid, path, executable):
    if os.environ.get("SESSION_REPORT_CHAT", "1") == "0":
        return False
    if not common.valid_sid(sid):
        raise ValueError("invalid session id")
    meta = common.load_meta(sid)
    report = meta.get("report")
    if report and meta.get("chat_delivered_report") == report:
        return True
    try:
        result = subprocess.run([executable, "queue", "--thread", sid, "--message", reminder(path)],
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout or "queue command failed")[-500:])
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        common.update_meta(sid, chat_delivery_error=str(error))
        print(f"chat notification failed: {error}", flush=True)
        return False
    common.update_meta(sid, chat_delivered_report=report, chat_delivery_error=None)
    return True
