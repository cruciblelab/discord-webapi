# Geliştirici Notları (oturumlar arası kalıcı hafıza)

## Test coverage artırma (bu oturumda tamamlandı, fiziksel test beklerken)

Kullanıcı fiziksel testleri akşama erteledi, bu arada "test coverage artır"
ve "builtins genişlet" istedi (PyPI/repo taşıma işine hiç dokunmadık,
o kullanıcının kendi işi). `pytest-cov` ile ölçüldü: %91 → %95.

En değerli bulgu: **`require_role` fonksiyonu (public API, `discord_webapi`
top-level'dan export ediliyor) hiç test edilmiyormuş** — sıfır coverage.
Diğer önemli boşluklar: `bot/extension.py`'nin bot-tarafı wiring
fonksiyonlarının hiçbiri (`install_member_lookup` vb.) doğrudan test
edilmiyordu (sadece `DiscordWebAPI.__init__` üzerinden dolaylı), `single_process_lifespan`'ın
bot-başlatma-hatası yolu hiç tetiklenmemişti, `CommandRegistry.command_meta`
decorator'ı ve gerçek slash-command `interaction_check` gövdesi (sadece
prefix/hybrid'in `global_check`'i test ediliyordu) hiç çağrılmamıştı.

Eklenen test dosyaları: `tests/unit/test_bot_extension.py`,
`tests/unit/test_bridge_not_found_paths.py`, `tests/unit/test_registry_misc.py`,
`tests/integration/test_require_role.py`, ayrıca `test_storage.py`'ye
lazy `__getattr__` testi eklendi.

257 test yeşil (1 ortam-bağımlı Postgres testi hariç), ruff+mypy temiz.
Kalan düşük-coverage alanlar (`discord_webapi/__init__.py` %82,
`storage/sql.py` %87) çoğunlukla migration/hata-yolu kenar durumları —
düşük öncelik, bilerek derinleştirilmedi.

## Harici inceleme geri bildirimi (tamamlandı)

Kullanıcı önceki iki denetim raporunu (auth/authz + jobs/çoklu-sunucu)
harici birine incelettirmiş, üç nokta gelmiş:

1. `RedisTransport`/`RedisJobQueue` imzasız/kimlik doğrulamasız — çoklu-
   tenant paylaşımlı Redis'te risk. **Yanıt**: bilinçli tasarım kararı
   olduğu zaten dokümante edilmişti, ama gerçek bir iyileştirme yapılabilir
   gördüm: `namespace=` parametresi ekledim (`DEFAULT_NAMESPACE =
   "discord_webapi"`, geriye dönük uyumlu) — kanal/kuyruk isimleri artık
   `{namespace}:events`, `{namespace}:jobs:queue:...` şeklinde. Bu
   authentication değil ama farklı tenant'ların (ayrı `namespace` ile)
   aynı Redis'te yanlışlıkla birbirinin event/RPC/job trafiğini
   görmesini engelliyor. Gerçek mutually-untrusted izolasyon için hâlâ
   ayrı Redis DB/ACL gerekiyor, dokümante edildi.
2. `TokenBucketLimiter._buckets` sınırsız büyüyor — **düzeltildi**:
   `max_tracked_keys` (varsayılan 10.000) ile `OrderedDict` tabanlı
   LRU eviction eklendi.
3. `RedisTransport`'un "bir komuta tek handler" kısıtlaması — **bilinçli
   olarak değiştirilmedi**, dağıtık kilit/lease mekanizması eklemek
   library'nin basitlik hedefine (plain pub/sub, Streams/consumer-group
   yok) aykırı olurdu; operasyonel dokümantasyonla ele alınmaya devam
   ediyor (`docs/DAGITIM.md`'deki "tam olarak bir bot_process.py" notu).

**Refactor detayı**: `RedisTransport`/`RedisJobQueue`'daki modül-seviyesi
sabitler (`EVENTS_CHANNEL`, `_RPC_REQUEST_PREFIX` vb., `_QUEUE_PREFIX`,
`_STATUS_PREFIX`) instance-seviyesine taşındı (`self._events_channel`,
`self._queue_key()` vb.) çünkü artık `namespace`'e bağlı olarak her
instance farklı bir prefix kullanabiliyor — modül sabitleri olarak
kalamazlardı.

226 test yeşil (gerçek Redis'e karşı çalıştırıldı — ortamda
`redis-server` başlatılıp doğrulandı), ruff+mypy temiz. Yeni testler:
`tests/unit/test_ratelimit.py` (LRU eviction), `tests/unit/
test_redis_transport_namespace.py`, `tests/unit/test_redis_job_queue.py`'ye
eklenen namespace-isolation testi.

## Kuyruk sistemi taraması (tamamlandı)

Kullanıcının "genel bir tarama daha yap, buglar/kırılma yerleri" talebiyle
bir subagent'a kuyruk sistemi + çoklu sunucu refactoring'i + facade
değişikliklerini kapsayan geniş bir denetim yaptırıldı (önceki auth/authz
denetimi tekrar edilmedi, o kısım zaten temizdi). İki gerçek bug bulundu,
ikisi de `discord_webapi/jobs/redis.py`'de:

1. **TTL, pending/running durumundaki job'lara da uygulanıyordu** — worker
   backlog'u/kapalı kalması `result_ttl_seconds`'tan uzun sürerse, job
   kuyrukta beklerken status'u sessizce silinip job kayboluyordu. Fix:
   TTL artık sadece terminal state'e (succeeded/failed) uygulanıyor.
2. **`register_worker()`, `start()`'tan sonra çağrılırsa sessizce
   hiçbir şey yapmıyordu** (BLPOP key listesi `start()` anında
   sabitleniyor). `InProcessJobQueue`'nun geç register'ı sessizce kabul
   etmesiyle tutarsız — dev'de çalışan kod prod'da (Redis) sessizce
   bozulabilirdi. Fix: artık `RuntimeError` fırlatıyor.

Ayrıca iki küçük düzeltme: `_with_job_queue`'da `start()` başarısız
olursa `stop()` çağrılmıyor (kaynak-durumu hatası önlendi);
`for_bot_process()`'e `job_queue=...` eklendi (bot/Gateway erişimi
gereken job handler'ları için, önceden sadece `for_web_process`'te vardı).

