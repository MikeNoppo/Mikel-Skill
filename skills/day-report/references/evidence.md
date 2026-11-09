# Sumber pekerjaan harian

## Tanggal dan pemilik pekerjaan

Gunakan batas awal/akhir UTC dari `prepare.py`, bukan tanggal mesin atau tanggal UTC mentah. Pilih identitas dari akun terhubung/konteks pengguna. Nama akun GitHub, nama author Git, dan email commit bisa berbeda; cocokkan dengan bukti sebelum menyimpulkan.

Untuk PR, utamakan connector GitHub yang tersedia, lalu GitHub CLI. Cari PR yang dibuat dalam rentang hari itu dan baca detailnya. Untuk PR yang sudah ada, perubahan tanggal `updated_at` saja belum membuktikan pekerjaan pengguna; periksa commit, review, atau percakapan yang relevan. Bedakan kontribusi dari kepemilikan PR.

Untuk commit, gunakan riwayat repository yang diketahui, termasuk branch pekerjaan yang relevan. `git log --all` hanya mencakup referensi yang tersedia secara lokal. Tanggal author dan committer dapat berbeda karena rebase/cherry-pick; catat dasar pemilihan dan hindari menghitung pekerjaan yang sama dua kali. SHA lengkap disimpan pada data; renderer menyingkatnya untuk dibaca. Sertakan pekerjaan lokal yang terbukti dari diff/percakapan sebagai pekerjaan belum di-commit, bukan commit fiktif.

Pencarian tidak harus mencakup semua repository di akun. Ikuti cakupan yang diminta; gunakan proyek dan chat yang relevan dari konteks sebelum meminta pengguna mengulang informasi. Nyatakan repository atau sumber yang belum dapat diperiksa.

## Kekuatan bukti

- Deskripsi PR menjelaskan tujuan; periksa perubahan atau sumber lain untuk memastikan perilaku sebelum–sesudah.
- Hasil tes lama adalah bukti historis, bukan tes yang dijalankan pada laporan ini.
- Screenshot membuktikan keadaan yang tampak, bukan proses di balik layar yang tidak diperiksa.
- Tandai pemeriksaan layar, alur dengan data uji, atau end-to-end sungguhan secara terpisah.
- Perubahan internal tetap dapat dilaporkan. Jelaskan dampaknya dalam kalimat biasa, misalnya "mencegah proses menyimpan data yang sama dua kali".
- Jika sumber tidak membuktikan suatu hasil, tulis belum diperiksa atau masih menunggu, bukan sudah berhasil.

## Bahasa

| Rincian sumber | Kalimat untuk pembaca laporan |
| --- | --- |
| PR merged ke develop | Perubahan sudah digabungkan ke versi pengembangan |
| revoke refresh token | Perangkat lain perlu login kembali |
| payload reset berubah | Saat reset, admin perlu mengisi bukti tambahan |
| outbox persisten dengan retry | Pemberitahuan tetap dicoba kirim bila pengiriman terganggu |
| request timeout | Proses tidak terus menunggu saat sambungan bermasalah |

Gunakan nama tombol dan status yang terlihat pada aplikasi. Pertahankan istilah commit/PR karena merupakan sumber pekerjaan yang diminta; rincian file, SQL, endpoint, dan konfigurasi tidak perlu tampil kecuali dibutuhkan untuk memahami hasil.
