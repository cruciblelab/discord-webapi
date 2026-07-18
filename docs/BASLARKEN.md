# Başlarken

## Gereksinimler

- Python 3.11+
- Bir Discord uygulaması (Discord Developer Portal'da oluşturulmuş):
  bot token'ı, OAuth2 client id/secret, ve bir redirect URI.

## Kurulum

```bash
pip install discord-webapi[sql-sqlite]
```

Başka bir veritabanı kullanacaksanız bizim `sql-postgres` ya da
`sql-mysql` extra'mızı seçin. Çoklu sunucu deployment'ımızı ya da kuyruk
sistemimizi kullanacaksanız `redis` extra'mız da gerekiyor.

## Discord tarafında yapılması gerekenler

1. [Discord Developer Portal](https://discord.com/developers/applications)'da
   bir uygulama oluşturun.
2. **Bot** sekmesinden bir bot token'ı alın (`DISCORD_BOT_TOKEN`).
3. **OAuth2 → General** sekmesinden client id ve client secret'ı alın
   (`DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`).
4. Aynı sekmede bir **Redirect URI** ekleyin: geliştirme için
   `http://localhost:8000/auth/discord/callback`.
5. **Bot** sekmesinde "Server Members Intent" ve "Message Content Intent"i
   açın (biz bunları `default_intents()` fonksiyonumuzla zaten talep
   ediyoruz, ama Discord tarafında da açık olmaları gerekiyor).
6. **OAuth2 → URL Generator**'dan `bot` ve `applications.commands`
   scope'larıyla bir davet linki oluşturup botu test sunucunuza ekleyin.

## En basit örneğimiz

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

`DWA_FERNET_KEY`, Discord'un access/refresh token'larını veritabanımızda
şifrelemek için kullandığımız anahtar — tek seferlik üretilip güvenli bir
yerde saklanmalı (örn. bir secret manager), her deploy'da yeniden
üretilmemeli (aksi halde önceki oturumlar çözülemez hale gelir).

Bizim sunduğumuz bu tek `quickstart()` çağrısı şunları otomatik kurar:

- `DISCORD_BOT_TOKEN`/`DISCORD_CLIENT_ID`/`DISCORD_CLIENT_SECRET`/
  `DWA_FERNET_KEY` ortam değişkenlerini okur.
- Yerel bir SQLite dosyasında (`dashboard.sqlite3`) session ve
  command-override storage'ımızı kurar (`database_url=` ile Postgres/MySQL'e
  yönlendirebilirsiniz).
- `/auth/discord/{login,callback,logout,me,sessions}` route'larımızı bağlar.
- `/` ve `/dashboard`'da gömülü, minimal demo dashboard'umuzu sunar.
- Bot hazır olduğunda (`on_ready`) slash komutlarını otomatik Discord'a
  senkronize eder (`sync_commands=True` varsayılanımız — bkz. aşağıdaki not).

## İlk testiniz

1. `http://localhost:8000/dashboard` adresine gidin, "Discord ile giriş
   yap" ile giriş yapın.
2. Discord'da test sunucunuzda `/ping` yazın — bot "pong" ile cevap
   vermeli.
3. `GET /api/guilds/{sunucu_id}/commands` — komut listesini döner
   ("Manage Server" iznine sahip olmanız gerekir).
4. `PATCH /api/guilds/{sunucu_id}/commands/ping` gövdesiyle
   `{"enabled": false}` gönderin, sonra Discord'da tekrar `/ping` deneyin
   — bot yeniden başlatılmadan komut reddedilmeli.

Daha kapsamlı, adım adım fiziksel test kontrol listemiz için proje
kökümüzdeki `TESTING.md`'ye bakın.

## Slash komut senkronizasyonu hakkında önemli not

discord.py, tanımladığınız slash komutları Discord'a **kendiliğinden asla
göndermez** — `bot.tree.sync()` çağrılmadıkça `/ping` gibi komutlar
Discord'un arayüzünde hiç görünmez, hiçbir hata da vermez. Biz
`DiscordWebAPI`'de bunu `sync_commands=True` (varsayılanımız) ile bot
hazır olduğunda otomatik yapıyoruz. Global senkronizasyon Discord'un tüm
sunuculara yayılması için ~1 saate kadar sürebilir; geliştirme sırasında
`sync_guild_id=<test_sunucu_id>` vererek tek bir sunucuya anında
senkronize edebilirsiniz.

## Sırada ne var

- Tüm özelliklerimizin listesi için [`OZELLIKLER.md`](OZELLIKLER.md).
- Kütüphanemizin iç mimarisini anlamak için [`MIMARI.md`](MIMARI.md).
- Büyük botlar için çoklu sunucu/kuyruk kurulumumuz için [`DAGITIM.md`](DAGITIM.md).
- Güvenlik modelimiz için [`GUVENLIK.md`](GUVENLIK.md).