**Not**: Bu oturumda ortamda gerçek bir Redis sunucusu (`redis-server`)
başlatılıp testler ona karşı gerçekten çalıştırıldı (önceki oturumlarda
Redis'e bağımlı testler hep skip ediliyordu, lokal ortamda Redis yoktu)
— 220 test yeşil, hepsi gerçek geçti, sadece 1 ortam-bağımlı Postgres
testi (Postgres kurulu değil) skip/fail.

## Kuyruk sistemi / background jobs (tamamlandı)

Kullanıcının "sırada kuyruk sistemi var" talebiyle eklendi (çoklu sunucu
işinden hemen sonra, çoklu bot hâlâ ertelenmiş durumda).

**Mimari**: `Transport`'un aynı deseni tekrarlandı — `discord_webapi/jobs/`
paketi, `JobQueue` Protocol'ü (`base.py`) + `InProcessJobQueue` (varsayılan,
asyncio.Queue + N worker task, zaten competing-consumer semantiği veriyor
tek process içinde) + `RedisJobQueue` (`redis.py`, `RPUSH`/`BLPOP` ile).

**Önemli tasarım farkı — `RedisTransport`'tan bilinçli olarak farklı**:
`RedisTransport`'un RPC'si "bir komuta tam olarak bir handler" kısıtlaması
taşıyordu (plain pub/sub — iki process aynı komutu register ederse
undefined davranış). Redis list'ler (`RPUSH`/`BLPOP`) bunun tam tersini,
GERÇEK competing-consumer semantiğini bedavaya veriyor — kaç tane worker
process aynı `job_type`'ı register edip `start()` çağırırsa çağırsın,
Redis aynı job_id'yi iki worker'a birden vermemeyi garanti ediyor. Bu
yüzden job queue, transport'tan farklı olarak GERÇEK yatay ölçekleme
için tasarlandı (birden fazla worker process, ayrı makinelerde).

**Yapılanlar**:
1. `discord_webapi/jobs/base.py`: `JobStatus` (pydantic model) + `JobQueue`
   Protocol (`start`/`stop`/`register_worker`/`enqueue`/`get_status`).
