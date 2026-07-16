# Özellikler

## Discord OAuth2 girişi

```python
from discord_webapi import DiscordAuth

auth = DiscordAuth(
    client_id=...,
    client_secret=...,
    redirect_uri="https://dashboard.example.com/auth/discord/callback",
    encryption_keys=fernet_key,
    session_store=SQLSessionStore(engine),  # varsayılan: MemorySessionStore
)
auth.install(app)
```

Bağlanan route'lar:

- `GET /auth/discord/login` — Discord'a yönlendirir (CSRF korumalı state).
- `GET /auth/discord/callback` — code exchange, session kurulumu.
- `POST /auth/discord/logout` — oturumu kapatır.
- `GET /auth/discord/me` — giriş yapmış kullanıcının bilgisi.
- `GET /auth/discord/sessions` — kullanıcının tüm aktif oturumlarını
  listeler, hangisinin şu anki oturum olduğunu (`is_current`) işaretler.
  Şifreli Discord token'ları hiçbir zaman dönmez.
- `DELETE /auth/discord/sessions/{session_id}` — belirli bir oturumu
  iptal eder ("her yerden çıkış yap" için tek tek çağrılabilir). Sadece
  kendi oturumunuzu iptal edebilirsiniz; başkasının session id'si 404
  döner (var olup olmadığını sızdırmamak için 403 değil).

**Mobil/API istemciler için**: `/auth/discord/login?mobile=true` cookie
yerine, girişten sonra `mobile_redirect_uri`'ye `session_id` query
parametresiyle yönlendirir. İstemci bu değeri her istekte
`Authorization: Bearer <session_id>` olarak gönderir — aynı auth mantığı,
iki farklı taşıma şekli.

## Sunucu-rol bazlı yetkilendirme

```python
from discord_webapi import require_guild_permission, GuildContext

@app.post("/api/guilds/{guild_id}/settings")
async def update_settings(
    guild_id: int, ctx: GuildContext = Depends(require_guild_permission("manage_guild"))
):
    ...
```

Discord'un kendi `discord.Permissions` bitfield'ı kullanılıyor —
`administrator` her zaman geçer.

## Kanal bazlı izin override'ı

```python
from discord_webapi import require_channel_permission

@app.get("/api/guilds/{guild_id}/channels/{channel_id}/can-send")
async def can_send(ctx=Depends(require_channel_permission("send_messages"))):
    ...
```

`require_guild_permission`'dan farkı: guild-level izne sahip olsanız bile,
o kanala özel bir override izni geri alabilir (`channel.permissions_for`
kullanılıyor — Discord'un kendi UI'ının gösterdiğiyle aynı hesaplama).

## Bot-özel roller (AppRole)

Discord'un rol sisteminden bağımsız, sadece bu uygulamaya özel roller:

```python
from discord_webapi import require_app_role

@app.post("/api/guilds/{guild_id}/mod-action")
async def mod_action(ctx=Depends(require_app_role("moderator"))):
    ...
```

Yönetimi: `GET/PUT/DELETE /api/guilds/{guild_id}/app-roles`.

## Komut yönetimi

```python
registry = CommandRegistry(bot, transport=transport, store=command_store)
registry.register_all()
```

- `GET /api/guilds/{guild_id}/commands` — botun tüm komutlarını (spec +
  override + invocation sayacı ile) listeler.
- `PATCH /api/guilds/{guild_id}/commands/{name}` — enable/disable,
  cooldown ayarı — **restart gerekmez**, aynı anda çalışan bot canlı
  olarak uygular.

Cooldown, discord.py'nin kendi `Cooldown`/`CooldownMapping` mekanizması
üzerinden, kullanıcı bazlı uygulanıyor.

## Sunucu listesi

```
GET /api/guilds
```

Giriş yapmış kullanıcının kendi Discord sunucu listesinden, hem botun da
içinde olduğu HEM DE kullanıcının "Manage Server" yetkisine sahip olduğu
sunucuları döner — "sunucu seç" ekranı için, her sunucuyu tek tek
denemeden.

## Üye listesi

```
GET /api/guilds/{guild_id}/members
```

Rolleriyle birlikte üye listesi (view-only).

## Audit log (opt-in)

```python
DiscordWebAPI(..., audit_store=SQLAuditStore(engine))
api.install(app, enable_audit_log=True)
```

`GET /api/guilds/{guild_id}/audit-log` — state-changing dashboard
aksiyonlarının (komut override yazma, app-role set/delete) kaydı. Auth
login/logout olayları kapsam dışı (bilinçli tercih).

## Cookie/gizlilik onayı (opt-in)

