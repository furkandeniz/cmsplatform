# CMSPlus

Herhangi bir web sitesini/projeyi (Drupal, WordPress, özel geliştirme fark etmeksizin) tek yerden izlemek ve test
etmek için platform: proje ve ortam (Production/Staging/...) yönetimi, otomatik sağlık/SSL/SEO/Lighthouse
kontrolleri, ortamlar arası görsel karşılaştırma, kural tabanlı Playwright senaryoları ve zamanlanmış cron job'lar
üzerinden e-posta uyarıları. Tüm kontroller URL üzerinden çalışır; belirli bir CMS veya teknolojiye bağımlılık
yoktur.

## Özellikler

- **Proje & ortam yönetimi** — Her proje birden çok ortama sahip olabilir (Production, Staging, Development...).
  Bir ortam "birincil" (primary) olarak işaretlenir ve proje kartlarında özet gösterilir.
- **Sağlık kontrolü** — HTTP isteği atıp durum kodu, yanıt süresi, response header/body'yi kaydeder (`httpx`).
- **SSL kontrolü** — Sertifikanın geçerlilik tarihini, kalan gün sayısını, issuer/subject bilgisini okur (`cryptography`).
- **SEO kontrolü** — Sayfayı Playwright ile açıp title/meta description/canonical/h1/OG etiketleri/structured data/
  görsel alt metinleri gibi sinyalleri çıkarır, eksiklere göre 0-100 arası bir skor hesaplar.
- **Lighthouse denetimi** — Node.js tabanlı Lighthouse'u subprocess olarak çalıştırıp performans/erişilebilirlik/
  best-practices/SEO skorlarını ve en kötü audit'leri kaydeder.
- **Ortamlar arası görsel karşılaştırma** — Aynı path'in iki ortamdaki (örn. Staging vs Production) ekran görüntüsünü
  alıp piksel bazında karşılaştırır; farklı bölgeleri kırmızı kutularla işaretleyip fark yüzdesini raporlar
  (`Pillow` + `numpy`).
- **Senaryolar** — Her ortamda, adım adım tanımlanan kural tabanlı Playwright akışları (bkz. aşağıdaki tablo).
  Tamamen deterministiktir, yapay zeka içermez; her adım doğrudan bir Playwright komutuna karşılık gelir. İlk
  başarısız adımda durur, hata mesajı ve ekran görüntüsüyle birlikte çalıştırma geçmişine kaydedilir. Çalıştırma
  geçmişi sunucu taraflı sayfalanır (10 kayıt/sayfa).
- **Cron job'lar** — Her ortam için health/ssl/seo/lighthouse/senaryo kontrollerinden biri, belirli bir sıklıkta
  (15dk / 1sa / 6sa / günlük / haftalık) otomatik çalışacak şekilde zamanlanabilir (`APScheduler`, uygulama süreci
  ayakta olduğu sürece çalışır — ayrı bir worker gerekmez). Durum değişince (başarılıdan başarısıza veya tersi)
  isteğe bağlı olarak e-posta uyarısı gönderilir.

## Stack

