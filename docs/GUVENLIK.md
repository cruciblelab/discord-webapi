# Güvenlik Modeli

Bu dosya, kütüphanenin güvenlik tasarım kararlarını ve kapsamlı bir
güvenlik denetiminde doğrulanan/düzeltilen noktaları özetliyor.

## Kimlik doğrulama

- **OAuth2 state/CSRF**: `secrets.token_urlsafe(32)` (256 bit) state
  token'ı, httpOnly/Secure/SameSite=Lax bir cookie'de tutuluyor,
  callback'te `secrets.compare_digest` ile karşılaştırılıyor.
- **Session id**: `secrets.token_urlsafe(32)`, opak — JWT değil, sunucu
  taraflı bir `SessionStore` satırına karşılık geliyor. Discord'un
  kendi access/refresh token'ları hiçbir zaman tarayıcıya gitmiyor;
  `Fernet`/`MultiFernet` ile şifrelenip aynı session satırında tutuluyor
  (key rotasyonu destekleniyor).
- **Cookie flag'leri**: `httponly=True`, `secure=True` (varsayılan),
  `samesite="lax"` — hem session hem OAuth2 state cookie'si için.
- **Token refresh race**: eşzamanlı iki isteğin aynı session'ın süresi
  dolmuş Discord token'ını aynı anda refresh etmeye çalışması,
  per-session `asyncio.Lock` ile önleniyor — kaybeden istek kazananın
  yazdığı güncel token'ı kullanıyor. Lock, refresh tamamlandıktan sonra
  evict ediliyor (sınırsız büyümesin diye).
- **Oturum yönetimi**: `DELETE /auth/discord/sessions/{id}` sadece
  çağıranın kendi `user_id`'sine ait session'ı silebiliyor — başkasının
  session id'si 404 dönüyor (var olup olmadığını sızdırmamak için 403
  değil).

## Yetkilendirme

- Her guild/channel-scoped kontrol **fail-closed**: bot'un warm cache'i
  kullanıcıyı o guild'de/kanalda üye olarak bulamazsa 403 dönüyor,
  varsayılan olarak izin vermiyor.
- `guild_id`/`channel_id` path parametreleri her zaman bot-tarafı
  lookup'a (`(guild_id, user_id)` anahtarlı) karşı doğrulanıyor — bir
  kullanıcı path'teki `guild_id`'yi değiştirerek başka bir sunucunun
  verisine erişemiyor, çünkü lookup'ın kendisi o kombinasyona özel.
- `GET /api/guilds` filtrelemesi tamamen sunucu tarafında yapılıyor
  (`has_permission(..., "manage_guild")`) — istemciden gelen hiçbir
  girdiye güvenilmiyor.

## Rate limiting

State-changing tüm endpoint'ler (`PATCH` komut override, `PUT`/`DELETE`
app-role, `DELETE` session, `POST` job enqueue) bir `TokenBucketLimiter`
ile korunuyor — çalınmış bir session'ın brute-force/abuse aracı olmaması
için. `discord_webapi.ratelimit.TokenBucketLimiter` bağımsız bir modülde
(auth ile commands arasında circular import olmadan paylaşılabilsin diye).

## SQL storage

Tamamen SQLAlchemy ORM üzerinden — hiçbir yerde raw string
interpolation/f-string SQL yok, injection riski yok. Token'lar sadece
şifreli (`encrypted_access_token`/`encrypted_refresh_token`) tutuluyor,
hiçbir yerde loglanmıyor.

## Transport güven sınırları

- **`RedisTransport`**: pub/sub kanalları imzasız/kimlik doğrulamasız —
  Redis'in kendisinin güvenilir altyapı olması gerekiyor (herkese açık
  bırakılmamalı). Aynı Redis'e yazabilen biri RPC cevaplarını/event'leri
  taklit edebilir. Bu bilinçli bir tasarım kararı — kaynak: Redis
  genellikle "iç veritabanı" gibi ele alınır, dışa açık bir servis değil.
- **`RedisJobQueue`**: aynı gerekçe — Redis'in kendisi güvenilir olmalı.

## Bilinen, düşük öncelikli noktalar (düzeltilmedi, dokümante edildi)

- `commands.ratelimit.TokenBucketLimiter`'ın `_buckets` dict'i process
  ömrü boyunca sınırsız büyüyor (yeni kullanıcı başına bir entry) — sadece
  bellek, auth bypass değil.

## Denetim geçmişi

Kapsamlı bir güvenlik denetiminde (auth, authz, transport, storage, rate
limiting) iki gerçek bug bulunup düzeltildi:

1. `/auth/discord/logout` ve session-management endpoint'lerinde rate
   limit eksikti.
2. `DiscordAuth._refresh_locks` dict'i sınırsız büyüyordu.

Detaylı denetim raporu için `CHANGELOG.md`'deki ilgili sürüm notuna
bakın.
