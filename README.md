# session-report

Laporan sesi HTML berbahasa Indonesia untuk Claude Code dan Codex. Berisi hasil kerja, alasan dan implementasi, status siap commit/PR, diagram arsitektur/alur lama dan baru, diff, bukti pengujian, keputusan tertunda, serta langkah berikutnya. Code review hanya ditampilkan bila review memang ada dalam sesi; membuat laporan tidak menjalankan review baru.

## Pakai

Panggil `/session-report` di Claude Code atau `$session-report` di Codex. Agent utama menyelesaikan laporan langsung di percakapan yang sama dengan model dan effort sesi tersebut. Tidak ada hook pencatatan, pemicu akhir turn, worker, subagent, cooldown, atau pesan chat terjadwal.

Sebelum menulis, agent memeriksa laporan sesi melalui `scripts/prepare.py`. Jika ada, data lama dibaca dan diperbarui secara kumulatif. JSON disimpan di `/tmp/session-reports/<session-id>/report.json`; HTML memakai URL yang sama pada pemanggilan berikutnya, termasuk laporan lama dari versi otomatis. Sesi lain memiliki laporan tersendiri. Untuk memperbarui laporan dari sesi lain, minta secara eksplisit dan sebutkan laporan tersebut.

Agent menampilkan link di chat setelah render. `--open` membuka laporan langsung. `latest.html` dan `index.html` membantu menemukan laporan. File di `/tmp` dapat hilang saat reboot. Bila environment tidak menyediakan ID sesi, agent harus memberikan ID sesi asli secara eksplisit.

## Instalasi atau migrasi

Butuh Python 3.10+ dan git, tanpa dependency Python tambahan. Clone ke `~/.agents/skills/session-report`; Claude Code memakai symlink `~/.claude/skills/session-report` ke folder yang sama. Codex menemukan skill di folder `.agents/skills`.

Untuk melepas konfigurasi otomatis versi lama:

```sh
python3 ~/.agents/skills/session-report/scripts/install.py
```

Script hanya menghapus hook skill ini dan permission khusus yang dulu dipasangnya, mempertahankan konfigurasi lain. Backup pertama migrasi disimpan sebagai `.bak-session-report-manual`. Tidak memasang hook baru. Mulai ulang sesi Claude/Codex yang sudah terbuka agar konfigurasi lama tidak lagi tersimpan dalam sesi. Entrypoint `track.py` dan `gate.py` lama menjadi no-op untuk kompatibilitas sesi yang belum dimuat ulang.

## Tampilan

Tema putih tetap, tipografi charcoal, navigasi bagian di kiri pada desktop dan horizontal pada layar kecil. Isi memakai pemisah tipis, warna status secukupnya, diagram offline, diff yang dapat dibuka, dan layout cetak. Tema OS gelap tidak mengubah warna laporan.

## Bukti dan privasi

Percakapan menjadi sumber cakupan kerja. File sesi dicantumkan eksplisit; hash commit penuh hanya dimasukkan bila terbukti dibuat dalam sesi. Renderer membaca kondisi git saat dipanggil, menampilkan patch commit yang dicantumkan dan perubahan file yang belum di-commit. Commit upstream tidak otomatis dianggap pekerjaan sesi. Metadata commit versi lama tetap dapat dibaca untuk laporan sesi yang sudah ada. Perubahan bersamaan pada file yang sama dapat membuat atribusi ambigu; jelaskan batas bukti atau gunakan worktree terpisah.

Renderer memvalidasi JSON dengan schema tetap, memakai template HTML, dan menyematkan Mermaid 11.12.0 lokal sehingga diagram bekerja offline. CSP memblokir koneksi jaringan. Folder laporan/state dibatasi ke pemilik (0700), file baru 0600. `SESSION_REPORT_DIR` mengganti folder laporan; Notifikasi desktop tidak digunakan.

## Verifikasi

```sh
python3 test/test_session_report.py
```

Format data ada di [REPORT-DATA.md](REPORT-DATA.md).
