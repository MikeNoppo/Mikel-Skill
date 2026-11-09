# Mikel-Skill

Kumpulan skill pribadi untuk laporan pekerjaan. Skill dijalankan manual dan menghasilkan HTML yang dapat dibuka serta dibagikan.

## Session report

[session-report](skills/session-report/SKILL.md) membuat laporan teknis satu sesi: implementasi, diff, status, diagram, dan bukti pengujian. Panggil `$session-report` di Codex atau `/session-report` di Claude Code.

## Instalasi

Butuh Git dan Python 3.10+ tanpa dependency Python tambahan.

```sh
mkdir -p "$HOME/Projects"
git clone https://github.com/MikeNoppo/Mikel-Skill.git "$HOME/Projects/Mikel-Skill"
python3 "$HOME/Projects/Mikel-Skill/scripts/install.py"
```

Installer menautkan skill ke `~/.agents/skills` dan `~/.claude/skills`, tanpa menimpa instalasi lain atau mengubah konfigurasi dan hook.

Panduan lengkap tersedia di [skills/session-report/README.md](skills/session-report/README.md).

## Verifikasi

```sh
python3 skills/session-report/test/test_session_report.py
```

Repository menyimpan skill dan pengujian. Laporan pribadi tetap dibuat lokal.
