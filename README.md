# discord-webapi

FastAPI + discord.py üzerine kurulu, Discord bot web dashboard'ları için
dar ve opinionated bir katman: OAuth2 giriş, sunucu-rol bazlı yetkilendirme,
botun komutlarını panele canlı yansıtan bir köprü, ve daha fazlası.

Durum: aktif geliştirme (v0.5).

Detaylı Türkçe dokümantasyon için [`docs/`](docs/) klasörüne bakın:

- [`docs/BASLARKEN.md`](docs/BASLARKEN.md) — kurulum, ilk çalıştırma, temel akış
- [`docs/MIMARI.md`](docs/MIMARI.md) — kütüphanenin nasıl çalıştığı, alt sistemler
- [`docs/OZELLIKLER.md`](docs/OZELLIKLER.md) — tüm özelliklerin listesi ve kullanımı
- [`docs/DAGITIM.md`](docs/DAGITIM.md) — tek process, çoklu sunucu, kuyruk sistemi
- [`docs/GUVENLIK.md`](docs/GUVENLIK.md) — güvenlik modeli ve tasarım kararları

## Neden

Bir Discord botu için yönetim paneli yapmak, her seferinde aynı sıkıcı işi
elle yazmak demek: Discord OAuth2 girişi, sunucu-rol bazlı izin kontrolleri,
ve botun komutlarını web paneline yansıtacak ad-hoc bir mekanizma.
discord-webapi bunu FastAPI ve discord.py'nin üzerine oturan, dar ve
opinionated bir katmana indiriyor — FastAPI'ye ya da discord.py'ye rakip
değil, ikisinin arasındaki "bot + dashboard" boşluğunu dolduran bir köprü.

Her endpoint; tarayıcı tabanlı bir dashboard, bir mobil uygulama, ya da
üçüncü taraf bir API/SaaS istemcisi için aynı şekilde çalışır — kimlik
doğrulama tek bir opak session üzerinden yürür, istemci bunu ister httpOnly
bir cookie (tarayıcı) ister `Authorization: Bearer <session_id>` header'ı
(mobil, sunucu-sunucu entegrasyonları) olarak sunabilir. Mobil giriş akışı
için `docs/OZELLIKLER.md`'ye bakın.

## Kurulum

```bash
pip install discord-webapi[sql]   # ya da [redis], ya da [all]
```

`discord_webapi.storage.sql` herhangi bir SQLAlchemy `AsyncEngine`'e karşı
çalışır — SQLite, Postgres ve MySQL/MariaDB hepsi eşit derecede
destekleniyor, veritabanınıza uyan extra'yı seçin:

```bash
pip install discord-webapi[sql-sqlite]    # aiosqlite — sıfır kurulum, tek instance
pip install discord-webapi[sql-postgres]  # asyncpg
pip install discord-webapi[sql-mysql]     # aiomysql
pip install discord-webapi[sql]           # emin değilseniz üçü birden
pip install discord-webapi[redis]         # RedisTransport / RedisJobQueue için
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

Bu tek çağrı; OAuth2 girişi, SQLite tabanlı session/command-override
storage'ı, gömülü bir demo dashboard'u, ve slash komutlarının Discord'a
otomatik senkronizasyonunu kurar. Detaylar ve tam bir örnek için
`examples/single_process_bot/` ve `docs/BASLARKEN.md`'ye bakın.

## Öne çıkan özellikler (v0.5)

- **OAuth2 giriş** — opak session modeli, tarayıcı (cookie) ve mobil
  (Bearer token) için aynı akış.
- **Sunucu-rol bazlı yetkilendirme** — Discord'un kendi izin sistemi
  (`require_guild_permission`), kanal bazlı izin override'ları
  (`require_channel_permission`), bot-özel roller (`require_app_role`).
- **Komut yönetimi** — botun komutlarını tek seferlik introspect eder,
  dashboard'dan canlı enable/disable + cooldown (restart gerekmez).
- **`GET /api/guilds`** — kullanıcının yönetebileceği sunucuların listesi.
- **Oturum yönetimi** — aktif oturumları listele/iptal et ("her yerden
  çıkış yap").
- **Audit log ve cookie-consent kaydı** — opt-in, isteğe bağlı.
- **`discord_webapi.extras`** — hazır ban/kick/timeout/warn/welcome
  komutları, serbestçe import edilebilir ya da sıfırdan yazılabilir.
- **WebSocket canlı relay** — dashboard'a anlık command-config güncellemesi.
- **Çoklu sunucu/makine deployment** — bot ve web dashboard'ı ayrı
  process'lerde/makinelerde çalıştırma (`DiscordWebAPI.for_bot_process` /
  `for_web_process`), web tarafı yatay ölçeklenebilir.
- **Kuyruk sistemi (`discord_webapi.jobs`)** — uzun süren işler için opt-in
  bir job queue, `InProcessJobQueue` ya da gerçek dağıtık `RedisJobQueue`.
- **Çoklu veritabanı desteği** — SQLite, Postgres, MySQL/MariaDB.

Kapsam dışı bırakılan bilinçli kararlar (neden olduğu için `docs/MIMARI.md`'de
detaylı): dashboard UI/frontend (backend odaklı kalıyoruz), disnake/py-cord
desteği, çoklu bot (tek dashboard'dan birden fazla bot/token yönetimi).

## Örnekler

- `examples/single_process_bot/` — minimum uçtan uca demo.
- `examples/full_featured_bot/` — v0.1'den v0.5'e kadarki neredeyse tüm
  özellikleri gösteren kapsamlı örnek.
- `examples/split_deployment/` — bot, web dashboard ve job worker'ın ayrı
  process/makinelerde çalıştırılması.

## Test

```bash
pip install -e ".[dev]"
pytest
ruff check discord_webapi
mypy discord_webapi
```

Fiziksel/manuel test için (gerçek bir Discord sunucusunda adım adım
kontrol listesi) `TESTING.md`'ye bakın.

## Lisans

MIT
