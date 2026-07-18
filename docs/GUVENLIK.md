# Güvenlik Modelimiz

Bu dosyada, kütüphanemizin güvenlik tasarım kararlarımızı ve kapsamlı bir
güvenlik denetimimizde doğruladığımız/düzelttiğimiz noktaları özetliyoruz.

## Kimlik doğrulamamız

- **OAuth2 state/CSRF**: `secrets.token_urlsafe(32)` (256 bit) state
  token'ımızı, httpOnly/Secure/SameSite=Lax bir cookie'de tutuyoruz,
  callback'te `secrets.compare_digest` ile karşılaştırıyoruz.
- **Session id'miz**: `secrets.token_urlsafe(32)`, opak — JWT değil,
  sunucu taraflı bir `SessionStore` satırına karşılık geliyor. Discord'un
  kendi access/refresh token'ları hiçbir zaman tarayıcıya gitmiyor;
  `Fernet`/`MultiFernet`'imizle şifrelenip aynı session satırında
  tutuluyor (key rotasyonunu destekliyoruz).
- **Cookie flag'lerimiz**: `httponly=True`, `secure=True` (varsayılanımız),
  `samesite="lax"` — hem session hem OAuth2 state cookie'miz için.
- **Token refresh race'i**: eşzamanlı iki isteğin aynı session'ın süresi
  dolmuş Discord token'ını aynı anda refresh etmeye çalışmasını,
  per-session `asyncio.Lock`'umuzla önlüyoruz — kaybeden istek kazananın
  yazdığı güncel token'ı kullanıyor. Lock'umuz, refresh tamamlandıktan
  sonra evict ediliyor (sınırsız büyümesin diye).
- **Oturum yönetimimiz**: `DELETE /auth/discord/sessions/{id}` sadece
  çağıranın kendi `user_id`'sine ait session'ı silebiliyor — başkasının
  session id'si 404 dönüyor (var olup olmadığını sızdırmamak için 403
  değil).

## Yetkilendirmemiz

- Her guild/channel-scoped kontrolümüz **fail-closed**: bot'un warm
  cache'i kullanıcıyı o guild'de/kanalda üye olarak bulamazsa 403
  dönüyoruz, varsayılan olarak izin vermiyoruz.
- `guild_id`/`channel_id` path parametrelerini her zaman bot-tarafı
  lookup'a (`(guild_id, user_id)` anahtarlı) karşı doğruluyoruz — bir
  kullanıcı path'teki `guild_id`'yi değiştirerek başka bir sunucunun
  verisine erişemiyor, çünkü lookup'ın kendisi o kombinasyona özel.
- `GET /api/guilds` filtrelememizi tamamen sunucu tarafında yapıyoruz
  (`has_permission(..., "manage_guild")`) — istemciden gelen hiçbir
  girdiye güvenmiyoruz.

## Rate limiting'imiz

State-changing tüm endpoint'lerimizi (`PATCH` komut override, `PUT`/`DELETE`
app-role, `DELETE` session, `POST` job enqueue) bir `TokenBucketLimiter`'ımızla
koruyoruz — çalınmış bir session'ın brute-force/abuse aracı olmaması için.
`discord_webapi.dashboard_ratelimit.TokenBucketLimiter`'ımızı bağımsız bir
modülde tutuyoruz (auth ile commands arasında circular import olmadan
paylaşabilelim diye).

## SQL storage'ımız

Tamamen SQLAlchemy ORM üzerinden çalışıyoruz — hiçbir yerde raw string
interpolation/f-string SQL kullanmıyoruz, injection riski yok. Token'ları
sadece şifreli (`encrypted_access_token`/`encrypted_refresh_token`)
tutuyoruz, hiçbir yerde loglamıyoruz.

## Transport güven sınırlarımız

- **`RedisTransport`'umuz**: pub/sub kanallarımız imzasız/kimlik
  doğrulamasız — Redis'in kendisinin güvenilir altyapı olmasını
  bekliyoruz (herkese açık bırakılmamalı). Aynı Redis'e yazabilen biri
  RPC cevaplarımızı/event'lerimizi taklit edebilir. Bu bizim bilinçli
  bir tasarım kararımız — gerekçemiz: Redis genellikle "iç veritabanı"
  gibi ele alınır, dışa açık bir servis değil.
- **`RedisJobQueue`'muz**: aynı gerekçe — Redis'in kendisi güvenilir
  olmalı.