- FastAPI + Jinja2 (server-rendered, Tailwind CDN)
- PostgreSQL + SQLAlchemy 2.0 (Docker Compose ile; Alembic yok — şema değişiklikleri elle `ALTER TABLE` gerektirir,
  bkz. [Geliştirme notları](#geliştirme-notları))
- httpx (sağlık kontrolü), cryptography (SSL kontrolü), Playwright (SEO taraması + senaryolar + görsel karşılaştırma
  için ekran görüntüsü), pandas (SEO/Lighthouse raporlama)
- Node.js + Lighthouse (performans/erişilebilirlik/best-practices/SEO denetimi)
- APScheduler (ortam başına zamanlanmış cron job'lar)
- smtplib (stdlib) ile cron job bildirim e-postaları
- Pillow + numpy ile ortamlar arası görsel karşılaştırma (fark tespiti ve işaretleme)

## Kurulum

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium   # SEO taraması + senaryolar + görsel karşılaştırma için gerekli
cp .env.example .env

cd lighthouse && npm install && cd ..     # Lighthouse raporu için gerekli (Node.js >= 18.16)

docker compose up -d db

.venv/bin/uvicorn app.main:app --reload
```

Uygulama http://127.0.0.1:8000 adresinde çalışır.

### Ortam değişkenleri (`.env`)

| Değişken | Açıklama |
| --- | --- |
| `DATABASE_URL` | SQLAlchemy bağlantı dizesi (`postgresql+psycopg2://...`). Varsayılan, `docker-compose.yml`'deki `db` servisiyle eşleşir. |
| `SMTP_HOST` | Cron job bildirim e-postaları için SMTP sunucusu. Boş bırakılırsa e-posta gönderilmez, sadece loglanır — geliştirme sırasında hata vermez. |
| `SMTP_PORT` | Varsayılan `587`. |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | SMTP kimlik bilgileri (ör. Gmail için normal şifre yerine bir [uygulama şifresi](https://myaccount.google.com/apppasswords)). |
| `SMTP_FROM_EMAIL` | Gönderen adresi; boşsa `SMTP_USERNAME`, o da yoksa `cmsplus@localhost` kullanılır. |
| `SMTP_USE_TLS` | `true`/`false`. Varsayılan `true`. |
| `BASE_URL` | Bildirim e-postalarındaki linklerin işaret edeceği adres (ör. `http://localhost:8000`). |

### Sorun Giderme

- **"node bulunamadı (Lighthouse için Node.js kurulu olmalı)"** — Node.js kurulu olsa bile, uygulamayı başlatan
  sürecin `PATH`'inde Node'un bulunduğu dizin (Homebrew'da `/opt/homebrew/bin`) yoksa bu hata alınır. Uygulamayı
  normal bir terminalden (`~/.zprofile`/`~/.zshrc` düzgün ayarlıysa) başlatmak genelde yeterlidir; IDE/arka plan
  görevi gibi PATH'i miras almayan bir ortamdan başlatılıyorsa `PATH`'in Node'un `bin` dizinini içerdiğinden emin ol.
- **Playwright ile ilgili hatalar (senaryo/SEO/görsel karşılaştırma çalışmıyor)** — `playwright install chromium`
  komutunun çalıştırıldığından emin ol.

## Yapı

```
app/
  main.py                FastAPI app ve tüm route'lar (proje/ortam CRUD, kontroller, senaryolar, cron job'lar, karşılaştırmalar)
  database.py             SQLAlchemy engine/session (DATABASE_URL, Base.metadata.create_all)
  models.py                Project, Environment, HealthCheck, SeoCheck, LighthouseCheck, CronJob,
                            EnvironmentComparison/ComparisonPage, Scenario/ScenarioStep/ScenarioRun/ScenarioStepResult
  health_check.py          httpx ile sağlık kontrolü
  ssl_check.py              SSL sertifika kontrolü
  seo_check.py             Playwright ile SEO extraction + skor hesaplama
  lighthouse_check.py      Node/Lighthouse subprocess wrapper
  visual_compare.py        Playwright ile ekran görüntüsü + Pillow/numpy ile fark tespiti
  scenario_runner.py       Playwright ile kural tabanlı senaryo/adım çalıştırma motoru
  scheduler.py             APScheduler kurulumu + cron job çalıştırma + durum değişiminde e-posta bildirimi
  email_notify.py          SMTP ile bildirim e-postası gönderme
  templates/               Jinja2 template'leri
  static/                  CSS/JS, yüklenen ekran görüntüleri (app/static/uploads/, git'e dahil değil)
lighthouse/
  run.mjs          Lighthouse'u çalıştırıp JSON raporu stdout'a yazan Node script'i
  package.json     lighthouse + chrome-launcher bağımlılıkları
```

## Veri modeli

Her proje (`Project`) bir veya daha fazla ortama (`Environment`) sahiptir. URL bilgisi ve isteğe bağlı bir
CMS/sürüm notu (`drupal_version` alanı — Drupal projeleri için düşünülmüş olsa da boş bırakılabilir, herhangi bir
site için zorunlu değildir) ortam seviyesinde tutulur; her ortamın son sağlık/SSL/SEO/Lighthouse kontrol sonucu, hızlı erişim için doğrudan
`Environment` satırında da önbelleklenir (`last_check_ok`, `ssl_days_remaining`, `last_seo_score` vb.), ayrıca
tam geçmiş ayrı tablolarda (`HealthCheck`, `SeoCheck`, `LighthouseCheck`) tutulur.

Bir projede 2+ ortam varsa, proje sayfasından "Ortamları Karşılaştır" ile bir `EnvironmentComparison` oluşturulur:
seçilen path'ler (`ComparisonPage`) her iki ortamın URL'sine eklenip ekran görüntüsü alınır, piksel bazında
karşılaştırılıp fark yüzdesi ve işaretli bir diff görseli üretilir.

Her ortamda ayrıca kural tabanlı **senaryolar** (`Scenario`) tanımlanabilir: sıralı adımlardan (`ScenarioStep`)
oluşur, "Çalıştır" ile Playwright üzerinden sırayla işletilir; her çalıştırma (`ScenarioRun`) ve her adımın sonucu
(`ScenarioStepResult`, açıklama/durum/hata/ekran görüntüsü/süre ile) ayrı ayrı kaydedilir.

`CronJob`, bir ortam için health/ssl/seo/lighthouse kontrollerinden birini ya da belirli bir `Scenario`'yu belirli
bir sıklıkta otomatik çalıştırır; `notify_enabled` + `notify_emails` ile durum değişiminde e-posta uyarısı
gönderilir.

### Senaryo adım türleri

| Adım türü | Ne yapar | Kullandığı alanlar |
| --- | --- | --- |
| `navigate` | Ortamın URL'sine `path` ekleyip sayfaya gider | `path` |
| `click` | Seçiciye tıklar | `selector` |
| `fill` | Alana metin yazar | `selector`, `value` |
| `select_option` | Bir `<select>`'te seçim yapar | `selector`, `value` |
| `wait` | Belirtilen süre bekler | `wait_ms` |
| `assert_text` | Sayfada metin olduğunu doğrular | `value` |
| `assert_no_text` | Sayfada metin olmadığını doğrular | `value` |
| `assert_element` | Seçiciye uyan eleman olduğunu doğrular | `selector` |
| `assert_count` | Eleman sayısını bir operatörle (`>=`, `<=`, `==`, `!=`, `>`, `<`) karşılaştırır | `selector`, `operator`, `count` |
| `screenshot` | Ekran görüntüsü alır | — |
| `save_value` | Seçicideki elementin değerini (input/textarea/select ise `.value`, diğerlerinde metni) bir değişkene kaydeder | `selector`, `value` (değişken adı) |
| `compare_values` | İki kaydedilmiş değişkeni `==`/`!=` ile karşılaştırır; para birimi/binlik ayıraç/ondalık formatı farklarına karşı locale-bağımsız sayısal karşılaştırma yapar (`$1,499` ile `1499.00` eşit sayılır) | `value`, `value2` (iki değişken adı), `operator` |

`save_value`/`compare_values` ile kaydedilen değişkenler yalnızca tek bir çalıştırma (`run_scenario` çağrısı)
boyunca bellekte tutulur, kalıcı değildir — örn. bir sayfadan fiyatı kaydedip başka bir sayfadaki fiyatla
karşılaştırmak için kullanılır.

## Zamanlanmış görevler (cron job)

Bir ortamın detay sayfasından, o ortam için health/ssl/seo/lighthouse kontrollerinden biri ya da o ortama ait bir
senaryo seçilip bir sıklıkla (15 dakika / 1 saat / 6 saat / günlük / haftalık) zamanlanabilir. Uygulama süreci
ayakta olduğu sürece `APScheduler` bu job'ları arka planda çalıştırır — ayrı bir worker/cron daemon'a gerek yoktur,
ama bu da uygulama yeniden başladığında zamanlayıcının sıfırdan kurulduğu (kaçırılan çalıştırmaların telafi
edilmediği) anlamına gelir. Bir job'ın son durumu önceki durumundan farklıysa (`ok` → `başarısız` veya tersi) ve
bildirim açıksa, tanımlı e-posta adreslerine durum bilgisi gönderilir.

## Geliştirme notları

- Projede Alembic (migration aracı) yok. `Base.metadata.create_all()` (`app/main.py`) yalnızca eksik tabloları
  oluşturur, var olan bir tabloya yeni kolon eklemez — modele yeni bir kolon eklendiğinde bunu veritabanına
  manuel bir `ALTER TABLE ... ADD COLUMN ...` ile yansıtmak gerekir.
- Otomatik test paketi bulunmuyor; değişiklikler uygulamayı çalıştırıp ilgili akışı tarayıcıdan/`curl` ile
  doğrulayarak test edilmelidir.
- `app/static/uploads/` (ekran görüntüleri) ve `backups/` (veritabanı yedekleri) `.gitignore`'da hariç
  tutulmuştur.
