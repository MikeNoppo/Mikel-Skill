# session-report

Laporan HTML berbahasa Indonesia untuk review pekerjaan agent di Claude Code dan Codex. Developer bisa melihat hasil, alasan perubahan, bukti pengujian, dan keputusan yang perlu diambil dalam satu tempat.

Laporan mencakup status siap commit/PR, implementasi per repo, diagram arsitektur dan alur lama/baru, daftar file beserta diff, hasil code review, pengujian dan E2E, trade-off, pekerjaan di luar cakupan, serta langkah berikutnya. Screenshot E2E opsional dan hanya digunakan untuk pengujian UI.

## Pasang

Butuh Linux, Python 3.10+, git, serta Claude Code dan/atau Codex CLI yang mendukung lifecycle hooks. Tidak ada dependency Python tambahan. Claude Code menggunakan `claude --resume <id> --fork-session --effort low` dengan model sesi asal; Codex menggunakan `codex exec fork --ephemeral` dengan reasoning low. Worker Claude hanya mendapat tool Read, mengembalikan JSON terstruktur, dan tidak mengubah effort sesi utama.

Clone repo private ini ke `~/.agents/skills/session-report`, lalu buat symlink `~/.claude/skills/session-report` ke folder tersebut jika belum ada. Jalankan:

```sh
python3 ~/.agents/skills/session-report/scripts/install.py
```

Installer memperbarui hanya hook milik skill ini di `~/.claude/settings.json` dan `~/.codex/hooks.json`, mempertahankan konfigurasi lain dan backup pertama `.bak-session-report`. Path hook mengikuti lokasi script installer. Di Codex CLI, buka `/hooks` dan trust hook setelah pemasangan atau perubahan konfigurasi. Reload/restart sesi jika harness belum memuat konfigurasi baru.

Instruksi skill menggunakan lokasi instalasi di atas. Bila dipasang di lokasi lain, sesuaikan path render di `SKILL.md`.

## Pakai

Manual: `/session-report` di Claude Code atau `$session-report` di Codex. Otomatis: saat turn yang memiliki perubahan selesai, Stop hook memicu laporan background. Worker membaca konteks sesi; jika agent masih menunggu jawaban yang dibutuhkan untuk melanjutkan tugas, worker mengembalikan skip dan HTML tidak dibuat.

Hasil ada di `/tmp/session-reports/`: satu HTML per sesi (hash 12 karakter dari seluruh session ID), `latest.html`, dan `index.html`. Folder dibatasi ke user pemilik (0700). Di Omarchy, klik notifikasi untuk membuka laporan; desktop lain mendapat notifikasi jika `notify-send` tersedia. Setelah selesai, link juga dikirim ke chat asal sebagai `Laporan sesi: Buka laporan`. Codex menggunakan `codex queue` untuk meminta satu balasan singkat di thread asal; Claude memakai Stop hook `asyncRewake` yang membangunkan percakapan setelah worker selesai. Pesan baru ini memakai satu giliran singkat pada model sesi utama. Data laporan sementara dan bisa hilang saat reboot.

Model menulis JSON dengan schema tetap; renderer menyusun HTML, bukti git, diff, dan screenshot. Mermaid 11.12.0 disertakan lokal, diverifikasi terhadap SHA-512 paket npm saat pengambilan. HTML menyematkan bundle dan dapat dibuka offline. Content Security Policy memblokir koneksi jaringan.

## Pencatatan dan biaya

PreToolUse/PostToolUse membandingkan reflog dan kondisi repo. Hanya commit lokal yang muncul di dalam operasi tool yang dimasukkan; commit yang masuk lewat pull/merge tidak diatribusikan ke sesi. Patch ditampilkan per commit sesi, dilanjutkan perubahan yang belum di-commit. Commit yang di-rebase dicocokkan melalui patch-id. Push, checkout, switch, dan stash memperbarui kondisi laporan.

Perubahan sebelum hook terpasang tidak direkonstruksi dengan menebak history. Tuliskan file yang belum tercatat pada `repos[].files`; commit historis hanya ditampilkan bila benar-benar tercatat. Pekerjaan bersamaan di working tree yang sama selama satu tool berjalan dapat membuat atribusi ambigu. Gunakan worktree terpisah untuk sesi paralel.

Laporan background membaca konteks sesi dan memakai kuota akun. Claude memakai salinan sesi lewat proses CLI terpisah karena effort pada subagent `fork` di Claude Code 2.1.312 selalu mengikuti parent dan mengabaikan override. Proses CLI tidak menjamin berbagi prompt cache seperti fork in-process; kuota bisa lebih besar walaupun reasoning low. Default cooldown lima menit: perubahan selama jeda tetap pending dan diproses pada akhir turn berikutnya setelah jeda berakhir. Tidak ada timer yang membuat laporan ketika sesi sedang diam. Laporan manual selalu bisa dijalankan.

| Environment | Default | Fungsi |
|---|---|---|
| `SESSION_REPORT_COOLDOWN` | `300` | Jeda minimum laporan otomatis, detik; `0` menonaktifkan jeda |
| `SESSION_REPORT_DIR` | `/tmp/session-reports` | Folder absolut milik user untuk laporan dan state |
| `SESSION_REPORT_NOTIFY` | `1` | `0` menonaktifkan notifikasi desktop |
| `SESSION_REPORT_CHAT` | `1` | `0` menonaktifkan pesan link otomatis di chat |
| `SESSION_REPORT_CHILD` | tidak disetel | `1` mencegah hook rekursif di worker laporan |

Manual mode memakai `CODEX_THREAD_ID` atau `CLAUDE_CODE_SESSION_ID` sesuai harness. Bila environment tidak menyediakan ID, `auto` membuat identitas baru yang unik dan tidak mengambil laporan sesi lain. Jika pengiriman chat gagal atau sesi sudah ditutup, laporan tetap tersedia melalui file dan notifikasi desktop; error pengiriman dicatat di state sesi. Pesan chat Claude memerlukan sesi interaktif yang masih hidup: mode `claude -p` membatalkan async hook saat teardown.

## Verifikasi

```sh
python3 test/test_session_report.py
```

Pengujian memakai repo git dan direktori laporan sementara. Detail penanganan 15 temuan review ada di [REVIEW-FIXES.md](REVIEW-FIXES.md). Format data untuk agent ada di [REPORT-DATA.md](REPORT-DATA.md).
