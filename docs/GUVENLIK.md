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
için. `discord_webapi.dashboard_ratelimit.TokenBucketLimiter` bağımsız bir modülde
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
- **Çoklu-tenant Redis paylaşımı**: birbirinden bağımsız birden fazla
  deployment (ör. farklı müşterilerin botları) aynı Redis
  instance'ını/cluster'ını paylaşıyorsa, her birine ayrı bir
  `namespace=` verin (`RedisTransport(namespace=...)`,
  `RedisJobQueue(namespace=...)`) — kanal/kuyruk isimleri
  namespace'lendiği için, farklı namespace'lere sahip iki deployment aynı
  Redis'te bile birbirinin event'lerini/RPC trafiğini/job'larını
  göremiyor. **Bu bir kimlik doğrulama değil, sadece isim-alanı
  izolasyonu** — birbirine güvenmeyen (mutually untrusted) tenant'lar
  için gerçek izolasyon istiyorsanız ayrı Redis veritabanı/ACL kullanıcısı
  kullanın, sadece `namespace` yeterli değildir.
- **"Bir komuta tek handler" kısıtlaması** (`RedisTransport`): iki process
  aynı komutu register ederse hangisinin cevap vereceği garanti değil
  (ilk cevap kazanır, undefined davranış). Bu operasyonel bir tuzak —
  dikkatli deploy gerektiriyor (bkz. `docs/DAGITIM.md`'deki "tam olarak
  bir `bot_process.py`" notu). Kütüphane şu an bunu çalışma zamanında
  otomatik tespit etmiyor; deploy sürecinizde (ör. tek bir replica/pod
  sayısı ile) bunu garanti altına almanız gerekiyor.

## Bilinen, düşük öncelikli noktalar (düzeltildi)

- ~~`TokenBucketLimiter`'ın `_buckets` dict'i process ömrü boyunca
  sınırsız büyüyor~~ **Düzeltildi**: artık `max_tracked_keys` (varsayılan
  10.000) ile sınırlı, LRU-evicted bir `OrderedDict` kullanıyor. Bir
  entry'nin evict edilmesi zararsız — o key bir sonraki görülüşünde dolu
  bir bucket'la geri geliyor (hiç görülmemiş bir key'le aynı davranış).

## Denetim geçmişi

Kapsamlı bir güvenlik denetiminde (auth, authz, transport, storage, rate
limiting) iki gerçek bug bulunup düzeltildi:

1. `/auth/discord/logout` ve session-management endpoint'lerinde rate
   limit eksikti.
2. `DiscordAuth._refresh_locks` dict'i sınırsız büyüyordu.

Kuyruk sistemi eklendikten sonraki ikinci bir taramada (bu kez jobs/
çoklu-sunucu refactoring'ine odaklı) iki bug daha bulunup düzeltildi:

3. `RedisJobQueue`'da kuyrukta bekleyen bir job'ın status'u, TTL süresi
   geçince sessizce silinip job'ın kaybolmasına yol açabiliyordu — TTL
   artık sadece terminal (succeeded/failed) durumdaki job'lara uygulanıyor.
4. `RedisJobQueue.register_worker()`, `start()`'tan sonra çağrılırsa
   sessizce hiçbir şey yapmıyordu — artık açık bir hata fırlatıyor.

Bu iki denetimi harici olarak inceleyen bir üçüncü taraf, üç ek nokta
işaret etti (ikisi bilinçli tasarım kararı olarak zaten dokümante
edilmişti, biri gerçek bir iyileştirmeydi) — üçü de ele alındı:

5. `TokenBucketLimiter._buckets`'ın sınırsız büyümesi — yukarıda
   anlatıldığı gibi düzeltildi (LRU-bounded).
6. Çoklu-tenant Redis paylaşımı riski — `RedisTransport`/`RedisJobQueue`'ye
   `namespace=` parametresi eklendi, farklı tenant'ların kanal/kuyruk
   isimlerini çakıştırmadan aynı Redis'i paylaşabilmesi için (yukarıdaki
   "Transport güven sınırları" bölümüne bakın — bu izolasyon, kimlik
   doğrulama değil).
7. "Bir komuta tek handler" kısıtlaması — bilinçli bir tasarım kararı
   olarak kalıyor (bkz. yukarısı), operasyonel bir dikkat noktası olarak
   dokümante edildi, çalışma zamanında otomatik tespit eklenmedi.

Detaylı denetim raporları için `CHANGELOG.md`'deki ilgili sürüm
notlarına bakın.
