# Fiziksel Test Planı (Termux / gerçek Discord sunucusu)

Bu doküman, `discord-webapi` v0.2'nin tüm özelliklerini gerçek bir Discord
botu + gerçek bir sunucu (guild) üzerinde elle test etmek için adım adım bir
kontrol listesidir. Otomatik test paketi (`pytest`) zaten yeşil — burada
amaç, otomatik testlerin kapsamadığı ("gerçek tarayıcı", "gerçek Discord
Gateway", "gerçek OAuth2 redirect") uçtan uca senaryoları doğrulamak.

## 0. Ön Hazırlık

- [ ] Bir test Discord sunucusu oluştur (veya mevcut bir test sunucusu kullan) ve botu davet et (`applications.commands` + `bot` scope, gerekli izinlerle).
- [ ] Discord Developer Portal'da:
  - [ ] Bot token'ı al (`DISCORD_BOT_TOKEN`)
  - [ ] `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`
  - [ ] OAuth2 redirect URL'i ekle: `http://localhost:8000/auth/discord/callback` (veya kendi `DASHBOARD_BASE_URL`'ine göre)
  - [ ] **Privileged Gateway Intents**'ten `Server Members Intent`'i aç (üye listesi/rol testleri için gerekli)
- [ ] `.env` dosyasını doldur: `DISCORD_BOT_TOKEN`, `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `DWA_FERNET_KEY` (bir kere `Fernet.generate_key()` ile üret), `DASHBOARD_BASE_URL`.
- [ ] `pip install -e .[sql-sqlite]` (Termux'ta SQLite yeterli; Postgres/MySQL testleri için ayrı bölüm var — madde 7).
- [ ] `python examples/single_process_bot/main.py` (veya kendi giriş dosyan) çalıştır, `uvicorn` ayağa kalksın.

## 1. Temel Auth Akışı (tarayıcı, cookie)

- [ ] Tarayıcıda `http://localhost:8000/auth/discord/login` aç.
- [ ] Discord'un kendi OAuth2 onay ekranına yönlendiğini doğrula.
- [ ] Onayla → `/auth/discord/callback` üzerinden `/` (login_success_redirect) adresine geri döndüğünü doğrula.
- [ ] Tarayıcı dev tools → Application → Cookies: `dwa_session` isimli httpOnly cookie'nin var olduğunu doğrula.
- [ ] `GET /auth/discord/me` çağır (aynı tarayıcı sekmesinden veya `curl -b cookie.txt`) → kendi Discord kullanıcı bilgilerinin (id, username, avatar, guild_ids) döndüğünü doğrula.
- [ ] `POST /auth/discord/logout` çağır → `dwa_session` cookie'sinin silindiğini, `/auth/discord/me`'nin artık 401 döndüğünü doğrula.

## 2. Mobil / Bearer Token Akışı

(Bu adım için `DiscordAuth(mobile_redirect_uri=...)` ayarlı olmalı — kendi
test dosyanda bunu ekleyip botu yeniden başlat.)

