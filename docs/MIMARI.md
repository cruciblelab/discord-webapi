# Mimari

## Temel felsefemiz

discord-webapi'yi FastAPI'ye ya da discord.py'ye rakip olarak
tasarlamadık — ikisinin üzerine oturan, **dar ve opinionated** bir katman
olarak kurduk. Her Discord bot dashboard'unun tekrar tekrar yazdığı üç
şeyi (OAuth2 giriş, sunucu-rol yetkilendirme, botun komutlarını panele
yansıtma) biz standartlaştırıyoruz, gerisini olduğu gibi tüketiciye
bırakıyoruz.

**Bilinçli olarak yapmadıklarımız** (tekrar tekrar gündeme gelip bizim
tarafımızdan bilinçli olarak reddettiğimiz/ertelediğimiz kararlar):

- **Dashboard UI/frontend sağlamıyoruz.** Gömülü `dashboard.html`'imiz
  bilerek minimal bir demo — gerçek bir ürün paneline dönüştürmeyi
  planlamıyoruz. Görsel/UI işi kütüphanemizin amacından saptırır, ekstra
  bakım yükü getirir. Frontend'i her tüketicinin kendi ihtiyacına göre
  yazmasını tercih ediyoruz.
- **disnake/py-cord desteği vermiyoruz.** py-cord'un slash-komut mimarisi
  (`SlashCommand`/`ApplicationCommandMixin`) discord.py'ninkinden
  (`app_commands`/`CommandTree`/`hybrid_command`) kökten farklı — "aynı
  `discord` isim alanını kullanıyor, drop-in'dir" varsayımımız yanlış
  çıktı. Destek eklemek bizim `commands/bridge.py` ve
  `commands/registry.py`'mizi iki ayrı mimariye göre yazmak demek.
  Gerçek talep gelirse ayrı bir `discord-webapi-pycord` paketi olarak
  ele alabiliriz.
- **Çoklu bot (tek dashboard'dan birden fazla bot/token yönetimi)
  sunmuyoruz.** `guild_id → hangi bot` routing'i gerektirir, her alt
  sistemimizin "hangi bota soracağını" bilmesi anlamına gelir — küçük
  bir ek değil, gerçek bir mimari genişleme. Gerçek talep olmadan
  şimdi yapmak vizyon riski taşıyor.

## Katmanlarımız

```
discord_webapi/
  transport/       Bot süreci <-> web süreci arasındaki tek soyutlamamız
  storage/         Session/command-override/authz/audit/consent kalıcılığımız
  auth/            Discord OAuth2 girişimiz, opak session modelimiz
  authz/           Sunucu-rol / kanal / app-role yetkilendirmemiz
  commands/        Komut introspection'ımız, canlı enable/disable, cooldown
  guilds/          "Hangi sunucuları yönetebilirim" listemiz
  members/         Üye listemiz (rolleriyle birlikte)
  audit/           Opt-in audit log'umuz
  consent/         Opt-in cookie/gizlilik onayı kaydımız
  jobs/            Opt-in arka plan iş kuyruğumuz
  observability/   Opt-in metrics/observability katmanımız
  builtins/        Hazır, opsiyonel komutlarımız (ban/kick/timeout/warn/welcome)
  bot/             Tek-process bot+FastAPI lifespan yardımcılarımız
  web/             Gömülü dashboard HTML'imiz, WebSocket relay'imiz
```

## Transport: bizim tek gerçek soyutlamamız

Auth, authz ve command registry'miz **hiçbir zaman** doğrudan bir
`discord.Bot` nesnesine ya da somut bir backend'e karşı yazılmıyor —
sadece bizim `Transport` Protocol'ümüze karşı:

```python
class Transport(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def publish(self, event: Event) -> None: ...          # broadcast
    def subscribe(self, event_type: str, handler) -> None: ...
    def register_handler(self, command: str, handler) -> None: ...
    async def request(self, command: str, payload: dict, *, timeout: float = 5.0) -> dict: ...  # RPC
```

İki implementasyonumuz var:

- **`InProcessTransport`** (varsayılanımız): bot ve web aynı process'te,
  aynı asyncio event loop'unu paylaşır. Sıfır ek altyapı.
- **`RedisTransport`**: bot ve web ayrı process'lerde/makinelerde
  çalışabilir, Redis Pub/Sub üzerinden event broadcast + RPC. **Tek bir
  komuta tek bir handler** kuralımız var (iki process aynı komutu
  register ederse undefined davranış — hangisinin cevap vereceği garanti
  değil).

İkisi de bizim aynı **contract test suite**'imizden geçiyor
(`tests/transport/`) — bu, kütüphanemizin geri kalanının yanlışlıkla
in-process-only bir davranışa bağımlı olmadığının somut garantisi.

Web tarafımız, botun Discord Gateway'inden gelen veriye (üye rolleri,
kanal izinleri) her zaman `Transport.request(...)` ile ulaşır — asla
kendi REST çağrısını yapmaz. Bot sürecimiz kendi zaten sıcak (warm)
Gateway cache'inden cevap verir, rate limit'e takılmaz.

