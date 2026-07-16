# Fiziksel Test Planı (Termux / gerçek Discord sunucusu)

Bu doküman, `discord-webapi`'nin tüm özelliklerini (v0.2 çekirdeğinden
v0.7 extension sistemine kadar) gerçek bir Discord botu + gerçek bir sunucu
(guild) üzerinde elle test etmek için adım adım bir kontrol listesidir.
Otomatik test paketi (`pytest`, 427 test yeşil) zaten geçiyor — burada amaç,
otomatik testlerin kapsamadığı ("gerçek tarayıcı", "gerçek Discord Gateway",
"gerçek OAuth2 redirect", "gerçek moderasyon aksiyonu") uçtan uca
senaryoları doğrulamak.

**Bölümler**: 1-13 çekirdek + v0.2-v0.4 özellikleri. 14-21 daha yeni
özellikler (rate limit sistemi, escalation, yeni builtin'ler, bot-tarafı
audit, required_app_role, jobs, üçüncü-taraf extension'lar, yeni örnekler).
İkisini de tek turda yapmak zorunda değilsin — takıldığın adımı ve tam
hata/log çıktısını paylaş.

**Hazır test botu**: Her adımı elle kurmak yerine `examples/full_featured_bot/`
kullan — WebSocket relay, audit log, cookie-consent banner ve her builtin
(`ban`/`kick`/`timeout`/`warn`/`welcome`) açık şekilde tek bir bot içinde
hazır (bkz. o klasördeki `README.md`). WebSocket'in gerçek canlı yayın
testini yapmak için aynı klasördeki `ws_test_client.py` scripti var —
madde 8'de bu script kullanılıyor.

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

`examples/full_featured_bot`'ta bu zaten açık (`mobile_redirect_uri`
`DASHBOARD_BASE_URL + "/mobile-login-done"` olarak ayarlı). **Bu akış,
mobilde tarayıcı cookie'si kazmadan test yapmanın en pratik yolu** —
madde 3 ve sonrasındaki tüm `curl` komutları için `session_id`'yi burada
alacaksın.

- [ ] `http://localhost:8000/dashboard`'ı aç, **URL'i elle yazma** — "Discord ile giriş yap" butonunun altındaki **"Mobil giriş (session_id al)"** butonuna tıkla. (Elle yazarsan `?mobile=true` önüne yanlışlıkla boşluk girebiliyor, bu da sessizce normal girişe düşüyor — buton bunu tamamen ortadan kaldırıyor.)
- [ ] Discord'da onayla → `/mobile-login-done` sayfası `session_id`'yi büyük, kolayca kopyalanabilir bir kutuda gösterir (bu, örnek projenin kendi küçük sayfası — kütüphanenin bir parçası değil). Boş görünüyorsa sayfa zaten "gerçek bir mobil login yönlendirmesiyle gelmedin" diye uyarıyor — o zaman `/`'a dönüp butona tekrar tıkla.
- [ ] O `session_id` değeriyle `curl -H "Authorization: Bearer <session_id>" http://localhost:8000/auth/discord/me` çağır → aynı kullanıcı bilgisinin döndüğünü doğrula (cookie olmadan, sadece header ile).
- [ ] Aynı bearer token ile `logout` sonrası tekrar `/me` çağır → 401 döndüğünü doğrula.
- [ ] Bu `session_id`'yi bir yere not et (ör. Termux'ta `export DWA_SESSION=<değer>`) — aşağıdaki tüm adımlarda tekrar kullanacaksın.

## 3. Komut Listeleme ve Enable/Disable (canlı, restart'sız)

