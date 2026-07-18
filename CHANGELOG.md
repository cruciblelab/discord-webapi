# Changelog

Formatı [Keep a Changelog](https://keepachangelog.com/) temel alıyor.

## [Unreleased] — `AutoShardedBot` desteği (type-hint fix) + roadmap'in uzun-vade maddeleri gözden geçirildi

Roadmap'in tamamı bittikten sonra §4'teki (uzun vade/bilinçli ertelenen)
7 maddeyi tek tek kullanıcıyla gözden geçirdik: dashboard UI, İngilizce
docs, multi-bot routing hepsi ertelenmiş kalması onaylandı. Discord
sharding/RedisTransport→Streams sorusunda kullanıcı net karar veremedi
("hobiciler için kütüphane olur, profesyonel olmalı" endişesiyle) --
önce gerçekten neyin eksik olduğunu bir alt-agent'la araştırdık.

**Bulgu**: "sharding desteği" iki çok farklı şey:
1. **Tek-process auto-sharding** (gerçek büyük botların ezici
   çoğunluğunun ihtiyacı, binlerce/on binlerce sunucu) -- zaten tam
   çalışıyordu, sıfır kod değişikliği gerekmedi. Kütüphanenin her yeri
   zaten sadece discord.py'nin birleşik `bot.guilds` cache'ine bakıyor,
   shard sayısından bağımsız. Tek gerçek eksik: `bot: commands.Bot` type
   hint'i `commands.AutoShardedBot`'u (kardeş sınıf, alt sınıfı değil)
   kabul etmiyordu.
2. **Çoklu-process shard cluster'ları** (sadece devasa ölçekte, Dyno/MEE6
   tier, yüzbinlerce sunucu) -- gerçek bir eksik, ama multi-bot routing
   ile aynı temel problem (RedisTransport'un "bir komuta tek handler"
   kısıtlaması). Somut talep olmadan ertelenmiş kalması onaylandı.

**Yapılan**: 1. maddeyi kapatan `AnyBot` type alias'ı
(`discord_webapi.bot.types`, `commands.Bot | commands.AutoShardedBot`) --
14 dosyada (`__init__.py`, `commands/registry.py`, `commands/bridge.py`,
`members.py`, `extras/{ban,kick,timeout,warn,welcome,role_assign,
captcha_verify}.py`, `extras/automod/__init__.py`,
`extensions/{sdk,scaffold}.py`, `bot/extension.py`) `commands.Bot` yerine
kullanıldı. Döngüsel import riskini önlemek için `AnyBot` kendi başına,
hiçbir `discord_webapi` içe aktarması olmayan bir "leaf" modülde
(`bot/types.py`) tanımlandı -- `bot/extension.py` bunu import ediyor,
ama `bot/extension.py`'nin kendisi de `commands/bridge.py`'yi import
ettiği için `AnyBot`'un orada tanımlanması `commands/bridge.py`'nin
`AnyBot`'u geri import etmesiyle döngü oluştururdu. Yeni
`tests/unit/test_sharded_bot.py`, gerçek bir `commands.AutoShardedBot`
nesnesiyle `CommandRegistry`/`register_all()`/`extras.{ban,kick,timeout,
warn}.setup()`'ın uçtan uca çalıştığını doğruluyor (sadece mypy'yi
susturmuyor). Davranış değişmedi, sadece type-hint doğruluğu -- tam test
suite (543 test, 3 yeni) + ruff + mypy temiz.

`docs/ROADMAP.md`'nin kalan tüm maddeleri bu turda kapatıldı (P2.3 hariç,
kullanıcının ayrı ele alacağı PyPI/versiyon kararına bağlı olarak bilinçli
ertelendi):

- **web-api-captcha'ya CI + CHANGELOG.md eklendi.** Python 3.11/3.12'de
  ruff/mypy/pytest -- discord-webapi'nin kendi `ci.yml`'sinden esinlenildi,
  discord.py sürüm matrisi ve DB service container'ları olmadan (SQL store
  testleri sadece sqlite'a karşı çalışıyor). İlk çalıştırma yeşil.
- **Gerçek bir paketleme bug'ı bulunup düzeltildi**: `pyproject.toml`'daki
  `captcha` extra'sının git URL'ine doğrudan referansı, hatchling'in
  `tool.hatch.metadata.allow-direct-references = true` olmadan kabul
  etmediği bir şeydi -- `pip install -e ".[captcha]"` (ve `.[all]`,
  `.[dev]`) metadata üretiminde tamamen patlıyordu. Taze bir klondan
  gerçek GitHub kurulumu denenince ortaya çıktı, düzeltildi ve doğrulandı.
