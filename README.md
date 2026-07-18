# discord-webapi

FastAPI + discord.py üzerine kurduğumuz, Discord bot web dashboard'ları
için dar ve opinionated bir katman: OAuth2 girişimiz, sunucu-rol bazlı
yetkilendirmemiz, botun komutlarını panele canlı yansıtan köprümüz, ve
daha fazlası.

Durum: aktif geliştiriyoruz (v0.5).

Detaylı Türkçe dokümantasyonumuz için [`docs/`](docs/) klasörümüze bakın:

- [`docs/BASLARKEN.md`](docs/BASLARKEN.md) — kurulum, ilk çalıştırma, temel akış
- [`docs/MIMARI.md`](docs/MIMARI.md) — kütüphanemizin nasıl çalıştığı, alt sistemlerimiz
- [`docs/OZELLIKLER.md`](docs/OZELLIKLER.md) — tüm özelliklerimizin listesi ve kullanımı
- [`docs/DAGITIM.md`](docs/DAGITIM.md) — tek process, çoklu sunucu, kuyruk sistemimiz
- [`docs/GUVENLIK.md`](docs/GUVENLIK.md) — güvenlik modelimiz ve tasarım kararlarımız

## Neden yaptık

Bir Discord botu için yönetim paneli yapmak, her seferinde aynı sıkıcı işi
elle yazmak demek: Discord OAuth2 girişi, sunucu-rol bazlı izin kontrolleri,
ve botun komutlarını web paneline yansıtacak ad-hoc bir mekanizma. Biz de
discord-webapi'yi tam olarak bunu FastAPI ve discord.py'nin üzerine oturan,
dar ve opinionated bir katmana indirmek için yazdık — FastAPI'ye ya da
discord.py'ye rakip olarak değil, ikisinin arasındaki "bot + dashboard"
boşluğunu dolduran bir köprü olarak tasarladık.

Kurduğumuz her endpoint; tarayıcı tabanlı bir dashboard, bir mobil
uygulama, ya da üçüncü taraf bir API/SaaS istemcisi için aynı şekilde
çalışıyor — kimlik doğrulamamız tek bir opak session üzerinden yürüyor,
istemci bunu ister httpOnly bir cookie (tarayıcı) ister `Authorization:
Bearer <session_id>` header'ı (mobil, sunucu-sunucu entegrasyonları)
olarak sunabiliyor. Mobil giriş akışımız için `docs/OZELLIKLER.md`'ye
bakabilirsiniz.

## Kurulum

```bash
pip install discord-webapi[sql]   # ya da bizim [redis] extramız, ya da [all]
```

`discord_webapi.storage.sql`'imiz herhangi bir SQLAlchemy `AsyncEngine`'e
karşı çalışır — SQLite, Postgres ve MySQL/MariaDB'yi hepsini eşit derecede
destekliyoruz, veritabanınıza uyan extra'mızı seçin:

```bash
pip install discord-webapi[sql-sqlite]    # aiosqlite — sıfır kurulum, tek instance
pip install discord-webapi[sql-postgres]  # asyncpg
pip install discord-webapi[sql-mysql]     # aiomysql
pip install discord-webapi[sql]           # emin değilseniz üçünü birden kurar
pip install discord-webapi[redis]         # bizim RedisTransport / RedisJobQueue'muz için
```

## Hızlı başlangıç

```python
from discord.ext import commands
from discord_webapi import DiscordWebAPI
from discord_webapi.bot import default_intents

bot = commands.Bot(command_prefix="!", intents=default_intents(), help_command=None)

@bot.hybrid_command(name="ping", description="Pong döner")
async def ping(ctx: commands.Context) -> None:
    await ctx.reply("pong")

app = DiscordWebAPI.quickstart(bot=bot)
```

```bash
export DISCORD_BOT_TOKEN=...
export DISCORD_CLIENT_ID=...
export DISCORD_CLIENT_SECRET=...
export DWA_FERNET_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
uvicorn main:app --reload
```

