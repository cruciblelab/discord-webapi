# Mimari

## Temel felsefe

discord-webapi, FastAPI'ye ya da discord.py'ye rakip olmayı hedeflemiyor —
ikisinin üzerine oturan, **dar ve opinionated** bir katman. Her Discord bot
dashboard'unun tekrar tekrar yazdığı üç şeyi (OAuth2 giriş, sunucu-rol
yetkilendirme, botun komutlarını panele yansıtma) standartlaştırıyor,
gerisini olduğu gibi tüketiciye bırakıyor.

**Bilinçli olarak yapılmayanlar** (tekrar tekrar gündeme gelip kullanıcı
tarafından bilinçli olarak reddedilen/ertelenen kararlar):

- **Dashboard UI/frontend sağlanmıyor.** Gömülü `dashboard.html` bilerek
  minimal bir demo — gerçek bir ürün paneline dönüştürülmesi
  planlanmıyor. Görsel/UI işi kütüphanenin amacından saptırır, ekstra
  bakım yükü getirir. Frontend'i her tüketici kendi ihtiyacına göre yazar.
- **disnake/py-cord desteği yok.** py-cord'un slash-komut mimarisi
  (`SlashCommand`/`ApplicationCommandMixin`) discord.py'ninkinden
  (`app_commands`/`CommandTree`/`hybrid_command`) kökten farklı — "aynı
  `discord` isim alanını kullanıyor, drop-in'dir" varsayımı yanlış.
  Destek eklemek `commands/bridge.py` ve `commands/registry.py`'yi iki
  ayrı mimariye göre yazmak demek. Gerçek talep gelirse ayrı bir
  `discord-webapi-pycord` paketi olarak ele alınabilir.
- **Çoklu bot (tek dashboard'dan birden fazla bot/token yönetimi) yok.**
  `guild_id → hangi bot` routing'i gerektirir, her alt sistemin "hangi
  bota soracağını" bilmesi anlamına gelir — küçük bir ek değil, gerçek
  bir mimari genişleme. Gerçek talep olmadan şimdi yapmak vizyon riski
  taşıyor.

## Katmanlar

```
discord_webapi/
  transport/   Bot süreci <-> web süreci arasındaki tek soyutlama
  storage/     Session/command-override/authz/audit/consent kalıcılığı
  auth/        Discord OAuth2 girişi, opak session modeli
  authz/       Sunucu-rol / kanal / app-role yetkilendirme
  commands/    Komut introspection'ı, canlı enable/disable, cooldown
  guilds/      "Hangi sunucuları yönetebilirim" listesi
  members/     Üye listesi (rolleriyle birlikte)
  audit/       Opt-in audit log
  consent/     Opt-in cookie/gizlilik onayı kaydı
  jobs/        Opt-in arka plan iş kuyruğu
  builtins/    Hazır, opsiyonel komutlar (ban/kick/timeout/warn/welcome)
  bot/         Tek-process bot+FastAPI lifespan yardımcıları
  web/         Gömülü dashboard HTML'i, WebSocket relay
```

## Transport: tek gerçek soyutlama

Auth, authz ve command registry **hiçbir zaman** doğrudan bir `discord.Bot`
nesnesine ya da somut bir backend'e karşı yazılmıyor — sadece
`Transport` Protocol'üne karşı:

```python
class Transport(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def publish(self, event: Event) -> None: ...          # broadcast
    def subscribe(self, event_type: str, handler) -> None: ...
    def register_handler(self, command: str, handler) -> None: ...
    async def request(self, command: str, payload: dict, *, timeout: float = 5.0) -> dict: ...  # RPC
```

İki implementasyon:

- **`InProcessTransport`** (varsayılan): bot ve web aynı process'te, aynı
  asyncio event loop'unu paylaşır. Sıfır ek altyapı.
- **`RedisTransport`**: bot ve web ayrı process'lerde/makinelerde
  çalışabilir, Redis Pub/Sub üzerinden event broadcast + RPC. **Tek bir
  komuta tek bir handler** kuralı var (iki process aynı komutu register
  ederse undefined davranış — hangisinin cevap vereceği garanti değil).

İkisi de aynı **contract test suite**'inden geçiyor (`tests/transport/`)
— bu, kütüphanenin geri kalanının yanlışlıkla in-process-only bir
davranışa bağımlı olmadığının somut garantisi.

Web tarafı, botun Discord Gateway'inden gelen veriye (üye rolleri, kanal
izinleri) her zaman `Transport.request(...)` ile ulaşır — asla kendi
REST çağrısı yapmaz. Bot süreci kendi zaten sıcak (warm) Gateway
cache'inden cevap verir, rate limit'e takılmaz.