## Storage: protokollerimiz + Memory/SQL implementasyonlarımız

`SessionStore`, `CommandConfigStore`, `AuthzStore`, `AuditStore`,
`ConsentStore` — her biri bizim bir Protocol'ümüz, iki
implementasyonumuz var: `Memory*` (sıfır altyapı, dev/test için) ve
`SQL*` (SQLAlchemy 2.0 async, SQLite/Postgres/MySQL fark etmeksizin
aynı kod).

## Command Registry: bizim flagship özelliğimiz

`CommandRegistry`'miz, botun kayıtlı komutlarını
(`bot.tree.walk_commands()` + `bot.walk_commands()` üzerinden) tek
seferlik introspect ediyor, ve iki enforcement noktası kuruyor:

- `bot.add_check(registry.global_check)` — prefix/hybrid komutlar için.
- `bot.tree.interaction_check`'in sarmalanmış hali — slash komutlar için.

İkisi de O(1) in-memory dict lookup — **asla** per-invocation DB sorgusu
(her komut çağrısının hot path'i). Cache'imiz, dashboard'dan bir yazma
(`PATCH /api/guilds/{id}/commands/{name}`) yapıldığında bizim
`command_config_changed` Transport event'imizle güncelleniyor. Yazma
yolumuz her zaman **web → store → event**, bot'a asla direkt yazma yok.

Dashboard'umuzun komut listeleme/override endpoint'leri de artık
`Transport.request(...)` üzerinden çalışıyor (registry'ye doğrudan bir
Python referansı üzerinden değil) — bu, bot ve web'imizin ayrı
process'lerde çalışabilmesinin (bkz. `DAGITIM.md`) temel önkoşulu.

## Yetkilendirmemiz (authz)

Discord'un kendi `discord.Permissions` bitfield'ını reuse ediyoruz
(`administrator` her zaman kısayolumuz). Dört seviyemiz var:

- `require_guild_permission("manage_guild")` — sunucu-rol bazlı.
- `require_channel_permission(...)` — kanal-özel override'larımız dahil
  (guild-level izne sahip olsanız bile kanal bazında geri alınabilir).
- `require_role(role_id=...)` — Discord'un belirli bir rolüne sahip olma.
- `require_app_role(name)` — botun kendi tanımladığı, Discord'un rol
  sisteminden bağımsız rollerimiz (`AppRole`).

## Kuyruk sistemimiz (jobs)

`Transport`'umuzla aynı desende, ama bilinçli olarak farklı semantikle:
`RedisTransport`'umuzun "bir komuta tek handler" kısıtlamasının aksine,
`RedisJobQueue`'muz (Redis list'ler, `RPUSH`/`BLPOP`) gerçek
competing-consumer semantiği veriyor — kaç worker process aynı
`job_type`'ı register ederse etsin, Redis aynı job'ı iki worker'a
birden vermemeyi garanti ediyor. Detaylar için `OZELLIKLER.md` ve
`DAGITIM.md`.

## Çoklu sunucu/makine deployment'ımız

`DiscordWebAPI.for_bot_process()` / `for_web_process()` — bot'un Discord
Gateway bağlantısı bir process'te, FastAPI dashboard'ımız ayrı
process'lerde/makinelerde (`RedisTransport`'umuz üzerinden). Bunun mümkün
olmasının nedeni: her alt sistemimiz zaten sadece `Transport`'umuz
üzerinden konuşuyordu. Detaylar için `DAGITIM.md`.