**Önemli**: `GET`'i tarayıcı adres çubuğuna yapıştırabilirsin, ama `PATCH`
adres çubuğundan **yapılamaz** — tarayıcı adres çubuğu her zaman GET
isteği yapar, bu yüzden bir PATCH endpoint'ini tarayıcıdan açmaya
çalışırsan "Method Not Allowed" (405) alırsın; bu bir hata değil, yanlış
araç kullanmak. PATCH için `curl` kullan (Termux'ta hazır gelir). Madde
2'de aldığın `session_id`'yi burada `Authorization: Bearer` header'ı
olarak kullanıyoruz — cookie'yle uğraşmana gerek yok.

- [ ] Botta en az 2-3 farklı komut tanımlı olsun (biri slash/hybrid, biri prefix — `full_featured_bot`'ta zaten var: `ping`, `say`, `ban`, `kick`, `timeout`, `warn`).
- [ ] `GET /api/guilds/{guild_id}/commands` çağır (tarayıcıdan doğrudan açabilirsin, ama login cookie'si göndermesi için aynı tarayıcıda login olmuş olman lazım — yoksa `curl` kullan):
  ```
  curl -H "Authorization: Bearer $DWA_SESSION" \
      http://localhost:8000/api/guilds/<guild_id>/commands
  ```
  → tüm komutların (isim, açıklama, kategori, enabled, cooldown alanları, `invocation_count`) listelendiğini doğrula.
- [ ] Discord'da botun bir komutunu çalıştır (ör. `/kick` veya `!kick`) → başarıyla çalıştığını doğrula.
- [ ] Komutu kapat:
  ```
  curl -X PATCH -H "Authorization: Bearer $DWA_SESSION" \
      -H "Content-Type: application/json" \
      -d '{"enabled": false}' \
      http://localhost:8000/api/guilds/<guild_id>/commands/ping
  ```
- [ ] **Botu yeniden başlatmadan** Discord'da aynı komutu tekrar çalıştırmayı dene → komutun artık çalışmadığını (sessizce reddedildiğini) doğrula. Hem slash hem prefix/hybrid komutlarda ayrı ayrı dene.
- [ ] Aynı curl komutunu `{"enabled": true}` ile tekrar çalıştır → komutun tekrar çalıştığını doğrula.

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

- [ ] Bir WebSocket istemcisi ile bağlan: `websocat`, tarayıcı konsolu
      (`new WebSocket(...)`), veya `examples/full_featured_bot/ws_test_client.py`
      (`pip install websockets`, sonra `python ws_test_client.py <guild_id>
      <session_id>` — `session_id`'yi tarayıcıda `/dashboard`'a login olduktan
      sonra dev tools'tan `dwa_session` cookie'sinin değeri olarak al).
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

## 11. Audit Log (opt-in)

Bu özellik varsayılan kapalı. `enable_audit_log=True` ile botu başlat
(`examples/full_featured_bot`'ta zaten açık).

- [ ] `PATCH /api/guilds/{guild_id}/commands/{command_name}` ile bir override değiştir.
- [ ] `PUT`/`DELETE /api/guilds/{guild_id}/app-roles/{name}` ile bir AppRole değiştir.
- [ ] `GET /api/guilds/{guild_id}/audit-log` çağır → her iki aksiyonun da `action` (`command.set_override`, `app_role.set`/`app_role.delete`), `actor_user_id`, `target` ve `created_at` alanlarıyla, en yeni en üstte olacak şekilde listelendiğini doğrula.
- [ ] `manage_guild` izni olmayan bir kullanıcıyla aynı endpoint'e eriş → 403 aldığını doğrula.

## 12. Cookie-Consent Banner (opt-in)

Bu özellik varsayılan kapalı. `enable_cookie_consent=True` ile botu başlat
(`examples/full_featured_bot`'ta zaten açık, özel bir mesaj metniyle).

- [ ] `/dashboard`'ı **giriş yapmadan** aç → sayfanın altında cookie-consent banner'ının göründüğünü doğrula.
- [ ] "Accept" butonuna tıkla → banner'ın kapandığını doğrula. Sayfayı yenile → banner'ın (localStorage sayesinde) tekrar çıkmadığını doğrula.
- [ ] Tarayıcının localStorage'ını temizle (dev tools → Application → Local Storage), Discord ile giriş yap, `/api/consent`'i çağır (`curl` veya tarayıcı konsolundan `fetch`) → henüz onay verilmediyse `null`, "Accept"e tıklandıktan sonra `consent_version`/`given_at` alanlarıyla dolu bir kayıt döndüğünü doğrula.
- [ ] `cookie_consent_message`/`cookie_consent_version`'ı değiştirip botu yeniden başlat → banner metninin değiştiğini ve (versiyon değiştiği için) daha önce onaylamış bir kullanıcıya bile banner'ın tekrar gösterildiğini doğrula.

## 13. Kanal Bazlı İzin Override (v0.4, yeni)

`require_guild_permission`'dan farkı: guild seviyesinde bir izne sahip
olsan bile, o kanala özel bir override o izni geri alabiliyorsa bu kontrol
seni reddediyor. `full_featured_bot`'ta demo endpoint zaten hazır:
`GET /api/guilds/{guild_id}/channels/{channel_id}/can-send`.

- [ ] Sunucunda "Send Messages" iznin olan bir kanalda bu endpoint'i çağır → 200 ve `user_id`/`channel_id` döndüğünü doğrula:
  ```
  curl -H "Authorization: Bearer $DWA_SESSION" \
      http://localhost:8000/api/guilds/<guild_id>/channels/<channel_id>/can-send
  ```
- [ ] Discord'da o kanala özel bir override ekle: kanal ayarları → İzinler → kendi rolün için "Send Messages"i **Deny** yap.
- [ ] Aynı endpoint'i tekrar çağır → **45 saniye içinde** (varsayılan `channel_permission_cache_ttl_seconds=30`) 403 döndüğünü doğrula — cache TTL'inin dolmasını beklemen gerekebilir, hemen değişmeyebilir.
- [ ] Override'ı kaldır (Deny'ı temizle) → TTL dolduktan sonra tekrar 200 döndüğünü doğrula.
- [ ] Var olmayan bir `channel_id` ile çağır → 403 (bulunamadı) aldığını doğrula.

## 14. Sunucu bazlı rate limit sistemi (`ratelimits`, v0.6)

`CommandRegistry`'nin cooldown'undan farkı: bu bir komuta bağlı değil,
keyfi bir string `key`'e bağlanıyor ve dashboard'dan sunucu bazlı canlı
ayarlanabiliyor. `full_featured_bot`'ta `/ping` komutu bunu kullanıyor
(`enable_ratelimits_api=True` açık) ve `examples/skeleton_custom_command`
`/weather` ile aynısını gösteriyor.

- [ ] Botta `/ping` komutunu (full_featured_bot) birkaç kez üst üste çalıştır → varsayılan limitte (5 çağrı / 10 sn) bir noktadan sonra "Slow down!" yanıtı aldığını doğrula.
- [ ] Limiti bir sunucu için sıkılaştır (restart YOK):
  ```
  curl -X PUT -H "Authorization: Bearer $DWA_SESSION" -H "Content-Type: application/json" \
      -d '{"max_calls": 1, "per_seconds": 30}' \
      http://localhost:8000/api/guilds/<guild_id>/ratelimits/ping
  ```
- [ ] `/ping`'i iki kez çalıştır → ilki geçer, ikincisi "Slow down!" ile reddedilir (30 sn içinde).
- [ ] **Farklı bir kullanıcıyla** aynı anda `/ping` dene → limitin kişi bazlı (`sub_key`) olduğunu, diğer kullanıcının etkilenmediğini doğrula.
- [ ] `GET /api/guilds/<guild_id>/ratelimits/ping` → kuralın döndüğünü doğrula. `DELETE` ile sil → `/ping` tekrar varsayılan limite döner.
- [ ] **İkinci bir sunucuda** (botun olduğu başka bir guild) `/ping`'in hâlâ varsayılan limitte olduğunu, ilk sunucudaki değişiklikten etkilenmediğini doğrula (per-guild izolasyon).

## 15. Escalation motoru (ceza-eşikleme, `escalation`, v0.6)

**Hiçbir varsayılan eşik/aksiyon YOK** — merdivenin her basamağını sen
tanımlarsın. `full_featured_bot`'ta `automod`'un `on_violation`'ı
`EscalationEngine`'i besliyor (`enable_escalation_api=True` açık).
`examples/hybrid_moderation` bunu odaklı gösteriyor.

- [ ] Merdiven tanımla (restart YOK): 3 automod ihlalinde timeout, 5'te kick:
  ```
  curl -X PUT -H "Authorization: Bearer $DWA_SESSION" -H "Content-Type: application/json" \
      -d '{"action": "timeout", "action_minutes": 10}' \
      http://localhost:8000/api/guilds/<guild_id>/escalation-rules/automod/3
  curl -X PUT -H "Authorization: Bearer $DWA_SESSION" -H "Content-Type: application/json" \
      -d '{"action": "kick"}' \
      http://localhost:8000/api/guilds/<guild_id>/escalation-rules/automod/5
  ```
- [ ] `GET /api/guilds/<guild_id>/escalation-rules` → iki kuralın da listelendiğini doğrula.
- [ ] Bir test hesabıyla, automod'un yakalayacağı bir mesajı (madde 16'daki yasaklı kelime) **tam 3 kez** gönder → 3. ihlalde o hesabın gerçekten timeout aldığını Discord'da doğrula.
- [ ] Aynı hesapla 5. ihlale ulaş → gerçekten kick edildiğini doğrula. (Not: kick sonrası tekrar sunucuya davet et.)
- [ ] **Hiç kural tanımlanmamış** bir `key` için ihlaller olsun → sadece sayıldığını, hiçbir aksiyon alınmadığını doğrula ("biz dayatmayalım" ilkesi).
- [ ] `DELETE .../escalation-rules/automod/3` ile bir basamağı sil → o eşikte artık aksiyon alınmadığını doğrula.

## 16. Yeni builtin'ler: `role_assign` + `automod` (v0.5-v0.6)

**role_assign** (`/role-add`, `/role-remove`):
- [ ] `/role-add @member @role` çalıştır → rolün gerçekten atandığını doğrula.
- [ ] Botun kendi en yüksek rolünden **daha yüksek** bir rolü atamayı dene → reddedildiğini doğrula (rol-hiyerarşisi koruması; bu, hedef üyenin değil, verilen ROLÜN sırasını kontrol ediyor).
- [ ] `/role-remove @member @role` → rolün alındığını doğrula.

**automod** (7 bağımsız kontrol) — `full_featured_bot`'ta `banned_words_list=[]`
(boş) + `block_invites=True` ile açık. Test için `main.py`'de
`banned_words_list=["yasakkelime"]` yap ve yeniden başlat:
- [ ] Yasaklı kelime içeren mesaj gönder → mesajın silindiğini + kısa uyarı yanıtının (10sn sonra otomatik silinen) çıktığını doğrula.
- [ ] Başka bir sunucunun davet linkini (`discord.gg/...`) gönder → silindiğini doğrula (invite filter).
- [ ] Kısa sürede çok sayıda (varsayılan 5/10sn) mesaj gönder → spam olarak yakalandığını doğrula.
- [ ] Çok sayıda mention (varsayılan >5) içeren mesaj → mention-spam yakalandığını doğrula.
- [ ] `manage_messages` izni olan bir moderatör hesabıyla aynı yasaklı mesajı gönder → **muaf** tutulduğunu (silinmediğini) doğrula (`exemptions`).
- [ ] (Opsiyonel) `caps_ratio`, `max_emoji`, `allowed_domains`/`blocked_domains` parametrelerini `setup_automod`'a ekleyip caps/emoji/link filtrelerini de dene.

## 17. Bot-tarafı audit (warn / escalation / automod, v0.7)

Audit log artık sadece dashboard yazmalarını değil, bot-tarafı moderasyon
aksiyonlarını da (opt-in) kaydediyor. `full_featured_bot` `enable_audit_log=True`
ile açık. **Not**: warn/automod audit'i için `setup_warn`/`setup_automod`'a
`audit_logger=app.state.discord_webapi_audit_logger` geçilmeli (quickstart
sonrası; escalation audit'i `enable_audit_log` ile otomatik).

- [ ] Madde 15'teki gibi automod ihlalleriyle bir escalation tetikle (timeout/kick).
- [ ] `GET /api/guilds/<guild_id>/audit-log` çağır → `escalation.timeout`/`escalation.kick` kaydının `actor_user_id: 0` (otomatik aksiyon), `target` (üye id), ve `detail` (key/threshold/count) ile göründüğünü doğrula.
- [ ] `full_featured_bot`'a `setup_warn(bot, audit_logger=...)` ekleyip `/warn @member sebep` çalıştır → audit-log'da `action: "warn"`, `actor_user_id` = moderatörün id'si olan bir kayıt gördüğünü doğrula.
- [ ] `setup_automod(bot, ..., audit_logger=...)` ile bir ihlal tetikle → `automod.violation` kaydını (actor 0) doğrula.
- [ ] Bu bot-tarafı kayıtların, madde 11'deki dashboard kayıtlarıyla **aynı** audit-log'da (aynı store) birlikte listelendiğini doğrula.

## 18. Komut için `required_app_role` (v0.7)

Bir komutu belirli bir AppRole'e sahip olanlarla sınırla — Discord izninden
bağımsız, dashboard'dan canlı ayarlanır.
- [ ] Madde 5'teki gibi bir `moderator` AppRole oluştur, kendi user id'ni ekle.
- [ ] Bir komuta bu rolü şart koş:
  ```
  curl -X PATCH -H "Authorization: Bearer $DWA_SESSION" -H "Content-Type: application/json" \
      -d '{"enabled": true, "required_app_role": "moderator"}' \
      http://localhost:8000/api/guilds/<guild_id>/commands/ping
  ```
- [ ] `moderator` AppRole'ünde olan hesabınla `/ping` çalıştır → çalıştığını doğrula.
- [ ] AppRole'de **olmayan** ikinci bir hesapla `/ping` dene → reddedildiğini doğrula (Discord izni ne olursa olsun).
- [ ] `GET .../commands` ile komutun `required_app_role: "moderator"` gösterdiğini doğrula. `{"enabled": true, "required_app_role": null}` ile kaldır → herkes tekrar çalıştırabilsin.

## 19. İş kuyruğu (`jobs`, opt-in)

Varsayılan kapalı; `enable_jobs=True` + bir `job_queue` (worker'ları
`register_worker` ile kayıtlı) gerektirir — bu senaryo composable API
gerektiriyor (quickstart job_queue kurmuyor).
- [ ] `InProcessJobQueue()` kur, bir `job_type` için `register_worker` ile handler kaydet, `DiscordWebAPI(..., job_queue=...)` + `install(app, enable_jobs=True)`.
- [ ] `POST /api/guilds/<guild_id>/jobs` ile bir iş kuyruğa at → `job_id` döndüğünü doğrula.
- [ ] `GET /api/guilds/<guild_id>/jobs/<job_id>` ile durumun `pending`→`running`→`succeeded` (ya da `failed`) olarak ilerlediğini doğrula.
- [ ] (Redis varsa) `RedisJobQueue` ile **iki ayrı worker süreci** başlat, çok sayıda iş at → her işin sadece BİR worker tarafından işlendiğini (competing-consumer) doğrula.

## 20. Üçüncü-taraf extension (`extensions` + scaffold, v0.7)

`discord-webapi`'nin kendi `extras`'ı gibi, başkalarının yazıp paylaşabileceği
paketler. Kod çalıştıran bir plugin VM değil — sıradan bir pip paketi.
- [ ] Bir iskelet extension üret: `discord-webapi-scaffold new funbot` (ya da `python -m discord_webapi.extensions.scaffold new funbot`).
- [ ] Üretilen klasöre gir, `pip install -e ".[dev]"` → `python -m pytest` (üretilen örnek test geçmeli).
- [ ] Ana bot projenden keşfet:
  ```python
  from discord_webapi.extensions import ExtensionRegistry
  reg = ExtensionRegistry.discover()
  print(reg.names)                      # ['funbot'] görmeli
  d = reg.get("funbot")
  print(d.compatible, d.compat_reason)  # True, None
  ```
- [ ] `d.extension.setup(bot, rate_limiter=app.state.discord_webapi_ratelimiter)` çağır → üretilen `/roll` komutunun botta çalıştığını Discord'da doğrula.
- [ ] `funbot/__init__.py`'de manifest'in `discord_webapi_requires`'ını uyumsuz bir aralığa (`">=99.0"`) değiştir, tekrar keşfet → `d.compatible == False` ve `compat_reason`'ın anlamlı bir mesaj döndüğünü doğrula.
- [ ] İki farklı extension'ı aynı `name` ile kurup keşfet → `reg.errors`'da "duplicate" hatası olduğunu, birinin yine de çalıştığını doğrula.

## 21. Yeni odaklı örnekler (v0.7)

- [ ] `examples/skeleton_custom_command/` çalıştır → `/weather Istanbul` kendi yanıtını versin; madde 14'teki gibi `ratelimits/weather` ile limiti canlı ayarla, `/weather`'ın rate-limit'lendiğini doğrula.
- [ ] `examples/hybrid_moderation/` çalıştır → `main.py`'de `BANNED_WORDS`'e bir kelime ekle; o kelimeyi gönderince (a) mesaj silinsin, (b) `/warns` sayısı artsın (paylaşılan WarnStore), (c) madde 15'teki gibi bir escalation merdiveni tanımlıysa eşiğe ulaşınca aksiyon alınsın — üç sistemin birlikte, her biri kendi şeridinde çalıştığını gözlemle.

---

Bir adım beklenmedik davranış gösterirse (özellikle WebSocket round-trip,
multi-DB kalıcılık, escalation tetikleme, ya da extension keşfi), hangi
adımda takıldığını ve tam hata/log çıktısını paylaş — birlikte kök nedene
inelim.
