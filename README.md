# CMSPlus

Herhangi bir web sitesini/projeyi (Drupal, WordPress, özel geliştirme fark etmeksizin) tek yerden izlemek ve test
etmek için platform: proje ve ortam (Production/Staging/...) yönetimi, otomatik sağlık/SSL/SEO/Lighthouse
kontrolleri, ortamlar arası görsel karşılaştırma, kural tabanlı Playwright senaryoları ve zamanlanmış cron job'lar
üzerinden e-posta uyarıları. Tüm kontroller URL üzerinden çalışır; belirli bir CMS veya teknolojiye bağımlılık
yoktur.

## Özellikler

- **Kullanıcı girişi ve yetkilendirme** — E-posta/şifre ile session tabanlı giriş (bkz.
  [Kullanıcılar ve yetkilendirme](#kullanıcılar-ve-yetkilendirme)). Admin rolü tüm projeleri görür ve
  yönetir; Kullanıcı rolü sadece kendisine atanan projeleri görür.
- **Proje & ortam yönetimi** — Her proje birden çok ortama sahip olabilir (Production, Staging, Development...).
  Bir ortam "birincil" (primary) olarak işaretlenir ve proje kartlarında özet gösterilir.
- **Sağlık kontrolü** — HTTP isteği atıp durum kodu, yanıt süresi, response header/body'yi kaydeder (`httpx`).
- **SSL kontrolü** — Sertifikanın geçerlilik tarihini, kalan gün sayısını, issuer/subject bilgisini okur (`cryptography`).
- **SEO kontrolü** — Sayfayı Playwright ile açıp title/meta description/canonical/h1/OG etiketleri/structured data/
  görsel alt metinleri gibi sinyalleri çıkarır, eksiklere göre 0-100 arası bir skor hesaplar.
- **Lighthouse denetimi** — Node.js tabanlı Lighthouse'u subprocess olarak çalıştırıp performans/erişilebilirlik/
  best-practices/SEO skorlarını ve en kötü audit'leri kaydeder.
- **Cache ısıtma** — [gowarm](https://github.com/tarikflz/gowarm) (Go) subprocess olarak çalıştırılır: ortamın
  sitemap'indeki her URL, tanımlanan cookie/header kombinasyonlarıyla ("axes" — örn. region×language) gezilip
  origin/CDN cache'i ısıtılır; cache hit/miss durumu response header'larından (`CF-Cache-Status`,
  `X-Drupal-Cache` vb.) okunup özetlenir.
- **Ortamlar arası görsel karşılaştırma** — Aynı path'in iki ortamdaki (örn. Staging vs Production) ekran görüntüsünü
  alıp piksel bazında karşılaştırır; farklı bölgeleri kırmızı kutularla işaretleyip fark yüzdesini raporlar
  (`Pillow` + `numpy`).
- **Senaryolar** — Her ortamda, adım adım tanımlanan kural tabanlı Playwright akışları (bkz. aşağıdaki tablo).
  Tamamen deterministiktir, yapay zeka içermez; her adım doğrudan bir Playwright komutuna karşılık gelir. İlk
  başarısız adımda durur, hata mesajı ve ekran görüntüsüyle birlikte çalıştırma geçmişine kaydedilir. Çalıştırma
  geçmişi sunucu taraflı sayfalanır (10 kayıt/sayfa).
- **Cron job'lar** — Her ortam için health/ssl/seo/lighthouse/cache ısıtma/senaryo kontrollerinden biri, belirli bir sıklıkta
  (15dk / 1sa / 6sa / günlük / haftalık) otomatik çalışacak şekilde zamanlanabilir (`APScheduler`, uygulama süreci
  ayakta olduğu sürece çalışır — ayrı bir worker gerekmez). Durum değişince (başarılıdan başarısıza veya tersi)
  isteğe bağlı olarak e-posta uyarısı gönderilir.

## Stack

- FastAPI + Jinja2 (server-rendered, Tailwind CDN)
- Starlette `SessionMiddleware` (imzalı çerez) + stdlib `hashlib.pbkdf2_hmac` ile oturum/şifre yönetimi
  (`itsdangerous`, ekstra bir auth kütüphanesi yok)
- PostgreSQL + SQLAlchemy 2.0 (Docker Compose ile; Alembic yok — şema değişiklikleri elle `ALTER TABLE` gerektirir,
  bkz. [Geliştirme notları](#geliştirme-notları))
- httpx (sağlık kontrolü), cryptography (SSL kontrolü), Playwright (SEO taraması + senaryolar + görsel karşılaştırma
  için ekran görüntüsü), pandas (SEO/Lighthouse raporlama)
- Node.js + Lighthouse (performans/erişilebilirlik/best-practices/SEO denetimi)
- Go + gowarm (sitemap tabanlı cache ısıtma; PyYAML ile config üretilir)
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

# Cache ısıtma için gerekli (Go >= 1.24) — binary'yi derleyip cache_warmer/bin/gowarm olarak kurar
GOBIN="$(pwd)/cache_warmer/bin" go install github.com/tarikflz/gowarm/cmd@latest
mv cache_warmer/bin/cmd cache_warmer/bin/gowarm

docker compose up -d db

.venv/bin/uvicorn app.main:app --reload
```

Uygulama http://127.0.0.1:8000 adresinde çalışır.

### Ortam değişkenleri (`.env`)

| Değişken | Açıklama |
| --- | --- |
| `DATABASE_URL` | SQLAlchemy bağlantı dizesi (`postgresql+psycopg2://...`). Varsayılan, `docker-compose.yml`'deki `db` servisiyle eşleşir. |
| `SECRET_KEY` | Oturum çerezini imzalamak için kullanılır; rastgele, uzun bir değer olmalı (ör. `python3 -c "import secrets; print(secrets.token_hex(32))"`). Boş bırakılırsa güvensiz bir varsayılana düşer — üretimde mutlaka set edilmeli. |
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
- **"gowarm binary bulunamadı"** — `cache_warmer/bin/gowarm` derlenmemiş demektir; Kurulum bölümündeki `go install`
  adımını çalıştır (Node PATH sorununun eşleniği — binary repo-relative sabit bir path'te arandığı için `PATH`
  sorunu yaşanmaz, sadece derlenmiş olması yeterli).

## Yapı

```
app/
  main.py                FastAPI app ve tüm route'lar (proje/ortam CRUD, kontroller, senaryolar, cron job'lar, karşılaştırmalar)
  database.py             SQLAlchemy engine/session (DATABASE_URL, Base.metadata.create_all)
  auth.py                 Şifre hash/verify, oturum yardımcıları (get_allowed_project_ids, require_admin), seed
  models.py                User, Project, Environment, HealthCheck, SeoCheck, LighthouseCheck, CacheWarmCheck,
                            CronJob, EnvironmentComparison/ComparisonPage, Scenario/ScenarioStep/ScenarioRun/
                            ScenarioStepResult
  health_check.py          httpx ile sağlık kontrolü
  ssl_check.py              SSL sertifika kontrolü
  seo_check.py             Playwright ile SEO extraction + skor hesaplama
  lighthouse_check.py      Node/Lighthouse subprocess wrapper
  cache_warm_check.py      Go/gowarm subprocess wrapper (config.yaml üretimi + summary JSON parse)
  visual_compare.py        Playwright ile ekran görüntüsü + Pillow/numpy ile fark tespiti
  scenario_runner.py       Playwright ile kural tabanlı senaryo/adım çalıştırma motoru
  scheduler.py             APScheduler kurulumu + cron job çalıştırma + durum değişiminde e-posta bildirimi
  email_notify.py          SMTP ile bildirim e-postası gönderme
  templates/               Jinja2 template'leri
  static/                  CSS/JS, yüklenen ekran görüntüleri (app/static/uploads/, git'e dahil değil)
lighthouse/
  run.mjs          Lighthouse'u çalıştırıp JSON raporu stdout'a yazan Node script'i
  package.json     lighthouse + chrome-launcher bağımlılıkları
cache_warmer/
  bin/gowarm       `go install` ile derlenen binary (git'e dahil değil, bkz. Kurulum)
```

## Kullanıcılar ve yetkilendirme

Uygulamanın tamamı (statik dosyalar hariç) girişe kapalıdır; girişsiz istekler `/login`'e yönlendirilir. İki rol
vardır:

- **Admin** — tüm projeleri görür, proje/ortam oluşturur-düzenler-siler, `/users` sayfasından kullanıcı
  ekler/düzenler/siler.
- **Kullanıcı** — sadece kendisine atanan projeleri görür (proje listesi, sağlık/SEO/Lighthouse/cache ısıtma
  geçmişi, senaryolar dahil her yerde filtrelenir; atanmamış bir projeye doğrudan URL ile de erişemez, 404 döner);
  atandığı projelerde mevcut özellikleri kullanabilir (kontrol/senaryo çalıştırma, cron job) ama proje/ortam
  oluşturma-düzenleme-silme ve kullanıcı yönetimi admin'e özeldir.

İlk açılışta bir varsayılan admin kullanıcısı otomatik oluşturulur (bkz. `app/auth.py` — `DEFAULT_USER_EMAIL`/
`DEFAULT_USER_PASSWORD`); bu satır zaten varsa tekrar oluşturulmaz. Şifreler stdlib `hashlib.pbkdf2_hmac` ile
salt'lı hash'lenip saklanır. Proje görünürlüğü, `app/main.py`'deki `_get_project_or_404`/`_get_environment_or_404`
gibi tek noktadan geçen yardımcı fonksiyonlarda (`app.auth.get_allowed_project_ids`) uygulanır — yeni bir
proje-scoped route eklerken bu fonksiyonlardan geçtiğinden emin olunmalı, aksi halde erişim kontrolü atlanır.

## Veri modeli

Her proje (`Project`) bir veya daha fazla ortama (`Environment`) sahiptir. URL bilgisi ve isteğe bağlı bir
CMS/sürüm notu (`drupal_version` alanı — Drupal projeleri için düşünülmüş olsa da boş bırakılabilir, herhangi bir
site için zorunlu değildir) ortam seviyesinde tutulur; her ortamın son sağlık/SSL/SEO/Lighthouse/cache ısıtma kontrol
sonucu, hızlı erişim için doğrudan `Environment` satırında da önbelleklenir (`last_check_ok`, `ssl_days_remaining`,
`last_seo_score`, `last_cache_warm_ok` vb.), ayrıca tam geçmiş ayrı tablolarda (`HealthCheck`, `SeoCheck`,
`LighthouseCheck`, `CacheWarmCheck`) tutulur.

**Cache ısıtma** isteğe bağlıdır: bir ortamın `cache_warm_sitemap_url` ve `cache_warm_axes_yaml` (gowarm'ın
`axes:` YAML listesi — hangi cookie/header kombinasyonlarıyla ısıtılacağını tanımlar) alanları ortam düzenleme
formundan doldurulmadan "Cache Isıt" çalıştırılamaz. Sonuç (`CacheWarmCheck`) toplam/başarılı/başarısız istek
sayısını, cache hit/miss/bypass/unknown sayaçlarını, hit oranını ve başarısız isteklerin listesini içerir.

Bir projede 2+ ortam varsa, proje sayfasından "Ortamları Karşılaştır" ile bir `EnvironmentComparison` oluşturulur:
seçilen path'ler (`ComparisonPage`) her iki ortamın URL'sine eklenip ekran görüntüsü alınır, piksel bazında
karşılaştırılıp fark yüzdesi ve işaretli bir diff görseli üretilir.

Her ortamda ayrıca kural tabanlı **senaryolar** (`Scenario`) tanımlanabilir: sıralı adımlardan (`ScenarioStep`)
oluşur, "Çalıştır" ile Playwright üzerinden sırayla işletilir; her çalıştırma (`ScenarioRun`) ve her adımın sonucu
(`ScenarioStepResult`, açıklama/durum/hata/ekran görüntüsü/süre ile) ayrı ayrı kaydedilir.

`CronJob`, bir ortam için health/ssl/seo/lighthouse/cache ısıtma kontrollerinden birini ya da belirli bir
`Scenario`'yu belirli bir sıklıkta otomatik çalıştırır; `notify_enabled` + `notify_emails` ile durum değişiminde
e-posta uyarısı gönderilir.

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

Bir ortamın detay sayfasından, o ortam için health/ssl/seo/lighthouse/cache ısıtma kontrollerinden biri ya da o ortama ait bir
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