- **P1.5 (docs netleştirmeleri)**: `docs/DAGITIM.md`'ye MySQL/MariaDB'nin
  `_commit_upsert` ve `DATETIME(fsp=6)` garantilerinin Postgres'le birebir
  aynı olduğunu açıklayan bir bölüm eklendi (Redis namespace uyarısı zaten
  `docs/GUVENLIK.md`'de vardı).
- **P2.1**: `DiscordWebAPI.quickstart()`'ın engine kurulumu
  `_quickstart_engine()`'e, 8 SQL store'un kurulumu `_quickstart_sql_stores()`'a
  (bir `_QuickstartStores` NamedTuple döndürür) çıkarıldı -- davranış
  değişmedi, sadece okunabilirlik.
- **P2.2**: `SimpleNamespace` fake'lemesi kontrol edildi -- sadece
  `tests/`'te ve scaffold'ın ürettiği test şablonunda kullanılıyor,
  prod kodunda hiç yok, ek işlem gerekmedi.
- **P1.5-obs — opsiyonel observability/metrics**: yeni
  `discord_webapi.observability` -- `MetricsSink` Protocol'ü (`increment`/
  `observe`, varsayılan `NoOpMetricsSink`) + `PrometheusMetricsSink`
  (`discord-webapi[metrics]` extra'sı). Dört noktaya kancalandı: transport
  RPC latency + hata sayacı (`InProcessTransport`/`RedisTransport`), job
  başarı/başarısızlık sayacı (`InProcessJobQueue`/`RedisJobQueue`),
  escalation rung tetiklenme sayacı (`EscalationEngine`), komut çağrı
  sayacı (`CommandRegistry`). `DiscordWebAPI`/`quickstart()`'a yeni
  `metrics=` parametresi -- tek bir sink geçmek transport/registry/
  escalation'ın hepsine otomatik ulaşıyor. Varsayılan tamamen no-op,
  çekirdeğe yeni bağımlılık eklenmedi. 11 yeni test, tam suite (540 test)
  + ruff + mypy temiz.

## [Unreleased] — Captcha, ayrı bir kütüphaneye taşındı: `webapi-captcha`

Kullanıcının talebi (özet): captcha modülü "overengineering" olmuş, bir
API parçasından çok bağımsız bir araca dönüşmüş hissi vermiş -- ayrı,
public bir kütüphane olarak çıkaralım, hem onu hem discord-webapi'yi
ayrı ayrı geliştirelim. Önce somut bir bağımlılık ölçümü yapıldı (yaklaşık
4300 satır Python + 502 satır JS + ~4200 satır test içinde SADECE 3 gerçek
çapraz-modül bağımlılığı bulundu: `Transport`/`Event`, `TokenBucketLimiter`,
`DiscordUser`/`get_current_user_optional`) -- bu düşük riski doğruladı ve
"şimdi yapalım" kararını destekledi. Kullanıcının netleştirdiği koşullar:
ayrı repo (`cruciblelab/web-api-captcha`), Apache 2.0 lisans, GitHub'dan
doğrudan kurulum, `discord_webapi/captcha/` klasöründe birkaç gerekli
dosya kalsın (yükleme yapılmadan kullanılmaya çalışılırsa doğrudan "bunu
yüklemeniz lazım" diyen açık bir hata versin), paket adı `webapi-captcha`.

### Yeni repo: `cruciblelab/web-api-captcha`

- Bütün captcha kodu (`_shared.py`, `adaptive.py`, `api.py`, `base.py`,
  `checks.py`, `events.py`, `gate.py`, `memory.py`, `models.py`,
  `pageguard.py`, `presets.py`, `providers/`, `rendering.py`,
  `replay_guard.py`, `reputation.py`, `scoring.py`, `signals.py`,
  `sql.py`, `widget.js`, `widget.py`) `webapi_captcha/` paketine taşındı.
- 3 bağımlılık noktası genellendi: kendi `Transport` Protocol'ü +
  `InProcessTransport` (discord-webapi'ninkiyle yapısal olarak uyumlu --
  hiçbir yerde `isinstance` kontrolü yok, sadece publish/subscribe
  kullanılıyor, bu yüzden discord-webapi'nin kendi transport'u adaptörsüz
  çalışıyor), vendored `TokenBucketLimiter`, ve Discord'a özgü
  `DiscordUser`/`get_current_user_optional` yerine genel bir
  `current_user_id_resolver` FastAPI dependency'si (`build_captcha_router`'a
  yeni parametre, varsayılan "kimse giriş yapmamış").
- Bundled widget'ın (`widget.js`) TÜM kullanıcıya görünen metinleri
  (buton/hata/durum yazıları, ~30 string) Türkçe'den İngilizce'ye
  çevrildi ve varsayılan yapıldı -- public, Apache-2.0 bir paket için
  genel bir kitleye hitap etmesi gerektiği için (kullanıcıya soruldu,
  "İngilizce'ye çevir, varsayılan yap" seçildi).
- İsimlendirme tutarlılığı için `dwa_`/`dwa-` önekleri (SQL tablo adları,
  cookie adı, CSS sınıfları, JS event adları, script dosya adı) `wac_`/
  `wac-`'a çevrildi (`discord-webapi` → `webapi-captcha` kısaltması).
- Test paketi (18 dosyadan 17'si -- `test_captcha_verify.py` Discord'a
  özgü olduğu için discord-webapi'de kaldı) taşındı; `test_captcha_api.py`'nin
  hesap-bağlama testleri artık gerçek `DiscordAuth`/OAuth mock'u yerine
  yeni `current_user_id_resolver` desenini (basit bir `app.state`
  bayrağı) kullanıyor. 241 test, standalone (discord-webapi kurulu
  olmadan) ruff/mypy --strict/pytest tertemiz.
- Gerçek bir README.md yazıldı (kurulum, iki temel kullanım deseni,
  sağlayıcı ailesi özeti, adaptive/PageGuard, widget, discord-webapi
  entegrasyon notu).

### discord-webapi tarafı

- `discord_webapi/captcha/` artık sadece tek bir `__init__.py` -- ince bir
  re-export katmanı. `webapi_captcha` kuruluysa `from discord_webapi.captcha
  import X` eskisi gibi çalışmaya devam ediyor (aynı isim listesi);
  kurulu değilse `import`, kurulum komutlarını (pip/GitHub) ve "istemezsen
  kendi çözümünü yaz ya da üçüncü-taraf birini kullan, bizi ilgilendirmez"
  notunu içeren açık bir `ImportError` fırlatıyor.
- İki küçük Discord'a özgü kolaylık eklendi: `resolve_discord_user_id`
  (discord-webapi'nin kendi OAuth session'ına bağlı hazır bir
  `current_user_id_resolver`) ve `build_discord_captcha_router()`
  (`build_captcha_router`'ın bunu önceden bağlanmış hali) -- hesap-bağlı
  bir gate'i discord-webapi'nin girişine bağlamak için sıfır elle kablo
  gerektiriyor.
- `pyproject.toml`'daki `captcha` extra'sı artık `Pillow>=10.1` yerine
  `webapi-captcha[render] @ git+https://github.com/cruciblelab/web-api-captcha`.
- `discord_webapi/extras/captcha_verify.py` ve iki örnek
  (`examples/captcha_playground`, `examples/captcha_gate_bot`) yeni pakete
  göre güncellendi -- `captcha_gate_bot` account-bound gate'lerinde artık
  `build_discord_captcha_router()` kullanıyor.
- discord-webapi'nin kendi captcha testleri (17 dosya) kaldırıldı --
  aynı testler artık web-api-captcha'da yaşıyor; yeni bir
  `tests/integration/test_captcha_shim.py` sadece re-export şimini ve
  `resolve_discord_user_id`/`build_discord_captcha_router`'ın gerçek bir
  Discord OAuth girişiyle uçtan uca doğru çalıştığını doğruluyor.
- Tüm proje (`discord_webapi/`, `examples/`) ruff/mypy --strict temiz,
  529 test yeşil (2 test Postgres/Redis altyapısı bu ortamda
  bulunmadığı için başarısız -- bu değişiklikle ilgisiz, ortam kaynaklı).

## [Unreleased] — Captcha sisteminde sağlamlaştırma + hızlı kullanım için ekstralar (hibrit, tam özelleştirilebilir)

Kullanıcının isteği (özet, kendi kelimeleriyle): "capctha sistemine
sağlamlaştırma ve ekstralara hızlı kullanımlar için tam özelleştirilebilir
hibrit modele açık yeni şeyler ekleyelim" — sorduğum iki soruya verdiği
cevap: sağlamlaştırma için dört cephenin HEPSİ (daha fazla anti-bot
sinyali, deneme/hız limiti, sağlayıcı çeşitliliği/yedekleme, depolama/
güvenlik sertleştirme); ekstralar için hem hazır bir captcha komutu hem
de Cloudflare tarzı `PageGuard` preset'i — "nasıl ettikleri önemsiz,
temeli sağlam verelim, sen aç genişlet iyileştirme sağlamlaştırma yap."

Mevcut captcha altyapısı (önceki oturumlarda kurulan `AdaptiveCaptchaGate`/
`PageGuard`/`scoring.py`/`replay_guard.py`) zaten çok olgun olduğu için bu
tur BUNLARIN üzerine ekleme yaptı, yeniden yazmadı.

### 1) Daha fazla anti-bot sinyali

- `VerificationContext`'e yeni `user_agent: str | None` alanı eklendi --
  `client_ip` ile aynı mantık: sunucunun kendi gözlemlediği bir değer
  (`Request`'in `User-Agent` header'ı), `signals`'daki gibi istemcinin
  JS'inin iddia ettiği bir şey değil. `CaptchaGate.verify()`/
  `AdaptiveCaptchaGate.verify()`'a yeni opsiyonel `user_agent=` parametresi
  eklendi, `build_captcha_router()` gerçek HTTP header'ı otomatik geçiyor
  (uçtan uca HTTP testiyle doğrulandı).
- `signals.honeypot_field_empty(field_name)`: klasik honeypot tekniği --
  gizli bir form alanını bir bot doldurursa reddeder, gerçek kullanıcı
  hiç görmediği için asla dolduramaz.
- `signals.reject_headless_user_agent(patterns=None)`: `ctx.user_agent`'ı
  bilinen headless-browser/otomasyon araçlarına (`HeadlessChrome`,
  `PhantomJS`, `Puppeteer`, `Playwright`, `Selenium`, `Electron`) karşı
  kontrol ediyor -- dar tutuldu (bilinçli olarak), sıradan tarayıcıları
  yanlışlıkla engellememesi için.
- `pageguard.suspicious_user_agent()`: aynı listeyi `PageGuard`'ın
  `extra_suspicious` yuvasına (sunucu tarafında, JS gerektirmeden,
  `missing_accept_language` ile aynı desen) takan hazır bir fabrika.

### 2) Deneme/hız limiti sağlamlaştırma

`build_captcha_router()`'a iki yeni, opsiyonel IP-bazlı rate limiter:
- `challenge_rate_limiter`: `GET /challenge`'ta daha önce HİÇ limit
  yoktu -- kendi barındırılan (Math/Text) sağlayıcının her çağrıda yeni
  bir `CaptchaStore` satırı yazması, sınırsız issuance'ı o tabloyu
  doldurmanın ucuz bir yolu yapıyordu.
- `gate_verify_ip_rate_limiter`: mevcut `verify_rate_limiter`,
  `/gate/{token}/verify`'da SADECE token bazında sınırlıyordu -- bir IP
  farklı farklı token'lara saldırırsa (her biri kendi taze bütçesiyle)
  hiç yakalanmıyordu. Yeni limiter bunu IP bazında da kapatıyor,
  mevcut token-bazlı limitin davranışını değiştirmeden.

### 3) Sağlayıcı çeşitliliği/yedekleme

- `providers/turnstile.py` -- Cloudflare Turnstile, reCAPTCHA/hCaptcha ile
  birebir aynı şekilde (`site_key`/`secret_key`, `siteverify` POST'u,
  non-JSON/non-dict yanıtta baştan kapalı-hata).
- `providers/fallback.py` -- `FallbackCaptchaProvider`: birden fazla
  `CaptchaProvider`'ı sırayla dener, biri `issue()`'da patlarsa bir
  sonrakine geçer (kendi barındırılan bir sağlayıcının store yazması
  başarısız olursa, ya da kendi yazdığınız ücretli bir servis sağlayıcısı
  ağ hatası verirse). Hangi alt sağlayıcının hangi challenge'ı verdiğini
  `challenge_id`'nin başına bir index ekleyerek takip ediyor -- `verify()`
  her zaman doğru sağlayıcıya yönleniyor (bir insan HANGİ sağlayıcının
  sorusunu çözdüyse doğrulama da SADECE o sağlayıcıdan olabilir).

### 4) Depolama/güvenlik sertleştirme

- `SQLCaptchaStore`'a opsiyonel `encryption_keys` parametresi (varsayılan
  `None` -- eski davranış, tam geriye uyumlu): verilirse
  `PendingCaptcha.answer` (henüz çözülmemiş bir challenge'ın beklenen
  cevabı) `Fernet`/`MultiFernet` ile şifrelenmiş olarak saklanıyor --
  `DiscordAuth`'un token şifrelemesiyle aynı desen. Salt okuma erişimi
  olan biri artık bekleyen tüm challenge'ların cevaplarını göremiyor.
  Anahtar uyuşmazlığında (ya da şifreleme sonradan açıldığında eski
  plaintext satırlar için) `get()` `None` dönüyor (hata fırlatmak yerine
  "bu challenge yok" ile aynı, paketin geri kalanındaki "kapalı-hata"
  felsefesiyle tutarlı).
- Dört SQL store'a (`SQLCaptchaStore`, `SQLVerificationStore`,
  `SQLTrajectoryFingerprintStore`, `SQLTrustStore`) yeni `purge_expired()`
  metodu: süresi geçmiş satırları toplu siliyor (kendi cron/APScheduler
  job'unuza bağlayın -- kütüphane kendi zamanlayıcısını çalıştırmıyor).
  Mevcut lazy-expiry (okuma anında tek satır silme) davranışı aynen
  duruyor, bu ayrıca hiç okunmayan satırlar için depolama hijyeni.

### 5) Ekstra: hazır captcha doğrulama komutu

`extras/captcha_verify.py` -- `warn.py`/`ban.py` ile aynı `setup(bot,
**kwargs)` konvansiyonu: `/verify` komutu `gate.create_verification()`
ile bir link üretip ephemeral yanıt olarak ya da (`dm_link=True`) DM
olarak gönderiyor. Bilinçli olarak ince tutuldu -- gerçek doğrulama
politikası (hangi captcha, hesap bağlama, IP-adaptif eskalasyon) tamamen
geçirilen `gate`'e ait; hem `CaptchaGate` hem `AdaptiveCaptchaGate` ile
değişmeden çalışıyor (küçük bir yapısal `Protocol`, ikisinden birini
import etmeden).

### 6) Preset: Cloudflare-tarzı `PageGuard` fabrikası

`captcha/presets.py::build_cloudflare_style_guard()` -- kullanıcının tarif
ettiği akışı (önce IP itibarı, kötüyse hemen captcha, varsayılan olarak
çizgi-çizme/PathTrace captchası, davranışsal skorlama, IP değişince
tekrar captcha) TEK bir çağrıyla kuran quickstart. Her parametre
`AdaptiveCaptchaGate`/`PageGuard`'ın kendi parametresi, sıfır-config bir
varsayılanla (boş bir `StaticBlocklistReputationChecker`, taze bir
`PathTraceProvider`, in-memory store'lar, varsayılan
`SignalScoreCheck()`) -- herhangi bir parçayı (gerçek bir itibar
kaynağı, `TurnstileProvider`, SQL store'lar, kendi scoring heuristiklerin)
değiştirmek için farklı bir fonksiyona gerek yok, aynı hibrit/tam
özelleştirilebilir felsefe. `bind_trust_to_ip` bu preset'te varsayılan
olarak `True` (gate'in kendi varsayılanı `False`'un aksine) -- "bir IP'den
bağlandı, başka IP'den bağlanırsa hemen captcha" isteğinin karşılığı.

### Doğrulama

Her yeni parça gerçek testlerle doğrulandı (yeni eklenen ~50 test dahil
tüm captcha test paketi: 248 test yeşil). `ruff check`, `mypy` (126
dosya), `python -m pytest` (yerel Redis ile, 801 test yeşil, 7 skip,
ilgisiz 1 Postgres testi bu ortamda deselect) -- hepsi temiz.

## [Unreleased] — Tüm kütüphanenin paralel-ajan denetimi: 10 gerçek bug bulundu ve düzeltildi

Kullanıcının isteği (birebir): "Tüm kütüphaneyi parçalara ayır ve her
parçayı ayrı ayrı kontrol et deneyle incele buglar hatalar kırılma
açıklar veya eksik kalmış yerler hepsini tespit et ve düzelt."

**Yöntem**: ~13.000 satırlık kütüphane 6 örtüşmeyen parçaya bölündü
(auth/transport/storage, commands/authz/captcha, escalation/ratelimits/
audit/consent, extras/automod, extensions/tools, ve genel), her biri için
ayrı bir arka-plan `general-purpose` ajanı TEK bir mesajda paralel olarak
başlatıldı -- yalnızca inceleme yapıp (gerçek deneyle, sadece kod okuyarak
değil) onaylanmış bulguları file:line + repro + önerilen düzeltme ile
raporlamaları istendi, kendileri hiçbir düzeltme yapmadı. Ajanların
raporladığı ~24 bulgudan gerçek, somut repro ile doğrulananlar (aşağıda)
tek tek düzeltildi -- oturumun tamamında izlenen sıkı disiplin: her
düzeltme, ÖNCE eski koda karşı yeni testin gerçekten kırmızı olduğu
(`git stash` ile fix'i geri alıp testin başarısız olduğu), SONRA fix
geri gelince yeşile döndüğü doğrulanarak kabul edildi -- varsayım değil,
her biri için gerçek çalıştırma kanıtı var.

### Facade -- iki `DiscordWebAPI` örneği arasında sızan rate-limit bütçesi

`commands`/`app_roles`/`consent`/`jobs`/`ratelimits`/`escalation` için 6
router-builder modülünün her biri, `DiscordWebAPI.install()` açıkça bir
limiter geçmediğinde modül-seviyesi bir varsayılan `TokenBucketLimiter`'a
düşüyordu -- ki hiçbir zaman geçmiyordu. Sonuç: aynı process'teki HER
`DiscordWebAPI` örneği bu 6 singleton'ı PAYLAŞIYORDU; bir bot/kiracının
dashboard trafiği, tamamen ayrı bir örneğin bütçesini tüketebiliyordu.
İki gerçek app ile HTTP üzerinden doğrulandı: app A'nın 20 PATCH çağrısı
bütçeyi tüketince, app B'nin İLK PATCH'i bile 429 alıyordu. Düzeltme:
`DiscordWebAPI.__init__` artık 6 örnek-seviyesi limiter kuruyor,
`install()` bunları ilgili her router'a açıkça geçiyor.

### Commands -- autocomplete tuşlamaları cooldown/invocation_count'u yakıyordu

discord.py'nin `CommandTree._call()`'ı, `interaction.type`'a göre dallanmadan
ÖNCE `interaction_check(interaction)`'ı çağırıyor -- yani bir slash
komutun autocomplete-etkin bir parametresine her tuşlamada (kullanıcı
henüz komutu ÇALIŞTIRMADAN), bizim sarmalanmış `_interaction_check`'imiz
gerçek bir çağrıyla AYNI cooldown-tüketen, invocation-sayan yoldan
geçiyordu. 1 kullanımlık bir cooldown, kullanıcı sadece bir seçeneğe
yazı yazınca komutu kalıcı olarak "cooldown'da" gösterebiliyordu.
Düzeltme: `interaction.type is discord.InteractionType.autocomplete` ise
cooldown kontrolü/sayacı atlanıyor (global_check'teki mevcut
hybrid-çift-kontrol koruma desenine paralel).

### Escalation -- eşzamanlı ihlaller aynı eşiği iki kere tetikleyebiliyordu

`EscalationEngine.record_violation()`, `violation_store.add()` sonra
`count()` -- iki ayrı, senkronize edilmemiş çağrı yapıyordu. Aynı
(guild, user, key) için eşzamanlı iki ihlal (iki otomod hiti art arda)
her ikisinin de `add()`'i diğerinin `count()`'undan ÖNCE tamamlanabiliyor
-- ikisi de AYNI sayıyı okuyup threshold=2'yi ikisi de eşleştirip
üyeyi İKİ KERE atabiliyordu. Düzeltme: `AdaptiveCaptchaGate`/`CaptchaGate`
için zaten kullanılan per-key `asyncio.Lock` deseni burada da
(guild_id, user_id, key) başına uygulandı.

### Ratelimits -- kendi yayınladığı event'i kendi bucket'ını sıfırlamak için kullanıyordu

`GuildRateLimiter.set_rule()` cache'i ve bucket'ları SENKRON olarak
sıfırlıyor, SONRA `ratelimit_config_changed` event'ini yayınlıyordu.
`InProcessTransport.publish()` ise `asyncio.create_task` ile
fire-and-forget çalışıyor -- yani aynı örneğin kendi
`_on_config_changed` abonesi bu event'i DAHA SONRA, ayrı bir task olarak
tekrar işliyordu. Bu ikinci, gereksiz sıfırlama arada geçen gerçek token
tüketimini SİLİYORDU -- yani bir istemci tam sırasında bedava, hak
etmediği bir token kazanabiliyordu. Düzeltme: her `GuildRateLimiter`'a
benzersiz bir `origin_instance_id` verildi, event payload'ına eklendi;
`_on_config_changed` kendi origin_id'siyle gelen event'i (kendi yankısı)
görünce sıfırlamayı atlıyor -- başka bir process/örnekten gelen gerçek
değişiklikler hâlâ normal şekilde işleniyor.

### Automod -- link_filter port/scheme bypass, emoji_spam 2x fazla sayma, exemptions kanal-izni boşluğu

- **`link_filter.py`**: host regex'i `[^\s/]+` bir `:port` sonekini de
  yakalıyordu -- `evil.com:8080` ne `== "evil.com"`e ne
  `.endswith(".evil.com")`e uyduğu için engellenen bir domain'e port
  eklemek engeli AŞIYORDU (ve allowlist tarafında izinli bir domain'i
  portla paylaşmak yanlışlıkla ENGELLİYORDU). Ayrıca regex sadece
  `https?://` şemasını eşliyordu -- şemayı atlamak (Discord'un kendi
  istemcisi `www.`/çıplak domain'leri de otomatik linkliyor) TÜM filtreyi
  baştan bypass ediyordu. Düzeltme: port ayıklandı; `www.` öneki VEYA
  ardından `/` gelen çıplak bir domain de artık eşleşiyor (sıradan
  "node.js"/"vue.js" gibi metinleri false-positive yapmamak için trailing
  `/` şartı korundu).
- **`emoji_spam.py`**: bayrak emojisi (2 REGIONAL INDICATOR codepoint) ve
  ten-tonlu emoji (taban + 1 FITZPATRICK MODIFIER codepoint) her
  codepoint'i ayrı ayrı sayıyordu -- 3 bayrak mesajı `max_emoji` için 6
  sayılıyordu. Düzeltme: bayrak çiftleri ve taban+modifier ikilileri artık
  TEK eşleşme olarak sayılıyor.
- **`exemptions.py`**: `bypass_if_manage_messages`, kendi docstring'inin
  vaat ettiği "bu kanalda manuel mesaj silebilen" yerine
  `author.guild_permissions.manage_messages` (sunucu-geneli izin)
  kontrol ediyordu -- kanal-özel izin override'larını görmezden geliyordu.
  Düzeltme: `message.channel.permissions_for(author).manage_messages`.

### Extras -- warn.py'de eşzamanlı uyarılar auto-timeout'u iki kere ateşleyebiliyordu

`extras.warn`'ın `auto_timeout_after` mantığı, escalation engine ile
BİREBİR aynı add-then-count yarışına sahipti: aynı üye için eşzamanlı iki
`/warn` çağrısı, ikisi de aynı post-add sayıyı okuyup threshold'u
ikisi de eşleştirip üyeyi iki kere timeout'a alabiliyordu. Aynı
per-(guild_id, user_id) `asyncio.Lock` deseniyle düzeltildi.

### Extensions -- scaffold.py'de path traversal + manifest adı uyuşmazlığı

- `create_extension()`'daki `dist` (gerçek `target_dir / dist` yazma yolu),
  ham girdiden sadece `_`/boşluk değiştirilerek üretiliyordu -- `..` ve
  `/` hiç sanitize edilmiyordu. `"../../../etc/whatever"` gibi bir isim
  `target_dir`'ı tamamen aşarak dosya yazdırıyordu (gerçekten çalıştırılıp
  doğrulandı: dosyalar `target_dir` dışına yazıldı); mutlak bir yol
  (`"/etc/whatever"`) ise `Path("a") / "/etc/x"`'in "a"yı tamamen atıp
  mutlak yola dönüşmesi yüzünden `target_dir`'ı komple yok sayıyordu.
  Düzeltme: yeni `_sanitize_dist()` -- `/`, `..`, alfasayısal olmayan her
  şeyi tire ile değiştiriyor; ayrıca sonuç yolun gerçekten `target_dir`
  içinde kaldığını doğrulayan bir savunma-derinliği kontrolü eklendi.
- Üretilen `__init__.py`'deki `ExtensionManifest(name=...)`, dokümante
  edilen "importable-style, ExtensionRegistry.get(name)'in anahtarı"
  sözleşmesine rağmen ham, sanitize edilmemiş girdiyi kullanıyordu (paket
  kendi import edilebilir adıyla uyuşmuyordu). Düzeltme: artık `pkg`
  (sanitize edilmiş slug) kullanılıyor.

### Doğrulama

`ruff check discord_webapi tests examples`, `mypy discord_webapi` (122
dosya), `python -m pytest` (yerel Redis ile) -- hepsi temiz: 752 test
geçti, 7 skip (opsiyonel bağımlılıklar), yalnızca gerçek bir Postgres
sunucusu gerektiren 1 test bu ortamda deselect edildi (ana koddaki
değişiklikle ilgisiz, temiz checkout'ta da aynı şekilde başarısız
oluyor -- doğrulandı).

## [Unreleased] — `PageGuard`: Cloudflare deseni artık TEK bir link için değil, HERHANGİ bir sayfa için de kullanılabiliyor

Kullanıcının isteği (özet): "cloudflare gibi tam kapasite geniş bir
altyapı verelim -- her sayfaya ya da gerekli görülen sayfalara otomatik
IP itibarı + tarayıcı dil bilgisi kontrolü, kullanıcı görmez bile;
kötüyse direkt captchaya yollar, geçince belli süre kaydeder; cihazın IP
değişme sıklığı -- bir IP'den bağlandı sonra başkasından bağlanırsa
hemen captcha; Discord yetkilendirmesinden önce de captcha ekleme olsun;
hepsi isteğe bağlı, biz sunuyoruz, isterse kullanır isterse kendi
mekanizmasını kullanır."

Bu, `AdaptiveCaptchaGate`'in (önceki tur) TEK bir doğrulama linkini
koruma yeteneğini, HERHANGİ bir route'u koruyabilen genel bir katmana
genişletiyor -- gerçek "Cloudflare'ın önündeki gibi" altyapı isteğinin
karşılığı, hâlâ tamamen opt-in.

### `discord_webapi/captcha/adaptive.py` -- `TrustStore` artık IP-bağlama destekliyor

- `TrustStore.is_trusted(user_id, *, ip=None)` / `trust(user_id, *, ttl,
  ip=None)` -- yeni, opsiyonel `ip` parametresi. `trust(..., ip=X)`
  hangi IP'nin güveni kazandığını kaydediyor; `is_trusted(..., ip=Y)`
  (SADECE çağıran `bind_trust_to_ip=True` ile bunu isterse) kayıtlı IP'nin
  hâlâ eşleşmesini şart koşuyor. `ip=None` (varsayılan) eski davranışı
  KORUYOR -- güven hesabı her yerden takip ediyor, geriye tam uyumlu.
- `MemoryTrustStore`/`SQLTrustStore` (yeni `bound_ip` kolonu) güncellendi.
- `AdaptiveCaptchaGate`'e yeni `bind_trust_to_ip: bool = False` parametresi
  ve yeni public `is_currently_trusted(user_id, *, client_ip=None)` metodu
  eklendi (bir token mint etmeden "bu ziyaretçi şu an güvenilir mi"
  sorusunu cevaplıyor -- `PageGuard`'ın ihtiyaç duyduğu şey).
- Doğrudan doğrulandı: `bind_trust_to_ip=True` ile bir hesap/ziyaretçi
  IP A'dan doğrulanınca, IP B'den gelen AYNI hesap/ziyaretçi tekrar
  captcha ile karşılaşıyor; `bind_trust_to_ip=False` (varsayılan) ile
  eski davranış (güven her IP'den geçerli) korunuyor.

### `discord_webapi/captcha/pageguard.py` (yeni dosya)

- **`PageGuard`**: `AdaptiveCaptchaGate`'in önüne konan, HERHANGİ bir
  FastAPI route'unu koruyan sınıf. Her istekte: (1) ziyaretçi kimliği
  çözülüyor -- giriş yapılmışsa gerçek Discord `user_id`'si, yapılmamışsa
  rastgele, httpOnly bir çerezdeki değer (ilk ziyarette basılıyor) --
  Discord OAuth'tan ÖNCE de çalışabilmesinin sebebi bu; (2) zaten
  güvenilirse (ve `bind_trust_to_ip=True` ise hâlâ aynı IP'den
  geliyorsa) sayfa hiçbir şey göstermeden yükleniyor; (3) değilse IP
  itibarı + (varsa) `extra_suspicious` (opsiyonel ek sinyal) kontrol
  ediliyor -- temizse sessizce geç, şüpheliyse taze bir doğrulama
  linkine yönlendir.
- **`PageGuardRedirect`**: `require_human()`'ın fırlattığı düz bir
  exception -- FastAPI'nin `@app.exception_handler(...)` ile
  yakalanıyor, `RedirectResponse` + (varsa) yeni ziyaretçi çerezini
  taşıyor. Bilinçli tasarım kararı (gerçek bir FastAPI tuzağından
  kaçınmak için): enjekte edilen bir `Response` parametresine cookie
  yazıp endpoint kendi `HTMLResponse`'unu dönerse, FastAPI o cookie'yi
  SESSİZCE YOK SAYAR -- bu yüzden `require_human()` cookie'yi enjekte
  edilen bir nesneye yazmak yerine, çağıranın kendi döndürdüğü response'a
  uygulaması için `str | None` olarak geri döndürüyor (dokümante edildi).
- **`missing_accept_language(request)`**: opsiyonel `extra_suspicious`
  fonksiyonu -- gerçek tarayıcılar neredeyse her zaman bir
  `Accept-Language` başlığı gönderir, eksikliği ("tarayıcı dil bilgisi"
  isteğinin karşılığı) zayıf ama dürüst, sunucu-taraflı, JS gerektirmeyen
  bir sinyal. Diğer her sezgisel gibi tek başına değil, IP itibarıyla
  BİRLİKTE kullanılıyor.
- **`_pseudo_user_id(raw)`**: anonim çerez değerini, gerçek Discord
  snowflake'leriyle çakışması astronomik olarak imkansız, kararlı bir
  64-bit tamsayıya çeviriyor -- `VerificationRequest.user_id: int`
  modelini `int | str`'ye gevşetmeden (kütüphanenin geri kalanını
  etkilemeyen, izole bir çözüm) anonim ziyaretçilerin
  `AdaptiveCaptchaGate`/`TrustStore` ile çalışmasını sağlıyor.

### `examples/captcha_gate_bot`: Test 5 (`/test-full-guard`) ve Test 6 (`/test-secure-login`)

- `/test-full-guard`: `PathTraceProvider` + `_behavior_checks()` +
  `bind_trust_to_ip=True` ile yapılandırılmış bir `AdaptiveCaptchaGate`
  önünde `PageGuard`. IP'n temiz ve `Accept-Language` başlığın varsa hiç
  captcha görmüyorsun; kara listeye eklenince (aynı paylaşılan
  `blocklist`) çizgi-takip captcha'sına yönlendiriliyorsun, çözünce
  otomatik geldiğin sayfaya dönüyorsun.
- `/test-secure-login`: aynı guard, ama "Discord ile giriş yap"
  linkinin KENDİSİNDEN önce çalışıyor -- zaten giriş yapmışsan çıkış
  yap butonu var (`/auth/discord/logout`'a `fetch(..., {method:"POST"})`
  ile, çünkü o endpoint POST-only).

### Doğrulama

`TestClient` ile (`client=(ip, port)` farklı IP'leri simüle ederek):
temiz IP sessizce 200 dönüyor, ziyaretçi çerezi sadece ilk seferde
basılıyor; IP kara listeye eklenince gerçek bir çizgi-takip captcha'sına
yönlendiriliyor (307); GERÇEK bir geometrik+kinematik olarak sadık iz
çözülünce aynı ziyaretçi+IP bir daha sessizce geçiyor; FARKLI bir
ziyaretçi çerezi aynı (hâlâ kara listede) IP'den yine yönlendiriliyor;
AYNI ziyaretçi çerezi FARKLI (o da kara listede) bir IP'den bağlanınca
yine yönlendiriliyor -- `bind_trust_to_ip`'in gerçekten IP değişiminde
yeniden kontrol zorladığını kanıtlıyor. `/test-secure-login`: temiz IP
"Discord ile giriş yap" linkini hemen gösteriyor, kara listeli IP o link
render edilmeden ÖNCE captcha'ya yönlendiriliyor. `ruff`/`mypy` temiz,
`pytest` 716 passed (bilinen Postgres testi hariç, +10 yeni test).

## [Unreleased] — Path-Trace: hız/zamanlama kinematiği eklendi -- aşırı kusursuz (bot-gibi) bir iz artık daha sıkı toleransla test ediliyor

Kullanıcının önceki turdaki canvas-ölçek düzeltmesinin ardından gelen
isteği (özet): "birebir aynı çizmek önemli değil, hafif sapmalar sorun
değil, ama aşırı kusursuz takip -- milisaniye/saliyelik bile ardışık hız
değişmeyen, aynı ritimde, aynı pürüzsüzlükte bir iz -- şüpheli olmalı.
Eğer sistem bunu güvenilmez bulursa, ikinci kez daha ince bir toleransla
(daha ince çizgiyle) test etsin." Haklı bir gözlem -- mevcut Path-Trace
kontrolü SADECE geometriye (çizgiye yakınlık, köşe kapsaması) bakıyordu,
izin NASIL çizildiğine (insan eli mi, script mi) hiç bakmıyordu.
`captcha/scoring.py`'nin tıklama-öncesi fare hareketi için zaten yaptığı
"minimum-jerk insan hareketi vs. sabit-hızlı bot" ayrımını buraya da
uyguladık.

### `discord_webapi/captcha/widget.js`

- `toCanvasPoint(e)` artık her örneğe `performance.now()` zaman damgası
  ekliyor (`[x, y, t_ms]`) -- `scoring.py`'nin `mouse_trajectory`'siyle
  aynı format. Eski istemciler (zaman damgası göndermeyenler) sadece
  kinematik kontrolü atlıyor, geometrik kontrol aynı şekilde çalışıyor.

### `discord_webapi/captcha/providers/path_trace.py`

- Yeni `_looks_suspiciously_uniform(trace)`: segment hızlarının ve
  örnekler-arası zaman aralıklarının varyasyon katsayısını (coefficient
  of variation) hesaplıyor; İKİSİ DE aşırı düşükse (< 0.05) "şüpheli
  derecede düzgün" sayıyor -- yeterli zaman damgalı örnek yoksa (eski
  istemci, çok az nokta) `False` dönüp cezalandırmıyor (scoring.py'nin
  "eksik veri varsa cezalandırma, çekimser kal" ilkesiyle aynı).
- `verify()`: şüpheli bulunursa DOĞRUDAN reddetmiyor -- kullanıcının
  istediği tam olarak buydu -- bunun yerine (a)/(b) geometrik
  kontrollerini `tolerance / 2` ile TEKRAR çalıştırıyor. Gerçekten çok
  düzgün AMA aynı zamanda o kadar hassas bir el (stylus, çok kararlı bir
  fare kullanıcısı, yardımcı bir cihaz) yine geçiyor; sabit hız/zamanlamayı
  tutturmuş ama çizginin kendisinde piksel-hassas olmayan bir script
  burada yakalanıyor.
- Dürüstlük notu (docstring'e eklendi): bu da `scoring.py`'deki gibi
  yumuşak bir sezgisel -- gerçek bir insan izinin kaydedilip birebir
  tekrar oynatılmasını (aynı zaman damgalarıyla) yakalayamaz, o bir
  "replay" saldırısı ve bu modülün en üstteki docstring'i bunu zaten
  dürüstçe kabul ediyor.

### Doğrulama

4 yeni test: (1) geometrik olarak tam toleransın içinde ama yarısının
dışında, SABİT hız+zamanlamayla üretilmiş bir iz REDDEDİLİYOR; (2) aynı
geometrik sapmaya sahip ama DOĞAL (düzensiz) zamanlamalı bir iz KABUL
EDİLİYOR (aynı sapma, sadece kinematik şüpheli değilse tolerans
sıkılaştırılmıyor); (3) sabit hız+zamanlama AMA çizginin üzerinde tam
hassas bir iz yine KABUL EDİLİYOR (kusursuzluk tek başına reddetmiyor,
sadece daha hassas olmayı gerektiriyor); (4) yetersiz zaman damgalı
örnekte kinematik kontrol çekimser kalıyor. Ayrıca gerçek headless
Chromium (Playwright) ile GERÇEK bir fare sürüklemesi (kendi doğal
zamanlama/jitter'ıyla, sentetik değil) normal şekilde geçtiğini
doğruladım -- yeni kontrol gerçek insan kullanımını etkilemiyor.
`ruff`/`mypy` temiz, `pytest` 706 passed (bilinen Postgres testi hariç).

## [Unreleased] — Path-Trace: canvas'ın görsel boyutu native çözünürlüğünden farklıysa çizim yanlış koordinatta kaydediliyordu (gerçek bug)

Kullanıcı sıralı test planının 3. adımında bildirdi: normal şekilde,
eğriyi gerçekten takip ederek çizdiği halde çizgi-takip captcha'sı
reddediliyordu ("normal şekilde yapıyorum yine reddediliyor"), ve
"çizdiğim çizgiyi düzleştirme yapıyor heralde" diye şüphelendi. Bu
gerçek ve ciddi bir bug'dı.

### Kök neden

`widget.js`'in `renderPathTraceChallenge`'ı, fare/dokunma noktalarını
`canvas.getBoundingClientRect()`'ten (canvas'ın CSS'te GÖRÜNDÜĞÜ boyut)
alıp doğrudan, hiçbir ölçek düzeltmesi yapmadan, çizginin sunucudan
gelen native koordinat uzayıyla (canvas'ın `width`/`height` HTML
attribute'ları -- 320x160) karşılaştırıyordu. Bu ikisi HER ZAMAN eşit
değil: `.dwa-captcha-widget{max-width:300px}` zaten canvas'ın native
320px'inden dar; host sayfanın kendi CSS'i (bir `canvas{max-width:100%}`
tarzı reset, dar bir konteyner, tarayıcı zoom'u, ...) bunu daha da
küçültebilir/büyütebilir. Sonuç: kullanıcının GÖRDÜĞÜ (küçültülmüş)
çizgiyi tam olarak takip etmesi bile, kaydedilen noktaların yanlış
ölçekte olması yüzünden sunucu tarafında sistematik bir kaymaya/
"düzleşmeye" yol açıyor, tolerans kontrolünü (24px) rastgele
başarısız kılabiliyordu.

### Düzeltme

`renderPathTraceChallenge`'a `toCanvasPoint(e)` yardımcı fonksiyonu
eklendi: `canvas.width / rect.width` ve `canvas.height / rect.height`
oranlarıyla her fare/dokunma noktasını canvas'ın NATIVE çizim
koordinat uzayına çeviriyor, `pointerdown`/`pointermove` bu fonksiyonu
kullanıyor. Ölçekleme yoksa (`rect.width === canvas.width`) oran 1'dir,
davranış değişmez -- sadece host sayfanın canvas'ı küçültüp/büyüttüğü
durumlarda fark yaratır.

### Doğrulama -- gerçek tarayıcı, kök nedeni ayırt edecek şekilde

Gerçek headless Chromium (Playwright) ile: canvas'ı host sayfa CSS'i
gibi kasıtlı olarak 320x160 native'den 222x112 CSS boyutuna küçülttüm,
gerçek bir fareyle GÖRÜNEN (küçültülmüş) eğrinin üzerinden sadakatle
geçtim (ekran koordinatlarını gerçek CSS-ölçekli canvas kutusuna göre
hesaplayarak, gerçek bir kullanıcının yapacağı gibi). **Eski kodla aynı
senaryo REDDEDİLDİ** ("the captcha answer was wrong") -- bu, kullanıcının
bildirdiği bug'ı birebir yeniden üretti. **Yeni kodla aynı senaryo
KABUL EDİLDİ** ("Doğrulandı"). Bu, kök nedenin gerçekten bu ölçek
uyuşmazlığı olduğunu ve düzeltmenin gerçekten çalıştığını kanıtlıyor.

## [Unreleased] — /appeal doğrulaması da artık DM ile onaylıyor (aynı sınıftan bir bug daha)

Kullanıcı sıralı test planını takip ederken bildirdi: `/simulate-ban`'ı
3 kez çalıştırıp `/appeal` denedi, gerçek bir doğrulama linki geldi,
web'de widget'ı çözdü ("Doğrulandı" gördü) ama Discord tarafında
**hiçbir onay/DM gelmedi** -- geri dönüp `/appeal`'i tekrar çalıştırınca
bu sefer doğrulama istemeden "kaydedildi" dedi (ki BU KISIM doğru
davranış -- bir kez doğrulanan kullanıcı bu demo boyunca muaf).

Kök neden: `_on_appeal_verified` handler'ı `_appeal_verified_users`
setine ekliyordu ama Scenario 4'te (`/giveaway-test`) daha önce
düzeltilen AYNI bug -- hiçbir kullanıcıya-görünür geri bildirim yoktu.
`giveaway_test`'in DM-onayı deseni buraya da uygulandı: doğrulama
başarılı olunca artık "Doğrulandın! Artık `/appeal` komutunu tekrar
çalıştırıp itirazını gönderebilirsin." DM'i gidiyor (bu demo orijinal
`reason`'ı doğrulama round-trip'i boyunca hatırlamadığından itirazı
otomatik yeniden göndermiyor, kullanıcının `/appeal`'i tekrar
çalıştırması gerekiyor -- gerçek bir bot bunu kuyruğa alıp otomatik
tekrar gönderebilir).

Doğrudan doğrulandı: gerçek bir Proof-of-Work çözülüp (`_solve_pow`
yardımcı fonksiyonuyla, sahte bir cevap değil) `appeal_gate.verify()`
çağrıldı, `bot.fetch_user`/`user.send` mock'lanarak DM'in gerçekten
gönderildiği ve doğru içeriği taşıdığı kanıtlandı.

## [Unreleased] — 4 gerçek bug daha: login zorunlu gate'lerde captcha login öncesi gösterilmiyor, giveaway-test artık DM ile onaylıyor, /test-join yeniden adlandırıldı

Kullanıcının fiziksel test geri bildirimi, tek tek incelenip ayrıştırıldı:

1. **Gerçek bug: `require_account=True` olan gate'lerde widget, giriş
   yapılmadan da gösteriliyordu.** `/verify/giveaway`, `/verify/appeal`,
   `/verify/adaptive` sayfaları giriş yapılmasa bile hem login linkini
   HEM widget'ı aynı anda gösteriyordu -- `AccountMatchCheck` sadece
   `verify()` anında devreye giriyordu. Yani giriş yapmadan bir Math
   captcha'yı çözmek veya gerçek bir Proof-of-Work'ü beklemek mümkündü,
   sadece sonunda "account" kontrolünde başarısız oluyordu -- kullanıcının
   "giriş yapmama gerek olmadan captcha oldu" şikayeti buydu. Düzeltme:
   `_verify_page` artık `gate.require_account and user is None` ise
   widget'ı HİÇ render etmiyor, sadece "önce giriş yap" sayfası
   gösteriyor -- `/giveaway-test/verify`'nin zaten yaptığı gibi.
   Doğrudan doğrulandı: giriş yapılmadan `/verify/adaptive/{token}`
   artık widget içermiyor; doğru hesapla girişte widget görünüyor.
2. **Gerçek bug: `/giveaway-test`'te captcha çözülünce hiçbir onay
   gelmiyordu.** `_on_giveaway_test_joined` handler'ı sadece bellekteki
   katılımcı listesine ekliyordu, kullanıcıya hiçbir geri bildirim
   (DM) yoktu -- kullanıcının "2sinde de bir şey olmuyor ama
   `/giveaway-test-participants`'ta listelenmişim" şikayeti tam olarak
   buydu (mekanizma çalışıyordu, geri bildirim yoktu). Scenario 1'in
   `_on_giveaway_verified`'ıyla aynı desende artık "Katıldın! **{title}**
   için doğrulaman başarıyla tamamlandı." DM'i gönderiliyor (yalnızca
   ilk başarılı doğrulamada, idempotent ikinci `verify()` çağrısında
   tekrar göndermiyor). Doğrudan doğrulandı: `bot.fetch_user`/`user.send`
   mock'lanarak, doğrulama sonrası DM'in gerçekten gönderildiği ve
   içeriğinin doğru olduğu kanıtlandı.
3. **Netleştirme (bug değil, isimlendirme sorunu): `/test-join`.**
   Kullanıcı ısrarla "katıldım ama otomatik katılma mesajı gelmedi"
   diye bildirdi -- ama Scenario 3 zaten TASARIM GEREĞİ gerçek bir
   katılım akışı değil, üç captcha türünü yan yana karşılaştırma
   demosu (giriş istemiyor, onay mesajı yok). Sorun kodda değil,
   "Katıl" butonunun/`test-join` komut adının yanlış beklenti
   yaratmasıydı. Komut `/test-compare-captchas`'a, buton "Karşılaştır"a
   yeniden adlandırıldı, ephemeral cevaba "bu gerçek bir katılım değil"
   notu eklendi -- gerçek giriş-zorunlu + otomatik-katıl akışına
   (`/giveaway-test`) açıkça yönlendiriyor.
4. **Netleştirme (bug değil, kasıtlı tasarım): `/join`'in
   `giveaway_name`'i serbest metin.** Kullanıcı "rastgele isim yazsam da
   kabul etti" diye sordu -- bu demo'da gerçek bir çekiliş
   kataloğu/kaydı yok, `giveaway_name` sadece DM mesajında göstermek
   için taşınan metadata; herhangi bir string kabul etmesi kasıtlı,
   eksik bir doğrulama değil. Kodda açıklayıcı bir yorum eklendi.

### Doğrulama

`TestClient` ile (canlı Discord gerekmeden): giriş yapılmadan
`/verify/adaptive/{token}` widget içermiyor, "önce giriş yap" sayfası
dönüyor; doğru hesapla girişte widget görünüyor. `giveaway_test_
original_gate.verify()` doğrudan çağrılıp `bot.fetch_user`/`user.send`
mock'lanarak DM'in gerçekten gönderildiği ve doğru başlığı içerdiği
kanıtlandı. `ruff`/`mypy` temiz, `pytest` 702 passed (bilinen
Postgres-ortam testi hariç).

## [Unreleased] — verify sayfaları: giriş yapılmışsa kullanıcı adı gösteriliyor, yanlış hesabın linki erken engelleniyor

Kullanıcı isteği: "yetkilendirme yapıldıysa orada kullanıcı ismi gözüksün
ve token kontrolü vesaireler yapılsın, başka hesabın linkini
doğrulamaya çalışmasın." `AccountMatchCheck` zaten yanlış hesabı
*doğrulama anında* reddediyordu (`checks.py`) -- ama bu, kullanıcının
bunu ancak captcha'yı çözmeye çalıştıktan SONRA öğrenmesi demekti,
kafa karıştırıcı ve captcha'nın kendisi bozukmuş gibi görünebiliyordu.

### `examples/captcha_gate_bot/main.py`

- Yeni `_expected_user_id(gate, token)` yardımcı fonksiyonu: token'ın
  hangi kullanıcı için oluşturulduğunu `gate.store.get(token)` üzerinden
  okuyor (hem `CaptchaGate` hem `AdaptiveCaptchaGate` için çalışıyor,
  ikisi de `.store` attribute'una sahip).
- Yeni `_wrong_account_page(signed_in_as)`: "Bu link sana ait değil"
  mesajı + çıkış yap linki -- captcha hiç gösterilmiyor.
- `_verify_page` artık `user: DiscordUser | None` parametresi alıyor:
  giriş yapılmışsa önce token sahipliğini kontrol ediyor (uyuşmazsa
  `_wrong_account_page`, hiçbir widget render edilmiyor), uyuşuyorsa
  "Giriş yaptın: **username**" gösterip widget'ı render ediyor; giriş
  yapılmamışsa eskisi gibi login linki gösteriyor. `/verify/giveaway`,
  `/verify/appeal`, `/verify/adaptive` route'ları artık
  `get_current_user_optional` dependency'sini `_verify_page`'e
  geçiriyor.
- `giveaway_test_verify_page` (`/giveaway-test/verify`) zaten kullanıcı
  adını gösteriyordu ama sahiplik kontrolü yapmıyordu -- aynı
  `_expected_user_id` kontrolü eklendi (üç token da aynı buton
  tıklamasında aynı kullanıcı için basıldığından tek bir token'ı
  kontrol etmek yeterli).

### Doğrulama

`TestClient` ile auth dependency override kullanılarak (canlı Discord
gerekmeden) üç durum da doğrudan test edildi: giriş yapılmamış ->
login linki var, widget yok; yanlış hesapla giriş yapılmış -> "Bu link
sana ait değil" sayfası, widget YOK; doğru hesapla giriş yapılmış ->
kullanıcı adı gösteriliyor, widget VAR. `ruff`/`mypy` temiz, `pytest`
702 passed (bilinen Postgres-ortam testi hariç).

## [Unreleased] — sayfa yenilemede doğrulanmış link artık "geçersiz/süresi dolmuş" görünmüyor (gerçek bug)

Kullanıcının bir önceki turdaki widget düzeltmesini test ederken bildirdiği
yeni bir sorun: bir captcha çözüp doğrulandıktan sonra sayfayı
yenileyince (F5) widget "Doğrulama linki geçersiz veya süresi dolmuş"
diye hata gösteriyordu -- oysa link aslında BAŞARIYLA doğrulanmıştı.

### Kök neden

`CaptchaGate.get_info()` (ve `AdaptiveCaptchaGate.get_info()`) "token
bulunamadı/süresi dolmuş" ile "token zaten doğrulandı" durumlarını AYNI
şekilde ele alıyordu -- ikisi de `None` dönüyordu, bu da API katmanında
404'e, widget'ta da "geçersiz veya süresi dolmuş" hatasına dönüşüyordu.
Yani widget'ın kendisi (bir önceki turda düzeltilen "tekrar sorma"
sorunu) artık doğru davransa bile, SAYFA YENİLEME senaryosunda
`loadInfo()` her seferinde sunucudan bilgi çekiyor ve sunucu "zaten
doğrulandı" ile "hiç var olmadı"yı ayırt edemediği için yanlış mesaj
gösteriyordu.

### Düzeltme

- `GateInfo` modeline (`captcha/api.py`) yeni bir `verified: bool = False`
  alanı eklendi.
- `CaptchaGate.get_info()` ve `AdaptiveCaptchaGate.get_info()` artık
  `request is None` (gerçekten yok/süresi dolmuş) ile `request.verified`
  (zaten doğrulanmış) durumlarını AYRI ele alıyor -- sadece ilki `None`
  dönüyor, ikincisi `{"verified": True, "challenge": None, ...}` gibi bir
  bilgi nesnesi dönüyor.
- `widget.js`'e yeni bir `showAlreadyVerified()` metodu eklendi:
  `loadInfo()` artık `info.verified === true` durumunda kutuyu kalıcı
  olarak "Zaten doğrulandı" + yeşil tik göstererek dondurur (bir önceki
  turdaki "başarıda donma" davranışıyla tutarlı), "geçersiz/süresi
  dolmuş" hatasına düşmez.

### Doğrulama

Gerçek headless Chromium (Playwright) ile: bir Math captcha çözüldü,
4 saniye beklendi (hâlâ "Doğrulandı"), **sonra sayfa gerçekten
yenilendi** (`page.reload()`) -- widget "Zaten doğrulandı" gösterdi,
"geçersiz" veya "süresi dolmuş" YAZMADI. Ayrıca `tests/unit/
test_captcha_gate.py::test_get_info_distinguishes_already_verified_
from_gone` ve `test_captcha_adaptive.py`'deki eşdeğeri eklendi.
Mevcut bir entegrasyon testi (`test_gate_verify_solves_the_giveaway_
scenario`) eski, yanlış davranışı (`404` bekliyordu) doğruluyordu --
yeni, doğru beklentiye (`200` + `verified: true`) güncellendi.

## [Unreleased] — widget: başarıdan sonra kendini sıfırlayıp tekrar captcha sormuyor artık (gerçek bug)

Kullanıcı fiziksel testte net bir bug bildirdi: bir captcha'yı çözüp
"Doğrulandı" gördükten ~1 saniye sonra widget kendini sıfırlayıp tekrar
captcha soruyordu -- "başarılı olan yer artık başarılı görünsün, tekrar
tekrar captcha çözmeyelim, potansiyel saldırı açığı." Haklı.

### `discord_webapi/captcha/widget.js`

- **Kök neden**: `runVerification`'ın sonundaki `setTimeout(..., 2500)`
  widget'ı başarı/başarısızlık AYRIMI yapmadan her durumda "tekrar dene"
  durumuna sıfırlıyordu. Yani doğrulanmış bir token için bile kutu 2.5
  saniye sonra yeniden "İnsan olduğumu doğrula"ya dönüyor, kullanıcı aynı
  captcha'yı tekrar tekrar çözebiliyordu.
- **Düzeltme**: başarıda widget artık kalıcı olarak "Doğrulandı"
  durumunda donuyor (yeşil tik kalıyor, challenge paneli -- math görseli /
  çizim canvas'ı / 3. taraf -- kapatılıyor ki harcanmış submit butonu
  tekrar tıklanamasın, `busy`/`verified` kalıcı olarak true, kutu
  tıklanamaz). YALNIZCA başarısızlıkta eskisi gibi 2.5s sonra yeniden
  deneme sunuluyor (yanlış math cevabı, özensiz çizim gibi gerçek
  retry'lar hâlâ mümkün).
- **Güvenlik notu**: sunucu tarafı zaten güvenliydi -- doğrulanmış token
  tek-kullanımlık, `CaptchaGate.verify` ikinci çağrıda kontrolleri
  tekrar çalıştırmadan idempotent başarı döndürüyor ve `on_verified`
  yalnızca İLK doğrulamada yayınlanıyor (çift katılım/çift sayım yok).
  Yani gerçek bir güvenlik açığı değildi; ama kullanıcının içgüdüsü doğru
  -- bir captcha'yı sonsuz kez "çöz" diye sunmak kötü bir desen, düzeltildi.
- **Doğrulama**: gerçek headless Chromium (Playwright) ile uçtan uca
  sürüldü -- Math captcha doğru cevaplanınca kutu "Doğrulandı"da kalıyor
  ve 4 saniye sonra (eski 2.5s sıfırlama penceresinin ötesinde) hâlâ
  yeşil/doğrulanmış, panel kapalı; yanlış cevaplanınca "Doğrulanamadı"
  gösterip 3 saniye sonra "Tekrar deneyin"e dönerek retry'a izin veriyor.
  Bu, bundled widget'ı kullanan TÜM akışları (giveaway/appeal/test/
  adaptive) birden düzeltiyor.

## [Unreleased] — fiziksel test geri bildirimi: 4 gerçek bug/tasarım hatası düzeltildi

Kullanıcı önceki turdaki 5 test sayfasını gerçekten deneyip dört somut
sorun bildirdi -- hepsi araştırılıp gerçek bulunanlar düzeltildi:

1. **"Test 1'de sadece tıklamaya bakmak yanlış"** -- haklı: Test 1
   `require_captcha=False` ile SADECE davranış skorunu (`SignalScoreCheck`)
   tek başına gate olarak kullanıyordu. Bu tam olarak `scoring.py`'nin
   kendi docstring'inin uyardığı hata -- istemci sinyalleri "speed bump",
   tek başına insan/robot hükmü değil. Doğrudan doğrulandı: düzeltmeden
   önce elle uydurulmuş "iyi görünen" sinyaller (gerçekçi eğri/hız/zaman
   varyansına sahip sahte bir fare izi) `require_captcha=False` gate'ini
   TEK BAŞINA geçiyordu -- kullanıcının sorduğu tam olarak buydu.
   Düzeltme: Test 1 artık her yerdeki diğer "görünmez" gate'ler gibi
   gerçek Proof-of-Work + davranış skorunu birlikte istiyor
   (`require_captcha=False` yerine `ProofOfWorkProvider`). Aynı sahte
   "iyi" sinyaller artık PoW çözümü olmadan `"captcha"` kontrolünde
   reddediliyor -- doğrudan doğrulandı.
2. **"Çizgi çok düzleşiyor, olduğu gibi işlemeli"** -- gerçek bir
   doğrulama zafiyetiydi: `PathTraceProvider.verify()` sadece (a) her
   nokta polyline'a `tolerance` içinde mi ve (b) her köşeye yakın bir
   nokta var mı kontrol ediyordu -- eğrinin kendi kirişinden sapması
   (bulge) `tolerance`'tan küçük kaldığında bu ikisini, eğriyi hiç takip
   etmeden, dümdüz bir köşegen çizerek de geçmek mümkündü.
   **DÜZELTME İKİ AŞAMALI OLDU** (kullanıcının "emin olalım" demesi
   sayesinde ilk denemenin bozuk olduğu yakalandı): İlk deneme verify'a
   üçüncü bir "iz yeterince kavis yaptı mı" kontrolü ekledi -- ama bu ÖLÜ
   KOD çıktı: kontrol (b) geçtiğinde iz zaten matematiksel olarak
   `curve_bulge - tolerance` kadar kavis yapmış oluyor, yani üçüncü
   kontrol asla tetiklenemiyordu; ayrıca gerçek bug durumunda (bulge <=
   tolerance) dış `if curve_bulge > tolerance` koşulu false olduğu için
   tamamen atlanıyordu. Somut ölçüm: 2000 challenge'da düz kısayolların
   89'u HÂLÂ kabul ediliyordu. **Gerçek düzeltme üretim tarafında**:
   `_make_path` artık üretilen dalgayı, kendi start->end kirişinden en az
   `tolerance * 1.5` kadar sapana dek yeniden üretiyor (rastgele sinüs
   bazen 17px'e kadar düz kalabiliyordu, 24px tolerans için bug'ın
   kaynağı buydu). Bu garantiyle kontrol (b) düz kısayolu doğası gereği
   reddediyor (tepe köşeler kirişten `tolerance`'tan uzakta kalıyor), ve
   ölü üçüncü kontrol kaldırıldı. Somut doğrulama: 3000 challenge'da düz
   kısayol kabul sayısı **0** (öncesi 89/2000), min bulge tam 36.0px,
   tüm sadık izler kabul, hiçbir vertex 160px canvas dışına taşmıyor.
   İki yeni test: `test_path_trace_rejects_a_straight_shortcut_across_
   many_issues` (200 challenge boyunca hiçbir düz kısayol geçmiyor) ve
   `test_path_trace_issued_wave_always_bulges_past_tolerance` (üretim
   garantisi). Mevcut 6 path-trace testi değişmeden yeşil.
3. **"/giveaway-test'te butona tıklayınca 'etkileşim başarısız oldu'"** --
   büyük olasılıkla kök neden: buton callback'i Discord'un ~3 saniyelik
   etkileşim yanıt penceresi içinde `interaction.response.send_message()`
   çağırmadan ÖNCE üç ayrı `create_verification()` çağrısını bekliyordu;
   herhangi bir gecikme/hata bu pencereyi kaçırıp "etkileşim başarısız
   oldu"ya sebep olabilirdi. Düzeltme: artık en başta
   `interaction.response.defer(ephemeral=True, thinking=True)` çağrılıyor
   (yanıt penceresi hemen kapatılıyor), asıl iş bittikten sonra
   `interaction.followup.send()` ile gerçek cevap gönderiliyor; DM
   gönderimi de artık `discord.Forbidden`'a karşı korunuyor (DM'leri kapalı
   bir kullanıcıya sessizce patlamak yerine linki ephemeral cevapta da
   gösteriyor).
4. **"/test-cloudflare'de 2 kontrol yapmayalım, ilk tıklamaya kadar 1.
   kontrol, 2.si görsel captcha olsun, saçma/profesyonel değil"** --
   haklı: önceki turda eklenen "üçüncü, daha katı sessiz kontrol" gerçek
   bir savunma katmanı değildi -- bir botun zaten geçtiği sessiz kontrolü
   ikinci kez sessizce tekrar çalıştırmak hiçbir yeni bilgi vermiyordu,
   sadece gerçek bir kullanıcıya anlamsız bir ekstra adım ekliyordu.
   `test4_strict_gate` ve üçüncü Path-Trace katmanı tamamen kaldırıldı --
   `/test-cloudflare` artık `AdaptiveCaptchaGate`'in zaten kendi başına
   yaptığı iki katmanlı deseni (IP temizse sessizce geç, kara listedeyse
   tek bir gerçek Math captcha'sı göster) hiçbir sayfa-JS zincirlemesi
   olmadan doğrudan kullanıyor.

Kullanıcının ayrıca sorduğu iki nokta (test-join sayfasında "3 captcha
diyor ama 2 tane görünüyor" ve "captcha geçince otomatik katılsın,
kuyrukta bekleme süresi olsun, Discord girişi istesin") kod incelemesiyle
doğrulanamadı -- `/test-widgets` şablonu üç ayrı `<div class="dwa-
captcha-widget">` içeriyor ve her biri kendi token'ıyla bağımsız
render ediliyor; ve Scenario 3 (`/test-join`) bilinçli olarak "3 captcha
türünü yan yana karşılaştır" demosu olarak tasarlandı, gerçek bir
giveaway akışı değil (o zaten Scenario 4/`/giveaway-test`'te -- orada
gerçekten Discord girişi ZORUNLU ve captcha geçince gerçekten otomatik
katılıyor). Kullanıcıdan ekran görüntüsü/tam adım istenip netleştirilecek.

## [Unreleased] — `examples/captcha_gate_bot`: 5 test sayfası + gerçek giveaway katılımcı kaydı + kendi "Cloudflare"imiz

Kullanıcı isteği (özet, Türkçe): "5 farklı test sayfası ekle: (1) sadece
widget, insansa başarılı/robotsa çizgi captcha'sına yükselt, (2) aynı
akış ama sayfa kasıtlı sahte/kötü veri yollasın, tespitin gerçekten
reddettiğini kanıtlasın, (3) `/giveaway-test`'te captcha başarılı olunca
bot gerçekten katılımcı listesine eklesin, (4) IP'yi kara listeye
eklenince kendi Cloudflare'imiz gibi bir 'insan mısın' ekranı çıksın,
geçilse bile hâlâ şüpheliyse ikinci bir teste tabi tutulsun." Ayrıca
önceki turların notlarının eksiksiz güncellendiği doğrulandı.

### `examples/captcha_gate_bot/main.py`

- **Test 1 (`/test-instant-widget`)**: iki yeni gate --
  `test1_behavior_gate` (`require_captcha=False`, sadece davranış
  kontrolleri) ve `test1_pathtrace_gate` (Path-Trace). Hesap şartı yok
  (kasıtlı -- bu sayfa *tespiti* test ediyor, hesap-bağlamayı değil,
  onu zaten giveaway/appeal gate'leri kapsıyor). Widget'ın kendi
  `onWidgetVerified` callback'i üzerinden: başarısızsa ikinci bir
  Path-Trace widget'ı sayfaya JS ile ekleniyor -- yeni bir `CaptchaGate`
  özelliği değil, dosyanın her yerinde kullanılan "iki ayrı gate'i sayfa
  JS'iyle birleştir" deseni.
- **Test 2 (`/test-forced-bad-data`)**: Test 1'le AYNI iki gate'i
  kullanıyor, ama widget'ı hiç çağırmıyor -- sayfa doğrudan
  `fetch("/test1-behavior/api/captcha/gate/{token}/verify", ...)`'a elle
  uydurulmuş `{webdriver: true, pointer_moves: 0, interaction_ms: 1,
  mouse_trajectory: []}` gönderiyor. Amaç gerçek bir kullanıcıyı test
  etmek değil -- tespitin kozmetik olmadığını, her seferinde reddettiğini
  kanıtlamak (red-team tarzı regresyon testi). Doğrudan doğrulandı:
  cevap her zaman `verified: false, failed_check: "no-webdriver"`.
- **Test 3 (`/giveaway-test` katılımcı kaydı)**: önceki oturumda zaten
  eklenmişti (`giveaway_id`-anahtarlı `_giveaway_test_participants`,
  `_on_giveaway_test_joined` handler'ı, `/giveaway-test-participants`
  komutu) -- bu turda sadece README/docstring'e eklendiğinden emin
  olundu, kod değişmedi.
- **Test 4 (`/test-cloudflare`)**: `/join-adaptive` ile AYNI paylaşılan
  `blocklist` nesnesini (ve `/api/test/block-my-ip`/`unblock-my-ip`
  debug endpoint'lerini) kullanan ama girişte hesap istemeyen İKİNCİ bir
  `AdaptiveCaptchaGate` (`test4_adaptive_gate`) -- gerçek bir Cloudflare
  tarzı ekran anonim trafiğin önünde çalışır, hesaba bağlı olamaz. Bunu
  geçmek tek başına yetmiyor: ardından daha katı, sadece-davranış bir
  ikinci gate (`test4_strict_gate`) çalışıyor; o da şüpheliyse üçüncü ve
  son adım olarak bir Path-Trace gate'i (`test4_pathtrace_gate`)
  devreye giriyor -- gerçek bir çift-eskalasyon zinciri, tek bir gate
  değil. Doğrudan doğrulandı: `/api/test/block-my-ip` çağrısı
  `/test-cloudflare`'in ilk widget'ının gerçekten bir Math challenge
  istemesine sebep oluyor, `/join-adaptive` için olduğu gibi.
- **Test 5 (`/test-index`)**: yukarıdaki dördünü (ve Discord komutlarını)
  tek bir linkler sayfasında toplayan, kullanıcının "veya uygun
  gördüğün şekilde" notuyla eklenen bir hub sayfası.

### Doğrulama

`TestClient` ile (canlı Discord bağlantısı gerekmeden, hiçbiri login
istemediği için): Test 1/2'nin sahte-kötü sinyalleri her zaman
`no-webdriver` ile reddettiği; Test 4'te `block-my-ip`'in gerçekten
adaptive gate'in `requires_captcha`'sını `true`'ya çevirdiği; Test 5'in
tüm linkleri içerdiği -- doğrudan çağrılarak kanıtlandı. `ruff check`
temiz, `mypy discord_webapi` 121 dosyada temiz, `pytest` 698 passed / 7
skipped (bilinen Postgres-ortam testi hariç).

## [Unreleased] — captcha: `AdaptiveCaptchaGate` -- IP itibarına göre otomatik escalation (Cloudflare "Under Attack Mode" deseni)

Kullanıcının önceki turdaki IP itibarı hook'unu bir adım ileri taşıma
isteği: "IP itibarı kötüyse direkt captcha testi otomatik tetiklensin,
temizse sorulmasın, geçince bir süre tekrar sorulmasın; ayrı, isteğe bağlı
bir modül olsun." Onay alındıktan sonra inşa edildi.

### Eklenen: `discord_webapi/captcha/adaptive.py` + `reputation.py`

- **`IPReputationChecker` Protocol** (`captcha/reputation.py`): "bu IP
  şüpheli mi" sorusunun cevabı -- kütüphane kendi itibar veritabanını
  SUNMUYOR (hangi kaynağa güveneceğine dair görüşü yok), sadece arayüzü
  veriyor. `StaticBlocklistReputationChecker`: tek somut implementasyon,
  bilinçli olarak dürüst isimlendirildi -- düz bir IP/CIDR blocklist'i,
  bir reputation *servisi* değil, öyle olduğunu iddia etmiyor.
- **`AdaptiveCaptchaGate`** (`captcha/adaptive.py`): `CaptchaGate`'e ayrı,
  yeni bir sınıf -- `require_captcha`'yı inşa anında sabitlemek yerine
  **dinamik olarak**, linkin ilk açıldığı anda (bağlanan IP belli
  olduğunda) karara bağlıyor. `CaptchaGate`'i büyütmek yerine yanına yeni
  bir parça koymayı tercih ettim -- statik davranışı zaten test edilmiş,
  kapsanmış bir sınıfa koşullu dallanma yığmaktansa. Akış: IP itibarı
  temizse hiç captcha yok (sadece `require_account`/`extra_checks`);
  şüpheliyse `escalation_provider`'dan gerçek bir challenge issue edilip
  zorunlu kılınıyor. Karar `decision_store`'da (yeni, ayrı bir store --
  `VerificationStore`'a hiç dokunulmadı) kalıcı tutuluyor, sayfa
  yenilemesi zarı yeniden atmıyor. `trust_store` (opsiyonel) -- geçen bir
  hesap `trust_ttl` boyunca bir daha hiç sorulmuyor (gerçek Discord
  hesabına bağlı, sahtelenebilir bir cihaz sinyaline değil).
- **Bundled widget'ta HİÇBİR değişiklik gerekmedi** -- widget zaten
  `get_info()`'nun döndürdüğü `requires_captcha`'ya göre kendi UI'sını
  seçiyor, adaptif olduğunu bilmiyor bile.
- **`build_captcha_router(gate=...)`** artık hem `CaptchaGate` hem
  `AdaptiveCaptchaGate` ile çalışıyor -- yeni bir `GateLike` Protocol
  (yapısal tip) ile, `adaptive.py`'ı zorunlu import etmeden (onu hiç
  kullanmayanlara bağımlılık yüklemesin diye).
- **SQL varyantları**: `SQLAdaptiveDecisionStore`, `SQLTrustStore` --
  diğer tüm store'larla aynı Protocol + Memory/SQL desende, kendi
  bağımsız tabloları.
- **`examples/captcha_gate_bot`'a `/join-adaptive`**: gerçek, çalışan bir
  demo. `GET /api/test/block-my-ip`/`unblock-my-ip` ile kendi IP'nizi
  bloke edip escalation'ı canlı izleyebiliyorsunuz -- kozmetik değil,
  gerçekten kontrol ediyor: doğruladım (`TestClient` ile, temiz IP'de
  `requires_captcha: false`, blokladıktan sonra `true` + gerçek Math
  challenge, unblock sonrası tekrar `false`).

25 yeni test: `test_captcha_adaptive.py` (yeni dosya -- karar bir kez
verilip kalıcı olması, temiz/şüpheli IP ayrımı, `require_account`/
`extra_checks`'in IP'den bağımsız hâlâ uygulanması, trust-store'un
tekrar sormaması ve TTL'in dolması, bilinmeyen token, idempotency,
`on_verified` filtresi, eksik IP'nin çekimser -- cezalandırmayan --
davranması), `test_captcha_reputation.py` (yeni dosya --
`StaticBlocklistReputationChecker`'ın IP/CIDR eşleşmesi, bozuk IP'de
hata vermemesi, block/unblock), SQL store testleri, ve gerçek HTTP
üzerinden uçtan uca bir entegrasyon testi (temiz/bloke IP'ler farklı
`TestClient(client=...)` ile simüle edilip gerçek captcha akışı
doğrulandı). Tüm suite yeşil (bilinen Postgres ortam hatası hariç),
ruff+mypy temiz (121 dosya).

## [Unreleased] — captcha: gerçek güvenlik araştırması + 2 ciddi bug bulunup düzeltildi + IP itibarı hook'u

Kullanıcının isteği: captcha alt sistemine kapsamlı bir araştırma yap
(internet + kod), hata olmaması gereken yerleri bul ve düzelt, ve "kendi
IP itibarı sistemimi eklemek istersem ekleyebilir miyim" sorusuna cevap
ver. İnternet araştırması (2025-2026 captcha/bot-tespiti güvenlik
literatürü) doğrudan kod incelemesine yön verdi ve iki gerçek, ciddi bug
buldu.

### Bulunan ve düzeltilen 2 gerçek bug

1. **`SQLCaptchaStore.increment_attempts` gerçek bir race condition
   içeriyordu (ciddi -- rate-limit bypass sınıfı)**. Araştırmada karşıma
   çıkan iyi belgelenmiş bir saldırı deseni: "captcha deneme sayacını
   yarışarak atlatmak" (bkz. kaynaklar). Eski kod SELECT-sonra-mutate-
   sonra-commit yapıyordu (ORM'in `row.attempts += 1; commit()`'i) --
   birden fazla eşzamanlı yanlış tahmin aynı çekilmemiş sayıyı okuyup
   birbirinin artışını kaybedebiliyordu. **Gerçekten test ettim**: eski
   kodu 20 eşzamanlı `increment_attempts` çağrısına karşı çalıştırdığımda
   nihai sayı 20 değil **1** çıktı -- 19 artış kayboldu. Yani pratikte bir
   saldırgan aynı challenge_id'ye onlarca eşzamanlı tahmin göndererek
   `max_attempts` sınırını fiilen etkisiz kılabilirdi. Düzeltme: tek,
   atomik bir `UPDATE ... SET attempts = attempts + 1` (MySQL'in
   `RETURNING` desteklememesi yüzünden ayrı bir read-back ile, ama artışın
   kendisi artık tek SQL adımı). `_shared.check_pending_challenge` da
   "önce kontrol et, başarısız olursa artır" yerine "önce atomik olarak
   artır, sonra kontrol et" sırasına değiştirildi -- read-then-write
   aralığını tamamen kapatıyor.
2. **Cevap karşılaştırması zamanlamaya duyarlıydı (düşük önem ama
   bedava düzeltme)**. `verify_pending_challenge` düz `==` kullanıyordu --
   ilk farklı karakterde erken dönen bir karşılaştırma, teorik olarak
   karakter-karakter zamanlama analiziyle daraltılabilir. `hmac.compare_digest`
   (sabit-zamanlı) ile değiştirildi.

### Eklenen: `VerificationContext.client_ip` -- IP itibarı hook'u

Kullanıcının sorusuna dürüst cevap: HAYIR, şu ana kadar hiçbir şekilde
mümkün değildi -- `ctx.signals` istemci JS'inin gönderdiği bir çanta,
oraya bir IP koymak istemcinin "ben buyum" demesi demek, sahteleniyor.
Gerçek bağlantı IP'si hiçbir check'e ulaşmıyordu. Şimdi:
`VerificationContext`/`CaptchaGate.verify()` yeni bir `client_ip`
parametresi taşıyor, `build_captcha_router()` bunu `Request.client.host`'tan
okuyup otomatik dolduruyor. Kütüphane kendi IP itibar veritabanını
sunmuyor (hangi kaynağa güveneceğine dair görüşü yok) ama artık gerçek,
sahtelenemez IP'yi kendi `extra_checks`'inize ulaştırıyor -- `docs/OZELLIKLER.md`'de
somut bir `PredicateCheck` örneğiyle gösterildi.

### Doğrulama

Eski (buggy) `increment_attempts` kodunu izole bir script'te 20 eşzamanlı
çağrıya karşı çalıştırıp gerçekten 1'e düştüğünü gördüm (bug'ın gerçek ve
ciddi olduğunun kanıtı), sonra düzeltilmiş kodun aynı senaryoda tam 20
verdiğini doğruladım. Mevcut tüm attempt-limit testleri (ör. "3 yanlış
denemeden sonra doğru cevap bile reddedilir") değişmeden geçti --
davranış dışarıdan aynı, sadece sayaç artık atomik.

11 yeni test: `test_captcha_shared.py` (yeni dosya -- doğru/yanlış cevap,
tam-limit-sonra-kilitlenme, süresi dolmuş challenge, bilinmeyen id,
limitten sonra verifier'ın hiç çağrılmadığı, normalize, eşzamanlı yanlış
tahminlerin limiti aşamadığı), `test_sql_captcha_store_increment_attempts_is_atomic_under_concurrency`
(20 eşzamanlı artışın kayıpsız 20 verdiği), `test_math_provider_keeps_multiplication_to_single_digits`
(önceki turdan), `test_client_ip_reaches_a_custom_check_for_your_own_ip_reputation`
+ `test_verify_gate_passes_the_real_client_ip_through_to_checks` (IP
itibarı hook'unun gerçekten çalıştığı, hem gate seviyesinde hem gerçek
HTTP isteği üzerinden). Tüm suite yeşil (bilinen Postgres ortam hatası
hariç), ruff+mypy temiz (119 dosya).

## [Unreleased] — `/giveaway-test`: "uyarlanabilir" gate'e gerçek PoW maliyeti eklendi

Kullanıcı, bir önceki turda "insan-benzeri sinyaller geçti" testimi
görünce haklı bir soru sordu: "bu kötü değil mi, normalde hiç geçmemesi
gerekmez mi?" Cevap: hayır, bu YENİ bir açık değil -- davranış skorunun
en baştan beri dürüstçe belgelenen sınırı bu (`scoring.py`: "a determined
bot that knows these rules can send signals that score as human"). Ben
elle, kuralları bilerek "iyi görünen" sinyaller yazdım -- tam olarak
sahtelenebilirliğin ne demek olduğunu kanıtlayan şey. Ama kullanıcı gerçek
bir eksik de buldu: `/giveaway-test`'in "uyarlanabilir" gate'i
`require_captcha=False` ile kurulmuştu, yani SADECE hesap + davranış
skoru vardı -- diğer gate'lerdeki (`giveaway_gate`/`appeal_gate`) gerçek
PoW maliyeti hiç yoktu.

### Değişen

- **`giveaway_test_invisible_gate` artık `ProofOfWorkProvider` kullanıyor**
  (`require_captcha=False` değil) -- "görünmez" olması, hiç maliyet
  olmaması anlamına gelmiyor, sadece görünür bir bulmaca olmaması
  anlamına geliyor. Artık gerçekten sahtelenemeyen bir katman (sunucu
  hash'i kendisi yeniden hesaplıyor) + hesap-bağlama + davranış skoru
  birlikte gerekiyor.
- Doğrulama yeniden yapıldı: bot-benzeri sinyaller hâlâ anında reddediliyor
  (PoW'a bile gerek kalmadan); elle hazırlanmış insan-benzeri sinyaller
  AMA çözülmemiş bir PoW ile artık ARTIK GEÇMİYOR (`"captcha"` check'inde
  reddediliyor) -- "iyi görünen sinyaller tek başına yetmiyor" iddiası
  gerçekten kanıtlandı; sadece insan-benzeri sinyaller + gerçekten
  çözülmüş bir PoW nonce'u birlikte geçiyor.

Kod değişikliği kütüphaneye dokunmuyor, sadece örnek. Test suite'e etkisi
yok; ruff+mypy temiz.

## [Unreleased] — captcha: gerçek çekiliş botu simülasyonu (adaptive escalation) + Math zorluk düzeltmesi

Kullanıcı iki şey bildirdi: (1) son testte math captcha "16 × 19" sordu --
gerçek bir bug, insan için "kolay" olması gereken bir captcha için
mantıksız zor. (2) Asıl istediği "normal widgetli test" farklıymış:
gerçek bir çekiliş botu simülasyonu -- kanalda butona tıkla, görünmez
(ephemeral) mesaj + DM'den link, linke girince önce Discord girişi
istensin, giriş sonrası captcha ekranı açılsın, 2 widget olsun: biri
robot şüphesiyle reddedip çizgi-çizme captcha'sını tetikleyen uyarlanabilir
bir akış, diğeri sade orijinal.

### Değişenler

- **`MathCaptchaProvider` gerçek bug'ı düzeltildi**
  (`discord_webapi/captcha/providers/math_captcha.py`): docstring "1-20
  arası, insan için kolay" diyordu ama çarpma işleminde de aynı 1-20
  aralığı kullanılıyordu -- `16 × 19 = 304` gibi gerçekte hiç kolay
  olmayan sorular üretebiliyordu. Artık çarpma işlemi 1-9 aralığına
  (en fazla 9×9=81) sınırlı, toplama/çıkarma hâlâ 1-20 kullanıyor. Yeni
  test: operatörü zorla `*` yapıp üretilen cevabın hep ≤81 kaldığını
  doğruluyor.
- **`examples/captcha_gate_bot`'a gerçek bir çekiliş simülasyonu eklendi**
  (`/giveaway-test`): kanala gerçek bir çekiliş botu gibi embed + "Katıl"
  butonlu bir mesaj atıyor. Tıklanınca: ephemeral (kanaldaki herkesten
  gizli) bir yanıt + DM'den doğrulama linki. Link önce giriş istiyor --
  sunucu tarafında kontrol ediliyor, giriş yapılmadan hiçbir captcha
  gösterilmiyor. Giriş sonrası 2 bağımsız doğrulama:
  1. **Uyarlanabilir**: önce sessizce sadece davranış skorunu dener
     (`require_captcha=False`); şüpheli çıkarsa sayfa JS'i ikinci bir
     widget'ı (çizgi-takip) açığa çıkarıp kullanıcıdan çizgiyi çizmesini
     istiyor. `CaptchaGate`'in kendisinde escalation özelliği yok --
     bu, sayfa JS'inin İKİ AYRI gate'i birleştirmesiyle (önce görünmezi
     dene, başarısız olursa çizgi-takip gate'ini aç) elde ediliyor --
     kütüphanenin her yerindeki "kendi kompozisyonunu kur" deseninin
     aynısı, yeni bir `CaptchaGate` özelliği değil.
  2. **Orijinal**: tek başına, her zaman gerekli bir Math captcha.

### Doğrulama

OAuth round-trip'i (gerçek tarayıcı gerektiriyor) atlayıp gate'lere
doğrudan karşı test ettim: bot-benzeri sinyaller (webdriver=true, sıfır
mouse hareketi, anlık tıklama) görünmez gate'i gerçekten reddetti;
insan-benzeri sinyaller geçti; çizgi-takip fallback'i gerçek bir çizilmiş
yolla gerçekten doğrulandı. Ayrıca giriş yapmadan sayfanın hiçbir captcha
göstermediğini (sadece giriş linki) doğruladım.

1 yeni test (`test_captcha_providers.py`: çarpma işleminin 9×9'u
aşmadığı). Tüm suite yeşil (bilinen Postgres ortam hatası hariç),
ruff+mypy temiz.

## [Unreleased] — captcha: `on_verified()` çapraz-gate sızıntısı bulunup düzeltildi + 3'lü karşılaştırma testi

Kullanıcı, bir önceki turdaki çoklu-gate desteğini gerçekten test etmemi
istedi: web + bot komutu, 3 captcha türü alt alta (çizgi-takip / "başarılı
dönse de robot doğrulaması isteyen" güvenli mod / sade orijinal), bir test
komutu, DM'e buton gönderen bir test mesajı, ve 2 katılımcıyla sağlam bir
test. Bunu gerçekten inşa edip çalıştırırken kütüphanede önceden
bilinmeyen gerçek bir bug bulundu.

### Bulunan gerçek bug ve düzeltmesi

- **`CaptchaGate.on_verified()` filtre yapmıyordu.** Bu örnekte 5 gate
  (çekiliş, itiraz, ve yeni 3 test gate'i) hepsi TEK bir `Transport`'u
  paylaşıyor -- `captcha_verified` tek bir event type, o transport
  üzerindeki HER gate'e broadcast ediliyor. `on_verified()` hiçbir filtre
  yapmadığı için bir gate'e abone olmak diğer TÜM gate'lerin
  doğrulamalarını da görüyordu (2 kullanıcıyla simüle edilen testte
  katılımcı sayısı 2 yerine 6 çıktı, ayrıca çekiliş gate'inin handler'ı
  test gate'lerinin doğrulamaları için de tetiklenip hatalı `KeyError`/
  `AttributeError` fırlatıyordu). Düzeltme: `on_verified(handler, *,
  purpose=None)` -- `purpose` verilirse sadece o `purpose`'a sahip
  event'leri geçiriyor, `purpose=None` (varsayılan) eski davranışın
  birebir aynısı (geriye dönük tam uyumlu).
- `examples/captcha_gate_bot`'taki TÜM `on_verified()` çağrıları
  (çekiliş, itiraz, ve 3 yeni test gate'i) artık kendi `purpose`'larını
  filtreliyor.

### Eklenen: `/test-join`, `/test-participants`, `/test-widgets`

- **3 yeni demo gate**: Path-Trace (sade, görünmez katman yok), "safety
  mode" (görünür Math captcha VE görünmez davranış skoru ikisi de şart --
  davranış skoru geçse bile yanlış Math cevabı hâlâ `"captcha"`
  check'inde reddediliyor, gerçekten test edildi), "orijinal" (sade tek
  başına Math). Her biri `/test-path-trace`, `/test-safety`,
  `/test-original` prefix'leri altında ayrı mount ediliyor.
- **`/test-join`** -- DM'e bir `discord.ui.Button` ("Katıl") gönderiyor;
  tıklanınca üç token birden mint edilip tek bir `/test-widgets` linki
  ephemeral olarak dönüyor.
- **`/test-widgets`** -- üç widget'ı alt alta gösteren sayfa.
- **`/test-participants`** -- şu ana kadar üç test gate'inden herhangi
  birini tamamlayan herkesi listeliyor.

### Doğrulama

`TestClient` ile 2 farklı sahte Discord kullanıcısı (`111`, `222`) üç test
gate'inin her birinden gerçekten geçirildi -- düzeltmeden önce katılımcı
sayısı yanlış (6) çıkıyordu, düzeltmeden sonra doğru (2, çapraz sızıntı
yok) çıktı. Path-trace gerçek yoğun bir trace ile, safety-mode hem doğru
hem yanlış Math cevabıyla (ikisinde de davranış sinyalleri insan-gibi
tutularak -- gerçekten `"captcha"` check'inin ayrı çalıştığını kanıtlamak
için) ayrı ayrı test edildi.

2 yeni birim testi (`test_captcha_gate.py`: filtresiz eski davranışın
korunduğunu, `purpose=` ile çapraz-gate sızıntısının önlendiğini
kanıtlıyor). Tüm suite yeşil (bilinen Postgres ortam hatası hariç),
ruff+mypy temiz.

## [Unreleased] — captcha: gerçek bot-komut senaryoları için çoklu-gate desteği + `examples/captcha_gate_bot`

Kullanıcının sorusu: "peki komutlarda çalışıyor mu, çekiliş botu +
'çok ban yemiş kullanıcı itiraz komutundan önce doğrulasın' senaryoları
şu an gerçekten çalışıyor mu?" Dürüst cevap araştırılırken gerçek, önceden
bilinmeyen bir mimari sınır ortaya çıktı ve düzeltildi.

### Bulunan gerçek sınır ve düzeltmesi

- **`build_captcha_router()` tek bir global `app.state.discord_webapi_captcha_gate`
  okuyordu** -- tek entegrasyonu olan bir bot için doğru tasarım, ama
  kullanıcının sorduğu senaryo (çekiliş gate'i + ayrı bir itiraz gate'i,
  aynı anda) için yetersiz: iki gate aynı anda çalışamıyordu. Düzeltme:
  `build_captcha_router(gate=...)` artık isteğe bağlı bir `gate` parametresi
  alıyor -- verilirse app.state yerine o gate'e bağlanıyor (geriye dönük
  uyumlu, `gate=None` eski davranışın aynısı). Router her gate için ayrı
  bir `prefix` ile birden fazla kez mount edilebiliyor.
- **Widget'a `data-api-base` özniteliği eklendi** -- prefix'li mount'larla
  konuşabilmesi için (`data-api-base="/giveaway"`).
- **`examples/captcha_gate_bot/`** (yeni örnek): kullanıcının birebir
  sorduğu iki senaryo, gerçek bir discord.py bot'una ve gerçek Discord
  OAuth hesap-bağlamasına karşı (playground'un sahte `user_id=0`'ı değil):
  1. **`/join`** -- çekilişe katılma linki DM'leniyor, web tarafında
     görünmez PoW + davranış skoru + **gerçek Discord hesabına bağlama**
     (`require_account=True`) ile doğrulanıyor, `on_verified` ateşlenince
     bot "katıldın!" DM'i atıyor -- polling yok.
  2. **`/appeal`** -- bir ban eşiğini (demo: `_fake_ban_counts`, gerçek
     kullanımda kendi `WarnStore`/`EscalationEngine`'inizle değiştirin)
     geçen kullanıcı, **ayrı bir gate** üzerinden doğrulanmadan komutu
     kullanamıyor; bir kez doğrulanınca temiz kalıyor.
  İki gate de `/giveaway` ve `/appeal` prefix'leri altında ayrı ayrı mount
  ediliyor -- yukarıdaki çoklu-gate desteğinin somut kullanımı.

### Doğrulama

Gerçek bir Discord bot bağlantısı gerektirmeden (`FastAPI` `TestClient`
ile, diğer örnek botlardaki "fiziksel test" adımının bir öncesi):
modülün gerçekten import edilip her iki prefix'in de doğru mount
olduğu, `/giveaway` prefix'i altındaki bir token'ın `/appeal` prefix'i
altında 404 döndüğü (ve tersi -- gerçek izolasyon), gerçek bir PoW
challenge'ının issue edildiği, ve `require_account=True` olduğu için
giriş yapmadan verify çağrısının doğru şekilde `failed_check="account"`
döndürdüğü doğrulandı. Discord Gateway bağlantısı gerektiren kısım
(`/join`/`/appeal` komutlarının gerçekten tetiklenmesi) bu repodaki her
örnek bot için zaten dokümante edilen fiziksel-test adımı olarak kalıyor.

4 yeni entegrasyon testi (`test_captcha_api.py`: iki gate'in `gate=`
parametresiyle çakışmadan aynı anda mount edilmesi, token izolasyonu,
`gate=`'nin app.state'e göre önceliği). Tüm suite yeşil (bilinen Postgres
ortam hatası hariç), ruff+mypy temiz.

## [Unreleased] — captcha: hazır, dahili widget (`discord_webapi.captcha.widget`)

Kullanıcı iki şey istedi: (1) playground'daki elle yazılmış doğrulama
kutusunun görünümü "2010lardan fırlama" duruyordu, modernleştirilsin; (2)
daha önemlisi -- bu widget playground'a özel bir mock olmaktan çıkıp
**kütüphanenin kendisinin** sunduğu hazır bir UI bileşeni olsun: hem alt
yapıyı (checks/heuristics/providers -- zaten vardı) hem de hızlı
kullanmak isteyenler için tek satırlık hazır bir widget'ı birlikte verelim.

### Eklenenler

- **`discord_webapi/captcha/widget.py` + `widget.js`** (yeni modül):
  `build_captcha_widget_router()` -- bir tek `<div class="dwa-captcha-widget"
  data-token="...">` + bir tek `<script src="...">` ile gömülen, gerçek bir
  Cloudflare-Turnstile-tarzı checkbox widget'ı sunuyor. Widget kendi
  UI'sını `CaptchaGate`'in verdiği `challenge.kind`'a göre otomatik
  uyarlıyor: captcha yoksa sade checkbox; Math/Text ise gömülü görsel +
  metin kutusu + kendi "Doğrula" butonu; PoW ise tamamen görünmez (arka
  planda gerçek hashcash aramasını `crypto.subtle.digest` ile yapıp
  bitince checkbox'ı aktif ediyor); Path-trace ise gömülü bir
  `<canvas>`; reCAPTCHA/hCaptcha ise onların kendi widget script'ini
  gömüp kendi "Doğrula" butonuyla token okuyor. Mouse/dokunma
  sinyallerini (kinematik dahil) sayfa yüklendiği andan itibaren kendisi
  topluyor. Her adım (yaklaşma, tam tıklanan piksel + merkezden sapma,
  kontrol animasyonu, sunucu sonucu) `document` üzerinde bir
  `dwa-captcha-widget-log` CustomEvent'i olarak yayınlanıyor -- kendi
  görünür zaman çizelgesini isteyen sayfa sadece bunu dinliyor.
  `data-callback` özniteliğiyle adı verilen fonksiyon, doğrulama
  bitince `result` ile çağrılıyor (`grecaptcha`/`hcaptcha`'nın
  `data-callback` desenine benzer). `window.dwaCaptchaWidgetInit()` de
  dışa açık -- dinamik olarak eklenen widget div'lerini sayfa
  yenilenmeden tekrar taratmak için.
- **Modern görünüm**: eski kalın-kenarlıklı düz dikdörtgen yerine
  yuvarlatılmış köşeler, ince/yumuşak gölge, SVG çizgili tik/çarpı
  ikonları (düz metin karakteri yerine), conic-gradient tabanlı yumuşak
  spinner, sistem font stack'i, açık/koyu tema desteği
  (`prefers-color-scheme`).
- **Bilerek opsiyonel**: rate limiter/escalation gibi
  `DiscordWebAPI.install()`'a otomatik bağlanmıyor -- kendi frontend'ini
  ham `build_captcha_router()` endpoint'lerine karşı yazmak isteyenler
  widget'ı hiç kullanmayabilir, kütüphane hiçbir şekilde dayatmıyor.
- **`examples/captcha_playground`** artık bu bundled widget'ı
  dogfoodluyor: eski elle-yazılmış widget IIFE'si tamamen kaldırıldı,
  yerine gerçek `<div class="dwa-captcha-widget">` + bir
  `CaptchaGate` konfigürasyonu seçme dropdown'u geldi (hiçbiri/Math/
  Text/PoW/Path-trace/varsa reCAPTCHA-hCaptcha) -- widget'ın kendi
  UI'sının her birine göre değiştiğini canlı gösteriyor.
- **Gerçek bir bug bulunup düzeltildi bu sırada**: `build_captcha_router()`
  tek bir global `app.state.discord_webapi_captcha_gate`'i okuyor (gerçek
  bir deploy'da doğru tasarım -- tek entegrasyon, tek gate), ama
  playground birden fazla gate (kind başına biri) kurup hiçbirini
  `app.state`'e atamamıştı -- widget'ın `GET /api/captcha/gate/{token}`
  isteği sessizce 404 dönüyordu. Playground'un token-mint endpoint'i
  artık token verirken ilgili gate'i `app.state`'e de atıyor (yalnızca bu
  tek-operatörlü yerel demo için uygun bir çözüm, gerçek çoklu-kullanıcılı
  bir deploy'da tek bir gate seçilmeli).

Playwright ile gerçek bir headless Chromium'da uçtan uca doğrulandı:
"none" gate'inde davranış katmanı çalıştı (webdriver=true olduğu için
doğru şekilde reddetti -- Playwright'ın kendi otomasyon izini
yakaladığının kanıtı), Math gate'inde görsel+input+submit akışı
çöküşsüz tamamlandı, PoW gate'inde arka plan araması gerçekten çalışıp
checkbox'ı otomatik aktif etti, Path-trace gate'inde canvas doğru
render edildi. Sayfa hatası (`pageerror`) hiç görülmedi.

3 yeni test (`tests/unit/test_captcha_widget.py`: script'in doğru
content-type ile servis edilmesi, özel mount path, gerçek gate
endpoint'lerine referans verdiğinin sağlaması). Tüm suite yeşil (bilinen
Postgres ortam hatası hariç), ruff+mypy temiz (119 dosya).

## [Unreleased] — captcha_playground: dokunmatik "yaklaşma" log'u yanıltıcıydı, düzeltildi

Kullanıcı telefonda widget'ı test edince log'da `yaklaştı` -> 89ms sonra
`uzaklaşıldı` -> 3ms sonra `tıklandı` sırasını gördü ve bunu "çok hızlı,
hata ihtimali yüksek" diye şüphelendi -- haklı bir gözlemdi ama sebebi
bir güvenlik zafiyeti değil, dokunmatik ekranların tarayıcı olay modeli:
dokunmatikte gerçek bir "önce yaklaş sonra tıkla" kavramı yok, tarayıcı
tek bir dokunuşun etrafına sentetik bir enter+leave çifti üretiyor --
`pointerleave` neredeyse `click` ile aynı anda ateşleniyor çünkü ikisi de
AYNI dokunuşun parçası, gerçekten ayrılıp geri gelme değil.

### Değişenler

- **`kutudan uzaklaşıldı` log'u artık sadece mouse/pen için yazılıyor**,
  touch için bastırıldı -- yanıltıcı "ayrı bir yaklaşma daha oldu" izlenimi
  vermesin diye.
- **Tıklama log satırına dokunmatik notu eklendi**: `pointer_type` touch/
  pen ise, "yaklaşma+tıklama aynı dokunuşun parçası olduğu için birbirine
  çok yakın zamanlıdır, bu normaldir" açıklaması otomatik ekleniyor.
- Playwright'ın gerçek dokunmatik emülasyonuyla (`page.touchscreen.tap`,
  iPhone 12 cihaz profili) doğrulandı: `uzaklaşıldı` satırı artık hiç
  görünmüyor, tıklama satırında yeni açıklama var.

Kütüphaneye (`discord_webapi/captcha/`) hiçbir dokunuş yok, sadece örnek.
Test suite'e etkisi yok; ruff/mypy temiz.

## [Unreleased] — captcha_playground: gerçek doğrulama widget'ı + tam adım-adım log

Kullanıcı iki şey istedi: (1) tam merkeze tıklamanın gerçekten
`click-not-dead-center` sezgiseline dahil olup olmadığının teyidi, (2)
fiziksel test için Cloudflare Turnstile tarzı gerçek bir dikdörtgen
kutu/checkbox widget'ı + sayfaya girildiği andan itibaren her adımın
(yaklaşma, tam tıklanan piksel, animasyonlar) log'a yazılması.

### Değişenler

- **`#captcha-widget`** eklendi (`examples/captcha_playground/playground.html`,
  yeni "0)" bölümü): gerçek bir checkbox+etiket kutusu. Loglanan adımlar,
  sırayla: sayfa yüklenmesi -> ilk hareket/dokunuş algılanması -> mouse'un
  kutuya ilk yaklaşması (`pointerenter`, kutudan ayrılırsa da not
  düşülüyor) -> tıklama (kutu-içi tam piksel konumu + merkezden piksel
  cinsinden sapma -- 2px altındaysa "insan için fazla kusursuz, şüpheli"
  notuyla) -> ~700ms'lik gerçek bir kontrol animasyonu -> sunucuya
  gönderilen ham sinyaller -> her check'in PASS/FAIL'i -> genel sonuç
  (yeşil ✓ / kırmızı ✕). ~2.5sn sonra kendini sıfırlayıp tekrar
  denenebiliyor.
- Playwright (headless gerçek Chromium) ile uçtan uca doğrulandı: tam
  merkeze (0.2px sapma) yapılan bir tıklama gerçekten
  `click-not-dead-center=0.00` üretti ve widget'ın kendi "şüpheli" uyarısını
  tetikledi; ayrıca Playwright'ın kendi otomasyon izini
  (`navigator.webdriver=true`) `no-webdriver` check'i doğru şekilde
  yakalayıp reddetti -- yani check'lerin gerçekten çalıştığının canlı,
  bağımsız bir kanıtı.

Kod değişikliği kütüphaneyi (`discord_webapi/captcha/`) etkilemiyor,
sadece örnek. Test suite'e etkisi yok; ruff/mypy temiz.

## [Unreleased] — captcha_playground: teşhis/şeffaflık iyileştirmeleri (kullanıcının gerçek telefon testinden sonra)

Kullanıcı playground'u telefonundan gerçekten test etti ve üç şey
sordu: (1) davranış skorunda mouse-kinematiği neden yoktu, anında geçti,
gerçekten kontrol ediliyor mu; (2) PoW süresi neden 3980ms'den 12735ms'ye
sıçradı; (3) path-trace neden iki kez FAIL, hesaplama gerçekten yapılıyor
mu. Hiçbiri bug değildi ama playground hiçbirini açıklamıyordu -- sadece
teşhis eksikliğiydi. Kod tarafında (`discord_webapi/captcha/`) hiçbir
değişiklik yok, sadece `examples/captcha_playground/`:

- Davranış check'inden önce ham sinyalleri (`pointer_type`, `pointer_moves`,
  `click_offset`, `interaction_ms`, `webdriver`) log'a yazıyor artık --
  dokunmatikse "mouse-kinematiği bilerek çekimser kalır, hata değil"
  notuyla. `interaction_ms`'in tıklama anından değil sayfa yüklenmesinden
  itibaren ölçüldüğü de açıkça yazılıyor.
- PoW: arama sırasında ilerleme (`N deneme yapıldı`) gösteriliyor, bitince
  beklenen ortalama deneme sayısıyla karşılaştırıp "şansa bağlı büyük
  değişkenlik normaldir" notunu ekliyor (hashcash aramasının süresi
  geometrik dağılımlı -- aynı zorlukta 3 kat fark tamamen olağan).
- Path-trace: sunucudaki geometriyi (`_dist_point_to_segment`/
  `_dist_point_to_polyline`) tarayıcıda da hesaplayıp göndermeden ÖNCE
  "en uzak sapma Xpx (tolerans Ypx), kapsanmayan köşe: N/M" diye
  yazıyor -- geçip geçmeyeceğini tahmin ediyor, gerçekten sunucunun ne
  hesapladığını görünür kılıyor. Ayrıca **playground'un** `PathTraceProvider`
  tolerans'ı 24px'ten 34px'e çıkarıldı (kütüphanenin varsayılanı
  DEĞİŞMEDİ) -- gerçek parmak dokunuşu bir mouse imlecinden çok daha az
  hassas, 24px telefon için fazla sıkıydı.
- Görsel captcha submit: "gönderiliyor" anında loglanıyor, sonuçta
  gönderilen cevap tekrar yazılıyor (sunucunun gerçekten o cevabı kontrol
  ettiğini görünür kılmak için).

Sunucuyu yeniden ayağa kaldırıp yeni tolerans + geometri hesaplarını curl
ile tekrar doğruladım (gerçek bir path'i yoğun örnekleyerek gönderdim,
`verified: true` döndü). Kod değişikliği testleri etkilemiyor; ruff/mypy
temiz.

## [Unreleased] — captcha: homing-correction sezgiseli (fail-open) + tıklanabilir test sitesi

Kullanıcı, daha önce test edip "bağımsız değer katmıyor, eklemiyorum"
dediğim homing-correction sezgiselini yine de eklememi ve tüm captcha
sistemini kendi tarayıcısında elle test edebileceği bir sayfa hazırlamamı
istedi ("sonuçları sana vereyim").

### Değişenler

- **`mouse-homing-correction` eklendi** (`captcha/scoring.py`), önceki
  turdaki bulgu dikkate alınarak **asla puan düşürmeyecek** şekilde: mesafe-
  hedef eğrisinde en az bir gerçek "aşma ve düzeltme" (overshoot) anı
  bulursa `1.0`, bulamazsa `0.0` değil **çekimser (`None`)** döner. Bunun
  sebebi: overshoot yokluğu insan olmadığının kanıtı değil (yavaş/hassas
  hareketlerde hiç görülmeyebilir) -- sadece varlığı ek pozitif kanıt.
  Varsayılan ağırlık 1.0 (düşük, durumsal bir sinyal olduğu için).
- **`examples/captcha_playground/`** (yeni örnek): bot/OAuth gerektirmeyen,
  tek sayfalık, tıklanabilir bir test sitesi -- Math/Text/PoW/Path-trace
  captcha'larının hepsi + reCAPTCHA/hCaptcha (gerçek site key varsa) +
  görünmez katmanın tamamı (`reject_webdriver`, `require_min_interaction_ms`,
  tüm sezgiselleriyle `SignalScoreCheck`, `RepeatedMovementCheck`) tek
  ekrandan gerçekten çalıştırılıp PASS/FAIL log paneline yazılıyor. PoW
  gerçek hashcash aramasını tarayıcının kendi `crypto.subtle.digest`'ıyla
  yapıyor (mock değil). "Aynı hareketi tekrar gönder" butonu, replay
  tespitinin ikinci gönderimde FAIL'e döndüğünü canlı gösteriyor -- elle
  uçtan uca doğrulandı (curl ile tüm endpoint'ler tek tek denendi: math
  doğru/yanlış cevap, pow gerçek nonce araması, path-trace geçerli/geçersiz
  iz, behavior-check + replay -- hepsi beklenen sonucu verdi).

3 yeni test (`mouse-homing-correction`'ın gerçek overshoot'u puanlaması,
düzgün insan hareketinde cezalandırmadan çekimser kalması, lineer bot
hareketinde de çekimser kalması). Tüm suite yeşil (bilinen Postgres ortam
hatası hariç), ruff+mypy temiz.

## [Unreleased] — captcha: replay-tespiti (`RepeatedMovementCheck`) + granüler açma/kapama

Kullanıcının iki isteği: (1) her özelliğin/algoritmanın tek tek
açılıp kapatılabilir olduğunu netleştirmek ("bu algoritmayı istemiyorum,
şunu istiyorum ya da zaten 3. taraf hizmet kullanacağım" senaryosu), (2)
aynı hareketin/tıklamanın hep tekrarlandığı, farklı cihaz/IP'lerden de
olsa hep aynı davranışın sergilendiği durumları şüpheli sayacak bir katman.

### Değişenler

- **`RepeatedMovementCheck` eklendi** (`discord_webapi.captcha.replay_guard`,
  yeni modül): önceki turda dürüstçe yazılan "tek istekli kinematik analiz
  replay saldırısını yakalayamaz" sınırına karşı **tek gerçek çözüm** --
  çünkü bu, tek isteğe değil **geçmişe** bakan bir kontrol. `mouse_trajectory`'den
  kaba, öteleme-bağımsız bir parmak izi (`fingerprint_trajectory`) çıkarıp
  bu izin yakın zamanda -- **kim tarafından olursa olsun** -- kullanılıp
  kullanılmadığına bakıyor. Bilerek global (kullanıcı/IP bazlı değil):
  amaç, aynı kaydın farklı bir hesap/cihaz/IP altında tekrar sunulmasını
  yakalamak -- per-hesap/per-IP rate limit bunu göremez. Sinyal
  eksik/dokunmatikse fail-open (geçer). `MemoryTrajectoryFingerprintStore`
  (tek process) + `SQLTrajectoryFingerprintStore` (çoklu web replica'sı)
  -- diğer tüm store'larla aynı Protocol + Memory/SQL deseni. Varsayılan
  olarak hiçbir gate'e bağlı değil, `extra_checks=[...]` ile isteğe bağlı.
- **Homing-dynamics denendi, eklenmedi**: kullanıcının önerdiği "hedefe
  yaklaşırken overshoot-düzeltme" sinyalini gerçek veriyle test ettim --
  kendi elle kurduğum "insan" trajectory'sinde bile sıfır overshoot
  çıktı (minimum-jerk modeli zaten monoton, overshoot sadece hızlı/balistik
  hareketlerde ortaya çıkan ikincil bir olgu, her insan hareketinde yok).
  İkili yapılırsa meşru düz hareketleri cezalandırır; dereceli yapılırsa
  zaten var olan `mouse-velocity-variance` ile neredeyse aynı bilgiyi
  tekrarlar. Bağımsız değer katmadığı için eklenmedi -- test etmeden
  eklemek yerine dürüstçe geri çekildi.
- **Granülerlik netleştirildi (docs)**: `docs/OZELLIKLER.md`'ye, katman
  seviyesinin (provider/check aç-kapa) bir altında, katmanın İÇİNDEKİ
  tek tek özelliklerin de (örn. `SignalScoreCheck`'in belirli bir
  sezgiselini listeden çıkarmak, kendi provider'ınızı/3. taraf servisinizi
  hiç bizim kodumuza dokunmadan kullanmak) nasıl seçilip
  değiştirilebileceğini gösteren somut bir örnek eklendi. Bu zaten mevcut
  bir yetenekti (`heuristics=[...]`, `CaptchaProvider` Protocol'ü) --
  netlik için dokümante edildi.

15 yeni test (`fingerprint_trajectory`'nin determinizmi/öteleme-bağımsızlığı/
farklı şekilleri ayırt etmesi/bozuk-veride None dönmesi; Memory+SQL
fingerprint store CRUD+expiry; `RepeatedMovementCheck`'in ilk gönderimi
geçirmesi, aynı hareketi tekrar reddetmesi, **farklı hesap altında bile**
reddetmesi, ötelenmiş replay'i de yakalaması, iki farklı gerçek hareketi
ikisini de geçirmesi, sinyal yoksa/dokunmatikse fail-open olması, gate'e
extra_check olarak oturması). Tüm suite yeşil (bilinen Postgres ortam
hatası hariç), ruff+mypy temiz.

## [Unreleased] — captcha: mouse kinematiği skoru (araştırma + uygulama)

Kullanıcının somut sorusu: "ardışık mouse hareketleri/hızlanma-yavaşlama
da puanlanabilir mi, insanı bot sanma ihtimali imkansıza yakın yapılabilir
mi?" -- gerçek bir araştırma/hesaplama istendi, ChatGPT gibi tahmin değil.
Minimum-jerk insan hareket modeli (Flash & Hogan 1985) ile naive
sabit-hız/sabit-aralık bot modeli sentetik olarak karşılaştırıldı (20
deneme); üç istatistikte de (eğrilik oranı, hız değişkenlik katsayısı,
zamanlama değişkenlik katsayısı) temiz ayrışma gözlendi, örtüşme yok.

### Değişenler

- **`SignalScoreCheck`'e üç yeni sezgisel eklendi**
  (`discord_webapi.captcha.scoring`): `mouse-curvature` (kat edilen
  yol/düz mesafe oranı), `mouse-velocity-variance` (hız değişkenlik
  katsayısı), `mouse-timing-variance` (örnekleme-aralığı değişkenlik
  katsayısı). Yeni `signals["mouse_trajectory"]` girdisi (`[x, y, t_ms]`
  listesi, widget'a yaklaşırken toplanmaya başlanır -- tıklama-öncesi
  kuralı diğer sezgisellerle aynı). Sinyal eksik/dokunmatik/çok az
  örnek/bozuk veri -> çekimser (eski istemcilerle geriye dönük uyumlu,
  haksız cezalandırmıyor). Aşırı büyük bir trajectory listesi ilk 2000
  örnekle sınırlanıyor (DoS'a karşı, çökme/asılma yok).
- **Dürüst araştırma sonucu (koda ve dokümana yazıldı):** hayır, "insanı
  bot sanma ihtimalini imkansıza yakın" yapılamaz -- bunun sebebi ayar
  eksikliği değil, yapısal bir sınır: bir bot gerçek, kaydedilmiş bir insan
  fare hareketini **replay** edebilir, replay edilen veri gerçek insan
  hareketi olduğundan bu (veya başka herhangi bir) tek-istekli kinematik
  kontrolü kusursuz geçer. Ayrıca bunu atlatmaya özel yazılmış halka açık
  "insan gibi fare yolu" üretici araçlar zaten var. Yine de eklemeye değer:
  naive/düşük emekli otomasyonun (gerçekte karşılaşılanın büyük kısmı)
  maliyetini ciddi yükseltiyor -- ama PoW (gerçek maliyet) + hesap-bağlama
  (gerçek kimlik) ile katmanlanan şeffaf bir sezgisel olarak kalıyor, tek
  başına "insan kanıtı" değil.

21 yeni test (insan/bot ayrışması her üç sezgiselde; graded/ikili-olmayan
skor; touch/eksik/az-örnek/bozuk-veri'de çekimser; aşırı büyük payload'da
çökmeden sınırlama; kısa hareket -> çekimser; breakdown'da görünme; bot'un
sahte trajectory eklemesinin işe yaramaması; gate'e extra_check olarak
oturma). Tüm captcha testleri + tüm suite yeşil (bilinen Postgres ortam
hatası hariç), ruff+mypy temiz.

## [Unreleased] — captcha: davranışsal skor + flash-tap kaldırıldı

Kullanıcı geri bildirimi: yanıp-sönen-nokta (flash-tap) modeli gerçek bir
değer katmadığı için saçma; onu kaldır. Basit görsel captcha'lar zaten
zayıf (kabul edildi). Asıl yatırım yapılacak yer backend'de arka planda
çalışan görünmez katman -- onu sağlamlaştır ve *davranışsal* bir skor ekle:
skorlama kullanıcı butona tıkladığında değil, mouse'u widget'a
**yaklaştırırken** başlar; tıklama konumundan (tam ortaya tıklamak bot
şüphesi), dilden, saat diliminden vb. bir skor tablosu çıkar.

### Değişenler

- **`FlashTapProvider` kaldırıldı** -- karanlık-ekran-yanıp-sönen-nokta
  modeli. Gerçek bir güvenlik değeri katmadan (challenge verisi zaten
  istemciye gidiyordu) yalnızca karmaşıklık ekliyordu. `kind="flash-tap"`
  artık yok.
- **`SignalScoreCheck` eklendi** (`discord_webapi.captcha.scoring`):
  görünmez katmanın "gerçek tarayıcı/insan gibi mi" yarısı. İstemcinin
  gönderdiği `signals` üzerinde **ağırlıklı, şeffaf sezgisellerle** bir
  skor üretip bir eşiği geçip geçmediğine bakan bir `VerificationCheck`.
  Varsayılan sezgiseller: `navigator.webdriver` yok, tıklama-öncesi
  pointer hareketi var (mobil dokunmada çekimser -- haksız cezalandırmaz),
  tıklama tam-ortada-değil (offset ~0 = fazla kusursuz = bot), dil var,
  saat dilimi var, makul etkileşim süresi. Her sezgisel ve ağırlık
  değiştirilebilir; kendi sinyalinizle kendi sezgiselinizi ekleyebilirsiniz
  (`ScoringHeuristic`/`default_behavior_heuristics()`). `compute(signals)`
  skor + kalem-kalem döküm veriyor (loglama/eşik ayarı için). **Dürüst
  not:** her girdi istemci JS'inde toplanır ve uydurulabilir -- bu bir
  bot dedektörü ya da ML DEĞİL, şeffaf bir sezgisel skor; her zaman PoW
  (gerçek maliyet) + hesap-bağlama (gerçek kimlik) ile birlikte kullanın.
- **`PathTraceProvider` sertleştirildi**: `json.loads`'tan önce ham yanıt
  boyutu sınırı (çok-megabaytlık bir gövdeyi ayrıştırmaya zorlanmayı önler).

Yeni testler dahil (davranış skoru: insan geçer / bot kalır / mobil
dokunma cezalanmaz / tam-orta tıklama skoru düşürür / özel sezgiseller;
skorer'ın gate'e extra_check olarak oturması; path-trace boyut sınırı).
Flash-tap testleri kaldırıldı. Kalan captcha testleri yeşil, ruff+mypy
temiz.

## [Unreleased] — captcha: yeni modeller (proof-of-work, çizgi-takip)

Kullanıcı Cloudflare-Turnstile tarzı görünmez bir katman + görsel
captcha'ların "yapay zeka kolay çözüyor" zayıflığına karşı daha zor
etkileşimli modeller istedi. Backend'in dürüstçe sağlayabildiği kadarını
kurdum (aşırı iddiadan kaçınarak).

### Eklenenler

- **`ProofOfWorkProvider`** (`kind="pow"`): görünmez, düşük-maliyet
  katmanı. İstemci arka planda hashcash araması yapıyor (~2^difficulty
  hash), sunucu **tek hash'le** doğruluyor -- görsel render/IP-itibarı/
  üçüncü-taraf çağrısı yok, sunucu maliyeti her zaman minimum. `difficulty`
  tek maliyet düğmesi (istemci maliyeti; sunucu maliyeti sabit). Sadece
  stdlib `hashlib` -- ek bağımlılık yok. Gerçek bir hashcash çözümüyle
  uçtan uca doğrulandı (HTTP üstünden de).
- **`PathTraceProvider`** (`kind="path-trace"`): ekranda kalın bir çizgi;
  kullanıcı fare/parmakla takip ediyor. Sunucu izin çizgiye tolerans içinde
  kalıp (kaçış yok) tüm vertex'leri kapsayıp kapsamadığını **gerçek
  geometriyle** doğruluyor (nokta-poliçizgi mesafesi). Sadece stdlib.
  (Not: bir sonraki değişiklikle `FlashTapProvider` -- yanıp-sönen nokta --
  değer katmadığı için kaldırıldı; yukarıdaki en üst girdiye bakın.)
- **`discord_webapi.captcha.signals`**: instrumentation için üç şeffaf
  `PredicateCheck` yardımcısı (`reject_webdriver`, `require_signal_flag`,
  `require_min_interaction_ms`) -- görünmez katmanın "gerçek tarayıcı mı"
  yarısı. Dürüstçe: bunlar kolay atlatılabilen hız engelleri, bot dedektörü
  değil (client-submitted sinyal, backend güvenilir insan/bot ayrımı
  yapamaz).
- `CaptchaChallenge`'a `params: dict` alanı: parametreli sağlayıcıların
  (PoW/path-trace) frontend'e yapılandırılmış challenge verisi geçmesi için
  -- kendi sağlayıcınız için de genişletme noktası. Bu sağlayıcıların
  hiçbiri Pillow gerektirmiyor (görsel captcha'ların aksine), yani
  `discord-webapi[captcha]` olmadan çalışıyorlar.

**Dürüstlük notu (dokümante edildi)**: mevcut görsel captcha'lar modern
OCR/vision modellerince kolay çözülüyor ("basit" katman olarak kalıyorlar).
Etkileşimli model (path-trace) statik OCR'dan daha zor
*sürtünme* katmanı ama kriptografik garanti değil -- challenge verisi
çizilebilmek için istemciye gittiğinden kararlı bir script okuyup eşleşen
cevap üretebilir. "Bot/AI çözemez" DEMİYORUZ; asıl sertlik PoW (maliyet) +
hesap-bağlama (kimlik) katmanlarından geliyor, doğru kullanım bunları
birlikte katmanlamak.

Ortak verify lifecycle'ı (expiry/deneme-limiti/tek-kullanımlık) provider'a
özel karşılaştırıcıyla yeniden kullanılabilecek şekilde
`_shared.check_pending_challenge`'a çıkarıldı (string-eşitliği
`verify_pending_challenge` bunun üzerinde). 40 yeni test (gerçek hashcash
çözümü, gerçek geometri, sinyal edge case'leri, PoW'un HTTP üstünden
uçtan uca akışı). 619 test yeşil (1 ortam-bağımlı Postgres testi hariç),
ruff+mypy temiz.

## [Unreleased] — captcha: hesap-bağlama + kompoz edilebilir doğrulama katmanları

Kullanıcının geri bildirimi: bir captcha "insan mı" der ama "hangi hesap"
demez -- güvenilirlik için doğrulama gerçek Discord hesabına bağlanmalı; ve
bu iki-seçenekli sabit bir menü değil, kek katları gibi kompoz edilebilir
katmanlar olmalı (bizimkini kullan, kendininkini ekle, karıştır, hiç
kullanma).

### Eklenenler / Değişenler

- **`discord_webapi.captcha.checks`** (yeni): kompoz edilebilir doğrulama
  "katmanları". Her biri bağımsız bir `VerificationCheck` (Protocol);
  gate hepsinin geçmesini şart koşuyor (mantıksal AND). Yerleşik olanlar:
  - `AccountMatchCheck` -- **asıl güven çıpası**: doğrulayan kişi,
    kütüphanenin kendi Discord OAuth girişiyle, linkin ait olduğu **tam
    hesap** olarak giriş yapmış olmalı. Forwardlanmış bir link başkası
    tarafından çözülürse burada patlıyor.
  - `CaptchaCheck` -- captcha çözümünü bir `CaptchaProvider`'a devrediyor.
  - `PredicateCheck` -- tüketicinin kendi async fonksiyonunu bir check'e
    sarıyor (tarayıcı parmak izi, davranışsal skor, "N gündür üye", harici
    anti-fraud... -- kancayı biz veriyoruz, politikayı/eşiği tüketici
    yazıyor; kasıtlı olarak biz ML/bot-tespiti inşa etmiyoruz).
- **`CaptchaGate`** artık genel bir doğrulama gate'i: `require_captcha`/
  `require_account`/`extra_checks` ile mod seçiliyor -- sadece captcha
  (varsayılan), sadece hesap (görsel yok, sadece doğru hesapla giriş),
  ikisi ("safety mod"), sadece tıklama (tek-kullanımlık gizli link tek
  kanıt), ya da tümüne kendi katmanlarını ekleme. `verify()` artık bir
  `CheckResult` döndürüyor (`.verified`/`.failed_check`/`.passed` --
  frontend "önce Discord ile giriş yap" gibi yönlendirebilsin diye) ama
  hâlâ truthy (`if await gate.verify(...):` çalışıyor). Consuming olan
  captcha check'i her zaman en sona çalışıyor -- daha ucuz bir check
  patlarsa doğru çözülmüş captcha boşa gitmesin diye.
- `CaptchaVerified` event'i artık `checks_passed: list[str]` taşıyor -- bot
  ne kadar güçlü doğrulandığını bilerek tepki verebilir.
- **`get_current_user_optional`** (`discord_webapi.auth.dependencies`): 401
  fırlatmak yerine giriş yoksa `None` döndüren dependency -- gate verify
  endpoint'i hesap check'i için giriş yapmış kullanıcıyı okuyor ama
  captcha-only/click-only modlarda giriş zorunlu olmadan da çalışıyor.
- Dashboard: `GET /api/captcha/gate/{token}` artık `GateInfo` döndürüyor
  (challenge + `requires_captcha`/`requires_account` -- frontend neyi
  render edeceğini bilsin diye); `POST .../verify` gövdesi artık
  `{captcha_response?, signals?}` ve giriş yapmış kullanıcıyı OAuth
  session'ından çözüyor. `VerificationRequest.challenge` artık nullable
  (captcha'sız modlar için), SQL sütunu da nullable.

Yeni testler dahil (hesap-only gate'in doğru kullanıcıyı gerçek OAuth
giriş akışıyla şart koşması -- HTTP üstünden uçtan uca, `respx`-mock'lu
login ile; safety mod; click-only; kendi extra_check'ini yığma; check
edge case'leri). 598 test yeşil (1 ortam-bağımlı Postgres testi hariç),
ruff+mypy temiz.

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