```python
DiscordWebAPI(..., consent_store=SQLConsentStore(engine))
api.install(app, enable_cookie_consent=True, cookie_consent_message="...")
```

`GET/POST /api/consent` — "kim, hangi versiyonu, ne zaman onayladı"
kaydı. Notice'ın metni/tasarımı tamamen tüketiciye ait; kütüphane sadece
kaydı tutuyor, davranış dayatmıyor.

## Hazır komutlar (`discord_webapi.builtins`)

Serbestçe import edilebilir, opsiyonel, `setup(bot, **kwargs)` ile açıkça
çağrılan komutlar — otomatik yükleme yok:

- `ban.py`, `kick.py`, `timeout.py` — rol-hiyerarşisi koruması, opsiyonel
  DM bildirimi.
- `warn.py` — kalıcı durumlu, kendi `WarnStore`'u (Memory/SQL), opsiyonel
  otomatik timeout eskalasyonu.
- `welcome.py` — `on_member_join` event listener'ı, kanal ya da DM.
- `role_assign.py` — `/role-add`/`/role-remove` komutları. Diğer moderasyon komutları gibi rol-hiyerarşisi korumalı, ama hedef *üyenin* değil, verilen/alınan *rolün* sırasını kontrol ediyor (bot token'ı API çağrısını yaptığı için Discord hiyerarşi kontrolünü botun kendi sırasına göre yapıyor, çağıran kullanıcının sırasına göre değil).
- `automod/` — ikinci komut-olmayan builtin, ve tek dosya yerine tam bir alt paket: yedi bağımsız, tek başına import edilebilir kontrol (`banned_words.py`, `spam.py`, `mention_spam.py`, `invite_filter.py`, `link_filter.py`, `caps_spam.py`, `emoji_spam.py`) + kimin muaf tutulacağını belirleyen `exemptions.py` + hepsini birleştiren `automod/__init__.py::setup()`. Her kontrol saf, senkron, yan etkisiz bir fonksiyon (`discord.Message -> str | None`) — hiç `await` yok, hiç I/O yok, düz bir sahte mesaj nesnesiyle tek başına test edilebiliyor. `setup()` Discord'a dokunan tek yer: etkin kontrolleri sırayla çalıştırıp ilk ihlalde duruyor, sonra mesajı siliyor / kısa bir kanal bildirimi gönderiyor / kalıcı bir log-kanalı kaydı atıyor / kendi `on_violation` callback'inizi await ediyor — hepsi bağımsız açılıp kapatılabilir. Ban/kick/timeout'a yükseltmiyor, kalıcı ihlal sayacı tutmuyor (o `warn.py`'nin işi) — `on_violation=` ile kendi `WarnStore`'unuzu besleyebilirsiniz, `automod`'un `warn.py`'ye hiç bağımlılığı olmadan.

`_shared.py`'deki `check_role_hierarchy`/`notify_member_best_effort`
bağımsız kullanılabilir — sadece bunları alıp kendi komutunuza gömebilir,
hazır komutu olduğu gibi kullanabilir, ya da hibrit yapabilirsiniz.

## WebSocket canlı relay (opt-in)

```python
api.install(app, enable_websocket=True)
```

`GET /api/guilds/{guild_id}/commands/stream` — komut config değişikliklerini
polling olmadan anlık push eder.

## Kuyruk sistemi (`discord_webapi.jobs`, opt-in)

Uzun süren işler (toplu moderasyon, export) için — request/response
döngüsünde beklenemeyecek işler:

```python
from discord_webapi.jobs import InProcessJobQueue

job_queue = InProcessJobQueue()
job_queue.register_worker("bulk_ban", handle_bulk_ban)

api = DiscordWebAPI(..., job_queue=job_queue)
api.install(app, enable_jobs=True)
```

- `POST /api/guilds/{guild_id}/jobs/{job_type}` — enqueue, 202 + `job_id`.
- `GET /api/guilds/{guild_id}/jobs/{job_id}` — durum sorgusu (pending →
  running → succeeded/failed).

Gerçek dağıtık kullanım için `RedisJobQueue` — detaylar `DAGITIM.md`'de.

## Çoklu veritabanı desteği

SQLite/Postgres/MySQL, `discord-webapi[sql-sqlite|sql-postgres|sql-mysql]`
extra'ları, `quickstart(database_url=...)`.

## `default_intents()` ve boilerplate azaltma

```python
from discord_webapi.bot import default_intents

bot = commands.Bot(command_prefix="!", intents=default_intents())
```

`Intents.default()` + `members=True` + `message_content=True` — dashboard
botlarının neredeyse her zaman ihtiyaç duyduğu iki intent'i tek satıra
indiriyor.
