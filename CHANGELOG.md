# Changelog

Formatı [Keep a Changelog](https://keepachangelog.com/) temel alıyor.

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
