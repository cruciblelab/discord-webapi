# Changelog

Formatı [Keep a Changelog](https://keepachangelog.com/) temel alıyor.

## [Unreleased] — `discord_webapi.captcha`: sıfırdan captcha altyapısı

### Eklenenler

- **`discord_webapi.captcha`** (opt-in, `DiscordWebAPI` tarafından
  otomatik kurulmuyor -- hangi sağlayıcı/anahtarlar sizin seçiminiz):
  pluggable bir captcha sistemi, iki bağımsız kullanım şekli için:
  - **Sitede direkt kullanım** (`build_captcha_router()`'ın
    `GET /api/captcha/challenge`/`POST /api/captcha/verify`'ı): Discord'la
    ilgisi olmayan herhangi bir noktayı (bir kayıt formu, vb.) korumak
    için.
  - **Bot komutu için eşik/gate** (`CaptchaGate`): bir doğrulama linkini
    (DM, ephemeral yanıt -- botun kendi tercihi) bir Discord kullanıcısına
    bağlar; kullanıcı linkte captcha'yı çözünce `captcha_verified`
    Transport event'i yayınlanır -- bot `gate.on_verified(...)` ile anında
    haberdar olur, polling yok, bot ve web ayrı process olsa bile çalışır.
    Örnek senaryo: bir çekiliş botunun `/join` komutu.
- **İki kendi sağlayıcımız** (`MathCaptchaProvider`, `TextCaptchaProvider`,
  `discord-webapi[captcha]` -- Pillow -- gerektiriyor): her ikisi de
  gerçek bir raster PNG üretiyor, SVG DEĞİL -- SVG'deki metin dosyanın
  içinde düz metin olarak durur, herhangi biri (ya da bir OCR/yapay zeka)
  doğrudan okuyabilir, bu da captcha'yı anlamsız kılardı. Her render'da
  farklı arka plan/harf rengi, harf başına döndürme ve hafif gürültü --
  aynı metin için her seferinde aynı görünen bir görsel üretmek bir
  scraper'ın görsel->cevap eşleşmelerini ezberlemesine izin verirdi.
- **İki üçüncü-taraf sağlayıcı sarmalayıcısı** (`ReCaptchaProvider`,
  `HCaptchaProvider` -- sadece zaten çekirdek bağımlılık olan `httpx`
  gerektiriyor, ek kurulum yok): kendi site_key/secret_key'inizi geçip
  Google reCAPTCHA v2 / hCaptcha'yı kullanın. Kendi captcha
  kütüphanenizi/servisinizi de `CaptchaProvider` Protocol'ünü (`issue()` +
  `verify()`) uygulayarak bağlayabilirsiniz.
- Kaba kuvvet koruması: her self-hosted challenge sınırlı sayıda yanlış
  denemeden sonra geçersiz oluyor (varsayılan 5), tek kullanımlık (doğru
  cevap bile ikinci kez kabul edilmiyor), süresi doluyor (varsayılan
  10-15 dakika). Dashboard endpoint'leri IP bazlı rate limit'li (kimliksiz,
  herkese açık endpoint'ler oldukları için diğer dashboard yazma
  endpoint'lerinin kullandığı kullanıcı-bazlı rate limit deseni burada
  uygulanamıyor).
- `MemoryCaptchaStore`/`MemoryVerificationStore` (varsayılan, sıfır
  altyapı) + `SQLCaptchaStore`/`SQLVerificationStore` (`discord-webapi[sql]`,
  kendi bağımsız tabloları -- `escalation`/`extras.warn`'la aynı ilke).

Gerçek Pillow render'ı elle görsel olarak doğrulandı (birkaç iterasyon --
ilk deneme sabit genişlik yüzünden uzun metinlerde harfler üst üste
biniyordu, gürültü çizgileri de metnin üstünden geçip okunaklılığı
bozuyordu; genişlik metne göre otomatik ayarlanacak, gürültü kısa yerel
çizgilere indirilecek şekilde düzeltildi). 55 yeni test (store CRUD,
render'ın gerçek PNG üretmesi, sağlayıcıların issue/verify akışı, üçüncü-
taraf sağlayıcıların `respx` ile mock'lanmış `siteverify` çağrıları,
`CaptchaGate`'in Transport event'i dahil tam çekiliş-senaryosu akışı,
dashboard API'sinin uçtan uca `TestClient` testleri). 583 test yeşil (1
ortam-bağımlı Postgres testi hariç), ruff+mypy temiz.

## [Unreleased] — Kapsamlı güvenlik/sağlamlık taraması (4 paralel denetim ajanı)

Kullanıcının "sağlam bir tarama yap, bugları fixle, sunduğumuz şeylerde
basit/kolaya kaçılan yerleri sağlamlaştır" talebiyle yapıldı. 4 alanı
paralel tarayan araştırma turu + bulunan gerçek hataların düzeltilmesi.
Ayrıntılar için `NOTES.md`'ye bakın.

### Düzeltilenler

- **`storage`**: `SessionStore.update()` artık her iki implementasyonda da
  (Memory/SQL) tutarlı — satır silinmişse (ör. başka bir sekmeden çıkış
  yapılmışsa) sessizce yeniden yaratmak (Memory'nin eski davranışı) ya da
  yakalanmayan bir `ValueError` fırlatmak (SQL'in eski davranışı) yerine
  ikisi de `SessionExpiredError` fırlatıyor -- `get_current_user`'ın zaten
  yakaladığı, temiz 401'e dönüşen hata.
- **`escalation/sql.py`**: `set_rule` artık `storage/sql.py`'deki diğer
  tüm "yeni satır" yazıcılarıyla aynı `IntegrityError`-toleranslı upsert
  desenini kullanıyor -- iki isteğin aynı yeni kuralı aynı anda oluşturma
  yarışı artık 500 yerine düzgün sonuçlanıyor.
- **`ratelimits/limiter.py`**: `set_rule` artık `max_calls`/`per_seconds`
  için `<= 0` değerleri reddediyor (hem Pydantic modelinde hem doğrudan
  çağrılara karşı) -- `per_seconds=0` önceden `check()`'in her çağrısında
  `ZeroDivisionError` fırlatan, kuralı elle düzeltilene kadar süren bir
  DoS'a yol açıyordu. Ayrıca `sub_key` (üye bazlı) kullanan bucket'lar artık
  periyodik olarak süpürülüyor -- önceden süresiz büyüyen bir bellek sızıntısıydı.
- **`escalation/engine.py`**: `_apply_action` artık gerçek moderasyon
  komutlarıyla (ban/kick/timeout) aynı rol-hiyerarşisi kontrolünü yapıyor
  ve Discord API hatalarını (`Forbidden`/`NotFound`) yakalıyor -- önceden
  hedef botu outrank ediyorsa ya da yetki yoksa `automod`'un `on_message`
  handler'ından fırlayan yakalanmamış bir hataydı. Audit kaydı artık
  aksiyonun gerçekten uygulanıp uygulanmadığını (`action_applied`) da tutuyor.
- **`extras/ban.py`/`kick.py`/`timeout.py`/`role_assign.py`**: hepsi artık
  `discord.Forbidden`/`discord.NotFound`'u yakalayıp temiz bir mesajla
  yanıtlıyor (önceden sadece `warn.py`'de vardı), opsiyonel `audit_logger`
  destekliyor (önceden sadece `warn`/`automod`'da vardı), ve audit-log
  reason'ı Discord'un 512 karakter sınırına göre kırpan ortak
  `build_audit_reason` helper'ını kullanıyor (`_shared.py`). `timeout.py`
  artık `ban`/`kick` gibi opsiyonel `dm_before_timeout` destekliyor;
  `warn.py` artık `require_reason` (varsayılan `True`, diğerleriyle
  tutarlı) ve `dm_before_warn` destekliyor.
- **`authz/app_roles.py`**: `AppRoleCache` artık `GuildRateLimiter`/
  `EscalationEngine`/`GuildMemberCache` ile aynı desende bir Transport
  event'i (`app_role_changed`) yayınlıyor -- önceden sadece yazan process'in
  kendi in-memory cache'ini temizliyordu, `for_bot_process`/`for_web_process`
  kurulumunda bir replica'da yapılan rol iptali diğer replica'larda
  `ttl_seconds`e kadar (varsayılan 30sn) hâlâ geçerli görünüyordu.
- **Audit log kapsam boşluğu**: `ratelimits/api.py`, `escalation/api.py`
  (kural CRUD'u), `jobs/api.py` artık diğer state-changing endpoint'lerle
  (`commands/api.py`, `authz/api.py`) aynı şekilde audit kaydı tutuyor --
  önceden bir rate-limit/escalation kuralını kim ayarladığı ya da bir job'ı
  kim kuyruğa aldığı hiç loglanmıyordu.
- **`consent/api.py`**: `POST /api/consent` artık diğer tüm state-changing
  endpoint'lerle aynı dashboard rate-limit korumasına sahip -- önceden
  sadece kimlik doğrulama gerektiren, korumasız bırakılmış tek yazma
  endpoint'iydi.
- **`discord_webapi/transport/redis.py`**: request/reply kanal önekleri
  artık birbirinin öneki DEĞİL (`rpc-cmd:`/`rpc-reply:`) -- önceden
  `"reply:..."` ile başlayan bir komut adı yanlışlıkla reply kanalı
  sanılıp isteği sessizce düşürüyordu. Her fire-and-forget task artık
  istisnasını loglayan bir done-callback'e sahip (önceden bir hata sessizce
  "Task exception was never retrieved" uyarısına dönüşüyordu). RPC reply
  publish'i artık kendi try/except'inde -- publish başarısız olursa en
  azından loglanıyor, sessizce kaybolmuyor.
- **`discord_webapi/jobs/redis.py`**: çıplak `assert self._redis is not
  None` ifadeleri (`python -O` altında kırpılabilir) yerine açık
  `RuntimeError` fırlatan `_require_redis()`. Yeni
  **`reclaim_stale_jobs(max_age_seconds=...)`**: bir worker process'i işin
  ortasında çökerse (BLPOP zaten job'ı kuyruktan atomik olarak çıkardığı
  için) job sonsuza kadar "running" durumunda takılı kalıyordu -- bu metod
  bu tür job'ları bulup "failed" yapıyor (otomatik yeniden kuyruğa almıyor,
  çünkü bazı job'lar -- toplu DM/ban gibi -- güvenli şekilde otomatik
  tekrar çalıştırılamaz).
- **`discord_webapi/tools/`**: `confirm()` artık interaktif olmayan
  stdin'de (`EOFError`) çökmek yerine "hayır" kabul ediyor, Türkçe tek harf
  "e" yanıtını da onay olarak kabul ediyor. `discord-webapi-migrate run`
  artık `discord-webapi-backup create` ile aynı `--tables` filtresine
  sahip. Eksik/bozuk checkpoint/yedek dosyaları artık ham bir traceback
  yerine temiz bir hata mesajıyla (`DumpFileError`) sonuçlanıyor.

### Kontrol edilip gerçek bir hata bulunmayan (doğrulandı, düzeltme gerekmedi)

- `RedisTransport.request()`'in paylaşılan `PubSub` nesnesi üzerinde
  subscribe/publish/unsubscribe'ın arka plan okuyucusunun `listen()`
  döngüsüyle eşzamanlı çalışması teorik bir yarış durumu gibi görünüyordu
  -- gerçek bir Redis'e karşı 160 eşzamanlı RPC round-trip'i (aynı anda 20,
  8 tur) hiçbir cevap karışması olmadan doğru sonuçlandı, kalıcı bir
  regresyon testi olarak eklendi. redis-py'nin bu deseni zaten güvenli
  şekilde ele aldığı anlaşılıyor.
- `commands/registry.py`'nin `global_check` çift-çağrı koruması, kurulu
  discord.py'nin `HybridAppCommand._check_can_run`'ına karşı doğrulandı --
  doğru.

### Bilinçli olarak düzeltilmeyen (dokümante edildi)

- `warn.py`'nin `auto_timeout_after` sayacı ile
  `EscalationEngine`'in ihlal sayaçları birbirinden bağımsız --
  ikisi aynı anda "uyarı" kavramı için kullanılırsa paylaşılan bir sayaç
  olmadan bağımsız tetiklenebilirler. Bu, `warn.py`'nin docstring'inde
  bir uyarı olarak not edildi; birleştirmek daha büyük bir yeniden tasarım
  gerektirir, bu turun kapsamı dışında bırakıldı.

Tüm düzeltmeler gerçek testlerle (gerçek SQLite/Redis'e karşı, mock değil)
doğrulandı -- birkaç yeni regresyon testi eklendi (storage, ratelimits,
escalation, extras, transport, jobs). 528 test yeşil (1 ortam-bağımlı
Postgres testi hariç), ruff+mypy temiz.

## [Unreleased] — `discord_webapi.tools.healthcheck`: bağlantı sağlığı CLI'si

### Eklenenler

- **`discord-webapi-healthcheck`** (`discord_webapi.tools.healthcheck`):
  veritabanının, (varsa) Redis'in, (varsa) bir HTTP endpoint'inin
  erişilebilir olduğunu kontrol eden bağımsız bir CLI. Cron/monitoring/
  container-orchestrator kullanımı için — tüm istenen kontroller geçerse
  `0`, biri bile başarısız olursa `1` ile çıkar.
  - `--database-url` (SQLAlchemy URL, `SELECT 1`), `--redis-url` (`PING`,
    `discord-webapi[redis]` extra'sı gerektirir, lazy import), `--http-url`
    (GET, 400 altı durum kodu = başarılı) — üçü de bağımsız ve opsiyonel,
    hiçbiri verilmezse hiçbir kontrol yapılmaz.
  - `--timeout` (varsayılan 5sn) her kontrole ayrı uygulanır.
  - `--json` satır başına bir JSON nesnesi basar (log toplama/monitoring
    pipeline'ları için); varsayılan insan-okunur metin çıktısı.

Gerçek bir SQLite dosyasına, gerçek bir loopback HTTP sunucusuna, ve
(erişilebilirse) gerçek bir Redis'e karşı hem başarı hem hata yollarıyla
doğrulandı — mock yok. 11 yeni test
(`tests/unit/test_tools_healthcheck.py`, Redis testi mevcut
`tests/transport/conftest.py` deseniyle aynı şekilde Redis erişilemezse
skip ediyor). 488 test yeşil (1 ortam-bağımlı Postgres testi hariç),
ruff+mypy temiz.

## [Unreleased] — `discord_webapi.tools.backup`: yedek alma CLI'si

### Eklenenler

- **`discord-webapi-backup`** (`discord_webapi.tools.backup`): bağımsız,
  istediğin an geri dönebileceğin bir yedek dosyası oluşturan/listeleyen/
  geri yükleyen CLI — bir migrasyona bağlı değil. `migrate` ile aynı
  şema-agnostik yaklaşım (SQLAlchemy introspection, hiçbir ORM sınıfı
  hardcode edilmiyor); ortak reflection/okuma/yazma/(de)serileştirme
  kodu iki araç arasında `discord_webapi/tools/_sql_dump.py`'ye taşındı.
  - `discord-webapi-backup create --from <url> --out <dosya>`: tam
    yedek (varsayılan). `--guild-id N` ile sadece bir guild'in satırları
    (guild_id sütunu olmayan tablolar tam alınır). `--since`/`--until`
    (ISO 8601) ile tarih aralığı (her tablonun sahip olduğu
    `created_at`/`updated_at`/`given_at`/`expires_at`'a göre). Bu iki
    kapsam birleştirilebilir. `--tables` ile belirli tablolarla
    sınırlandırılabilir.
  - `discord-webapi-backup list <dosya>`: hiçbir şey yazmadan yedeğin
    içeriğini (tablo/satır sayıları) gösterir.
  - `discord-webapi-backup restore <dosya> --to <url>`: yedeği bir
    veritabanına yazar (aynı sil-sonra-yaz semantiği). Bir yedek dosyası
    sadece satır verisi tutar, şema/sütun tipi tutmaz — `migrate`'in
    aksine hedefte olmayan bir tabloyu oluşturamaz, atlar (hedefin
    en az bir kez `create_all()`/`quickstart()` ile kurulmuş olması
    gerekir; bu, dokümantasyonda açıkça belirtilen bilinçli bir sınır).
  - `migrate` ile aynı güvenlik tasarımı: kaynağa asla yazmaz, `--yes`
    verilmedikçe onay ister, şifreler terminale basılmadan önce gizlenir.

Full/guild-scoped/date-scoped/birleşik kapsam ve restore gerçek
SQLite dosyalarına karşı elle doğrulandı, ardından 11 otomatik test
yazıldı (`tests/unit/test_tools_backup.py`). 449 test yeşil (1
ortam-bağımlı Postgres testi hariç), ruff+mypy temiz.

## [Unreleased] — `discord_webapi.tools.migrate`: veritabanı taşıma CLI'si + `tools/` alt paketi

### Eklenenler

- **`discord_webapi/tools/`**: terminal-bazlı operatör araçları için yeni
  bir alt paket — bot davranışı olan `extras`'tan ve çekirdek altyapıdan
  ayrı (farklı kullanım şekli: `setup(bot, ...)` çağrısı değil, tek
  seferlik bir CLI komutu). Gelecekteki benzer araçlar buraya eklenecek.
- **`discord-webapi-migrate`** (`discord_webapi.tools.migrate`): bir
  SQLAlchemy URL'inden diğerine (ör. yerel SQLite'tan MariaDB/Postgres'e)
  tüm verileri taşıyan CLI. Şema/tablo bilgisini hiç hardcode etmiyor —
  kaynak veritabanında ne varsa (çekirdek store'lar, `escalation`,
  `extras.warn`'ın `SQLWarnStore`'u, üçüncü-taraf bir extension'ın kendi
  tablosu) SQLAlchemy introspection'ıyla bulup kopyalıyor.
  - `discord-webapi-migrate run --from <url> --to <url>`: `--yes`
    verilmedikçe onay ister, satır sayılarını gösterir.
  - **Checkpoint varsayılan olarak açık**: yazmadan önce hedefin o anki
    durumunu (varsa) yerel bir JSON dosyasına kaydeder. `--no-checkpoint`
    ile kapatılabilir.
  - `discord-webapi-migrate restore <checkpoint-dosyası> --to <url>`:
    hedefi checkpoint anındaki haline geri döndürür.
  - Kaynağa asla yazmaz, sadece okur. Şifreler terminale/log'a
    yazdırılmadan önce URL'lerden gizleniyor (`_redact`).
  - Bu bir genel veritabanı yedeği DEĞİL, sadece discord-webapi'nin kendi
    tablolarını kapsıyor — dokümantasyonda bu net şekilde vurgulanıyor.

Gerçek SQLite↔SQLite round-trip testiyle uçtan uca doğrulandı (migrate →
checkpoint → simüle edilmiş "kötü" bir yazma → restore → temiz geri
dönüş) — bu süreçte checkpoint mekanizmasının kendi gerçek bir bug'ı
bulundu ve düzeltildi: `datetime` değerleri JSON'a string olarak
yazılıyordu ama restore sırasında tekrar `datetime` nesnesine
çevrilmiyordu, SQLite bunu reddediyordu (`_json_object_hook`'a
`__datetime_iso__` etiketi eklenerek düzeltildi).

10 yeni test (`tests/unit/test_tools_migrate.py`). 438 test yeşil (1
ortam-bağımlı Postgres testi hariç), ruff+mypy temiz.

## [Unreleased] — `examples/test_console`: tıklanabilir fiziksel test aracı

### Eklenenler

- **`examples/test_console/`**: fiziksel testler için özel bir bot +
  `/console`'da tek sayfalık, self-contained (CDN'siz, build adımsız)
  bir test arayüzü — curl komutlarıyla uğraşmadan butonlarla test etmek
  için.
  - Bot: `/ping` (rate-limited, key `"ping"`), `/warn @member sebep`
    (`extras.warn`, audit'li), `/warnings @member` (uyarı geçmişi),
    automod (`badword1`/`badword2`/`badword3` filtreli + davet linki
    engelleme, `on_violation` ile hem `WarnStore`'a hem
    `EscalationEngine`'e (`key="automod"`) besleniyor).
  - Konsol: komut listele/aç-kapat/cooldown/`required_app_role` düzenle,
    rate limit get/set/sil, escalation merdiveni tanımla/listele/sil,
    kullanıcı uyarılarını görüntüle, audit log'u görüntüle, ham
    yanıt/hata paneli. Giriş tek tıkla (`mobile_redirect_uri` doğrudan
    `/console`'a yönlendiriyor, sayfa `session_id`'yi URL'den okuyup
    kaydediyor — token elle kopyalanmıyor).
  - Uçtan uca doğrulandı (bu oturumda): `/console` gerçekten sunuluyor,
    kimliksiz istekler 401 dönüyor, `/warn` çağrısı gerçekten SQL audit
    tablosuna yazıyor, bir escalation kuralı gerçekten `guild.kick()`
    çağırıyor ve bunu da audit'liyor.
- `TESTING.md`: yeni 22. bölüm (`test_console` kontrol listesi) +
  giriş metni güncellendi (önerilen ana test aracı olarak işaretlendi).

Kod tarafında değişiklik yok (sadece yeni örnek + doküman); 427 test
yeşil, ruff+mypy temiz.

## [Unreleased] — P1.4: audit log bot-tarafı moderasyon aksiyonlarını da kapsıyor (opt-in)

### Eklenenler

Audit log şimdiye kadar sadece web-tarafı dashboard yazmalarını (`command.
set_override`, `app_role.set/delete`) kaydediyordu. Artık bot-tarafı
moderasyon aksiyonları da opsiyonel olarak audit'leniyor:

- **`EscalationEngine`**: `audit_logger=` parametresi. Bir rung tetiklenince
  `escalation.<action>` kaydı (`actor_user_id=0` = otomatik/sistem
  aksiyonu, `detail`'de key/threshold/count/configured_by). `DiscordWebAPI`
  `install(enable_audit_log=True)` ile motoru kendi audit logger'ına
  otomatik bağlıyor — dashboard yazma audit'iyle AYNI store'a, `GET
  /audit-log` her ikisini de gösteriyor.
- **`extras.warn.setup(bot, ..., audit_logger=)`**: her uyarıda `warn`
  kaydı (actor = uyaran moderatör).
- **`extras.automod.setup(bot, ..., audit_logger=)`**: her ihlalde
  `automod.violation` kaydı.
- `DiscordWebAPI.audit_logger` özelliği eklendi (`enable_audit_log=True`
  olana kadar `None`) — bot-tarafı kod (warn/automod setup'ları) buna
  erişip kendi aksiyonlarını audit'leyebilsin.

Hepsi tam opt-in: `audit_logger` verilmezse hiçbir şey yazılmaz, gizli
bağımlılık yok. 8 yeni test. 427 test yeşil (1 ortam-bağımlı Postgres testi
hariç), ruff+mypy temiz.

## [Unreleased] — P1: DX iyileştirmeleri (extras export ergonomisi, hata rehberliği, 2 örnek)

### Eklenenler / İyileştirildi

- **`extras` ergonomik erişim**: `discord_webapi.extras.ban` gibi attribute
  erişimi ve tab-completion artık çalışıyor (lazy `__getattr__` + `__all__`
  + `__dir__`), submodülleri eager import etmeden — `import
  discord_webapi.extras` hâlâ yan-etkisiz, her submodül ancak ilk
  dokunuşta import ediliyor.
- **`required_app_role` sessiz-hata düzeltmesi**: bir komutun
  `required_app_role`'ü ayarlı ama `CommandRegistry` `app_role_cache`
  olmadan kurulmuşsa (elle kurulum hatası; `DiscordWebAPI` bunu otomatik
  bağlar), artık fail-closed'a ek olarak açıklayıcı bir `WARNING` log'u
  atılıyor — "neden komutum hep reddediliyor?" sessiz durumu yerine.
- **`examples/skeleton_custom_command/`**: `skeletons.rate_limited` ile
  sıfırdan, kendi `rate_limit_key`'inle komut yazmanın odaklı örneği.
- **`examples/hybrid_moderation/`**: `automod` (`on_violation`) → `warn` +
  `EscalationEngine` üçlüsünün bir arada kullanımı — her sistem kendi
  şeridinde, ceza-merdiveni %100 dashboard'dan yapılandırılabilir, hiçbir
  şey hardcoded değil.

1 yeni test (log warning), 419 test yeşil (1 ortam-bağımlı Postgres testi
hariç), ruff+mypy temiz. Her iki örnek de sahte env ile uçtan uca build
doğrulandı.

## [Unreleased] — v0.7: `discord_webapi.extensions` — üçüncü-taraf paket ekosistemi (plugin VM DEĞİL)

### Eklenenler

- **`discord_webapi.extensions`**: insanların kendi tam-kapasite bot
  altyapılarını (eğlence botu, moderasyon paketi, ...) yazıp `pip` paketi
  olarak paylaşabilmesi, başkalarının da kurup projesine takabilmesi için
  hafif bir konvansiyon. **Bilinçli olarak bir plugin runtime'ı/sandbox'ı/
  çekirdeğe özel erişim veren bir API DEĞİL** — kullanıcının net kararı
  ("pluginler core'a etki etmesin, ağır sistem istemem"). Anahtar içgörü:
  bizim `extras`'ımız zaten yalnızca public API kullandığı için, üçüncü-taraf
  bir paket birinci-taraftan mimari olarak ayırt edilemez; o yüzden özel
  bir runtime gerekmez, extension sadece dokümante edilmiş konvansiyonu
  izleyen sıradan bir Python paketidir.
- `extensions/manifest.py::ExtensionManifest`: paketin adı/sürümü/yazarı/
  uyumlu discord-webapi aralığı (`discord_webapi_requires`). Sadece metadata,
  hiçbir ayrıcalık vermez.
- `extensions/base.py::Extension`: bir paketin entry point'ine koyduğu
  `manifest + setup` container'ı.
- `extensions/registry.py::ExtensionRegistry.discover()`: `discord_webapi.
  extensions` entry-point grubunu okur, sürüm uyumluluğunu kontrol eder,
  kırık/uyumsuz/duplicate extension'ları hata olarak toplar (biri diğerini
  gizlemez). **`setup`'ı asla otomatik çağırmaz** — kurulum her zaman
  host'un açık kararı.
- `extensions/sdk.py`: bir extension'ın karşı yazacağı **kararlı, stabilite-
  garantili** re-export yüzeyi (`GuildRateLimiter`, `EscalationEngine`,
  `rate_limited`, `check_role_hierarchy`, Store protokolleri, `Transport`,
  `Extension`/`ExtensionManifest`...).
- **Scaffold CLI**: `discord-webapi-scaffold new <isim>` (ya da `python -m
  discord_webapi.extensions.scaffold new <isim>`) — çalışan, kurulabilir,
  keşfedilebilir bir iskelet paket üretir (örnek `/roll` komutu, manifest,
  entry point, `pip install -e .` sonrası geçen test).
- `discord_webapi.__version__ = "0.6.0"` eklendi (extension uyumluluk
  kontrolü bununla yapılıyor).
- `pyproject.toml`: `[extensions]` extra'sı (`packaging`, uyumluluk kontrolü
  için — yoksa kontrol atlanır, extension yine çalışır), `[project.scripts]`
  scaffold komutu.
- `docs/PAKET_YAZMA.md`: extension yazma rehberi.

Uçtan uca doğrulandı: scaffold ile üretilen paket gerçekten `pip install`
edilip `ExtensionRegistry.discover()` ile keşfediliyor, uyumluluğu doğru
raporlanıyor, `setup`'ı çalışıyor. 24 yeni test. 419 test yeşil (1
ortam-bağımlı Postgres testi hariç), ruff+mypy temiz.

## [Unreleased] — Kod denetimi: `extras.warn`/`extras.welcome`'da 4 gerçek bug bulundu, düzeltildi

Geniş bir arka-plan kod denetimi (auth/authz/jobs/audit/consent/transport/
storage/extras/bridge.py) yapıldı. Çoğu alan temiz çıktı (jobs kuyruğu,
Redis transport reconnect/RPC temizliği, auth token refresh race'i, authz
cache invalidation'ı — hepsi doğru); `discord_webapi.extras`'ta 4 gerçek
bug bulundu:

### Düzeltildi

- **`extras/warn.py`: `auto_timeout_after` her warn'da yeniden tetikleniyordu.**
  Karşılaştırma `count >= auto_timeout_after` idi — eşiği bir kere geçtikten
  sonra HER yeni warn, timeout'u tekrar tekrar uyguluyordu. Docstring
  "üyenin N'inci uyarısı" diyor (tekil, bir kerelik), `escalation` motoru
  da tam olarak eşiğe denk geldiğinde tetikliyor — tutarsızlık. **Fix**:
  `count == auto_timeout_after` (tam olarak N'inci uyarıda, bir kere).
- **`extras/warn.py`: bot'un `moderate_members` izni yoksa `member.timeout()`
  yakalanmamış `discord.Forbidden` fırlatıyordu**, warn kaydı zaten
  DB'ye yazıldıktan SONRA — komut hatası olarak sızıyordu. **Fix**: blanket
  bir `@commands.bot_has_permissions(moderate_members=True)` decorator'ı
  eklemek yerine (bu, `auto_timeout_after` hiç kullanmayan herkesi de o
  izni vermeye zorlardı) `member.timeout()` çağrısı `try/except
  discord.Forbidden` ile sarıldı, kullanıcıya "izin yok" diye best-effort
  bir mesaj ekleniyor.
- **`extras/welcome.py`: kanal'a mesaj gönderimi `dm_instead`'in aksine
  best-effort değildi.** Bot'un o kanalda mesaj gönderme izni yoksa her
  üye katılımında yakalanmamış `Forbidden` fırlatıyordu. **Fix**: aynı
  `try/except discord.HTTPException` ile sarıldı.
- **`extras/welcome.py`: bilinmeyen template placeholder'ı yakalanmamış
  `KeyError` fırlatıyordu.** `message_template.format(...)` sadece
  `mention`/`member`/`guild` sağlıyor; `{user}` gibi başka bir placeholder
  kullanan bir template her üye katılımında listener'ı çökertiyordu.
  **Fix**: `KeyError`/`IndexError` yakalanıyor (best-effort, aynı "bozuk
  bir welcome mesajı bot'u çökmüş gibi göstermemeli" mantığı).

4 yeni test (`test_warn.py`'ye 2, `test_welcome.py`'ye 2). 395 test yeşil
(1 ortam-bağımlı Postgres testi hariç), ruff+mypy temiz.

## [Unreleased] — İki bilinen boşluk/karışıklık düzeltildi

### Düzeltildi

- **`CommandOverride.required_app_role` ölü alandı** — modelde tanımlıydı,
  SQL/Memory store'da persist ediliyordu, ama `PATCH
  /api/guilds/{id}/commands/{name}` hiçbir zaman kabul etmiyordu ve
  `CommandRegistry`'nin enforcement'ı (`global_check`/`interaction_check`)
  hiçbir zaman kontrol etmiyordu — yazılamayan, hiç uygulanmayan bir alan.
  Artık tam çalışıyor: `CommandRegistry` opsiyonel bir `app_role_cache`
  (`AppRoleCache`) parametresi alıyor (`DiscordWebAPI` kendi
  `app_role_cache`'ini otomatik bağlıyor), `_check_app_role` hem
  prefix/hybrid (`global_check`) hem slash (`interaction_check`) yolunda
  çağrılıyor, `set_override`/PATCH endpoint'i/RPC payload'ı hepsi
  `required_app_role`'ü baştan sona taşıyor. **Fail-closed**: bir komutun
  `required_app_role`'ü ayarlanmış ama registry'ye hiç `app_role_cache`
  verilmemişse (yanlış yapılandırma), çağrı sessizce izin verilmek yerine
  reddediliyor. 8 yeni test (`tests/unit/test_command_required_app_role.py`)
  + PATCH passthrough testi + facade wiring testi.
- **`discord_webapi/ratelimit.py` (`TokenBucketLimiter`, dashboard yazma
  endpoint'lerini abuse'tan koruyan iç mekanizma) `discord_webapi/ratelimits/`
  (`GuildRateLimiter`, botunuzun kendi komutları için genel amaçlı,
  dashboard'dan ayarlanabilir rate limit sistemi) ile isim olarak kafa
  karıştırıyordu** — tekil/çoğul farkı dışında hiçbir görsel ayrım yoktu,
  ikisi de tamamen farklı amaçlara hizmet ediyor. `discord_webapi/ratelimit.py`
  → `discord_webapi/dashboard_ratelimit.py` (bağımsız `TokenBucketLimiter`
  sınıfı) + `discord_webapi/dashboard_ratelimit_dependency.py` (auth'a
  bağımlı `rate_limit_dependency` FastAPI dependency'si — circular
  import'u önlemek için ayrı dosyada, `commands/ratelimit.py`'nin eskiden
  yaptığı gibi) olarak yeniden adlandırıldı/bölündü. Sadece isim/konum
  değişikliği, davranış aynı.

391 test yeşil (1 ortam-bağımlı Postgres testi hariç), ruff+mypy temiz.

## [Unreleased] — `discord_webapi.builtins` + `discord_webapi.skeletons` → tek `discord_webapi.extras` paketi

### Değişenler (BREAKING — henüz yayınlanmamış sürüm, migration gerekmiyor)

Kütüphanenin "çekirdek" (auth/authz/commands/transport/storage/
ratelimits/escalation — dashboard↔bot köprüsü) ile "opsiyonel eklenti"
(hazır komutlar, iskeletler) arasındaki paket sınırı bulanıklaşmıştı: iki
ayrı üst-seviye paket (`builtins`, `skeletons`) aynı kavramın (çekirdek
değil, opsiyonel) iki farklı derinliğini temsil ediyordu ama isimleri bu
ilişkiyi göstermiyordu. İkisi tek bir pakette birleştirildi:

- `discord_webapi.builtins` → `discord_webapi.extras` (ban/kick/timeout/
  warn/welcome/role_assign/automod — "tam" hazır komutlar, aynı davranış).
- `discord_webapi.skeletons` → `discord_webapi.extras.skeletons` (rate-limit
  decorator'ı — "iskelet", aynı davranış), artık `extras`'ın bir alt
  paketi olarak, "aynı çatı altında farklı derinlik" ilişkisini
  isimlendirmede de netleştiriyor.
- `builtins/README.md` + `skeletons/README.md` → tek `extras/README.md`
  (üst seviye, "tam vs iskelet" ayrımını açıklıyor) + `extras/skeletons/README.md`
  (iskelet-özel convention ve 10 senaryo, olduğu gibi korundu).
- Sadece dosya taşıma + import path güncellemesi — hiçbir davranış,
  fonksiyon imzası, ya da test mantığı değişmedi. Tüm testler taşınan
  konumlarında (`tests/unit/extras/`, `tests/unit/extras/automod/`,
  `tests/unit/extras/skeletons/`, `tests/integration/extras/`) aynı
  şekilde geçiyor.
- Henüz PyPI'da yayınlanmamış bir sürüm olduğu için bu, dışarıdan kimseyi
  etkilemeyen bir iç yeniden adlandırma — "breaking change" notu ileride
  bir sürüm numarasıyla yayınlanırsa diye kayıt altında.

381 test yeşil (1 ortam-bağımlı Postgres testi hariç), ruff+mypy temiz.

## [Unreleased] — `discord_webapi.skeletons` — "demir/rebar" komut altyapısı, tam komut değil

### Eklenenler

- **`discord_webapi.skeletons`**: `builtins`'ten ayrı, yeni bir paket — komutu discord.py'nin kendi `@bot.command(...)`/`@bot.tree.command(...)`/`@bot.hybrid_command(...)` decorator'ıyla siz kaydedersiniz, biz sadece onun altına istiflenen ince bir decorator ile dashboard'dan ayarlanabilir rate-limit kontrolünü ("demir") ekleriz — komutun ne yaptığını (gövdeyi/"çeliği") siz yazarsınız. `builtins.ban` gibi tam-uçtan-uca hazır bir komut değil; kullanmak zorunda değilsiniz, düz discord.py de yazabilirsiniz.
- `skeletons/_shared.py::rate_limited(key, *, rate_limiter=None, ...)`: genel decorator — sarmaladığı fonksiyonun ilk argümanının `commands.Context` mi `discord.Interaction` mi olduğunu otomatik ayırt eder, aynı decorator hem klasik prefix komutlarda hem slash komutlarda çalışır. Verilirse `GuildRateLimiter`'ı kullanıcı bazlı kontrol eder (DM'lerde atlar, rate limiter verilmezse hiç kontrol yapmaz), izin varsa sizin fonksiyonunuzu çağırır, yoksa `Context`/`Interaction`'a uygun şekilde ("reply" ya da "response.send_message"/"followup.send") cevap verir.
- `skeletons/ping.py::ping(*, rate_limiter=None, rate_limit_key="ping", ...)`: ilk somut örnek — ping'e özel varsayılanlarla ince bir sarmalayıcı.
- Strateji notu: bundan sonraki öncelik Discord'da kullanılan sistemlere/algoritmalara (rate limit, eskalasyon, permission vb.) daha kapsamlı odaklanmak; yeni bir `builtins` komutu yerine yeni bir skeleton ya da yeni bir altyapı sistemi tercih ediliyor, altyapıda gerçek bir boşluk çıkmadıkça.

10 yeni test (`tests/unit/test_skeletons_ping.py`), 371 test yeşil (1 ortam-bağımlı Postgres testi hariç), ruff+mypy temiz.

### `skeletons/README.md`'ye "derinlemesine örnekler" bölümü + kanıtlayıcı testler

Sadece dokümantasyon prose'u değil, iddia edilen her senaryonun gerçekten
çalıştığını kanıtlayan çalıştırılabilir testler eklendi
(`tests/integration/test_skeletons_deep_dive.py`, 5 test):
1. Dashboard'dan (`GuildRateLimiter.set_rule`/`delete_rule`, `PUT/DELETE
   /api/guilds/{id}/ratelimits/{key}`'in altında çalışan aynı mekanizma)
   canlı kural değişikliği — komut kodu HİÇ değişmeden.
2. Skeleton'ın rate-limit kontrolü ile tamamen ayrı, kendi
   `aiosqlite` tablonuza yazma (hibrit kullanım).
3. `rate_limiter=None` ile tamamen opt-out.
4. Aynı komutta hem `rate_limited(...)` hem `EscalationEngine.record_violation(...)`
   — iki bağımsız sistemin bir arada kullanımı.
5. Aynı komut kodu, iki farklı guild'de tamamen bağımsız limitlerle
   (guild bazlı branching kodu olmadan).

376 test yeşil (1 ortam-bağımlı Postgres testi hariç), ruff+mypy temiz.

### 5 senaryo daha eklendi (toplam 10)

Kullanıcının isteğiyle "derinlemesine örnekler" 5'ten 10'a çıkarıldı,
yine her biri gerçek testle kanıtlanmış:
6. Prefix ve slash komutun tek bir handler'ı paylaşması (kod tekrarını
   önleme), varsayılan olarak aynı rate-limit bucket'ını paylaştıklarını
   gösteren test dahil.
7. Dıştaki bir izin kontrolünün (ör. `commands.has_permissions`), altındaki
   rate-limit decorator'ı hiç çalıştırmadan reddetmesi — ve admin'i rate
   limit'in KENDİSİNDEN muaf tutmak isterseniz bunun decorator
   istiflemesi değil, handler içinde manuel bir kontrol gerektirdiğinin
   iki ayrı testle netleştirilmesi.
8. Birden fazla komutun aynı `rate_limit_key`'i paylaşarak ortak bir
   günlük kota oluşturması.
9. `rate_limited_message`'ın özelleştirilmesi/lokalize edilmesi.
10. `MemoryRateLimitStore` yerine `SQLRateLimitStore` ile birebir aynı
    kodun çalışması, kuralın gerçekten kalıcı olduğunun (yeni bir
    `GuildRateLimiter` örneğinin aynı store'dan kuralı görmesiyle)
    kanıtlanması.

5 yeni test (`tests/integration/test_skeletons_deep_dive.py`, toplam 10
test o dosyada), 381 test yeşil (1 ortam-bağımlı Postgres testi hariç),
ruff+mypy temiz.

## [Unreleased] — v0.6: `discord_webapi.escalation` — genel, tamamen kullanıcı-tanımlı eskalasyon motoru

### Eklenenler

- **`discord_webapi.escalation`**: `ratelimits` ile aynı mimari desende (Store Protocol + Memory/SQL + Transport event ile restart'sız canlı güncelleme), ama ban/kick/timeout/warn/automod gibi **her türlü moderasyon aksiyonu için ortak, tek bir "eşik merdiveni" sistemi**. `EscalationEngine.record_violation(member, key, source=..., reason=...)` bir ihlal kaydeder, sayar, sayı tam olarak bir eşiğe (`threshold`) denk geliyorsa o eşiğin aksiyonunu (`none`/`timeout`/`kick`/`ban`) uygular.
- **Hiçbir varsayılan eşik/aksiyon yok** — kullanıcının açık talebiydi ("eşikleri felan kendileri yazıp ayarlasınlar biz dayatmayalım"). Boş bir merdiven (`(guild_id, key)` için hiç kural yok) sadece ihlalleri sayar, hiçbir şey yapmaz; her basamak dashboard API'sinden ya da `set_rule()` ile açıkça tanımlanmalı.
- `key` keyfi bir string — `ratelimits` gibi tek bir discord.py komutuna bağlı değil; `warn`, `automod`, ya da kendi yazdığınız herhangi bir moderasyon mantığı aynı merdiveni paylaşabilir ya da her biri kendi ayrı `key`'iyle bağımsız sayılabilir.
- Dashboard API: `GET /api/guilds/{guild_id}/escalation-rules` (tüm merdivenler), `GET/PUT/DELETE /api/guilds/{guild_id}/escalation-rules/{key}[/{threshold}]` (opt-in, `enable_escalation_api=True`).
- `DiscordWebAPI` her zaman bir `escalation_engine` kuruyor (opt-in olan sadece dashboard endpoint'i) — `rate_limiter` ile aynı gerekçe: bot-tarafı kod dashboard API'si hiç açılmasa bile `api.escalation_engine`/`request.app.state.discord_webapi_escalation_engine` üzerinden doğrudan kullanabiliyor.
- `examples/full_featured_bot/main.py`: `builtins.automod`'un `on_violation` hook'u artık `EscalationEngine.record_violation(member, "automod", ...)` çağırıyor — automod'un kendi hiçbir eskalasyon mantığı yok, tamamen ayrı, dashboard'dan yapılandırılabilir eskalasyon motoruna devrediyor. Somut "hibrit kullanım" örneği: hazır bir builtin (`automod`) + kendi kodunuzdan (bu callback) bizim başka bir altyapımızı (escalation) besleyerek.

Kullanıcının netleştirdiği isteğin ("ban kick timeout vesaire... eşikleri felan kendileri yazıp ayarlasınlar biz dayatmayalım") birebir karşılığı. Detaylar için `NOTES.md`'ye bakın.

361 test yeşil (1 ortam-bağımlı Postgres testi hariç, 38'i escalation paketine ait), ruff+mypy temiz.

## [Unreleased] — v0.6: `discord_webapi.ratelimits` — sunucu bazlı, kod'a bağımsız rate limit sistemi

### Eklenenler

- **`discord_webapi.ratelimits`**: `CommandRegistry`'nin cooldown'ıyla aynı mimari desende (Store Protocol + Memory/SQL + Transport event ile restart'sız canlı güncelleme), ama keyfi bir string `key`'e bağlanan, discord.py `Command` nesnesine ihtiyaç duymayan bir rate-limit sistemi. `GuildRateLimiter.check(guild_id, key, sub_key=...)` — bir automod kontrolüne, bir webhook handler'ına, ya da `CommandRegistry`'den hiç geçmeyen elle yazılmış bir komuta bağlanabilir. `sub_key`, tek bir dashboard'dan-ayarlanabilir eşiği (`(guild_id, key)`) paylaşırken her alt-anahtara (ör. kullanıcı id'si) kendi bağımsız bucket'ını veriyor.
- Dashboard API: `GET/PUT/DELETE /api/guilds/{guild_id}/ratelimits/{key}` (opt-in, `enable_ratelimits_api=True`).
- `DiscordWebAPI` her zaman bir `rate_limiter` kuruyor (opt-in olan sadece dashboard endpoint'i) — bot-tarafı kod (ör. bir automod check'i) dashboard API'si hiç açılmasa bile `api.rate_limiter`/`request.app.state.discord_webapi_ratelimiter` üzerinden doğrudan kullanabiliyor.
- `examples/full_featured_bot/main.py`'daki elle yazılmış `/ping` komutu artık bu sistemi doğrudan kullanıyor — "hibrit kullanım"ın somut kanıtı: ne bir `builtins` komutu ne `CommandRegistry`'nin cooldown'ı, kendi rate limit'ini bizim altyapımızla, sunucu bazlı ayarlanabilir şekilde kuruyor.

Bu, kullanıcının netleştirdiği v0.6 vizyonunun ("rate limit/eşik/ceza gibi altyapıları, komuta bağımlı olmadan, hem tek satırla hem kendi kodlarıyla harmanlayarak kullanabilsinler") ilk somut adımı. Detaylar için `NOTES.md`'ye ve plan dosyasındaki "v0.6 Vizyonu" bölümüne bakın.

351 test yeşil (1 ortam-bağımlı Postgres testi hariç), ruff+mypy temiz.

## [Unreleased] — İki yeni builtin: rol atama, modüler otomatik moderasyon paketi

### Eklenenler

- **`discord_webapi.builtins.role_assign`**: `/role-add`/`/role-remove` komutları. `_shared.py`'ye eklenen `check_role_assignable` ile, hedef üyenin değil verilen/alınan ROLÜN kendisinin sırasını kontrol ediyor — Discord'un `MANAGE_ROLES` hiyerarşi kontrolü, API çağrısını yapan bot token'ının sırasına göre çalışıyor, çağıran insanın sırasına göre değil, bu yüzden ban/kick/timeout'un kendi client-side kontrolüne ihtiyaç duyması gibi bu da kendi kontrolüne ihtiyaç duyuyor.
- **`discord_webapi.builtins.automod`** (bir alt paket, tek dosya değil): yedi bağımsız, tek başına import edilebilir kontrol —
  `banned_words.py` (yasaklı kelime, tam kelime eşleşmesi), `spam.py` (mesaj-hızı, kayan pencere), `mention_spam.py` (mass-mention/raid koruması), `invite_filter.py` (Discord davet linki engelleme, allowlist'li), `link_filter.py` (genel URL domain allow/blocklist), `caps_spam.py` (aşırı büyük harf/"bağırma"), `emoji_spam.py` (aşırı emoji), ve `exemptions.py` (kimin muaf olduğu — `manage_messages` sahibi moderatörler varsayılan olarak muaf).
  Her kontrol saf, senkron, yan etkisiz bir fonksiyon (`discord.Message -> str | None`) — hiç `await`/I/O yok, düz bir sahte mesaj nesnesiyle tek başına test edilebiliyor. `automod/__init__.py::setup()` koordinatörü: etkin kontrolleri sırayla çalıştırıp ilk ihlalde duruyor, sonra mesaj silme / kısa kanal bildirimi / kalıcı log-kanalı kaydı / kendi `on_violation` callback'iniz — hepsi bağımsız açılıp kapatılabilir. Ban/kick/timeout'a yükseltmiyor, kalıcı ihlal sayacı tutmuyor (`warn.py`'nin işi) — `on_violation=` ile kendi `WarnStore`'unuzu besleyebilirsiniz, `automod`'un `warn.py`'ye hiç bağımlılığı olmadan.
- `examples/full_featured_bot/`'a her iki builtin de eklendi.

294 test yeşil (1 ortam-bağımlı Postgres testi hariç, 53'ü sadece automod paketine ait), ruff+mypy temiz.

## [Unreleased] — Test coverage: %91 → %95

Fiziksel test turu beklerken test coverage'ı `pytest-cov` ile ölçüp
zayıf noktaları kapattık. Öne çıkanlar:

- **`require_role`** (Discord-native rol id kontrolü) hiç test edilmiyordu
  — sıfırdan `tests/integration/test_require_role.py` eklendi.
- **`bot/extension.py`'nin tüm `install_*` fonksiyonları** (`install_member_lookup`,
  `install_channel_permission_lookup`, `install_guild_listing`) ve
  **`single_process_lifespan`/`web_only_lifespan`/`run_bot_process`**
  (bot başlatma hata yolu dahil) hiç doğrudan test edilmiyordu — sadece
  `DiscordWebAPI` üzerinden dolaylı olarak. `tests/unit/test_bot_extension.py`
  eklendi (%54 → %96).
- **`CommandRegistry.command_meta`** decorator'ı ve wrapped
  `interaction_check`'in gerçek gövdesi (slash komut enforcement — sadece
  `global_check` test ediliyordu) hiç test edilmiyordu —
  `tests/unit/test_registry_misc.py` eklendi.
- `commands/bridge.py`'nin "not found" guard clause'ları (guild/member/
  channel bulunamadı) — `tests/unit/test_bridge_not_found_paths.py`.
- `discord_webapi.storage`'ın lazy `__getattr__`'ı (SQL store'ların
  gecikmeli import'u) hiç test edilmiyordu.
- `discord_webapi.jobs.worker.run_worker` hiç test edilmiyordu.

Genel coverage %91 → %95 (`discord_webapi/__init__.py:82%`,
`storage/sql.py:87%` gibi kalanlar çoğunlukla migration/hata-yolu
kenar durumları — düşük öncelik). 257 test yeşil (1 ortam-bağımlı
Postgres testi hariç), ruff+mypy temiz.

## [Unreleased] — Harici inceleme geri bildirimi: rate limiter sınırı + Redis namespace izolasyonu

Önceki iki denetimi (auth/authz ve jobs/çoklu-sunucu) harici olarak
inceleyen bir üçüncü tarafın işaret ettiği üç nokta ele alındı:

### Düzeltilen

- **`TokenBucketLimiter._buckets` artık sınırlı (LRU-bounded)**: yeni
  `max_tracked_keys` parametresi (varsayılan 10.000) — `OrderedDict`
  kullanılarak en eski entry evict ediliyor. Evict edilen bir key zararsız
  şekilde bir sonraki görülüşünde dolu bir bucket'la geri geliyor.
- **`RedisTransport`/`RedisJobQueue`'ye `namespace=` parametresi eklendi**:
  birbirinden bağımsız birden fazla deployment (ör. farklı müşterilerin
  botları) tek bir Redis instance'ını/cluster'ını paylaşıyorsa, farklı
  `namespace` değerleriyle kanal/kuyruk isimlerinin çakışması önleniyor.
  Bu, kimlik doğrulama değil sadece isim-alanı izolasyonu — gerçek
  mutually-untrusted tenant izolasyonu için hâlâ ayrı Redis
  veritabanı/ACL kullanıcısı gerekiyor (`docs/GUVENLIK.md`'de detaylı).

### Bilinçli olarak değiştirilmeyen (zaten dokümante edilmiş tasarım kararı)

- `RedisTransport`'un "bir komuta tek handler" kısıtlaması — operasyonel
  bir dikkat noktası olarak kalıyor, dağıtık kilit/koordinasyon gibi
  ekstra karmaşıklık eklemeden dokümantasyonla (bkz. `docs/GUVENLIK.md`,
  `docs/DAGITIM.md`) ele alınmaya devam ediyor.

226 test yeşil (gerçek Redis'e karşı, 1 ortam-bağımlı Postgres testi
hariç), ruff+mypy temiz. Yeni testler: `tests/unit/test_ratelimit.py`,
`tests/unit/test_redis_transport_namespace.py`,
`tests/unit/test_redis_job_queue.py`'ye eklenen namespace testi.

## [Unreleased] — Kuyruk sistemi taraması: 2 gerçek bug bulunup düzeltildi

Kuyruk sistemi eklendikten sonra yapılan geniş kapsamlı bir bug/güvenlik
taramasında `discord_webapi/jobs/redis.py`'de iki gerçek bug bulundu:

- **Kuyrukta bekleyen (henüz worker'a düşmemiş) bir job'ın status kaydı,
  `result_ttl_seconds` süresi geçince sessizce silinebiliyordu** — worker'lar
  uzun süre kapalıysa/backlog oluşmuşsa, `BLPOP` job_id'yi kuyruktan
  çekiyor ama `get_status` `None` dönüyor, job hiçbir iz bırakmadan
  kayboluyordu. **Fix**: TTL artık sadece terminal duruma (succeeded/failed)
  ulaşan job'lara uygulanıyor — pending/running durumundaki bir job'ın
  status kaydı asla süresi dolarak silinmiyor. Ayrıca `get_status` yine de
  `None` dönerse (ör. Redis `maxmemory` baskısı altında eviction) artık
  sessizce değil, bir `logger.warning` ile job düşürülüyor.
- **`register_worker()`, `start()`'tan SONRA çağrılırsa sessizce hiçbir
  şey yapmıyordu** — worker zaten `_worker_loop`'un BLPOP key listesini
  `start()` anında sabitliyordu, yeni bir job_type asla işlenmiyordu, ne
  hata ne uyarı. Bu, `InProcessJobQueue`'nun (geç register'ı sessizce
  kabul eden) davranışıyla tutarsızdı — dev'de `InProcessJobQueue`'ya
  karşı çalışan kod, production'da `RedisJobQueue`'ya geçince sessizce
  bozulabilirdi. **Fix**: `start()`'tan sonra `register_worker()`
  çağrılırsa artık açık bir `RuntimeError` fırlatılıyor.

Ayrıca iki küçük iyileştirme:
- `_with_job_queue`'da `job_queue.start()` başarısız olursa artık
  `stop()` çağrılmıyor (hiç başlamamış bir queue'yu durdurmaya
  çalışmaktan kaynaklanan potansiyel kaynak-durumu hatası önlendi).
- `DiscordWebAPI.for_bot_process()`'e de `job_queue=...` parametresi
  eklendi (sadece `for_web_process`'te vardı) — bot/Gateway erişimi
  gereken job handler'ları artık bot sürecinde de register edilebiliyor.

220 test yeşil (gerçek Redis'e karşı çalıştırıldı, 1 ortam-bağımlı
Postgres testi hariç), ruff+mypy temiz. Yeni testler:
`tests/unit/test_redis_job_queue.py`, `tests/integration/test_facade.py`'ye
eklenen 2 test.

## [Unreleased] — Kuyruk sistemi (background jobs)

### Eklenenler

- **`discord_webapi.jobs`**: dashboard'dan tetiklenen, request/response döngüsünde beklenemeyecek kadar uzun süren işler için (toplu moderasyon, export, zamanlanmış temizlik) yeni bir alt paket. `Transport`'la aynı mimari desende: `JobQueue` Protocol'ü + `InProcessJobQueue` (varsayılan, sıfır altyapı) + `RedisJobQueue` (`discord-webapi[redis]`, `RPUSH`/`BLPOP` ile gerçek dağıtık kuyruk — `RedisTransport`'un "bir komuta tek handler" kısıtlamasının aksine, kaç tane worker process çalıştırırsan çalıştır Redis aynı job'ı iki kere işletmemeyi garanti ediyor, gerçek yatay ölçekleme).
- Dashboard API: `POST /api/guilds/{guild_id}/jobs/{job_type}` (enqueue, 202 + `job_id`), `GET /api/guilds/{guild_id}/jobs/{job_id}` (status poll — başka bir guild'in job'ı 404 dönüyor, 403 değil, job'ın var olup olmadığını sızdırmamak için). Opt-in: `DiscordWebAPI(job_queue=...)` + `install(enable_jobs=True)`.
- `discord_webapi.jobs.run_worker(queue)`: bağımsız worker process için giriş noktası (FastAPI yok, `run_bot_process`/`web_only_lifespan` ile aynı desen) — `bot_process.py`/`web_process.py`'ye üçüncü bir opsiyonel process tipi olarak `examples/split_deployment/worker_process.py` eklendi.
- `DiscordWebAPI.lifespan()`/`web_lifespan()` artık `job_queue` verildiyse onu da otomatik start/stop ediyor — tek-process kurulumda ekstra boilerplate gerekmiyor.
- Contract test suite (`tests/jobs/`): her iki implementasyon da aynı testlerden geçiyor (Transport'un kendi contract test deseniyle birebir aynı).

193 test yeşil (1 ortam-bağımlı Postgres testi hariç), ruff+mypy temiz.

## [Unreleased] — Çoklu sunucu/makine deployment (bot ve web ayrı process)

### Eklenenler

- **`DiscordWebAPI.for_bot_process(bot=..., transport=..., ...)`** ve **`DiscordWebAPI.for_web_process(transport=..., auth=..., ...)`**: büyük botlar için bot (Discord Gateway bağlantısı) ve FastAPI dashboard'ı tamamen ayrı process'lerde/makinelerde çalıştırma. Web tarafı `RedisTransport` üzerinden N tane replica olarak yatay ölçeklenebilir (load balancer arkasında), bot tarafı tek bir process olarak kalır. Varsayılan tek-process API'si (`DiscordWebAPI(bot=..., transport=..., auth=...)`, `quickstart()`) hiç değişmeden çalışmaya devam ediyor — bu tamamen opt-in bir ek.
- **`discord_webapi.bot.run_bot_process(bot, transport, token)`**: bot-only process için FastAPI'siz giriş noktası — Discord'a ve Transport'a bağlanır, sonsuza kadar bekler.
- **`discord_webapi.bot.web_only_lifespan(transport)`** / **`DiscordWebAPI.web_lifespan()`**: web-only process için FastAPI lifespan — bot yok, sadece Transport'un kendi bağlantısını başlatıp kapatıyor.
- `examples/split_deployment/`: `bot_process.py` + `web_process.py` + README, gerçek Redis+Postgres ile iki ayrı process'in nasıl çalıştırılacağını gösteriyor.

### Mimari değişiklik: `CommandRegistry` artık Transport RPC üzerinden

Bu özelliğin asıl engeli şuydu: `commands/api.py` (dashboard'un `GET/PATCH /api/guilds/{id}/commands` endpoint'leri) şimdiye kadar `app.state.discord_webapi_commands` üzerinden CANLI bir `CommandRegistry` nesnesine DOĞRUDAN erişiyordu — bu da web ve bot'un aynı process'te olmasını zorunlu kılan tek parçaydı (her diğer alt sistem — üyeler, kanal izinleri, guild listesi — zaten sadece `Transport` üzerinden konuşuyordu, hiçbirinde bu sorun yoktu).

**Fix**: `commands/registry.py`'ye `install_command_registry_bridge(registry, transport)` eklendi — registry'nin bulunduğu process'te (`list_command_status`/`set_command_override` RPC'lerini) `Transport.register_handler` ile cevaplıyor. `commands/api.py` artık `app.state.discord_webapi_commands`'a hiç bakmıyor, sadece `transport.request(...)` çağırıyor. Tek-process modda (`InProcessTransport`) bu, aynı process içinde bir RPC round-trip'e dönüşüyor (davranış aynı, sadece bir dolaylama katmanı) — hiçbir mevcut kullanım/test bundan etkilenmedi (testler `app.state.discord_webapi_commands` yerine `install_command_registry_bridge` + `app.state.discord_webapi_transport` kullanacak şekilde güncellendi).

182 test yeşil (1 ortam-bağımlı Postgres testi hariç), ruff+mypy temiz. Yeni test dosyası: `tests/integration/test_split_deployment.py` — iki ayrı `DiscordWebAPI` nesnesinin (bot-side/web-side, gerçek ayrı process'leri simüle ediyor) birbirine hiç referans vermeden, sadece paylaşılan Transport üzerinden doğru çalıştığını doğruluyor.

## [Unreleased] — Kapsamlı güvenlik denetimi (genişleme sonrası)

Genişleme (v0.5) bittikten sonra planlanan kapsamlı güvenlik denetimi
yapıldı. Auth (OAuth2 state/CSRF, session cookie flag'leri, Fernet
şifreleme, token refresh race), authz (guild/channel-scoped fail-closed
kontroller), yeni `guilds`/oturum yönetimi endpoint'leri, transport
(Redis pub/sub güven sınırı), SQL storage (injection, secret loglama) ve
rate limiting kapsamı incelendi. Çoğu alan zaten sağlamdı; iki gerçek bug
bulunup düzeltildi:

- **`/auth/discord/logout`, `/auth/discord/sessions`, `/auth/discord/sessions/{id}` hiç rate-limit'li değildi** — commands/app-roles PATCH/PUT/DELETE endpoint'lerinin aksine. Çalınmış bir düşük-güvenli oturum (ör. sızmış mobil bearer token) bu endpoint'leri brute-force/abuse için kullanabilirdi. **Fix**: aynı `TokenBucketLimiter` deseni (`DiscordAuth(session_management_rate_limiter=...)` ile özelleştirilebilir). `TokenBucketLimiter` sınıfı, `auth`↔`commands` arasında circular import'a yol açmadan paylaşılabilmesi için bağımsız bir `discord_webapi/ratelimit.py` modülüne taşındı (`commands.ratelimit` hâlâ geriye dönük uyumlu şekilde re-export ediyor).
- **`DiscordAuth._refresh_locks` sınırsız büyüyordu** — token refresh gereken her session için bir `asyncio.Lock` oluşturuluyordu ama asla silinmiyordu, process'in ömrü boyunca. **Fix**: refresh tamamlandıktan sonra `finally` bloğunda lock dict'ten siliniyor (aynı anda bekleyen başka bir task'ın kendi referansı zaten elinde olduğu için güvenli).

Diğer bulgular: `commands/ratelimit.py`'deki `_buckets` dict'i de aynı desende sınırsız büyüyor (düşük öncelik, bellek-only, auth bypass değil) — şimdilik düzeltilmedi. RedisTransport'un pub/sub kanallarında imzalama/auth yok — bilinçli güven sınırı olarak dokümante edilmiş durumda (Redis'in kendisi güvenilir altyapı olmalı). SQL storage tamamen ORM üzerinden, raw string interpolation yok; token'lar sadece şifreli (Fernet) tutuluyor, hiçbir yerde loglanmıyor.

178 test yeşil (1 ortam-bağımlı Postgres testi hariç), ruff+mypy temiz.

## [Unreleased] — Genişleme: sunucu listesi, oturum yönetimi

### Eklenenler

- **`GET /api/guilds`**: kullanıcının kendi Discord sunucu listesinden, botun da içinde olduğu VE kullanıcının "Manage Server" yetkisine sahip olduğu sunucuları döndürür — bir "sunucu seç" ekranı için, her sunucuyu tek tek deneyip 403/404 almaya gerek kalmadan. `discord_webapi/guilds/` (yeni modül), bot tarafında `install_guild_listing` (botun warm Gateway cache'inden cevaplıyor).
- **Oturum yönetimi ("her yerden çıkış yap")**: `GET /auth/discord/sessions` (kendi aktif oturumlarını listele, hangisinin şu anki oturum olduğu `is_current` ile işaretlenir, şifreli Discord token'ları asla dönmez) ve `DELETE /auth/discord/sessions/{session_id}` (sadece kendi oturumunu iptal edebilir — başkasının oturumu 404 döner). `SessionStore` protokolüne `list_by_user()` eklendi (Memory + SQL implementasyonları).

## [Unreleased] — Çekirdek dayanıklılık (hardening) turu

### Düzeltilen (kritik — kod incelemesiyle bulundu)

- **`RedisTransport` bağlantı koparsa sonsuza kadar ölüyordu.** `_read_loop`, Redis bağlantısı bir ağ kesintisi/Redis restart yüzünden koptuğunda hiçbir yeniden bağlanma denemesi yapmadan sessizce sonlanıyordu — bir daha hiçbir event/RPC cevabı gelmiyordu, tüm süreç yeniden başlatılana kadar. **Fix**: dış bir retry döngüsü eklendi (`RedisError` yakalanıp 1 saniye sonra tüm kanallara yeniden abone olunuyor).
- **WebSocket relay, istemci bağlantıyı kapatınca fark etmiyordu.** `commands_stream`, sadece kuyruktan event okuyup gönderiyordu — istemci sekmeyi kapatsa bile, o guild'de yeni bir event olmadan sunucu bunu hiç anlamıyordu, subscriber+task sonsuza kadar askıda kalıyordu (uzun süre çalışan bir deployment'ta gerçek bir sızıntı). **Fix**: event gönderimiyle paralel olarak bağlantıyı da izleyen ikinci bir task eklendi (`asyncio.wait(FIRST_COMPLETED)`), istemci kapanınca ikisi de düzgün temizleniyor.
- **SQL storage'da eşzamanlı yazma yarışı (race condition).** `set_override`/`set_app_role`/consent'in `set()`'i "oku, yoksa oluştur" deseni kullanıyordu — aynı guild/komut (veya app-role, consent kaydı) için iki istek neredeyse aynı anda ilk kez yazarsa, ikisi de "yok" görüp ikisi de INSERT deniyordu; kaybeden yakalanmamış bir `IntegrityError` ile 500 patlıyordu. **Fix**: paylaşılan bir `_commit_upsert()` yardımcı fonksiyonu — çakışma olursa rollback edip satırı tekrar okuyup update olarak uyguluyor. Gerçek Postgres'e karşı yarış senaryosunu tetikleyen bir regresyon testiyle doğrulandı (SQLite'ta StaticPool'un tek bağlantı paylaşması yüzünden bu yarış test edilemiyor, gerçek izolasyonlu bağlantılar gerekiyor).

## [0.4.0] — Kanal bazlı izin override, warn/welcome builtin'leri, mobil giriş sağlamlaştırması

### Düzeltilen (kritik — gerçek kullanım sırasında bulunan üç bug)

- **Cooldown/invocation_count, slash-çağrılan hybrid komutlarda çift işleniyordu.** discord.py, bir hybrid komut slash olarak çağrıldığında hem bizim wrap ettiğimiz `tree.interaction_check`'i HEM DE `global_check`'i (`HybridCommand._check_can_run` → `bot.can_run(ctx)` üzerinden) aynı çağrı için iki kez çalıştırıyor — bu, tek bir `/ping` çağrısının cooldown token'ını 2 kere tüketmesine ve `invocation_count`'un 2'şer 2'şer artmasına yol açıyordu ("1 kullanımda 30 saniye cooldown" ayarlandığında komut kalıcı olarak kilitleniyormuş gibi görünüyordu). **Fix**: `global_check` artık `ctx.interaction is not None` olduğunda (yani zaten `interaction_check` tarafından ele alınmış bir slash çağrısı olduğunda) hiçbir şey yapmadan `True` dönüyor.

- **Slash komutlar Discord'a hiç senkronize edilmiyordu.** discord.py, `bot.tree.sync()` çağrılmadıkça tanımlı slash komutları Discord'a hiç göndermiyor — sessizce, hatasız. `DiscordWebAPI` artık bot hazır olduğunda (`on_ready`) otomatik `bot.tree.sync()` çağırıyor (`sync_commands=True` varsayılan, kapatılabilir). `sync_guild_id=<test_sunucu_id>` verilirse global sync'in (~1 saate kadar sürebilen) yayılma gecikmesi olmadan tek bir sunucuya anında senkronize ediyor — test sırasında çok daha pratik.
- **`!ping` gibi prefix komutları hiç çalışmıyordu.** `default_intents()` `message_content` intent'ini açmıyordu — bu olmadan discord.py mesaj metnini okuyup `command_prefix`'e göre eşleştiremiyor, komut sessizce hiç tetiklenmiyor. Artık `default_intents()` bunu da açıyor (Discord Developer Portal'da "Message Content Intent"i de açman hâlâ gerekiyor, ayrıca).

### Eklenenler

- **Kanal bazlı izin override** (`require_channel_permission`): `require_guild_permission`'dan farkı, guild-level izne sahip olsan bile o kanala özel bir override iznini geri alabiliyor. `ChannelPermissionCache` (TTL'li, `AppRoleCache` ile aynı basit desende — push-invalidation yok), bot tarafında `install_channel_permission_lookup` (Discord'un `channel.permissions_for(member)`'ını kullanıyor, ekstra REST çağrısı yok). `full_featured_bot`'ta demo endpoint: `GET /api/guilds/{guild_id}/channels/{channel_id}/can-send`.
- `DiscordWebAPI(channel_permission_cache_ttl_seconds=30.0)` — yeni parametre.
- `discord_webapi.builtins.warn` — ilk kalıcı-durumlu builtin: `WarnStore` protokolü, `MemoryWarnStore` (varsayılan), `SQLWarnStore` (kendi bağımsız `create_all()`'ı ile, core `storage.sql`'dan ayrı). Opsiyonel `auto_timeout_after` ile otomatik timeout eskalasyonu.
- `discord_webapi.builtins.welcome` — ilk komut-olmayan builtin: configlenebilir `on_member_join` mesajı (kanala veya DM'e), kanal asla tahmin edilmiyor.
- Cookie-consent banner'ının bundled `dashboard.html`'e opsiyonel entegrasyonu: `build_default_dashboard_router(enable_cookie_consent=, cookie_consent_message=, cookie_consent_version=)`, `DiscordWebAPI.install()`/`quickstart()`'a aynı parametreler eklendi. Banner metni tamamen tüketiciye ait; versiyon değişince herkes tekrar onaylıyor.
- Bundled dashboard'a tıklanabilir **"Mobil giriş (session_id al)"** butonu — `?mobile=true`'yu elle yazma ihtiyacını ortadan kaldırıyor (yazım hatası riskini kapatıyor).
- `full_featured_bot`'ta gerçek bir `/mobile-login-done` sayfası (önceden 404'tü) — `session_id`'yi büyük/kopyalanabilir gösteriyor.

### Kapsam dışı bırakılan / ertelenen (bilinçli karar)

- **Multi-bot/shard routing**: orijinal roadmap'te v0.3+ listesindeydi, bu sürüme dahil edilmedi. Birden fazla bot instance/shard'ın aynı dashboard'u paylaşması, tek bir `Transport`'un doğru shard'a nasıl yönlendireceği gibi sorular kendi başına ayrı bir tasarım turu gerektiriyor — üçüncü-taraf paket sistemiyle aynı gerekçeyle (bkz. v0.3.0 notu) erteleniyor.

## [0.3.0] — Audit log, cookie consent, builtins

### Eklenenler

- **Audit log** (opt-in, `enable_audit_log=False` varsayılan): `AuditStore` (Memory/SQL), `AuditLogger`, `GET /api/guilds/{id}/audit-log`. Şu an komut override yazmalarını ve AppRole set/delete'lerini kaydediyor; auth login/logout olayları kapsam dışı.
- **Cookie/gizlilik consent kaydı** (opt-in, `enable_cookie_consent=False` varsayılan): `ConsentStore` (Memory/SQL), `GET/POST /api/consent`. Notice'ın metni/UI'ı tamamen tüketiciye ait — kütüphane sadece "kim, hangi versiyonu, ne zaman onayladı" kaydını tutar, yasal zorunluluk dışında hiçbir davranış dayatmaz.
- **`discord_webapi.builtins`**: hazır, tam-özellikli, serbestçe import edilebilir komutlar için yeni bir alt paket. `_shared.py`'de bağımsız kullanılabilir parçalar (rol-hiyerarşisi kontrolü, best-effort DM) — sadece bunları alıp sıfırdan yazılan bir komuta gömmek, hazır komutu olduğu gibi kullanmak, ya da ikisini birden (hibrit) yapmak mümkün. Şu an: `ban.py`, `kick.py`, `timeout.py` (Discord'un native timeout'u). Her builtin kendi dosyasında, `setup(bot, **kwargs)` ile açıkça çağrılır — otomatik yükleme yok, hiçbir zorunlu şablon dayatılmaz.

### Kapsam dışı bırakılan (bilinçli karar)

- Üçüncü-taraf paket/manifest formatı (JSON manifest, versiyonlama, installer/"VM" benzeri bir çalıştırma sistemi) bu sürüme dahil edilmedi — ayrı, çok daha büyük bir tasarım gerektiriyor. Bkz. `discord_webapi/builtins/README.md`.

## [0.2.0] — WebSocket relay, invocation counter, AppRole, cooldown, çoklu DB

### Eklenenler

- **AppRole**: Discord'un kendi rol sisteminden bağımsız, bot-özel roller (`require_app_role`, `AuthzStore`, `AppRoleCache`, `GET/PUT/DELETE /api/guilds/{id}/app-roles`).
- **Per-command cooldown**: `CommandOverride.cooldown_seconds`/`cooldown_uses`, discord.py'nin kendi `Cooldown`/`CooldownMapping` mekanizması üzerinden, hem prefix/hybrid hem slash komutlar için kullanıcı bazlı.
- **Dahili invocation sayacı**: `CommandStatus.invocation_count` — tam bir analytics sistemi değil, basit bir sayaç.
- **Çoklu veritabanı desteği**: SQLite/Postgres/MySQL, `discord-webapi[sql-sqlite|sql-postgres|sql-mysql]` extra'ları, `quickstart(database_url=...)`.
- **WebSocket canlı relay** (opt-in, varsayılan kapalı): `enable_websocket=True` ile `/api/guilds/{id}/commands/stream`, `command_config_changed` event'lerini polling olmadan anlık push eder.
- `Transport.unsubscribe()` — WebSocket bağlantısı kapandığında subscriber sızıntısını önler.
- `DiscordAuth.get_current_user` artık `HTTPConnection` alıyor (hem `Request` hem `WebSocket` için ortak taban) — aynı auth mantığı WebSocket handshake'inde de çalışıyor.
- `TESTING.md`: gerçek bir Discord sunucusunda fiziksel/manuel test için adım adım kontrol listesi.

### Testler

- 132 test yeşil (3 skip — sadece yerelde MySQL servisi çalışmadığından), `ruff check` ve `mypy discord_webapi` temiz.

## [0.1.0] — Çekirdek

- Pluggable Transport katmanı (`InProcessTransport`, `RedisTransport`, ortak contract test suite).
- Discord OAuth2 login: opak session modeli (JWT/refresh hibrit değil), tarayıcı (cookie) ve mobil (Bearer token) için aynı auth yüzeyi.
- Guild-rol tabanlı yetkilendirme (`require_guild_permission`), botun warm Gateway cache'inden Transport RPC ile okuma.
- Command Registry: discord.py komutlarının tek seferlik introspection'ı, canlı enable/disable (restart'sız), dashboard API.
- SQL storage (SQLAlchemy async) + Memory storage protokolleri.
- `DiscordWebAPI.quickstart()`, `default_intents()`, gömülü varsayılan dashboard HTML'i ile boilerplate ~%80 azaltıldı.