- **Çoklu-tenant Redis paylaşımı**: birbirinden bağımsız birden fazla
  deployment'ınız (ör. farklı müşterilerin botları) aynı Redis
  instance'ını/cluster'ını paylaşıyorsa, her birine bizim sunduğumuz
  ayrı bir `namespace=` parametresini verin (`RedisTransport(namespace=...)`,
  `RedisJobQueue(namespace=...)`) — kanal/kuyruk isimlerimiz
  namespace'lendiği için, farklı namespace'lere sahip iki deployment aynı
  Redis'te bile birbirinin event'lerini/RPC trafiğini/job'larını
  göremiyor. **Bu bir kimlik doğrulama değil, sadece bizim sunduğumuz
  isim-alanı izolasyonu** — birbirine güvenmeyen (mutually untrusted)
  tenant'lar için gerçek izolasyon istiyorsanız ayrı Redis
  veritabanı/ACL kullanıcısı kullanın, bizim `namespace` özelliğimiz tek
  başına yeterli değildir.
- **"Bir komuta tek handler" kısıtlamamız** (`RedisTransport`): iki
  process aynı komutu register ederse hangisinin cevap vereceği garanti
  değil (ilk cevap kazanır, undefined davranış). Bu operasyonel bir
  tuzak — dikkatli deploy gerektiriyor (bkz. `docs/DAGITIM.md`'deki "tam
  olarak bir `bot_process.py`" notumuz). Kütüphanemiz şu an bunu çalışma
  zamanında otomatik tespit etmiyor; deploy sürecinizde (ör. tek bir
  replica/pod sayısı ile) bunu garanti altına almanız gerekiyor.

## Bilinen, düşük öncelikli noktalarımız (düzelttik)

- ~~`TokenBucketLimiter`'ımızın `_buckets` dict'i process ömrü boyunca
  sınırsız büyüyor~~ **Düzelttik**: artık `max_tracked_keys` (varsayılanımız
  10.000) ile sınırlı, LRU-evicted bir `OrderedDict` kullanıyoruz. Bir
  entry'nin evict edilmesi zararsız — o key bir sonraki görülüşünde dolu
  bir bucket'la geri geliyor (hiç görülmemiş bir key'le aynı davranış).

## Denetim geçmişimiz

Kapsamlı bir güvenlik denetimimizde (auth, authz, transport, storage,
rate limiting) iki gerçek bug bulup düzelttik:

1. `/auth/discord/logout` ve session-management endpoint'lerimizde rate
   limit eksikti.
2. `DiscordAuth._refresh_locks` dict'imiz sınırsız büyüyordu.

Kuyruk sistemimizi ekledikten sonraki ikinci bir taramamızda (bu kez
jobs/çoklu-sunucu refactoring'imize odaklı) iki bug daha bulup düzelttik:

3. `RedisJobQueue`'muzda kuyrukta bekleyen bir job'ın status'u, TTL
   süresi geçince sessizce silinip job'ın kaybolmasına yol açabiliyordu
   — TTL'imiz artık sadece terminal (succeeded/failed) durumdaki
   job'lara uygulanıyor.
4. `RedisJobQueue.register_worker()`'ımız, `start()`'tan sonra çağrılırsa
   sessizce hiçbir şey yapmıyordu — artık açık bir hata fırlatıyor.

Bu iki denetimimizi harici olarak inceleyen bir üçüncü taraf, üç ek nokta
işaret etti (ikisi bizim bilinçli tasarım kararımız olarak zaten
dokümante etmiştik, biri gerçek bir iyileştirmeydi) — üçünü de ele aldık:

5. `TokenBucketLimiter._buckets`'ımızın sınırsız büyümesi — yukarıda
   anlattığımız gibi düzelttik (LRU-bounded).
6. Çoklu-tenant Redis paylaşımı riski — `RedisTransport`/`RedisJobQueue`'ye
   `namespace=` parametremizi ekledik, farklı tenant'ların kanal/kuyruk
   isimlerini çakıştırmadan aynı Redis'i paylaşabilmesi için (yukarıdaki
   "Transport güven sınırlarımız" bölümüne bakın — bu izolasyon, kimlik
   doğrulama değil).
7. "Bir komuta tek handler" kısıtlamamız — bilinçli bir tasarım kararımız
   olarak kalıyor (bkz. yukarısı), operasyonel bir dikkat noktası olarak
   dokümante ettik, çalışma zamanında otomatik tespit eklemedik.

Detaylı denetim raporlarımız için `CHANGELOG.md`'deki ilgili sürüm
notlarımıza bakın.
