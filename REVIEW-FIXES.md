# Review fixes

Penanganan 15 temuan review awal. Setiap perbaikan memiliki pengujian perilaku, bukan hanya pemeriksaan teks implementasi.

| # | Temuan | Penanganan dan bukti |
|---|---|---|
| 1 | Render manual memicu laporan duplikat | Render menyimpan jumlah perubahan yang sudah dilaporkan. Test memastikan gate diam sesudah render dan aktif lagi sesudah edit baru. |
| 2 | Commit pertama hilang pada repo baru | Snapshot sebelum operasi dan daftar commit eksplisit; parent commit pertama memakai empty tree. Test repo tanpa history. |
| 3 | Pull/merge/checkout mengklaim commit upstream | Atribusi dari reflog yang berubah selama operasi, bukan rentang base..HEAD. Commit yang masih reachable ditampilkan dengan patch masing-masing; rebase dicocokkan melalui patch-id. Test merge, switch dan rebase. |
| 4 | Teks `git commit` atau commit gagal memicu laporan | Snapshot membuktikan perubahan reflog; teks command dipakai hanya untuk menemukan directory kerja. Test perintah pencarian read-only dan commit gagal. |
| 5 | Komentar SQL terhapus dianggap header diff | Mode header berakhir pada hunk `@@`. Test baris `--- drop me` dan `+++ add me`. |
| 6 | Path non-ASCII hilang | Semua daftar path git memakai NUL separator; nama file tidak di-split pada baris/tab. Test `café.txt` dan path berisi tab/newline. |
| 7 | Manual auto menimpa sesi lain | ID dari environment harness terkait, tanpa mencari journal terbaru. Fallback ID unik; nama HTML memakai hash seluruh ID. Test identitas Claude/Codex dan fallback. |
| 8 | Push/checkout/stash tidak memperbarui status | Snapshot HEAD, branch, upstream dan isi file mendeteksi perubahan nyata. Test push ke bare remote lokal lalu gate aktif dan ahead=0. |
| 9 | Error ID/path dianggap schema error | Exit 2 hanya untuk JSON/schema; exit 1 untuk ID/path/environment. Test kedua kelas error. |
| 10 | Payload Codex dan workdir rapuh | Mendukung input patch string/dict serta command/cmd/workdir; matcher Pre/Post memasukkan nama shell terkait. Test raw patch dan command di repo berbeda dari cwd. Payload tiap versi Codex tetap bergantung pada API harness; alur hook live setelah update perlu trust `/hooks`. |
| 11 | Fork laporan dikenali dari substring | Memerlukan description tepat, fork background, path skill dan original session ID di prompt. Test agent lain tidak menekan laporan. |
| 12 | Mermaid CDN dapat mengakses diff privat | Bundle 11.12.0 lokal, checksum paket diverifikasi, disematkan ke HTML, CSP memblokir koneksi jaringan. Test bundle/policy dan Chromium offline: empat diagram dirender. |
| 13 | Report world-readable dan lock mengikuti symlink | Root/state/session directory diperiksa owner dan tipe, mode 0700; file baru 0600; lock/journal O_NOFOLLOW; atomic writer memakai tempfile unik. Test symlink root/lock tidak dapat menimpa target. |
| 14 | Matcher tidak di-upgrade, backup tertimpa | Installer memperbarui matcher dan handler miliknya, mempertahankan hook lain dan backup pertama. Test migrasi matcher, dua kali install, backup awal tetap utuh. |
| 15 | Meta ditulis ulang dan git dipanggil pada setiap edit | Cache directory→repo, edit Pre/Post yang sudah dikenal tidak menulis meta lagi. Semua penulisan atomik menggunakan helper bersama. Test mtime meta tetap setelah tiga pasangan edit hook. |

Review tambahan menemukan shell overwrite yang status git-nya tetap sama, file baru lewat shell yang tidak muncul di daftar file, dan `git am` yang terlewat. Snapshot sekarang membandingkan hash isi file dan mencatat path yang berubah; `am:` termasuk commit lokal. Seluruhnya mendapat test regresi.

Jumlah perubahan saat fork dimulai diteruskan ke renderer agar edit baru tidak dianggap sudah tercakup. Cooldown lima menit hanya menunda laporan otomatis; perubahan tetap pending, dan laporan manual dapat dijalankan kapan saja.

Batas atribusi: hook harus terpasang sebelum operasi; pekerjaan simultan di working tree yang sama selama satu tool berjalan dapat ambigu. History sebelum hook terpasang tidak ditebak. Diff commit ditampilkan per commit agar perubahan upstream di antaranya tidak tercampur. Resolusi konflik/rebase yang mengubah patch-id dapat memerlukan penjelasan file eksplisit dari agent.
