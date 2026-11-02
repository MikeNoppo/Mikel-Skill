# session-report

Laporan sesi HTML berbahasa Indonesia untuk Claude Code dan Codex. Berisi hasil kerja, alasan dan implementasi, status siap commit/PR, diagram arsitektur/alur lama dan baru, diff, bukti pengujian, keputusan tertunda, serta langkah berikutnya. Code review hanya ditampilkan bila review memang ada dalam sesi; membuat laporan tidak menjalankan review baru.

## Pakai

Panggil `/session-report` di Claude Code atau `$session-report` di Codex. Agent utama menyelesaikan laporan langsung di percakapan yang sama dengan model dan effort sesi tersebut. Tidak ada hook pencatatan, pemicu akhir turn, worker, subagent, cooldown, atau pesan chat terjadwal.

Sebelum menulis, agent memeriksa laporan sesi melalui `scripts/prepare.py`. Jika ada, data lama dibaca dan diperbarui secara kumulatif. JSON disimpan di `/tmp/session-reports/<session-id>/report.json`; HTML memakai URL yang sama pada pemanggilan berikutnya, termasuk laporan lama dari versi otomatis. Sesi lain memiliki laporan tersendiri. Untuk memperbarui laporan dari sesi lain, minta secara eksplisit dan sebutkan laporan tersebut.

Agent menampilkan link di chat setelah render. `--open` membuka laporan langsung. `latest.html` dan `index.html` membantu menemukan laporan. File di `/tmp` dapat hilang saat reboot. Bila environment tidak menyediakan ID sesi, agent harus memberikan ID sesi asli secara eksplisit.

## Instalasi

Butuh **git, Python 3.10+**, serta **Claude Code atau Codex**. Tidak ada dependency Python tambahan. Implementasi memakai fasilitas POSIX; Linux sudah diuji, macOS belum diuji menyeluruh. Windows native belum didukung; pengguna Windows dapat memakai WSL dengan browser/opener yang dikonfigurasi di lingkungan WSL.

Jalankan di terminal (tidak perlu sudo atau login GitHub):

```sh
mkdir -p "$HOME/.agents/skills"
git clone https://github.com/MikeNoppo/session-report.git "$HOME/.agents/skills/session-report"
python3 "$HOME/.agents/skills/session-report/scripts/install.py"
```

Installer membuat link skill untuk Claude Code dan memastikan lokasi penemuan Codex tersedia. Jika nama folder sudah dipakai instalasi lain, installer berhenti tanpa menimpanya. Instalasi tidak menambahkan hooks atau permission otomatis. Mulai sesi baru setelah instalasi, lalu panggil:

- **Claude Code:** `/session-report`
- **Codex:** `$session-report`

Skill menggunakan model dan effort percakapan yang sedang berjalan. Tidak perlu Omarchy. Pada Linux biasa, laporan dibuka melalui `xdg-open`; pada macOS memakai `open`. Jika browser tidak terbuka, gunakan link HTML yang ditampilkan di chat.

Untuk memperbarui instalasi:

```sh
git -C "$HOME/.agents/skills/session-report" pull --ff-only
python3 "$HOME/.agents/skills/session-report/scripts/install.py"
```

Repo hanya berisi skill, template, renderer, dan data uji contoh. Laporan sesi dibuat lokal, bukan dikirim atau di-commit ke repo ini. HTML dapat memuat diff kode dan screenshot; periksa isinya sebelum membagikannya.

### Migrasi dari versi otomatis

Command installer yang sama menghapus hook milik skill ini dan permission khusus yang dulu dipasangnya, mempertahankan konfigurasi lain. Backup pertama migrasi disimpan sebagai `.bak-session-report-manual`. Mulai ulang sesi Claude/Codex yang sudah terbuka agar konfigurasi lama tidak lagi tersimpan dalam sesi. Entrypoint `track.py` dan `gate.py` lama menjadi no-op untuk kompatibilitas sesi yang belum dimuat ulang.

## Tampilan

Tema White dan Black dapat dipilih melalui tombol di kanan atas HTML. Default White; pilihan disimpan di browser bila localStorage tersedia. Diagram dirender ulang sesuai tema. Navigasi bagian berada di kiri pada desktop dan horizontal pada layar kecil. Isi memakai pemisah tipis, warna status secukupnya, diagram offline, diff yang dapat dibuka, dan layout cetak.

## Cetak dan PDF

Gunakan Ctrl+P lalu Save as PDF. Layout cetak memakai A4, margin dokumen, nomor halaman dan tema putih, termasuk diagram meskipun layar memakai Black. Sidebar serta kontrol disembunyikan. Diff dibuka saat mencetak dan dikembalikan sesudahnya. Aktifkan Background graphics untuk mempertahankan warna status/diff; matikan Headers and footers bawaan browser agar URL lokal dan tanggal tidak ikut tercetak.

Judul mengikuti kontennya, header tabel berulang pada halaman berikutnya, dan baris tabel, diagram beserta penjelasan, screenshot serta blok singkat diusahakan tetap utuh. Blok yang lebih tinggi dari satu halaman tetap harus dibagi; diff panjang dibungkus dan dapat berlanjut antarhalaman. Jeda kosong dapat muncul agar satu blok tidak terbelah. Batas diff yang memang dipotong renderer tetap berlaku dan ditandai di laporan.

## Bukti dan privasi

Percakapan menjadi sumber cakupan kerja. File sesi dicantumkan eksplisit; hash commit penuh hanya dimasukkan bila terbukti dibuat dalam sesi. Renderer membaca kondisi git saat dipanggil, menampilkan patch commit yang dicantumkan dan perubahan file yang belum di-commit. Commit upstream tidak otomatis dianggap pekerjaan sesi. Metadata commit versi lama tetap dapat dibaca untuk laporan sesi yang sudah ada. Perubahan bersamaan pada file yang sama dapat membuat atribusi ambigu; jelaskan batas bukti atau gunakan worktree terpisah.

Renderer memvalidasi JSON dengan schema tetap, memakai template HTML, dan menyematkan Mermaid 11.12.0 lokal sehingga diagram bekerja offline. CSP memblokir koneksi jaringan. Folder laporan/state dibatasi ke pemilik (0700), file baru 0600. `SESSION_REPORT_DIR` mengganti folder laporan; Notifikasi desktop tidak digunakan.

## Verifikasi

```sh
python3 test/test_session_report.py
```

Format data ada di [REPORT-DATA.md](REPORT-DATA.md).
