# Format data laporan

Data disimpan sebagai `report.json`. Semua properti pada `assets/report.schema.json` wajib ada; gunakan `[]` atau `""` bila tidak berlaku. Schema menolak bagian tambahan agar format tetap enam bagian. Teks mendukung `**tebal**`, backtick pendek, dan baris baru; HTML bebas tidak dirender.

## Identitas dan ringkasan

`version` bernilai `1`. Isi `date` sebagai `YYYY-MM-DD`, `timezone` sesuai konteks pengguna, dan `scope` dengan proyek/cakupan yang sama seperti saat prepare. `title`, `summary`, `status_note` memakai bahasa pembaca. `status` adalah `finished`, `in_progress`, atau `blocked`, menggambarkan pekerjaan yang dilaporkan. Jika ada pekerjaan selesai dan pekerjaan lain masih berjalan, gunakan `in_progress` untuk keseluruhan laporan sambil mempertahankan status tiap pekerjaan. `coverage` menyebut apa yang diperiksa dan batasnya; bukan daftar file atau perintah.

## PR, commit, dan sumber lain

`sources` adalah daftar sumber, dengan properti:

- `kind`: `pr`, `commit`, `local`, `investigation`, atau `other`.
- `repository`: nama repo atau `""` jika tidak berlaku.
- `reference`: nomor PR tanpa `#`, SHA commit lengkap 40 karakter, atau penanda stabil untuk sumber lain.
- `title`: jelaskan pekerjaan dalam bahasa yang mudah dibaca.
- `url`: tautan sumber `https://...`, atau `""` bila tidak tersedia.
- `status`: status sumber yang terbukti, misalnya "Sudah digabungkan ke versi pengembangan" atau "Belum menjadi commit".
- `contribution`: `created` untuk sumber yang dibuat pengguna, `worked_on` untuk sumber yang dikerjakan, `related` untuk sumber pendamping. Jangan mengklaim sumber pendamping sebagai milik pengguna.
- `evidence`: dasar atribusi/tanggal/status untuk arsip internal. Tidak tampil di HTML.

Setiap sumber harus unik menurut `kind + repository + reference`. `changes[].source_refs` merujuk `reference` yang tercatat. Bila nomor PR sama di beberapa repo, gunakan `repository#reference` agar jelas. Renderer menyingkat SHA untuk tampilan, tetapi data menyimpan SHA lengkap.

## Apa yang dikerjakan

Setiap item `changes` memiliki `id`, `title`, `status`, `before`, `after`, `why`, `steps`, `impact`, `visual`, `screenshot_ids`, dan `source_refs`. `before` boleh kosong untuk penambahan baru. `steps` adalah langkah penggunaan atau alur yang relevan, bukan instruksi implementasi. `impact` menjawab apa artinya bagi pengguna, tim, atau operasi.

`visual: true` dipakai untuk perubahan tampilan atau alur yang memiliki keadaan layar baru. Perubahan ini harus merujuk minimal satu ID pada `evidence.steps`. Untuk pekerjaan internal, gunakan `visual: false`; gambar halaman PR/hasil pemeriksaan boleh mendukung konteks. Laporan secara keseluruhan tetap membutuhkan screenshot.

## Diagram

`architecture` memiliki `mermaid` dan `explanation`. `lifecycle` berisi `name`, `before` (diagram atau `null`) dan `after` (diagram). Gunakan label manusia, maksimal sekitar 12 node agar terbaca. Node perubahan boleh diberi `:::baru`, `:::ubah`, atau `:::hapus`. Jika diagram tidak relevan, isi `mermaid: ""` dengan penjelasan singkat dan faktual. `lifecycle: []` menampilkan catatan bahwa tidak ada perubahan perjalanan status yang dicatat.

## Screenshot dan pemeriksaan

`evidence.environment` menjelaskan sumber/lingkungan dan batas pengamatan. `evidence.steps` **tidak boleh kosong**. Setiap langkah berisi:

- `id`, `title`, `action`, `observed`: identitas, judul, tindakan, serta hasil yang benar-benar terlihat.
- `context`: misalnya "Aplikasi lokal dengan data uji", "Aplikasi operasional", "Halaman PR", atau "Hasil pemeriksaan". Jelaskan asal gambar lama bila digunakan kembali.
- `verification`: `ui_only` untuk inspeksi tampilan, `test_flow` untuk perjalanan dengan data uji, `end_to_end` hanya bila proses lengkap benar-benar diuji, `work_source` untuk screenshot PR/alat pemeriksaan.
- `result`: `observed` bila sebatas diamati, `pass` jika ada pemeriksaan yang benar-benar lulus, `fail` bila gagal.
- `screenshot`: path PNG/JPG/WebP nyata; absolut atau relatif terhadap `report.json`. Gambar disematkan agar HTML dapat dibagikan sendiri. URL gambar dan SVG tidak diterima sebagai screenshot.
- `captured_at`: waktu pengambilan yang diketahui; `""` bila tidak dapat dipastikan. Jangan menggantinya dengan waktu pembuatan laporan untuk screenshot lama.

Renderer memeriksa file, format gambar, rujukan ID, dan cakupan screenshot perubahan visual. Validasi otomatis tidak menggantikan kewajiban melihat gambar dan memeriksa relevansinya. Jika gambar belum ada, draft boleh menyimpan `evidence.steps: []` dengan status/kendala yang jujur; draft itu sengaja belum valid untuk render final. Renderer menolak membuat atau mengganti HTML final sampai screenshot tersedia.

## Risiko

Setiap `risks` memiliki `level` (`perhatian`, `sedang`, `rendah`), `title`, `impact`, dan `follow_up`. Tulis tindak lanjut yang konkret. Risiko yang tidak terbukti tidak ditambahkan hanya untuk mengisi bagian.