- [ ] `http://localhost:8000/auth/discord/login?mobile=true` aç.
- [ ] Onay sonrası tarayıcının `mobile_redirect_uri`'ye `?session_id=...&expires_at=...` query param'larıyla yönlendirildiğini doğrula (custom URL scheme kullanıyorsan tarayıcı "bu linki açacak uygulama yok" diyebilir — o zaman network sekmesinden redirect URL'ini oku).
- [ ] O `session_id` değeriyle `curl -H "Authorization: Bearer <session_id>" http://localhost:8000/auth/discord/me` çağır → aynı kullanıcı bilgisinin döndüğünü doğrula (cookie olmadan, sadece header ile).
- [ ] Aynı bearer token ile `logout` sonrası tekrar `/me` çağır → 401 döndüğünü doğrula.

## 3. Komut Listeleme ve Enable/Disable (canlı, restart'sız)

- [ ] Botta en az 2-3 farklı komut tanımlı olsun (biri slash/hybrid, biri prefix — örnek dosyada zaten var).
- [ ] `GET /api/guilds/{guild_id}/commands` çağır → tüm komutların (isim, açıklama, kategori, enabled, cooldown alanları, `invocation_count`) listelendiğini doğrula.
- [ ] Discord'da botun bir komutunu çalıştır (ör. `/kick` veya `!kick`) → başarıyla çalıştığını doğrula.
- [ ] `PATCH /api/guilds/{guild_id}/commands/{command_name}` ile `{"enabled": false}` gönder.
- [ ] **Botu yeniden başlatmadan** Discord'da aynı komutu tekrar çalıştırmayı dene → komutun artık çalışmadığını (sessizce reddedildiğini) doğrula. Hem slash hem prefix/hybrid komutlarda ayrı ayrı dene.
- [ ] `{"enabled": true}` ile geri aç → komutun tekrar çalıştığını doğrula.

## 4. Cooldown

- [ ] `PATCH .../commands/{command_name}` ile `{"enabled": true, "cooldown_seconds": 30, "cooldown_uses": 1}` gönder.
- [ ] Discord'da komutu bir kez çalıştır → başarılı.
- [ ] Hemen ardından tekrar çalıştır → "cooldown'dasın" hatası (slash: sessiz red / discord.py'nin kendi hata mesajı; prefix: `CommandOnCooldown` hatası, botun error handler'ı varsa kullanıcıya mesaj olarak düşer) aldığını doğrula.
- [ ] 30 saniye bekle, tekrar dene → tekrar çalıştığını doğrula.
- [ ] **Farklı bir Discord kullanıcısıyla** (varsa ikinci bir hesap/arkadaş) aynı anda dene → cooldown'un kişi bazlı olduğunu, diğer kullanıcının etkilenmediğini doğrula.
- [ ] `GET /api/guilds/{guild_id}/commands` ile `invocation_count`'un her başarılı çağrıda arttığını, cooldown'a takılan denemelerde **artmadığını** doğrula.
- [ ] `{"enabled": false}` yaparak devre dışı bırak, çalıştırmayı dene → `invocation_count`'un artmadığını doğrula (madde 3 ile birleşik).

## 5. AppRole (bot-özel roller)

- [ ] `PUT /api/guilds/{guild_id}/app-roles/{role_name}` ile (ör. `moderator`) bir AppRole oluştur, kendi Discord user id'ni üye listesine ekle.
- [ ] `GET /api/guilds/{guild_id}/app-roles` ile rolün listelendiğini doğrula.
- [ ] `require_app_role("moderator")` ile korunan bir endpoint'e (örnek projede varsa, yoksa kendi ekle) o kullanıcıyla erişip 200 aldığını doğrula.
- [ ] AppRole'e eklenmemiş başka bir kullanıcıyla (ikinci hesap ya da session'ı manuel silip farklı biriyle login olarak) aynı endpoint'e erişip 403 aldığını doğrula.
- [ ] `DELETE /api/guilds/{guild_id}/app-roles/{role_name}` ile rolü sil → erişimin tekrar reddedildiğini doğrula.
- [ ] Bunun **Discord'un kendi rol sistemiyle bağımsız** olduğunu doğrulamak için: kullanıcıya Discord sunucusunda hiçbir özel rol vermeden sadece AppRole ata, yine de erişebildiğini gözlemle.

## 6. Guild-rol tabanlı yetkilendirme (Discord izinleri)

- [ ] `require_guild_permission("manage_guild")` ile korunan bir endpoint'e (dashboard'daki komut enable/disable endpoint'leri zaten bunu kullanıyor olabilir) "Manage Server" izni olan bir hesapla eriş → başarılı.
- [ ] İzni olmayan bir hesapla (ikinci test kullanıcısı) aynı endpoint'e eriş → 403 doğrula.
- [ ] Discord'da o kullanıcının rolünü değiştir (izni ver/al), **45 saniye (varsayılan `member_cache_ttl_seconds`) içinde** tekrar dene → eski cache'ten dolayı henüz güncellenmemiş olabileceğini gözlemle; 45 saniye sonra tekrar dene → güncellendiğini doğrula (bu, cache TTL davranışını fiziksel olarak gözlemlemek için önemli).

## 7. Çoklu Veritabanı (Postgres / MySQL) — opsiyonel, altyapın varsa

