# CMSPlus

Drupal projelerini tek yerden yönetmek için platform: proje listesi, SEO kontrolleri, ekran görüntüleri, alertler.

## Stack

- FastAPI + Jinja2 (server-rendered, Tailwind CDN)
- PostgreSQL (Docker Compose)
- SQLAlchemy 2.0
- httpx (sağlık kontrolü), cryptography (SSL kontrolü), Playwright (SEO taraması), pandas (SEO/Lighthouse raporlama)
- Node.js + Lighthouse (performans/erişilebilirlik/best-practices/SEO denetimi)
- APScheduler (ortam başına zamanlanmış cron job'lar; uygulama süreci ayakta olduğu sürece çalışır)
- smtplib (stdlib) ile cron job bildirim e-postaları
- Pillow + numpy ile ortamlar arası görsel karşılaştırma (fark tespiti ve işaretleme)

## Kurulum

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium   # SEO taraması için gerekli
cp .env.example .env

cd lighthouse && npm install && cd ..     # Lighthouse raporu için gerekli (Node.js >= 18.16)

docker compose up -d db

.venv/bin/uvicorn app.main:app --reload
```

E-posta bildirimlerinin gerçekten gönderilmesi için `.env` dosyasındaki `SMTP_*` değişkenlerini doldur
(ör. Gmail için `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, kullanıcı adı ve normal şifre yerine bir
[uygulama şifresi](https://myaccount.google.com/apppasswords)). `SMTP_HOST` boş bırakılırsa e-posta
gönderilmez, yalnızca log'a yazılır — geliştirme sırasında hata vermez.

Uygulama http://127.0.0.1:8000 adresinde çalışır.

## Yapı

```
app/
  main.py               FastAPI app ve route'lar
  database.py           SQLAlchemy engine/session
  models.py             Project, Environment, HealthCheck, SeoCheck, LighthouseCheck, CronJob modelleri
  health_check.py        httpx ile sağlık kontrolü
  ssl_check.py            SSL sertifika kontrolü
  seo_check.py           Playwright ile SEO extraction + skor hesaplama
  lighthouse_check.py    Node/Lighthouse subprocess wrapper
  scheduler.py           APScheduler kurulumu + cron job çalıştırma
  email_notify.py        SMTP ile bildirim e-postası gönderme
  visual_compare.py      Playwright ile ekran görüntüsü + Pillow/numpy ile fark tespiti
  scenario_runner.py      Playwright ile kural tabanlı senaryo/adım çalıştırma motoru
  templates/              Jinja2 template'leri
  static/                 CSS/JS
lighthouse/
  run.mjs          Lighthouse'u çalıştırıp JSON raporu stdout'a yazan Node script'i
  package.json     lighthouse + chrome-launcher bağımlılıkları
```

## Veri modeli

Her proje (`Project`) bir veya daha fazla ortama (`Environment`: Production, Staging, Development...) sahip olabilir.
URL ve Drupal sürümü bilgisi ortam seviyesinde tutulur; her projede bir ortam "birincil" olarak işaretlenir ve
proje listesindeki kartlarda özet olarak gösterilir. Her ortamın kendi detay sayfası (`/projects/{id}/environments/{id}`)
vardır; sağlık/SSL/SEO/Lighthouse kontrolleri ve o ortama ait cron job'lar (otomatik, zamanlanmış kontroller) burada yönetilir.

Bir projede 2+ ortam varsa, proje sayfasından "Ortamları Karşılaştır" ile iki ortamın seçilen sayfalarının (aynı
path, her iki ortamın URL'sine eklenir) ekran görüntüsü alınıp piksel bazında karşılaştırılır; farklı bölgeler
kırmızı kutularla işaretlenmiş bir görsel olarak sunulur.

Her ortamda ayrıca kural tabanlı **senaryolar** tanımlanabilir: sayfaya git, tıkla, alan doldur, seçim yap, metin/eleman
var mı kontrol et, eleman sayısını karşılaştır (`>=`, `==` vb.) gibi adımlardan oluşan bir dizi, "Çalıştır" ile
Playwright üzerinden sırayla işletilir. İlk başarısız adımda durur, hata ve ekran görüntüsüyle birlikte kaydedilir.
Bu tamamen kural/adım tabanlıdır — yapay zeka içermez, her adım deterministik bir Playwright komutuna karşılık gelir.
