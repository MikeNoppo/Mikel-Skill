# Mikel-Skill

Kumpulan skill pribadi untuk laporan pekerjaan. Keduanya dijalankan manual dan menghasilkan HTML yang dapat dibuka serta dibagikan.

| Skill | Kegunaan | Pemanggilan |
| --- | --- | --- |
| [day-report](skills/day-report/SKILL.md) | Merangkum pekerjaan harian lintas sesi: PR, commit, perubahan, penambahan, dan screenshot wajib. Bahasa untuk pembaca umum. | `$day-report` di Codex atau `/day-report` di Claude Code |
| [session-report](skills/session-report/SKILL.md) | Laporan teknis satu sesi: implementasi, diff, status, diagram, dan bukti pengujian. | `$session-report` di Codex atau `/session-report` di Claude Code |

## Instalasi

Butuh Git dan Python 3.10+. Kedua skill memakai Python standard library; tidak ada dependency Python tambahan. Diagram memakai Mermaid lokal yang disematkan ke HTML. Pengambilan screenshot menggunakan alat browser atau aplikasi yang tersedia pada sesi.

```sh
mkdir -p "$HOME/Projects"
git clone https://github.com/MikeNoppo/Mikel-Skill.git "$HOME/Projects/Mikel-Skill"
python3 "$HOME/Projects/Mikel-Skill/scripts/install.py"
```

Installer menautkan setiap skill ke `~/.agents/skills` dan `~/.claude/skills`, tanpa menimpa instalasi yang mengarah ke tempat lain. File konfigurasi dan hook tidak diubah. Jika skill belum muncul pada sesi yang sudah berjalan, mulai chat baru.

Untuk memperbarui sumber:

```sh
git -C "$HOME/Projects/Mikel-Skill" pull --ff-only
python3 "$HOME/Projects/Mikel-Skill/scripts/install.py"
```

## Day report

Contoh pemanggilan:

```text
$day-report rangkum pekerjaan saya hari ini untuk proyek ISPO,
termasuk PR, commit, perubahan atau penambahan, dan screenshot
```

Laporan memiliki enam bagian: Ringkasan; Apa yang dibuat & kenapa; Arsitektur; Siklus hidup; Uji end-to-end; serta Known trade-off & risiko. PR dan commit tampil sebagai sumber pekerjaan. Detail file, branch, diff, dan tabel perintah pengujian tidak ditampilkan.

Screenshot nyata harus tersedia dan disematkan. Bila gambar belum tersedia, laporan tetap draft. Gambar aplikasi lokal dengan data uji diberi keterangan dan tidak dianggap membuktikan fitur sudah tersedia di aplikasi operasional. Laporan disimpan per tanggal dan proyek di `~/Reports/day-reports`; pemanggilan ulang memperbarui laporan harian yang sama.

## Session report

Panduan lengkap ada di [skills/session-report/README.md](skills/session-report/README.md), termasuk format data, pemakaian, cetak, privasi, dan migrasi dari versi otomatis lama. Perilaku laporan sesi tetap terpisah dari laporan harian.

## Verifikasi

```sh
python3 skills/session-report/test/test_session_report.py
python3 test/test_day_report.py
python3 test/test_install.py
```

Repository ini menyimpan skill, renderer, template, dan pengujian. Laporan pribadi, screenshot pekerjaan, serta hasil evaluasi lokal tidak disimpan ke repository.