## Storage: protokoller + Memory/SQL implementasyonları

`SessionStore`, `CommandConfigStore`, `AuthzStore`, `AuditStore`,
`ConsentStore` — her biri bir Protocol, iki implementasyonu var:
`Memory*` (sıfır altyapı, dev/test için) ve `SQL*` (SQLAlchemy 2.0 async,
SQLite/Postgres/MySQL fark etmeksizin aynı kod).

## Command Registry: flagship özellik

`CommandRegistry`, botun kayıtlı komutlarını (`bot.tree.walk_commands()` +
`bot.walk_commands()` üzerinden) tek seferlik introspect eder, ve iki
enforcement noktası kurar:

- `bot.add_check(registry.global_check)` — prefix/hybrid komutlar için.
- `bot.tree.interaction_check`'in sarmalanmış hali — slash komutlar için.

İkisi de O(1) in-memory dict lookup — **asla** per-invocation DB sorgusu
(her komut çağrısının hot path'i). Cache, dashboard'dan bir yazma
(`PATCH /api/guilds/{id}/commands/{name}`) yapıldığında
`command_config_changed` Transport event'i ile güncelleniyor. Yazma yolu
her zaman **web → store → event**, bot'a asla direkt yazma yok.

Dashboard'un komut listeleme/override endpoint'leri de artık
`Transport.request(...)` üzerinden çalışıyor (registry'ye doğrudan bir
Python referansı üzerinden değil) — bu, bot ve web'in ayrı process'lerde
çalışabilmesinin (bkz. `DAGITIM.md`) temel önkoşulu.

## Yetkilendirme (authz)

Discord'un kendi `discord.Permissions` bitfield'ı reuse ediliyor
(`administrator` her zaman kısayol). Dört seviye:

- `require_guild_permission("manage_guild")` — sunucu-rol bazlı.
- `require_channel_permission(...)` — kanal-özel override'lar dahil
  (guild-level izne sahip olsan bile kanal bazında geri alınabilir).
- `require_role(role_id=...)` — Discord'un belirli bir rolüne sahip olma.
- `require_app_role(name)` — botun kendi tanımladığı, Discord'un rol
  sisteminden bağımsız roller (`AppRole`).

## Kuyruk sistemi (jobs)

`Transport`'la aynı desende, ama bilinçli olarak farklı semantikle:
`RedisTransport`'un "bir komuta tek handler" kısıtlamasının aksine,
`RedisJobQueue` (Redis list'ler, `RPUSH`/`BLPOP`) gerçek
competing-consumer semantiği veriyor — kaç worker process aynı `job_type`'ı
register ederse etsin, Redis aynı job'ı iki worker'a birden vermemeyi
garanti ediyor. Detaylar için `OZELLIKLER.md` ve `DAGITIM.md`.

## Çoklu sunucu/makine deployment

`DiscordWebAPI.for_bot_process()` / `for_web_process()` — bot'un Discord
Gateway bağlantısı bir process'te, FastAPI dashboard'ı ayrı
process'lerde/makinelerde (`RedisTransport` üzerinden). Bunun mümkün
olmasının nedeni: her alt sistem zaten sadece `Transport` üzerinden
konuşuyordu. Detaylar için `DAGITIM.md`.
