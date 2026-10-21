# TradingView ke WhatsApp melalui WatZap

Skrip ini membuka chart TradingView di Google Chrome dengan profil browser
lokal yang persisten, menyimpan screenshot,
mengunggah gambar ke Cloudinary agar bisa diakses melalui URL publik, lalu
mengirimnya ke nomor WhatsApp tujuan melalui endpoint WatZap
`/send_image_url`.

## Persiapan

1. Gunakan Python 3.10 atau lebih baru.
2. Salin `.env.example` menjadi `.env` di folder yang sama dengan skrip, lalu isi kredensial. Skrip membaca file `.env` dari folder skrip, jadi bisa dijalankan dari folder kerja mana pun:
   - WatZap API Key tersedia di menu **INTEGRATIONS > API Key**.
   - WatZap Number Key tersedia pada nomor yang terhubung di tab **WhatsApp > API**.
   - Nomor tujuan gunakan format internasional tanpa `+`, misalnya `6281234567890`.
   - Buat akun Cloudinary dan isi Cloud Name, API Key, serta API Secret.
3. Instal dependensi dan browser Playwright:

   ```powershell
   py -m pip install -r requirements.txt
   ```

4. Siapkan sesi Chrome sekali saja. Perintah ini membuka Google Chrome biasa
   dengan profil khusus skrip (terpisah dari profil pribadi). Login ke
   TradingView melalui jendela Chrome, buka chart dengan layout indikator yang
   sudah disimpan, pastikan garis EMA tampil, lalu kembali ke terminal dan
   tekan Enter. Sesi tersimpan di
   `%LOCALAPPDATA%\ChartMonitor\ChromeRemoteProfile`.

   ```powershell
   py .\screenshot_tradingview.py --setup-chrome
   ```

## Menjalankan

```powershell
py .\screenshot_tradingview.py
```

Secara default skrip mengambil `BINANCE:BTCUSDT` pada interval 15 menit.
Simbol dan interval dapat diubah di `.env` atau diberikan langsung:

```powershell
py .\screenshot_tradingview.py --symbol "NASDAQ:AAPL" --interval "1D" --caption "Chart AAPL harian"
```

Untuk mempertahankan tampilan chart TradingView yang sudah disimpan (termasuk
indikator dan drawing), isi `TRADINGVIEW_CHART_URL` di `.env` dengan URL chart
tersebut. Jika URL ini diisi, skrip memakainya alih-alih symbol dan interval.
URL juga dapat diberikan melalui `--chart-url`.

Skrip menyambung ke Chrome melalui remote debugging di `127.0.0.1:9222`.
Chrome 136 ke atas tidak mengizinkan remote debugging memakai profil Chrome
bawaan, sehingga skrip menggunakan profil khusus dan terpisah dari profil
pribadi. Jalankan `--setup-chrome` untuk login pertama kali atau bila sesi
login habis. Browser dibiarkan terbuka agar sesi dapat dipakai ulang; tutup
jendela Chrome khusus itu setelah selesai menggunakan skrip.

Screenshot tetap tersimpan di harddisk lokal pada
`C:\laragon\app\ChartMonitor\screenshots\chart.png` secara default (folder
dibuat otomatis). Path relatif dari `SCREENSHOT_PATH` atau `--output` dihitung
dari folder skrip, bukan dari folder terminal saat ini. Screenshot dipotong ke
area chart berukuran 1600 × 768 piksel, dengan panel daftar pantau dan banner
mode baca-saja disembunyikan agar komposisinya mendekati contoh.

Untuk mengirim screenshot ke WhatsApp, WatZap membutuhkan gambar melalui URL
publik. Karena itu skrip juga mengunggah salinan gambar ke Cloudinary sebelum
mengirimkannya; file lokal tetap disimpan. Atur `SCREENSHOT_PATH`,
`CHART_WAIT_SECONDS`, atau `WHATSAPP_CAPTION` melalui `.env`. Skrip mengirim
satu gambar setiap kali dijalankan; jadwalkan dengan Windows Task Scheduler
jika ingin berjalan berkala.

## Catatan keamanan

- Jangan bagikan `.env` atau commit file tersebut ke repository.
- Profil Chrome khusus menyimpan sesi login TradingView. Jangan bagikan folder
  `%LOCALAPPDATA%\ChartMonitor\ChromeRemoteProfile`. Remote debugging hanya
  diikat ke loopback (`127.0.0.1`); jangan ubah agar menerima koneksi jaringan.
- Gambar yang diunggah ke Cloudinary memiliki URL publik, jadi chart tersebut
  bisa diakses oleh siapa pun yang memiliki URL.
- Pastikan WatZap API Key dan Number Key hanya dipakai di nomor API yang
  terhubung dan online.

Referensi: [WatZap API Key dan endpoint](https://docs.watzap.id/help/integrations/mendapatkan-api-key-di-member-area.md),
[WatZap Number Key](https://docs.watzap.id/help/integrations/mendapatkan-number-key-untuk-api.md),
dan [dokumentasi API WatZap](https://api-docs.watzap.id/).