2. `discord_webapi/jobs/memory.py`: `InProcessJobQueue`.
3. `discord_webapi/jobs/redis.py`: `RedisJobQueue` — `discord_webapi:jobs:
   queue:{job_type}` (RPUSH/BLPOP) + `discord_webapi:jobs:job:{job_id}`
   (JSON status, TTL'li — varsayılan 24 saat, `result_ttl_seconds`).
4. `discord_webapi/jobs/api.py`: `build_jobs_router()` —
   `POST /api/guilds/{id}/jobs/{job_type}` (enqueue, rate-limited,
   manage_guild gerektiriyor, 202+job_id döner) ve
   `GET /api/guilds/{id}/jobs/{job_id}` (status poll — başka guild'in
   job'ı 404, cross-guild leak yok).
5. `discord_webapi/jobs/worker.py::run_worker(queue)` — FastAPI'siz
   bağımsız worker process girişi (`run_bot_process` ile aynı desen).
6. `DiscordWebAPI(job_queue=..., ...)` + `install(enable_jobs=True)` —
   opt-in, `job_queue` verilmeden `enable_jobs=True` denenirse açık
   RuntimeError. `for_web_process`'e de `job_queue` parametresi eklendi.
7. `DiscordWebAPI.lifespan()`/`web_lifespan()` artık `job_queue`'yu da
   otomatik start/stop ediyor (`_with_job_queue` helper) — tek-process
   kurulumda consumer'ın elle `queue.start()/.stop()` çağırmasına gerek yok.
8. `examples/split_deployment/worker_process.py` — üçüncü opsiyonel
   process tipi, `web_process.py`'ye `enable_jobs=True` + `RedisJobQueue`
   eklendi.
9. Contract test suite `tests/jobs/` (Transport'un `tests/transport/`
   deseniyle birebir aynı — her iki implementasyon da aynı testlerden
   geçiyor) + `tests/integration/test_jobs_api.py` (dashboard API) +
   `tests/integration/test_facade.py`'ye `enable_jobs` wiring testi.

193 test yeşil (1 ortam-bağımlı Postgres testi hariç), ruff+mypy temiz.

**Not**: `tests/jobs/test_contract.py` ismi `test_transport`'un
`test_contract.py`'siyle çakışıp pytest module-name collision hatası
veriyordu (her iki `tests/*/` dizininde de `__init__.py` yok) —
`tests/jobs/test_jobs_contract.py` olarak yeniden adlandırılarak çözüldü.

**Sırada (kullanıcı isterse)**: çoklu bot hâlâ ertelenmiş durumda
(guild_id→hangi bot routing'i gerektirir, disnake/pycord'u ertelerken
kullanılan mantıkla aynı kategoride).

## Çoklu sunucu/makine deployment (bot ve web ayrı process, tamamlandı)

Kullanıcı "5-6 büyük sunucuda çalışan botlar için sağlam bir sistem"
istedi — netleştirince asıl istenen: bot'un Discord Gateway bağlantısı bir
process'te, FastAPI dashboard'ı ayrı process'te/makinede, web tarafı N
replica olarak yatay ölçeklenebilsin (load balancer arkasında). Çoklu
bot (birden fazla farklı bot/token) ve job queue şimdilik ertelendi
(kullanıcı: "kuyruk sistemi ve çoklu botu şuanlık boşverelim").

**Kritik keşif**: `RedisTransport` zaten multi-process/multi-machine için
tasarlanmıştı (v0.1'den beri), ve authz/members/guilds gibi her alt sistem
zaten SADECE `Transport` üzerinden konuşuyordu — bot objesine hiç direkt
erişmiyorlardı. Tek istisna: `commands/api.py` (dashboard'un command
listeleme/override endpoint'leri), `app.state.discord_webapi_commands`
üzerinden CANLI bir `CommandRegistry` nesnesine DOĞRUDAN erişiyordu — bu,
web ve bot'un aynı process'te olmasını zorunlu kılan TEK parçaydı.

**Yapılanlar**:
1. `commands/registry.py::install_command_registry_bridge(registry, transport)`
   eklendi — `list_command_status`/`set_command_override` RPC'lerini
   registry'nin yaşadığı process'te cevaplıyor.
2. `commands/api.py` artık `app.state.discord_webapi_commands`'a hiç
   bakmıyor, sadece `transport.request(...)` çağırıyor — tek-process modda
   (`InProcessTransport`) davranış birebir aynı kalıyor (sadece bir RPC
   round-trip'e dönüşüyor, aynı process içinde).
3. `DiscordWebAPI.__init__`'te `bot`/`auth` artık opsiyonel (`None`
   olabilir) — `self.registry` de `CommandRegistry | None` oldu, sadece
   `bot is not None` olduğunda kuruluyor (RedisTransport'un "bir command'a
   sadece bir handler" kuralı gereği — web-only process asla bu RPC'leri
   register etmemeli).
4. İki yeni classmethod: `DiscordWebAPI.for_bot_process(bot=..., transport=...)`
   (FastAPI yok, sadece bot-side wiring) ve
   `DiscordWebAPI.for_web_process(transport=..., auth=...)` (bot yok,
   sadece web-side wiring). Mevcut `DiscordWebAPI(bot=..., auth=...)` /
   `quickstart()` API'si hiç değişmeden çalışmaya devam ediyor.
5. `bot/extension.py`'ye `run_bot_process(bot, transport, token)`
   (FastAPI'siz, sonsuza kadar bekleyen bot-only entry point) ve
   `web_only_lifespan(transport)` (bot'suz FastAPI lifespan) eklendi.
6. `examples/split_deployment/` (`bot_process.py` + `web_process.py` +
   README) — gerçek Redis+Postgres ile nasıl çalıştırılacağını gösteriyor.
7. Yeni test: `tests/integration/test_split_deployment.py` — iki ayrı
   `DiscordWebAPI` nesnesi (birbirine hiç referans vermeden, sadece
   paylaşılan `InProcessTransport` — gerçek `RedisTransport`'un makineler
   arası paylaşımının yerine geçiyor) ile GET/PATCH commands API'sinin
   gerçekten sadece Transport üzerinden çalıştığını doğruluyor.

Mevcut testlerden ikisi (`test_commands_api.py`, `test_audit_log.py`)
`app.state.discord_webapi_commands` yerine `install_command_registry_bridge`
+ `app.state.discord_webapi_transport` kullanacak şekilde güncellendi.

182 test yeşil (1 ortam-bağımlı Postgres testi hariç), ruff+mypy temiz.

**Sırada (kullanıcı isterse)**: çoklu bot (farklı bot/token'ları tek
dashboard'dan yönetme — guild_id→hangi bot routing'i gerektirir, bilinçli
olarak ayrı/opt-in bir katman olarak ele alınmalı) ve job queue (Celery/arq
tarzı, `Transport` gibi opt-in bir modül olarak) hâlâ ertelenmiş durumda.

## Kapsamlı güvenlik denetimi (v0.5 sonrası, tamamlandı)

Genişleme bittikten sonra planlanmış olan tam kapsamlı güvenlik denetimi
bir subagent ile yapıldı (diff değil, tüm paket okunarak). Sonuç: mimari
zaten sağlam çıktı (OAuth2 state/CSRF `secrets.compare_digest` ile doğru,
session cookie flag'leri doğru, SQL tamamen ORM üzerinden/injection riski
yok, authz guild/channel'a fail-closed, `GET /api/guilds` client input'una
güvenmiyor, token'lar hiçbir yerde loglanmıyor). İki gerçek bug bulundu ve
düzeltildi:

1. Session-management endpoint'lerinde (`logout`, `sessions` GET/DELETE)
   rate limit yoktu — eklendi (`DiscordAuth(session_management_rate_limiter=...)`).
   Bunu yaparken `TokenBucketLimiter` sınıfı `discord_webapi/ratelimit.py`'ye
   (bağımsız, auth'a hiç import etmeyen bir modül) taşındı çünkü
   `commands.ratelimit`'i doğrudan auth/oauth.py'den import etmek circular
   import'a yol açıyordu (`auth.oauth → commands.ratelimit →
   auth.dependencies → auth.oauth`). `commands/ratelimit.py` artık sadece
   re-export + `rate_limit_dependency` (FastAPI `Depends` sarmalayıcısı,
   hâlâ auth'a bağımlı, ama artık `TokenBucketLimiter`'ın kendisi değil).
2. `DiscordAuth._refresh_locks` dict'i asla küçülmüyordu — token refresh
   gereken her session için kalıcı bir lock birikirdi. `finally` bloğunda
   evict edilecek şekilde düzeltildi.

Düşük öncelikli, düzeltilmeyen bulgular: `commands/ratelimit.py`'nin
`_buckets` dict'i de aynı şekilde sınırsız büyüyor (sadece bellek, auth
bypass değil) — ileride bakılabilir. RedisTransport'un pub/sub kanalları
imzasız (Redis'in kendisi güvenilir altyapı olmalı varsayımı, docstring'de
zaten belirtiliyor ama daha net bir uyarı eklenebilir).

## v0.5 — genişleme: `GET /api/guilds`, oturum yönetimi (tamamlandı)

Hardening turu bittikten sonra kullanıcının "ikisini de yap" dediği iki
genişleme özelliği:

1. **`GET /api/guilds`** (`discord_webapi/guilds/`): kullanıcının kendi
   Discord `guild_ids` listesindeki hangi sunucuların hem bu bot'un içinde
   olduğunu HEM DE kullanıcının orada "Manage Server" yetkisi olduğunu
   döndürür — "sunucu seç" ekranı için, tüketicinin tek tek her guild'i
   deneyip 403/404 almasına gerek kalmadan. Bot tarafı
   (`commands/bridge.py::list_manageable_guilds` + `bot/extension.py::
   install_guild_listing`) botun warm Gateway cache'inden cevaplıyor, web
   tarafı (`guilds/api.py`) `has_permission(..., "manage_guild")` ile
   filtreliyor (izin kontrolü kasıtlı olarak transport cevabından SONRA,
   web tarafında yapılıyor).
2. **Oturum yönetimi / "her yerden çıkış yap"**: `SessionStore` protokolüne
   `list_by_user(user_id)` eklendi (Memory + SQL), `DiscordAuth`'a
   `GET /auth/discord/sessions` (kendi aktif oturumlarını listele,
   `is_current` bayrağıyla, şifreli token alanları asla dönmez —
   `SessionSummary` modeli bilerek dar) ve
   `DELETE /auth/discord/sessions/{session_id}` (sadece kendi oturumunu
   iptal edebilir — başka bir `user_id`'ye ait session_id 404 döner, 403
   değil — session'ın var olup olmadığını sızdırmamak için).

Her ikisi de mevcut modül-başına-endpoint deseniyle (authz/consent/audit
gibi) uyumlu; yeni testler: `tests/integration/test_guilds_api.py`,
`tests/integration/test_auth_flow.py`'ye eklenen 4 test, `tests/unit/
test_storage.py` ve `test_sql_storage.py`'ye eklenen `list_by_user` testi.
177 test yeşil (Postgres-bağlantısı gerektiren 1 test yerelde ortam
yüzünden skip/fail oluyor, kod tarafıyla ilgisiz), ruff+mypy temiz.


Bu dosya proje reposunun içinde tutuluyor (git ile push ediliyor) çünkü
oturum hafızası kalıcı değil ve bazen proje dizini dışına (plan dosyaları,
scratchpad vb.) yazılan notlar bir sonraki oturumda erişilemez hale
gelebiliyor. **Her yeni oturuma başlarken önce bu dosyayı ve
`CHANGELOG.md`'yi oku.** Bir şey unutulduysa/karışıksa buraya geri dön.

Ayrıca bkz: `/root/.claude/plans/encapsulated-nibbling-pnueli.md` (orijinal
v0.1 mimari planı, proje dışında — orada olmayabilir, bu yüzden kritik
kararlar buraya da yansıtılıyor).

## Şu ana kadarki durum (v0.3 tamamlandı, doğrulandı)

- Transport (InProcess + Redis, contract test'li, `unsubscribe()` dahil)
- Auth: opak session, cookie + mobil Bearer token, `HTTPConnection` tabanlı (websocket'te de çalışıyor)
- Commands: registry, canlı enable/disable, per-command cooldown, `invocation_count` dahili sayaç
- AppRole: bot-özel roller, `AuthzStore` (Memory/SQL)
- Guild-rol yetkilendirme: `require_guild_permission`, `GuildMemberCache`
- Çoklu DB: SQLite/Postgres/MySQL
- WebSocket canlı relay (opt-in)
- `quickstart()`, `default_intents()`, bundled dashboard HTML
- **Audit log** (`discord_webapi/audit/`): `AuditStore` (Memory/SQL), `AuditLogger`, `GET /api/guilds/{id}/audit-log`. Opt-in (`enable_audit_log=False` varsayılan). Şu an sadece komut override'ları (`command.set_override`) ve AppRole yazmaları (`app_role.set`/`app_role.delete`) kaydediliyor — auth login/logout kapsam dışı (kullanıcı bunu seçti).
- **Cookie/consent kaydı** (`discord_webapi/consent/`): `ConsentStore` (Memory/SQL, ayrı protokol — `Session`'a alan eklenmedi), `GET/POST /api/consent`. Opt-in (`enable_cookie_consent=False` varsayılan). Notice'ın metni/UI'ı tamamen tüketiciye bırakıldı — kütüphane sadece "kullanıcı X, Y versiyonunu Z zamanında onayladı" kaydını tutuyor.
- **`discord_webapi/builtins/`**: hazır, tam-özellikli, serbestçe import edilebilir komutlar için klasör. `_shared.py`'de ortak, bağımsız kullanılabilir parçalar (`check_role_hierarchy`, `notify_member_best_effort`) — kullanıcı isterse sadece bunları alıp sıfırdan yazdığı komuta gömebilir, isterse hazır komutu (`ban.py`/`kick.py`/`timeout.py`) olduğu gibi kullanır, isterse hibrit yapar (kullanıcının bu oturumda tam olarak istediği şey: "ayrı ayrı kullanmak isteyenler yerde kullanır ya da sıfırdan yazarlar ya da hibrit kullanırlar"). Şu an: `ban.py`, `kick.py`, `timeout.py` (Discord'un kendi native timeout'unu kullanıyor, ayrı mute-role sistemi yok) + `README.md`. Kalıcı veri gerektiren gelecekteki builtin'ler (ör. `warn.py`) `AuditStore`/`ConsentStore` ile aynı desende kendi `Store` protokolünü alacak — DB/cache/permission katmanları hep ayrı, birleştirilebilir parçalar olarak kalacak, tek bir dosyaya gizli bağımlılık gömülmeyecek.
- `TESTING.md`: fiziksel test kontrol listesi (kullanıcı henüz Termux'ta çalıştırmadı).

Tüm otomatik testler yeşil (128 passed, 20 skipped — skip'ler yerelde
MySQL servisi çalışmadığından; Postgres testleri geçiyor), `ruff check` ve
`mypy discord_webapi` temiz.

## Önemli kapsam kararı: builtin/eklenti sistemi bilinçli olarak küçültüldü

Kullanıcı aslında çok daha büyük bir şey tarif etti: üçüncü taraf
paket/eklenti formatı — `.json` manifest (isim, versiyon, yazar,
bağımlılıklar), bir "build/install" adımı, neredeyse bir mini app-store /
plugin-VM sistemi (kullanıcının benzetmesi: kütüphane "ana yemek değil,
yanında gelen kaliteli ikram" — Discord bot geliştirmenin FastAPI'si).

Bu, tek oturumda makul şekilde inşa edilemeyecek kadar büyük ve ayrı bir
tasarım gerektiren bir iş (paket formatı, resolver/installer, üçüncü taraf
kod çalıştırmanın güvenlik incelemesi, versiyonlama politikası) — zaten
orijinal v0.1 planında "core donunca, vakit geçirmek için eklenir" diye
ertelenmiş "extension/structure sistemi" fikriyle aynı kategoride.

**Bu oturumda teslim edilen/küçültülen versiyon**: `discord_webapi/builtins/`
klasörü, `_shared.py`'de ayrıştırılmış bağımsız parçalar +
`ban.py`/`kick.py`/`timeout.py`. Kullanıcıya kapsam daraltması söylendi ve
kullanıcı onayladı ("ertelemen iyi ama altyapısı iyi olsun, zaten süs bu,
ana yemek değil — meze; her şeyi ayrı ayrı kullanmak isteyenler kullanır,
sıfırdan yazarlar ya da hibrit yaparlar, kendileri bilir"). Manifest/
versiyon/installer sistemi hâlâ YOK ve hâlâ bilinçli olarak ertelendi —
`builtins/README.md`'nin son bölümünde neden ertelendiği açıklamasıyla
birlikte duruyor.

## builtins durumu (güncel)

- `_shared.py`: `check_role_hierarchy`, `notify_member_best_effort` (bağımsız kullanılabilir).
- `ban.py`, `kick.py`, `timeout.py`: stateless moderasyon komutları, `_shared.py`'i kullanıyor.
- `warn.py`: **ilk kalıcı-durumlu builtin**. `WarnStore` protokolü + `MemoryWarnStore` (varsayılan) + `SQLWarnStore` (kendi `create_all()`'ı, core `storage.sql.create_all()`'dan tamamen bağımsız — `dwa_builtin_warns` tablosu sadece `SQLWarnStore` gerçekten kullanılırsa oluşur). Opsiyonel `auto_timeout_after=N` ile otomatik timeout eskalasyonu (varsayılan kapalı).
- `welcome.py`: **ilk komut-olmayan builtin** — `on_member_join` event listener, `setup(bot, channel_id=..., dm_instead=...)`. Kanal asla tahmin edilmiyor, açıkça verilmesi gerekiyor.

Hepsi 154 test ile kapsanıyor (unit: ban/kick/timeout/warn/warn_sql/welcome/shared), ruff+mypy temiz. Commit: bkz. git log.

## Cookie-consent banner dashboard entegrasyonu (tamamlandı)

Kullanıcı builtin eklemeyi durdurup ("hazır komut eklemeyelim şuan zamanı
değil") ana plana dönmemizi istedi; plan dosyası (`/root/.claude/plans/
encapsulated-nibbling-pnueli.md`) v0.3'ün tamamını (audit/consent/builtins
kararları + bilinçli ertelenen paket sistemi) yansıtacak şekilde
güncellendi, sonra kullanıcı üç açık v0.3+ maddesinden ("cookie-consent
banner", "multi-bot/shard routing", "channel-level permission overwrite")
ilkiyle başlamayı seçti — **hepsini istiyor, sırayla ekleyeceğiz**.

- `discord_webapi/web/dashboard.html`: `<!--COOKIE_CONSENT_BANNER-->` ve
  `/*COOKIE_CONSENT_SCRIPT*/` yer tutucuları eklendi.
- `discord_webapi/web/dashboard.py`: `build_default_dashboard_router(
  enable_cookie_consent=, cookie_consent_message=, cookie_consent_version=)`
  — banner metni tamamen tüketiciye ait (varsayılan bir İngilizce cümle var
  ama serbestçe override edilebiliyor), `cookie_consent_version` değişince
  herkes tekrar onaylamak zorunda kalıyor (localStorage + `/api/consent`
  karşılaştırması `COOKIE_CONSENT_VERSION` üzerinden).
- Banner JS'i: giriş yapılmamışsa `/api/consent` 401 döner, bu durumda
  localStorage'a "reddedilmiş/kapatılmış" bayrağı yazıp göstermeye devam
  ediyor; "Accept" tıklanınca hem localStorage hem (giriş yapılmışsa)
  `POST /api/consent` ile kalıcı kayıt.
- `DiscordWebAPI.install()`/`quickstart()`'a `cookie_consent_message`/
  `cookie_consent_version` parametreleri eklendi, `enable_cookie_consent=True`
  olduğunda hem consent API'sini hem dashboard banner'ını aynı config'le
  bağlıyor.
- Testler: `test_default_dashboard.py`'de banner var/yok + özelleştirme
  testleri, `test_consent_api.py`'de banner+API'nin aynı versiyonu
  paylaştığını doğrulayan uçtan uca test. 158 test yeşil, ruff+mypy temiz.

## Termux fiziksel test sürecinde çıkan iki gerçek sorun (çözüldü)

1. **Kullanıcı projeyi Android paylaşılan depolamada (`/storage/emulated/0/...`)
   çalıştırıyordu** — bu Android FUSE katmanı symlink desteklemiyor, `python -m
   venv` bu yüzden `Permission denied: 'lib' -> '.venv/lib64'` hatası verdi, ve
   git clone bazı dosyaları (ör. `.env.example`) düzgün yazamadı. **Kod
   tarafında bir bug değildi** — çözüm: projeyi Termux'un kendi ev dizininde
   (`~`, yani `/data/data/com.termux/files/home/...`) çalıştırmak.
2. **`quickstart()`'ta `mobile_redirect_uri` parametresi yoktu** — kullanıcı
   `PATCH` gerektiren bir endpoint'i tarayıcı adres çubuğuna yazıp "Not
   Allowed" (405) aldı; asıl sorun mobilde PATCH+auth header göndermenin
   pratik bir yolu olmamasıydı (cookie mobil tarayıcıda kolay okunamıyor).
   **Fix**: `DiscordWebAPI.quickstart(mobile_redirect_uri=...)` eklendi,
   `examples/full_featured_bot/main.py`'de varsayılan olarak açıldı
   (`{base_url}/mobile-login-done` — gerçek bir sayfa yok, sadece
   `session_id`'yi URL'den okumak için). `TESTING.md` madde 2 ve 3 artık bu
   akışı ve somut `curl -X PATCH -H "Authorization: Bearer ..."` komutlarını
   içeriyor.

## `session_id` boş geliyor sorunu (çözüldü — kod bugı değildi)

Kullanıcı `/mobile-login-done`'da hep boş `session_id` gördü. uvicorn
access log'unu inceleyince asıl sebep ortaya çıktı: kullanıcı gerçek bir
OAuth yönlendirmesiyle değil, **URL'i elle yazarak/yapıştırarak** o
sayfaya gidiyordu; log'da bir de gerçek mobil giriş denemesinde
`GET /auth/discord/login?%20mobile=true` görüldü — `%20` bir boşluk,
yani `?mobile=true` değil `? mobile=true` yazılmış/yapıştırılmış, bu da
FastAPI'nin `mobile` parametresini tanımamasına (sessizce `mobile=False`
varsaymasına) yol açtı. Otomatik testler (`test_mobile_auth.py`)
kütüphanenin kendisinin bu konuda sorunsuz olduğunu zaten kanıtlıyordu —
sorun tamamen elle URL yazmaktan kaynaklanan bir kullanıcı hatasıydı.

**Kalıcı çözüm** (URL yazma ihtiyacını tamamen ortadan kaldırıyor):
- Bundled `dashboard.html`'e tıklanabilir bir **"Mobil giriş (session_id
  al)"** butonu eklendi (`/auth/discord/login?mobile=true`'ya gidiyor) —
  artık kimse bu URL'i elle yazmak zorunda değil.
- `examples/full_featured_bot/main.py`'ye gerçek bir `/mobile-login-done`
  sayfası eklendi (önceden 404'tü) — `session_id`'yi büyük, kolayca
  seçilebilir/kopyalanabilir bir kutuda gösteriyor; `session_id` boşsa
  "gerçek bir mobil login yönlendirmesiyle gelmedin, butona tekrar tıkla"
  diye açıkça uyarıyor (sessiz 404 yerine).
- `TESTING.md` madde 2 artık "URL'i elle yazma, butona tıkla" diyor.
- Yeni test: `test_dashboard_has_a_clickable_mobile_login_link`. 159 test
  yeşil, ruff+mypy temiz.

## v0.4 tamamlandı: Channel-level permission overwrite

Kullanıcı Termux/mobil test sürecinde çok kafası karıştığı için ("kafam
çok karışıyor") büyük, kapsamlı bir v0.4 güncellemesi istedi: yeni
özellikler + sağlamlaştırma, sonra kontrolleri yap, sonra **bölüm bölüm**
kurulum + test adımlarını ver (her bölümden sonra kullanıcı rapor verecek,
ben kontrol edip düzeltip bir sonraki bölümü vereceğim — bu bir sonraki
oturumda da devam edecek bir iş akışı, unutma).

- **`require_channel_permission`**: `require_guild_permission`'dan farkı,
  guild-level izne sahip olsan bile o kanala özel bir override (Discord'un
  "Kanal İzinleri" / channel overwrite sistemi) o izni geri alabiliyorsa
  reddediyor. `ChannelPermissionCache` (`authz/cache.py`, TTL'li — 30sn
  varsayılan, `AppRoleCache` ile aynı basit desende, push-invalidation
  yok çünkü channel overwrite'lar guild membership'ten çok daha az
  değişiyor). Bot tarafında `install_channel_permission_lookup`
  (`bot/extension.py`) — Discord'un kendi `channel.permissions_for(member)`'ını
  kullanıyor (guild rolleri + kanal overwrite'ları otomatik birleşiyor),
  ekstra REST çağrısı yok, aynı warm-Gateway-cache-only ilkesi.
  `commands/bridge.py`'de `get_channel_permissions()`.
- `DiscordWebAPI(channel_permission_cache_ttl_seconds=30.0)` yeni parametre.
- `full_featured_bot`'ta demo endpoint: `GET /api/guilds/{guild_id}/channels/{channel_id}/can-send`.
- Testler: `tests/unit/test_authz.py`'ye 3 yeni `ChannelPermissionCache`
  testi, yeni `tests/integration/test_channel_permissions.py` (4 test).
  166 test yeşil, ruff+mypy temiz.
- **Multi-bot/shard routing bilinçli olarak ertelendi** — üçüncü-taraf
  paket sistemiyle aynı gerekçe: birden fazla bot instance/shard'ın aynı
  dashboard'u paylaşması, `Transport`'un hangi guild'in hangi shard'a ait
  olduğunu nasıl bileceği gibi sorular kendi başına ayrı bir tasarım turu
  gerektiriyor. Kullanıcıya bu daraltma söylenmeli (henüz söylenmedi
  olabilir — sohbetin geri kalanını kontrol et).

## KRİTİK BUG BULUNDU VE DÜZELTİLDİ: slash komutlar hiç senkronize edilmiyordu

Bölüm 3'te kullanıcı `/ping` yazınca Discord'da slash komut hiç
görünmedi, `!ping` de cevap vermedi. Kod incelemesinde iki gerçek,
ciddi bug bulundu (kullanıcı hatası değil):

1. **`bot.tree.sync()` hiçbir yerde çağrılmıyordu.** discord.py, slash
   komutları `sync()` çağrılmadıkça Discord'a hiç göndermiyor — hatasız,
   sessizce. Bu, kütüphanenin en başından beri (v0.1'den) var olan bir
   eksiklik, hiçbir zaman fark edilmemiş çünkü hiçbir otomatik test gerçek
   bir Discord bağlantısı üzerinden `/komut` çalıştırmıyor.
   **Fix**: `DiscordWebAPI._on_ready()` artık `bot.tree.sync()`'i
   otomatik çağırıyor (`sync_commands: bool = True` yeni parametre,
   `DiscordWebAPI(...)` ve `quickstart(...)`'a eklendi). `on_ready` birden
   fazla kez tetiklenebileceği için (Gateway reconnect) sadece bir kez
   sync ediliyor (`self._commands_synced` guard). `sync_guild_id: int |
   None = None` yeni parametresiyle global sync yerine (ki ~1 saate kadar
   yayılma gecikmesi olabiliyor) tek bir test sunucusuna anında sync
   yapılabiliyor (`copy_global_to` + `sync(guild=...)`).
2. **`default_intents()` `message_content` intent'ini açmıyordu.** Bu
   olmadan discord.py mesaj metnini okuyamıyor, prefix komutlar
   (`!ping`) hiç eşleşmiyor. **Fix**: `default_intents()` artık
   `intents.message_content = True` da yapıyor; docstring Discord
   Developer Portal'da "Message Content Intent"i de açmak gerektiğini
   hatırlatıyor.

Testler: `tests/integration/test_facade.py`'ye 4 yeni test (sync
davranışı: varsayılan global, guild-scoped, kapalıyken hiç, birden fazla
`on_ready`'de sadece bir kez), `test_quickstart.py`'ye
`message_content` testi. `test_facade.py`'nin mevcut testi de
`sync_commands=False` ile güncellendi (o test gerçek bir Gateway
bağlantısı simüle etmiyor, `application_id` olmadan `sync()` zaten
patlardı — bu discord.py'nin kendi davranışı, kütüphane bugı değil).
171 test yeşil, ruff+mypy temiz.

`examples/full_featured_bot/main.py` ve `.env.example`'a `TEST_GUILD_ID`
env var'ı eklendi — doldurulursa `sync_guild_id`'ye geçiliyor.

**Bu, kullanıcının fiziksel testinin gerçek değerini kanıtlıyor** —
otomatik test paketi hiçbir zaman bunu yakalayamazdı, sadece gerçek bir
Discord sunucusunda gerçek bir bot çalıştırmak bunu ortaya çıkardı.

## İKİNCİ KRİTİK BUG: cooldown/invocation_count slash-hybrid'de çift işleniyordu

Bölüm 4'te kullanıcı `ping`'e "30 saniyede 1 kullanım" cooldown koyunca
komut **kalıcı olarak** cevap vermez oldu (2 dakika bekledi, hâlâ hiç
cevap yok). Kök neden analizi (discord.py kaynak kodu okunarak, tahmin
değil): `HybridCommand._check_can_run` (discord.py'nin kendi
`hybrid.py`'si) yorum satırında açıkça şunu söylüyor: "Bot global check
once / Bot global check" — yani bir hybrid komut **slash** olarak
çağrıldığında, `CommandTree._call` önce bizim wrap ettiğimiz
`interaction_check`'i çalıştırıyor, SONRA `HybridCommand.can_run` →
`_check_can_run` → `bot.can_run(ctx)` ile bizim `global_check`'imizi
**tekrar** çalıştırıyor — aynı tek çağrı için iki kez.

Sonuç: her gerçek `/ping` çağrısı cooldown bucket'ından 2 token
tüketiyordu (1 yerine), `invocation_count` 2'şer 2'şer artıyordu
(kullanıcının PATCH cevabında gördüğü `invocation_count: 6` tam olarak
3 gerçek çağrı × 2 ile eşleşiyor). "1 kullanımda 30sn" ayarlandığında
tek bir gerçek çağrı bucket'ı hemen negatife düşürüyor ve her yeni
deneme de (cooldown'dayken bile) `update_rate_limit()`'i tekrar
çağırarak `_last`'ı güncelliyor — pencere gerçekten sıfırlanana kadar
sürekli "hâlâ cooldown'dasın" durumuna dönüyordu, kullanıcı defalarca
deneyince bu neredeyse hiç bitmeyen bir döngüye benziyordu.

**Fix** (`discord_webapi/commands/registry.py`, `global_check`):
`ctx.interaction is not None` ise (yani bu zaten `interaction_check`
tarafından ele alınmış bir slash çağrısıysa) hiçbir şey yapmadan `True`
dön. Prefix-only çağrılar (`ctx.interaction is None`) hâlâ normal
şekilde kontrol ediliyor — onlar hiçbir zaman `interaction_check`'e
uğramıyor.

Yeni regresyon testi: `test_global_check_is_a_noop_for_slash_invoked_hybrid_commands`
(`tests/unit/test_command_cooldown.py`) — `global_check`'i art arda iki
kez çağırıp (discord.py'nin gerçekten yaptığı gibi) cooldown'un
tetiklenmediğini ve sayacın artmadığını doğruluyor. 172 test yeşil,
ruff+mypy temiz.

**Bu, kullanıcının ısrarla fiziksel test yapmasının değerini bir kez
daha kanıtlıyor** — hem sync bug'ı hem bu ikisi de hiçbir otomatik testte
yakalanamazdı, ikisi de gerçek Discord etkileşimi gerektiriyordu.

## Bölüm bölüm fiziksel test — durum (duraklatıldı, Bölüm 6'dan devam edilecek)

Kullanıcı `TESTING.md`'yi bölüm bölüm test etti (ben bölümü veriyorum,
o fiziksel olarak deniyor, rapor veriyor, ben kontrol edip düzeltiyorum,
sonra sıradaki bölümü veriyorum). **Şu ana kadar tamamlanan**:
- Bölüm 1 (kurulum): birkaç Termux'a özel sorun çıktı ve çözüldü (bkz.
  yukarıdaki "Termux fiziksel test sürecinde çıkan..." notu) — özetle:
  paylaşılan depolamada çalışmak (symlink desteklemiyor), venv
  aktivasyonunu unutmak, `--system-site-packages` sonrası `uvicorn`
  komutunun sistem kopyasını bulması (çözüm: `python -m uvicorn`).
- Bölüm 2 (auth: tarayıcı + mobil): sorunsuz geçti.
- Bölüm 3 (komut listeleme + enable/disable): **kritik bug bulundu**
  (slash komutlar hiç sync edilmiyordu + `message_content` intent eksikti)
  — ikisi de düzeltildi, sonra bölüm baştan tekrar denendi, sorunsuz geçti.
- Bölüm 4 (cooldown): **ikinci kritik bug bulundu** (hybrid komutlar slash
  olarak çağrılınca cooldown/invocation_count çift işleniyordu) —
  düzeltildi, tekrar denendi, sorunsuz geçti.
- Bölüm 5 (AppRole): sorunsuz geçti.
- **Bölüm 6'dan (guild-rol tabanlı yetkilendirme) itibaren henüz test
  edilmedi** — kullanıcı test sürecini duraklatıp mimari/felsefe
  konusunda bir endişesini konuştu (aşağıya bakın), sonra roadmap'ten
  devam etmeyi seçti. **Bir sonraki oturumda ya Bölüm 6'dan teste devam
  et, ya da kullanıcı başka bir şey isterse ona göre yönlen.**

## Kullanıcının mimari/felsefe endişesi (çözüldü, kod değişikliği gerekmedi)

Kullanıcı test sırasında "biz FastAPI gibi özgür değil de şablon/template
sistemi mi olduk" endişesi dile getirdi. Kök neden: bundled dashboard'da
komut enable/disable, cooldown ayarlama gibi işlemler için **hiç UI
yok** — bu yüzden test ederken curl/terminal kullanmak zorunda kalması
"böyle yapmalısınız" gibi hissettirmiş. Açıklandı ve kullanıcı kabul
etti: kütüphanenin kendisi (Protocol'ler, composable API, builtins'in
opt-in oluşu) gerçekten istenen özgür/FastAPI-gibi felsefede; sorun
sadece test aracının (bundled dashboard) bu spesifik işlemler için UI
sunmaması. **Kod değişikliği yapılmadı** — kullanıcı "şuan gerek yok"
dedi, ama gelecekte bundled dashboard'a enable/disable + cooldown UI'ı
eklemek roadmap'e not edildi (yukarıdaki v0.4+ aday listesine bakın).

## disnake/py-cord desteği: araştırıldı, kullanıcı kararıyla süresiz ertelendi

py-cord ayrı bir venv'de kurulup gerçek test paketimiz (172 test) onun
üstünde çalıştırıldı — **21 dosya import hatasıyla patladı**: py-cord'un
slash-komut mimarisi (`SlashCommand`/`ApplicationCommandMixin`,
`discord.app_commands`/`CommandTree` yok) discord.py'den kökten farklı.
"Aynı `discord` isim alanını kullanıyor, drop-in'dir" varsayımı somut
veriyle çürütüldü. Destek eklemek `commands/bridge.py` +
`commands/registry.py`'yi (kütüphanenin en kırılgan katmanı, az önce
tam da burada iki gerçek bug bulduk) iki ayrı mimariye göre yazmak
demek. **Kullanıcı kararı**: "discord.py'ye odaklanalım, py-cord/disnake
talebi çok daha küçük bir topluluk, ileride gerçek talep olursa
`discord-webapi-pycord` gibi ayrı bir paket çıkarılabilir, şimdi hiç
düşünmeyelim." Plan dosyasına da işlendi — bu madde artık v0.4+ aday
listesinde değil, kapalı bir karar olarak duruyor.

## Çekirdek dayanıklılık (hardening) turu — kullanıcı isteğiyle başlatıldı

Kullanıcı builtins'i yine erteledi, "önce core sistemleri/algoritmaları/
bağlantıları en sağlam kapsamlı şekilde tamamlayalım, küçük kalırsa hafta
sonu projesine dönme korkum var" dedi. `code-review` skill'i diff-bazlı
çalıştığı için (bu branch'te commit'lenmemiş diff yoktu) elle,
dosya dosya bir inceleme yaptım — **iki gerçek, ciddi bug** bulundu:

1. **`discord_webapi/transport/redis.py`**: `_read_loop`'un Redis bağlantı
   kopmasına karşı hiçbir dayanıklılığı yoktu — `RedisError` fırlayınca
   reader task'ı sessizce ölüyor, bir daha asla toparlanmıyordu. Fix:
   `_read_loop` artık `_read_loop_once()`'u bir dış retry döngüsüyle
   sarmalıyor, `RedisError` yakalanınca 1 saniye bekleyip
   `_resubscribe_all()` ile tüm kanallara (events + tüm registered RPC
   komutları + bekleyen reply kanalları) yeniden abone oluyor. Regresyon
   testi: `test_reader_loop_reconnects_after_a_dropped_connection`
   (gerçek Redis gerektirmiyor, fake pubsub ile deterministik).
2. **`discord_webapi/web/websocket.py`**: `commands_stream`, istemci
   bağlantıyı kapattığında bunu **hiç fark etmiyordu** — sadece kuyruktan
   okuyup gönderiyordu, websocket'ten hiç okuma yapmıyordu. O guild'de
   yeni bir event gelene kadar (belki hiç gelmeyebilir) subscriber+task
   sonsuza kadar askıda kalıyordu — uzun süreli bir deployment'ta gerçek
   bir kaynak sızıntısı. Fix: `_relay_until_disconnect()` artık iki paralel
   task çalıştırıyor (`_forward_events` + `_watch_for_disconnect`,
   `asyncio.wait(FIRST_COMPLETED)` ile), istemci kapanınca ikisi de düzgün
   iptal ediliyor. **Yan keşif**: Starlette'in ham `websocket.receive()`'i
   disconnect'te exception FIRLATMIYOR (sadece `receive_text`/`receive_json`
   gibi üst seviye metodlar fırlatıyor) — mesaj tipini elle kontrol edip
   `WebSocketDisconnect`'i kendimiz fırlatmamız gerekti, aksi halde ikinci
   `receive()` çağrısı `RuntimeError` fırlatıyordu (test bunu hemen yakaladı).

190 test yeşil (18 yeni: Redis reconnect testi + gerçek Redis'e karşı
çalışan entegrasyon testleri artık local Redis çalıştığı için skip
olmuyor), ruff+mypy temiz.

3. **`discord_webapi/storage/sql.py`**: `set_override`/`set_app_role`/
   consent'in `set()`'i "oku, yoksa oluştur" deseninde — aynı satırı ilk
   kez yazmaya çalışan iki eşzamanlı istek, ikisi de "yok" görüp ikisi de
   INSERT deniyordu, kaybeden yakalanmamış bir `IntegrityError` (500)
   alıyordu. Fix: paylaşılan `_commit_upsert()` yardımcı fonksiyonu —
   `IntegrityError` yakalanırsa rollback edip satırı tekrar okuyup update
   olarak uyguluyor. Regresyon testi gerçek Postgres'e karşı yazıldı
   (`tests/unit/test_sql_storage_multidb.py`) — SQLite'ta StaticPool'un
   tek fiziksel bağlantıyı paylaşması yüzünden bu yarış hiç
   tetiklenemiyor, gerçek izole bağlantılar (Postgres/MySQL) gerekiyor.

191 test yeşil, ruff+mypy temiz (bkz. commit `fc0f94a` sonrası).

**Kullanıcı kararı**: genişleme (yeni sistemler/özellikler) bittikten
sonra **tek seferde** kapsamlı bir güvenlik denetimi yapılacak — şimdi
değil, çünkü genişleme sonrası zaten tekrar gerekecekti. Henüz
incelenmedi: `commands/bridge.py`'nin daha derin introspection edge
case'leri (ayrı, daha küçük bir hardening maddesi olarak kalabilir).

## Sıradaki adaylar (kullanıcı "roadmap'ten devam edelim" dedi, henüz seçim yapılmadı)

1. Bölüm 6+ fiziksel teste devam (yukarıya bakın).
2. Daha fazla builtin (`on_message` otomatik moderasyon, rol-atama komutu).
3. Multi-bot/shard routing tasarımına başlamak (büyük, ayrı bir tasarım
   turu gerektiriyor — üçüncü-taraf paket sistemiyle aynı kategori).
4. Bundled dashboard'a enable/disable + cooldown UI'ı eklemek.
Bir sonraki oturumda kullanıcıya hangisini istediğini sor (daha önce
`AskUserQuestion` ile sorulmuştu, disnake/py-cord seçilmiş ve şimdi
kapandı — geri kalan üç madde hâlâ açık).

## Genel süreç hatırlatmaları (tekrar unutulmasın diye)

- **Asla force-push yapma.** Push reddedilirse önce `git fetch` +
  `git log`/`git status` ile gerçek durumu anla, gerekirse yedek branch aç,
  sonra reconcile et.
- Her yeni özellik: pytest + ruff + mypy üçü de yeşil olmadan commit'leme.
- Sadece kullanıcı açıkça istediğinde commit/push yap.
- Bu sandbox'ta Postgres/MySQL servisleri fresh container'da kapalı
  başlıyor olabilir — `service postgresql start` / `service mariadb start`
  gerekebilir, testlerin skip/fail olması otomatik olarak kod regresyonu
  anlamına gelmez, önce servisleri kontrol et.