- [ ] Termux'ta yerel Postgres/MySQL kurmak zor olabilir; bunun yerine uzak bir test DB'si (ör. ücretsiz bir Postgres/MySQL sağlayıcısı) kullan.
- [ ] `pip install -e .[sql-postgres]` (veya `sql-mysql`).
- [ ] `.env`'e `DATABASE_URL=postgresql+asyncpg://user:pass@host/db` (veya `mysql+aiomysql://...`) ekle.
- [ ] Botu yeniden başlat → tabloların otomatik oluştuğunu (uygulama loglarında hata olmadığını) doğrula.
- [ ] Madde 1 (auth), madde 3-4 (komutlar/cooldown) testlerini bu DB ile tekrarla → SQLite ile aynı şekilde çalıştığını doğrula.
- [ ] Botu durdurup tekrar başlat → session/override/app-role verilerinin DB'de kalıcı olduğunu (kaybolmadığını) doğrula — bu, SQLite'tan asıl farkı gösteren test (SQLite dosyası da kalıcıdır aslında; asıl fark birden fazla instance/host'un aynı DB'yi paylaşabilmesi — elindeki altyapı izin veriyorsa iki ayrı süreci aynı `DATABASE_URL` ile başlatıp ikisinin de aynı override'ları gördüğünü doğrulayabilirsin).

## 8. WebSocket Canlı Relay (opt-in)

Bu özellik varsayılan kapalı. Test için `enable_websocket=True` ile botu başlat
(`DiscordWebAPI.quickstart(..., enable_websocket=True)` veya `api.install(app, enable_websocket=True)`).

- [ ] Bir WebSocket istemcisi ile bağlan: `websocat`, tarayıcı konsolu (`new WebSocket(...)`), veya basit bir Python scripti kullanabilirsin:
  ```python
  import asyncio, websockets
  async def main():
      # cookie ile: extra_headers={"Cookie": f"dwa_session={SESSION_ID}"}
      # veya bearer: extra_headers={"Authorization": f"Bearer {SESSION_ID}"}
      async with websockets.connect(
          "ws://localhost:8000/api/guilds/{GUILD_ID}/commands/stream",
          extra_headers={"Cookie": f"dwa_session={SESSION_ID}"},
      ) as ws:
          async for message in ws:
              print("event:", message)
  asyncio.run(main())
  ```
- [ ] **Auth testi**: Cookie/Bearer olmadan bağlanmayı dene → bağlantının `4401` koduyla kapandığını doğrula.
- [ ] **Yetki testi**: `manage_guild` izni olmayan bir kullanıcının session'ıyla bağlan → `4403` ile kapandığını doğrula.
- [ ] **Canlı yayın testi (asıl amaç)**: Yukarıdaki script'i geçerli/yetkili bir session ile bağlı bırak; başka bir terminalden (veya curl ile) `PATCH /api/guilds/{guild_id}/commands/{command_name}` çağırarak bir override değiştir → bağlı WebSocket istemcisinin **anında** (`{"guild_id": ..., "command_name": ...}` şeklinde) bir mesaj aldığını doğrula. Bu, otomatik test paketinin kapsayamadığı asıl round-trip senaryosu.
- [ ] Farklı bir `guild_id`'ye ait bir override değişikliği yap → bağlı olduğun guild'in WebSocket'ine **mesaj gelmediğini** doğrula (guild filtrelemesi çalışıyor mu).
- [ ] WebSocket bağlantısını kapat (script'i durdur), ardından birkaç kez daha `PATCH` çağır → sunucu tarafında hata/sızıntı olmadığını (loglarda exception olmadığını) doğrula — bu `Transport.unsubscribe()`'ın gerçekten devreye girdiğini gösterir.
- [ ] (İsteğe bağlı, ileri seviye) Aynı anda 5-10 WebSocket bağlantısı açıp hepsinin aynı `PATCH` sonrası mesaj aldığını doğrulayarak fan-out'u gözlemleyebilirsin.

## 9. Rate Limiting

- [ ] Aynı `PATCH .../commands/{command_name}` endpoint'ine kısa sürede çok sayıda (limitin üzerinde) istek at (ör. basit bir `for` döngüsüyle `curl`) → bir noktadan sonra `429 Too Many Requests` aldığını doğrula.
- [ ] Biraz bekle → limitin sıfırlanıp tekrar isteklerin geçtiğini doğrula.

## 10. Redis Transport (opsiyonel, çoklu-süreç senaryosu)

- [ ] Termux'ta veya erişebildiğin bir sunucuda `redis-server` çalıştır.
- [ ] Bot ve web'i **iki ayrı süreç** olarak, ikisi de `RedisTransport(redis_url=...)` kullanacak şekilde başlat (facade'i `InProcessTransport` yerine `RedisTransport` ile elle kur — `quickstart()` şu an `InProcessTransport` kullanıyor, bu senaryo composable API gerektirir).
- [ ] Web sürecinden `PATCH .../commands/{command_name}` çağır → bot sürecinin (ayrı process, ayrı event loop) komutu gerçekten devre dışı bıraktığını Discord'da doğrula.
- [ ] Web sürecinden `GET /api/guilds/{guild_id}/members` gibi bot-cache'ine giden bir istek at → botun kendi Gateway cache'inden (Redis RPC üzerinden) doğru veriyi döndürdüğünü doğrula.

---

Bir adım beklenmedik davranış gösterirse (özellikle WebSocket round-trip veya
multi-DB kalıcılık), hangi adımda takıldığını ve tam hata/log çıktısını
paylaş — birlikte kök nedene inelim.
