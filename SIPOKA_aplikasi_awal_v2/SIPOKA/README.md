# SIPOKA – Puskesmas Kaluku Bodoa

Starter aplikasi web internal untuk permintaan dan distribusi obat/BMHP.

## Fitur pada versi awal
- Login username + PIN dengan hash PBKDF2
- Peran admin, petugas farmasi, petugas unit, dan pimpinan
- Master obat/BMHP (data awal dari file yang diberikan: 269 baris unik berdasarkan kombinasi nama+satuan; kategori perlu diklasifikasi petugas) dan stok
- Permintaan unit, verifikasi farmasi, distribusi, pengurangan stok
- Riwayat permintaan dan laporan distribusi

## Menjalankan di komputer untuk uji coba
Disarankan Python 3.10+.

```bash
python -m venv .venv
# Windows:
.venv\\Scripts\\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
```

Set PIN admin awal sebelum menjalankan aplikasi:
- Windows PowerShell: `$env:SIPOKA_ADMIN_PIN="PINAWAL123"` (gunakan angka minimal 6 digit; contoh `654321`)
- macOS/Linux: `export SIPOKA_ADMIN_PIN=654321`

Atur secret aplikasi:
- Windows PowerShell: `$env:APP_SECRET="ganti-dengan-random-secret-panjang"`
- macOS/Linux: `export APP_SECRET="ganti-dengan-random-secret-panjang"`

Jalankan:
```bash
python app.py
```
Buka `http://127.0.0.1:5000`.

Akun awal:
- Username: `admin`
- PIN: sesuai `SIPOKA_ADMIN_PIN`; jika tidak diatur, PIN awal adalah `123456`.

**Segera login dan ubah PIN admin.** Jangan gunakan PIN default di server publik.

## Agar dapat diakses banyak orang melalui internet
Aplikasi perlu dipasang pada server/hosting yang mendukung Python dan HTTPS. Jalankan dengan server WSGI produksi (misalnya Gunicorn), bukan mode development Flask. Atur `APP_SECRET` yang kuat, `SIPOKA_ADMIN_PIN`, dan lokasi database persisten. Pastikan ada backup database rutin dan pembatasan akses sesuai kebijakan Puskesmas.

Untuk penggunaan multiuser di lingkungan kerja, sebaiknya gunakan PostgreSQL pada tahap produksi, HTTPS, backup otomatis, serta uji keamanan dan uji alur kerja sebelum dipakai untuk transaksi resmi.

## Catatan penting
Ini adalah prototipe awal untuk diuji, bukan sistem produksi yang telah diaudit. Data obat, stok awal, akun, dan satuan harus dimasukkan/diverifikasi oleh petugas berwenang. Jangan memasukkan data pasien atau informasi kesehatan pribadi. Sebelum dipakai resmi, lakukan pengujian, validasi SOP, backup, dan peninjauan keamanan oleh pengelola TI.
