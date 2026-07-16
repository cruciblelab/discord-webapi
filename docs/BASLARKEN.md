# Başlarken

## Gereksinimler

- Python 3.11+
- Bir Discord uygulaması (Discord Developer Portal'da oluşturulmuş):
  bot token'ı, OAuth2 client id/secret, ve bir redirect URI.

## Kurulum

```bash
pip install discord-webapi[sql-sqlite]
```

Başka bir veritabanı kullanacaksanız `sql-postgres` ya da `sql-mysql`
extra'sını seçin. Çoklu sunucu deployment'ı ya da kuyruk sistemi
kullanacaksanız `redis` extra'sı da gerekiyor.

## Discord tarafında yapılması gerekenler

1. [Discord Developer Portal](https://discord.com/developers/applications)'da
   bir uygulama oluşturun.
2. **Bot** sekmesinden bir bot token'ı alın (`DISCORD_BOT_TOKEN`).
3. **OAuth2 → General** sekmesinden client id ve client secret'ı alın
   (`DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`).
4. Aynı sekmede bir **Redirect URI** ekleyin: geliştirme için
   `http://localhost:8000/auth/discord/callback`.
5. **Bot** sekmesinde "Server Members Intent" ve "Message Content Intent"i
   açın (kütüphane bunları `default_intents()` ile zaten talep ediyor,
   ama Discord tarafında da açık olmaları gerekiyor).
6. **OAuth2 → URL Generator**'dan `bot` ve `applications.commands`
   scope'larıyla bir davet linki oluşturup botu test sunucunuza ekleyin.

## En basit örnek

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

Ortam değişkenlerini ayarlayıp çalıştırın:

```bash
export DISCORD_BOT_TOKEN=...
export DISCORD_CLIENT_ID=...
export DISCORD_CLIENT_SECRET=...
export DWA_FERNET_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
uvicorn main:app --reload
```

`DWA_FERNET_KEY`, Discord'un access/refresh token'larını veritabanında
şifrelemek için kullanılıyor — tek seferlik üretilip güvenli bir yerde
saklanmalı (örn. bir secret manager), her deploy'da yeniden üretilmemeli
(aksi halde önceki oturumlar çözülemez hale gelir).

Bu tek `quickstart()` çağrısı şunları otomatik kurar:

- `DISCORD_BOT_TOKEN`/`DISCORD_CLIENT_ID`/`DISCORD_CLIENT_SECRET`/
  `DWA_FERNET_KEY` ortam değişkenlerini okur.
- Yerel bir SQLite dosyasında (`dashboard.sqlite3`) session ve
  command-override storage'ı kurar (`database_url=` ile Postgres/MySQL'e
  yönlendirilebilir).
- `/auth/discord/{login,callback,logout,me,sessions}` route'larını bağlar.
- `/` ve `/dashboard`'da gömülü, minimal bir demo dashboard sunar.
- Bot hazır olduğunda (`on_ready`) slash komutlarını otomatik Discord'a
  senkronize eder (`sync_commands=True` varsayılan — bkz. aşağıdaki not).

## İlk test

1. `http://localhost:8000/dashboard` adresine gidin, "Discord ile giriş
   yap" ile giriş yapın.
2. Discord'da test sunucunuzda `/ping` yazın — bot "pong" ile cevap
   vermeli.
3. `GET /api/guilds/{sunucu_id}/commands` — komut listesini döner
   ("Manage Server" iznine sahip olmanız gerekir).
4. `PATCH /api/guilds/{sunucu_id}/commands/ping` gövdesiyle
   `{"enabled": false}` gönderin, sonra Discord'da tekrar `/ping` deneyin
   — bot yeniden başlatılmadan komut reddedilmeli.

Daha kapsamlı, adım adım fiziksel test kontrol listesi için proje kökündeki
`TESTING.md`'ye bakın.

## Slash komut senkronizasyonu hakkında önemli not

discord.py, tanımladığınız slash komutları Discord'a **kendiliğinden asla
göndermez** — `bot.tree.sync()` çağrılmadıkça `/ping` gibi komutlar
Discord'un arayüzünde hiç görünmez, hiçbir hata da vermez. `DiscordWebAPI`
bunu `sync_commands=True` (varsayılan) ile bot hazır olduğunda otomatik
yapıyor. Global senkronizasyon Discord'un tüm sunuculara yayılması için
~1 saate kadar sürebilir; geliştirme sırasında `sync_guild_id=<test_sunucu_id>`
vererek tek bir sunucuya anında senkronize edebilirsiniz.

## Sırada ne var

- Tüm özelliklerin listesi için [`OZELLIKLER.md`](OZELLIKLER.md).
- Kütüphanenin iç mimarisini anlamak için [`MIMARI.md`](MIMARI.md).
- Büyük botlar için çoklu sunucu/kuyruk kurulumu için [`DAGITIM.md`](DAGITIM.md).
- Güvenlik modeli için [`GUVENLIK.md`](GUVENLIK.md).