Bizim sunduğumuz bu tek çağrı; OAuth2 girişini, SQLite tabanlı
session/command-override storage'ımızı, gömülü demo dashboard'umuzu, ve
slash komutlarının Discord'a otomatik senkronizasyonunu tek seferde
kuruyor. Detaylar ve tam bir örnek için kendi `examples/single_process_bot/`
klasörümüze ve `docs/BASLARKEN.md`'ye bakın.

## Öne çıkan özelliklerimiz (v0.5)

- **OAuth2 girişimiz** — opak session modelimiz, tarayıcı (cookie) ve
  mobil (Bearer token) için aynı akışı kullanıyor.
- **Sunucu-rol bazlı yetkilendirmemiz** — Discord'un kendi izin sistemini
  (`require_guild_permission`), kanal bazlı izin override'larımızı
  (`require_channel_permission`), bot-özel rollerimizi (`require_app_role`)
  destekliyoruz.
- **Komut yönetimimiz** — botun komutlarını tek seferlik introspect
  ediyoruz, dashboard'dan canlı enable/disable + cooldown sunuyoruz
  (restart gerekmiyor).
- **`GET /api/guilds`** — kullanıcının yönetebileceği sunucuların listesini
  veriyoruz.
- **Oturum yönetimimiz** — aktif oturumları listeleyip iptal edebiliyorsunuz
  ("her yerden çıkış yap").
- **Audit log ve cookie-consent kaydımız** — opt-in, isteğe bağlı olarak
  sunuyoruz.
- **`discord_webapi.extras` paketimiz** — hazır ban/kick/timeout/warn/welcome
  komutlarımızı serbestçe import edebilirsiniz ya da sıfırdan
  yazabilirsiniz.
- **WebSocket canlı relay'imiz** — dashboard'a anlık command-config
  güncellemesi gönderiyoruz.
- **Çoklu sunucu/makine deployment desteğimiz** — bot ve web dashboard'ı
  ayrı process'lerde/makinelerde çalıştırabiliyorsunuz
  (`DiscordWebAPI.for_bot_process` / `for_web_process`), web tarafımız
  yatay ölçeklenebiliyor.
- **Kuyruk sistemimiz (`discord_webapi.jobs`)** — uzun süren işler için
  opt-in bir job queue sunuyoruz, `InProcessJobQueue`'muzu ya da gerçek
  dağıtık `RedisJobQueue`'muzu kullanabilirsiniz.
- **Çoklu veritabanı desteğimiz** — SQLite, Postgres, MySQL/MariaDB'yi
  destekliyoruz.
- **Opsiyonel observability/metrics'imiz** (`discord_webapi.observability`)
  — transport RPC latency, job/escalation/komut sayaçları için opt-in bir
  `MetricsSink`, hazır bir `PrometheusMetricsSink`'imizle birlikte.

Kapsam dışı bıraktığımız bilinçli kararlarımız (neden böyle karar
verdiğimizi `docs/MIMARI.md`'de detaylandırdık): dashboard UI/frontend
(backend odaklı kalmayı tercih ediyoruz), disnake/py-cord desteği, çoklu
bot (tek dashboard'dan birden fazla bot/token yönetimi).

## Örneklerimiz

- `examples/single_process_bot/` — minimum uçtan uca demomuz.
- `examples/full_featured_bot/` — v0.1'den v0.5'e kadar eklediğimiz
  neredeyse tüm özellikleri gösteren kapsamlı örneğimiz.
- `examples/split_deployment/` — bot, web dashboard ve job worker'ımızı
  ayrı process/makinelerde çalıştırma örneğimiz.

## Testlerimiz

```bash
pip install -e ".[dev]"
pytest
ruff check discord_webapi
mypy discord_webapi
```

Fiziksel/manuel testimiz için (gerçek bir Discord sunucusunda adım adım
kontrol listemiz) `TESTING.md`'ye bakın.

## Lisansımız

MIT

## Kardeş projemiz

Captcha/insan-doğrulama katmanımızı, bağımsız kullanılabilsin diye ayrı
bir kütüphaneye taşıdık: [`webapi-captcha`](https://github.com/cruciblelab/web-api-captcha)
(Apache 2.0). `discord_webapi.captcha` modülümüz onun ince bir
re-export'u — `pip install discord-webapi[captcha]` ile kurabilirsiniz.
