# Özellikler

## Discord OAuth2 girişi

```python
from discord_webapi import DiscordAuth

auth = DiscordAuth(
    client_id=...,
    client_secret=...,
    redirect_uri="https://dashboard.example.com/auth/discord/callback",
    encryption_keys=fernet_key,
    session_store=SQLSessionStore(engine),  # varsayılan: MemorySessionStore
)
auth.install(app)
```

Bağlanan route'lar:

- `GET /auth/discord/login` — Discord'a yönlendirir (CSRF korumalı state).
- `GET /auth/discord/callback` — code exchange, session kurulumu.
- `POST /auth/discord/logout` — oturumu kapatır.
- `GET /auth/discord/me` — giriş yapmış kullanıcının bilgisi.
- `GET /auth/discord/sessions` — kullanıcının tüm aktif oturumlarını
  listeler, hangisinin şu anki oturum olduğunu (`is_current`) işaretler.
  Şifreli Discord token'ları hiçbir zaman dönmez.
- `DELETE /auth/discord/sessions/{session_id}` — belirli bir oturumu
  iptal eder ("her yerden çıkış yap" için tek tek çağrılabilir). Sadece
  kendi oturumunuzu iptal edebilirsiniz; başkasının session id'si 404
  döner (var olup olmadığını sızdırmamak için 403 değil).

**Mobil/API istemciler için**: `/auth/discord/login?mobile=true` cookie
yerine, girişten sonra `mobile_redirect_uri`'ye `session_id` query
parametresiyle yönlendirir. İstemci bu değeri her istekte
`Authorization: Bearer <session_id>` olarak gönderir — aynı auth mantığı,
iki farklı taşıma şekli.

## Sunucu-rol bazlı yetkilendirme

```python
from discord_webapi import require_guild_permission, GuildContext

@app.post("/api/guilds/{guild_id}/settings")
async def update_settings(
    guild_id: int, ctx: GuildContext = Depends(require_guild_permission("manage_guild"))
):
    ...
```

Discord'un kendi `discord.Permissions` bitfield'ı kullanılıyor —
`administrator` her zaman geçer.

## Kanal bazlı izin override'ı

```python
from discord_webapi import require_channel_permission

@app.get("/api/guilds/{guild_id}/channels/{channel_id}/can-send")
async def can_send(ctx=Depends(require_channel_permission("send_messages"))):
    ...
```

`require_guild_permission`'dan farkı: guild-level izne sahip olsanız bile,
o kanala özel bir override izni geri alabilir (`channel.permissions_for`
kullanılıyor — Discord'un kendi UI'ının gösterdiğiyle aynı hesaplama).

## Bot-özel roller (AppRole)

Discord'un rol sisteminden bağımsız, sadece bu uygulamaya özel roller:

```python
from discord_webapi import require_app_role

@app.post("/api/guilds/{guild_id}/mod-action")
async def mod_action(ctx=Depends(require_app_role("moderator"))):
    ...
```

Yönetimi: `GET/PUT/DELETE /api/guilds/{guild_id}/app-roles`.

## Komut yönetimi

```python
registry = CommandRegistry(bot, transport=transport, store=command_store)
registry.register_all()
```

- `GET /api/guilds/{guild_id}/commands` — botun tüm komutlarını (spec +
  override + invocation sayacı ile) listeler.
- `PATCH /api/guilds/{guild_id}/commands/{name}` — enable/disable,
  cooldown ayarı — **restart gerekmez**, aynı anda çalışan bot canlı
  olarak uygular.

Cooldown, discord.py'nin kendi `Cooldown`/`CooldownMapping` mekanizması
üzerinden, kullanıcı bazlı uygulanıyor.

## Sunucu listesi

```
GET /api/guilds
```

Giriş yapmış kullanıcının kendi Discord sunucu listesinden, hem botun da
içinde olduğu HEM DE kullanıcının "Manage Server" yetkisine sahip olduğu
sunucuları döner — "sunucu seç" ekranı için, her sunucuyu tek tek
denemeden.

## Üye listesi

```
GET /api/guilds/{guild_id}/members
```

Rolleriyle birlikte üye listesi (view-only).

## Audit log (opt-in)

```python
DiscordWebAPI(..., audit_store=SQLAuditStore(engine))
api.install(app, enable_audit_log=True)
```

`GET /api/guilds/{guild_id}/audit-log` — state-changing dashboard
aksiyonlarının (komut override yazma, app-role set/delete) kaydı. Auth
login/logout olayları kapsam dışı (bilinçli tercih).

## Cookie/gizlilik onayı (opt-in)

```python
DiscordWebAPI(..., consent_store=SQLConsentStore(engine))
api.install(app, enable_cookie_consent=True, cookie_consent_message="...")
```

`GET/POST /api/consent` — "kim, hangi versiyonu, ne zaman onayladı"
kaydı. Notice'ın metni/tasarımı tamamen tüketiciye ait; kütüphane sadece
kaydı tutuyor, davranış dayatmıyor.

## Hazır komutlar (`discord_webapi.extras`)

Serbestçe import edilebilir, opsiyonel, `setup(bot, **kwargs)` ile açıkça
çağrılan komutlar — otomatik yükleme yok:

- `ban.py`, `kick.py`, `timeout.py` — rol-hiyerarşisi koruması, opsiyonel
  DM bildirimi.
- `warn.py` — kalıcı durumlu, kendi `WarnStore`'u (Memory/SQL), opsiyonel
  otomatik timeout eskalasyonu.
- `welcome.py` — `on_member_join` event listener'ı, kanal ya da DM.
- `role_assign.py` — `/role-add`/`/role-remove` komutları. Diğer moderasyon komutları gibi rol-hiyerarşisi korumalı, ama hedef *üyenin* değil, verilen/alınan *rolün* sırasını kontrol ediyor (bot token'ı API çağrısını yaptığı için Discord hiyerarşi kontrolünü botun kendi sırasına göre yapıyor, çağıran kullanıcının sırasına göre değil).
- `automod/` — ikinci komut-olmayan builtin, ve tek dosya yerine tam bir alt paket: yedi bağımsız, tek başına import edilebilir kontrol (`banned_words.py`, `spam.py`, `mention_spam.py`, `invite_filter.py`, `link_filter.py`, `caps_spam.py`, `emoji_spam.py`) + kimin muaf tutulacağını belirleyen `exemptions.py` + hepsini birleştiren `automod/__init__.py::setup()`. Her kontrol saf, senkron, yan etkisiz bir fonksiyon (`discord.Message -> str | None`) — hiç `await` yok, hiç I/O yok, düz bir sahte mesaj nesnesiyle tek başına test edilebiliyor. `setup()` Discord'a dokunan tek yer: etkin kontrolleri sırayla çalıştırıp ilk ihlalde duruyor, sonra mesajı siliyor / kısa bir kanal bildirimi gönderiyor / kalıcı bir log-kanalı kaydı atıyor / kendi `on_violation` callback'inizi await ediyor — hepsi bağımsız açılıp kapatılabilir. Ban/kick/timeout'a yükseltmiyor, kalıcı ihlal sayacı tutmuyor (o `warn.py`'nin işi) — `on_violation=` ile kendi `WarnStore`'unuzu besleyebilirsiniz, `automod`'un `warn.py`'ye hiç bağımlılığı olmadan.

`_shared.py`'deki `check_role_hierarchy`/`notify_member_best_effort`
bağımsız kullanılabilir — sadece bunları alıp kendi komutunuza gömebilir,
hazır komutu olduğu gibi kullanabilir, ya da hibrit yapabilirsiniz.

## WebSocket canlı relay (opt-in)

```python
api.install(app, enable_websocket=True)
```

`GET /api/guilds/{guild_id}/commands/stream` — komut config değişikliklerini
polling olmadan anlık push eder.

## Sunucu bazlı rate limit sistemi (`discord_webapi.ratelimits`)

`CommandRegistry`'nin cooldown'ı sadece bir discord.py komutuna bağlı —
`GuildRateLimiter` aynı deseni (sunucu bazlı, dashboard'dan
ayarlanabilir, restart'sız canlı güncelleme) keyfi bir string `key`'e
bağlıyor. Bir komuta bağlı olmak zorunda değil — bir automod kontrolüne,
bir webhook handler'ına, ya da `CommandRegistry`'den hiç geçmeyen
elle yazılmış bir komuta bağlanabilir:

```python
# Elle yazılmış bir komut, kendi rate limit'ini bizim altyapımızla kuruyor:
@bot.hybrid_command(name="ping")
async def ping(ctx):
    allowed = await app.state.discord_webapi_ratelimiter.check(
        ctx.guild.id, "ping", sub_key=str(ctx.author.id)
    )
    if not allowed:
        await ctx.reply("Yavaş ol.", ephemeral=True)
        return
    await ctx.reply("pong")
```

Dashboard'dan sunucu bazlı ayarlamak için:

```
PUT /api/guilds/{guild_id}/ratelimits/ping
{"max_calls": 1, "per_seconds": 3}
```

`DiscordWebAPI` her zaman bir `rate_limiter` (`GuildRateLimiter`)
nesnesi kuruyor — `enable_ratelimits_api=True` sadece dashboard'dan
düzenleme endpoint'ini açıyor, nesnenin kendisi (`api.rate_limiter` /
`request.app.state.discord_webapi_ratelimiter`) her zaman kod içinden
kullanılabilir, dashboard API'si kapalıyken bile.

## Genel eskalasyon/ceza-eşikleme motoru (`discord_webapi.escalation`)

`ban`/`kick`/`timeout`/`warn`/`automod` gibi her moderasyon aksiyonu için
ortak, tek bir "N ihlalde şunu yap" merdiveni. **Hiçbir varsayılan eşik
veya aksiyon yok** — her basamağı (kaç ihlalde, hangi aksiyon: `none`/
`timeout`/`kick`/`ban`) siz dashboard'dan ya da kod içinden açıkça
tanımlarsınız; boş bir merdiven sadece ihlalleri sayar, hiçbir şey yapmaz.

```python
# builtins.automod'un on_violation hook'u, kendi eskalasyon mantığını icat
# etmeden bizim escalation motorumuzu besliyor:
async def on_violation(message, reason):
    await app.state.discord_webapi_escalation_engine.record_violation(
        message.author, "automod", source="automod", reason=reason
    )

setup_automod(bot, on_violation=on_violation)
```

Dashboard'dan merdiveni yapılandırmak için:

```
PUT /api/guilds/{guild_id}/escalation-rules/automod/3
{"action": "timeout", "action_minutes": 10}

PUT /api/guilds/{guild_id}/escalation-rules/automod/5
{"action": "kick"}
```

`key` (`"automod"` yukarıdaki örnekte) keyfi bir string — `ratelimits`
gibi, `warn` komutunuz da, kendi yazdığınız bambaşka bir moderasyon
mantığı da aynı ya da farklı bir `key` altında kendi merdivenini
paylaşabilir/ayrı tutabilir. `DiscordWebAPI` her zaman bir
`escalation_engine` (`EscalationEngine`) nesnesi kuruyor —
`enable_escalation_api=True` sadece dashboard'dan düzenleme endpoint'ini
açıyor, nesnenin kendisi (`api.escalation_engine` /
`request.app.state.discord_webapi_escalation_engine`) her zaman kod
içinden kullanılabilir, dashboard API'si kapalıyken bile.

## Captcha / robot doğrulama (`discord_webapi.captcha`, opt-in)

Hepsi tek bir `CaptchaProvider` Protocol'ü (`issue()` + `verify()`)
uyguluyor -- kendi captcha kütüphanenizi/servisinizi de aynı arayüzle
bağlayabilirsiniz (miras yok, "kendi implementasyonunu getir" deseni).
Sağlayıcı aileleri:

- **Görsel (basit) captcha'lar** -- `MathCaptchaProvider` (matematik
  sorusu), `TextCaptchaProvider` (bozuk yazıyı okuma). Her render'da farklı
  renk/döndürme/gürültüyle gerçek bir PNG (SVG değil: SVG'de metin dosya
  içinde düz metin durur, doğrudan okunabilir). `discord-webapi[captcha]`
  (Pillow) gerektirir. **Dürüst not:** bu görselleri modern OCR/vision
  modelleri kolay çözüyor -- bunlar "basit" katman olarak duruyor.
- **Görünmez / düşük maliyet katmanı** -- `ProofOfWorkProvider`: Cloudflare
  Turnstile mantığında, kullanıcı hiçbir şey yapmaz; sayfa yüklenince/form
  gönderilince tarayıcı arka planda küçük bir hashcash araması yapar.
  Asimetri özü: istemci ~2^difficulty hash yapar, **sunucu tek hash'le**
  doğrular -- görsel render yok, IP-itibarı sorgusu yok, üçüncü-taraf
  çağrısı yok. Sunucu maliyeti her zaman minimum. `difficulty` tek maliyet
  düğmesi (ucuz tier ~12-16 bit; sıkı tier ~18-22 bit -- sunucu maliyeti
  ikisinde de aynı). Ek bağımlılık gerektirmez. **Dürüst not:** "CPU
  harcandı" der, "insan" demez -- kütlesel otomasyonun maliyetini
  yükseltir; hesap-bağlama ile katmanlayın. Tasarlanan akış: önce bunu
  sessizce çalıştır, sadece hâlâ şüpheli isteklerde görünür bir captcha'ya
  düş.
- **Davranışsal skor tablosu** (`SignalScoreCheck`, görünmez katmanın
  "gerçek tarayıcı/insan mı" yarısı): PoW "CPU harcandı" der; bu katman
  ise *nasıl* etkileşildiğine bakıp bir skor üretir. İstemci JS'i, kullanıcı
  mouse'u widget'a **yaklaştırırken** (tıklamadan önce) hareket örnekleri
  toplar, tıklama/dokunma konumunu (tam ortaya tıklamak insan için fazla
  kusursuz = bot şüphesi), `navigator.language`, saat dilimi, etkileşim
  süresi vb.'yi `signals`'a koyar; sunucu bunları **ağırlıklı şeffaf
  sezgisellerle** puanlar ve bir eşiği geçip geçmediğine bakar. Mobilde
  dokunma varsa mouse-izi sezgiseli çekimser kalır (haksız cezalandırmaz).
  Her sezgisel ve ağırlık değiştirilebilir; kendi sinyalinizle kendi
  sezgiselinizi ekleyebilirsiniz. `check.compute(signals)` skoru +
  kalem-kalem dökümü döndürür (loglama/eşik ayarı için). **Dürüst not
  (önemli):** buradaki her girdi istemci JS'inde toplanır, istemci bunu
  değiştirebilir/uydurabilir -- bu bir bot dedektörü ya da ML DEĞİL, şeffaf
  bir sezgisel skordur. Kuralları bilen kararlı bir bot "insan gibi"
  puanlanan sinyaller gönderebilir. Değeri: düşük-emekli otomasyonun
  maliyetini yükseltmek ve size ayarlanabilir bir düğme vermek -- **her
  zaman PoW (gerçek maliyet) + hesap-bağlama (gerçek kimlik) ile birlikte**,
  tek başına gate olarak değil. (Daha basit ikili kontroller için
  `captcha.signals`'da `reject_webdriver`/`require_signal_flag`/
  `require_min_interaction_ms` de var.)
- **Mouse kinematiği** (`signals["mouse_trajectory"]`, `[x, y, t_ms]`
  örnekleri -- yine widget'a **yaklaşırken** toplanmaya başlanır, tıklamada
  değil): `SignalScoreCheck`'e üç yeni sezgisel eklendi -- **eğrilik oranı**
  (kat edilen yol / düz mesafe -- insan hareketi eğri, sabit-hızlı
  linear-interpolation bot'u tam düz), **hız değişkenlik katsayısı** (insan
  hareketi yavaş-hızlı-yavaş çan eğrisi izler -- motor-kontrol
  literatüründeki "minimum-jerk" modeli, Flash & Hogan 1985; naive bot sabit
  hızda gider), **zamanlama değişkenlik katsayısı** (gerçek tarayıcı
  örneklemesi hiç düzenli değildir; sabit adımlarla ilerleyen bot'unki
  düzenlidir). Sentetik insan/bot karşılaştırmasında (20 deneme) üçü de
  temiz ayrışıyor -- insan denemeleri hep bot'un tam sıfır değerinin üstünde
  kalıyor. Sinyal eksik/dokunmatik/çok az örnek/bozuk veri -> **çekimser**
  (cezalandırmıyor, eski istemcilerle geriye dönük uyumlu).
  **Dürüst araştırma sonucu (kullanıcı talebiyle hesaplandı):** "insanı
  bot sanma ihtimalini imkansıza yakın yapmak" mümkün DEĞİL -- bunun sebebi
  eksik ayar değil, yapısal bir sınır: bir bot gerçek, önceden kaydedilmiş
  bir insan fare hareketini **replay** edebilir; replay edilen veri gerçek
  insan hareketi *olduğu için* bu kontrollerin hiçbirini yanıltmaz, tersine
  kusursuz geçer -- tek bir isteğin kinematik analizi "insan şimdi hareket
  etti" ile "bu kaydın replay'i şimdi oynatılıyor" arasını hiçbir zaman
  ayıramaz. Ayrıca tam bunu atlatmak için yazılmış halka açık "insan gibi
  fare yolu" üretici araçlar zaten var. Yani: eklemeye değer (naive/düşük
  emekli script'lerin -- ki gerçekte karşılaşılanın büyük kısmı budur --
  maliyetini ciddi yükseltiyor) ama yine PoW + hesap-bağlama ile katmanlanan
  şeffaf bir sezgisel, tek başına "insan kanıtı" değil.
  Ayrıca **`mouse-homing-correction`** var: hedefe yaklaşırken en az bir
  "aşma ve düzeltme" (overshoot) anı bulursa `1.0`, bulamazsa **`0.0`
  değil çekimser** -- overshoot'un yokluğu insan olmadığının kanıtı
  değil (yavaş/hassas hareketlerde hiç görülmeyebilir), sadece varlığı
  ek pozitif kanıt. Bu yüzden asla puan düşürmez, sadece yükseltebilir.
- **Basit görsel captcha'lar** (`MathCaptchaProvider`/`TextCaptchaProvider`)
  hâlâ duruyor ama **dürüstçe**: modern OCR/vision bunları kolay çözüyor,
  bu yüzden bunlar sadece "son çare / düşük-değerli" katman -- asıl güven
  PoW + davranış skoru + hesap-bağlamadan gelmeli. `PathTraceProvider`
  (çizgi-takip) opsiyonel bir etkileşim sürtünmesi olarak duruyor ama aynı
  dürüst uyarıyla: challenge verisi istemciye gittiğinden kararlı bir script
  okuyup eşleşen cevap üretebilir. (Yanıp-sönen-nokta modeli, gerçek bir
  değer katmadığı için kaldırıldı.)
- **Üçüncü-taraf widget'lar** -- `ReCaptchaProvider`, `HCaptchaProvider`
  (kendi site_key/secret_key'iniz). Sadece `httpx` (zaten çekirdek).
- **Tekrarlanan-hareket / replay tespiti** (`RepeatedMovementCheck`,
  `discord_webapi.captcha.replay_guard`) -- yukarıdaki kinematik
  sezgisellerin **tek gerçek çözemediği** sorunu (bir bot gerçek bir insan
  hareketini kaydedip replay ederse tek-istekli hiçbir analiz bunu
  yakalayamaz) için: bu, tek istekli değil **geçmişe bakan** bir kontrol.
  `mouse_trajectory`'den kaba, öteleme-bağımsız (translation-invariant)
  bir parmak izi çıkarır (ilk örneğe göre normalize edilmiş, kuantize
  `dx,dy,dt` deltalarının hash'i) ve bu parmak izinin **yakın zamanda
  -- kim tarafından olursa olsun --** kullanılıp kullanılmadığına bakar.
  Bilerek **global** (kullanıcı/IP/oturum bazlı değil): asıl yakalamak
  istediği tam da "aynı kayıt farklı bir hesap/cihaz/IP altında tekrar
  sunuluyor" senaryosu -- per-hesap/per-IP rate limit bunu göremez.
  Sinyal eksikse veya dokunmatikse **fail-open** (geçer) -- bu sinyali
  henüz göndermeyen bir istemciyi asla bloklamaz. `MemoryTrajectoryFingerprintStore`
  (tek process) / `SQLTrajectoryFingerprintStore` (çoklu web replica'sı
  -- aksi halde bir load balancer arkasında replay farklı bir replica'ya
  düşünce yakalanmayabilir). Varsayılan olarak hiçbir gate'e bağlı değil --
  `extra_checks=[RepeatedMovementCheck(store)]` ile isteyen ekler.

**Hazır widget (`discord_webapi.captcha.widget`, opt-in)**: alt yapının
üstüne "hızlı kullanmak isteyenler için" bir katman -- kendi frontend'ini
sıfırdan yazmak istemeyenler için tek `<div>` + tek `<script>` ile gömülen,
gerçek bir Cloudflare-Turnstile-tarzı checkbox widget:

```python
app.include_router(build_captcha_widget_router())
```
```html
<div class="dwa-captcha-widget" data-token="{token}"></div>
<script src="/static/discord-webapi-captcha-widget.js" data-callback="onVerified"></script>
<script>function onVerified(result) { /* result.verified, result.failed_check */ }</script>
```

Widget kendi UI'sını `CaptchaGate`'in verdiği challenge'a göre otomatik
uyarlıyor -- captcha yoksa sade bir checkbox; Math/Text ise görsel+metin
kutusu; PoW ise tamamen görünmez (arka planda kendi hashcash aramasını
`crypto.subtle.digest` ile yapıp bitince checkbox'ı aktif eder);
Path-trace ise gömülü bir `<canvas>`; reCAPTCHA/hCaptcha ise onların kendi
widget'ını gömer. Mouse/dokunma sinyallerini (kinematik dahil) sayfa
yüklendiği andan itibaren kendisi toplar -- ayrıca bir şey yazmanıza
gerek yok. Her adım (yaklaşma, tam tıklanan piksel, animasyon, sunucu
sonucu) `document` üzerinde bir `dwa-captcha-widget-log` CustomEvent'i
olarak da yayınlanır -- kendi görünür zaman çizelgenizi istiyorsanız
onu dinleyin (`examples/captcha_playground` tam olarak bunu yapıyor).

**Birden fazla gate amacı aynı anda** (örn. bir çekiliş gate'i + ayrı bir
"çok ban yemişse itiraz komutundan önce doğrula" gate'i): `build_captcha_router()`
varsayılan olarak tek bir `app.state.discord_webapi_captcha_gate`'i okur --
tek bir entegrasyonu olan gerçek bir deploy için doğru tasarım budur. Birden
fazla gate'iniz varsa `gate=` parametresini açıkça verip router'ı her gate
için ayrı bir prefix altında mount edin:

```python
app.include_router(build_captcha_router(gate=giveaway_gate), prefix="/giveaway")
app.include_router(build_captcha_router(gate=appeal_gate), prefix="/appeal")
```

Widget'ın `data-api-base` özniteliğini de eşleşen prefix'e ayarlayın
(`data-api-base="/giveaway"`). Somut, gerçek bir bot üzerinde çalışan örnek:
`examples/captcha_gate_bot/` -- tam olarak sorduğunuz iki senaryo: `/join`
(çekilişe katılma linki, DM, gerçek Discord hesabına bağlı doğrulama,
`on_verified` ile "katıldın!" DM'i) ve `/appeal` (belli bir ban eşiğini
geçen kullanıcı, ayrı bir gate üzerinden doğrulanmadan komutu kullanamıyor).

Bu, `DiscordWebAPI.install()`'a otomatik bağlanan diğer opt-in
özelliklerin (audit/consent/ratelimits) aksine hâlâ elle mount ediliyor
-- ama önceki katmanların hepsi gibi **tamamen isteğe bağlı**: kendi
frontend'inizi `build_captcha_router()`'ın ham endpoint'lerine karşı
yazmak isterseniz widget'ı hiç kullanmayabilirsiniz, kütüphane hiçbir
şekilde dayatmıyor -- "hem alt yapıyı verelim hem hazır kullanım isteyenlere
de bir UI verelim" ilkesinin birebir uygulanışı.

**Tıklayarak test etmek isteyenler için**: `examples/captcha_playground/` --
Discord bot'u/OAuth'u gerektirmeden, tarayıcıda tek sayfada hem bu hazır
widget'ı (bir `CaptchaGate` konfigürasyonu seçip canlı deneyebileceğiniz
şekilde) hem de her provider'ı (Math/Text/PoW/Path-trace + varsa
reCAPTCHA/hCaptcha) ham endpoint seviyesinde VE görünmez katmanın tamamını
(davranış skoru, replay-tespiti) gerçekten çalıştırıp PASS/FAIL log
paneline yazan bir örnek. "Aynı hareketi tekrar gönder" butonu, replay
tespitinin ikinci gönderimde FAIL'e döndüğünü canlı gösteriyor.

Rate limiter/escalation'ın aksine `DiscordWebAPI` hiçbir captcha
sağlayıcısını otomatik kurmaz (hangi sağlayıcı, hangi reCAPTCHA
anahtarları -- sağlıklı bir varsayılan yok) -- kendiniz oluşturup
`app.state`'e koyup router'ı bağlarsınız. İki kullanım şekli:

**1. Sitede direkt kullanım** (Discord'la ilgisi olmayan bir form vb.):

```python
provider = MathCaptchaProvider(MemoryCaptchaStore())
app.state.discord_webapi_captcha_providers = {"math": provider}
app.include_router(build_captcha_router())
```

`GET /api/captcha/challenge?kind=math` bir görsel + `challenge_id`
döndürür, `POST /api/captcha/verify` (`{"kind", "challenge_id",
"response"}`) doğrular.

**2. Bot komutu için eşik/gate** (`CaptchaGate`) -- örnek senaryo: bir
çekiliş botunun `/join` komutu kullanıcıya bir doğrulama linki yolluyor
(DM, ephemeral yanıt -- botun kendi tercihi, `CaptchaGate` karışmıyor),
kullanıcı linke gidip captcha'yı çözünce bot `Transport` event'i
üzerinden anında haberdar oluyor -- polling yok, bot ve web ayrı process
olsa bile çalışıyor:

```python
gate = CaptchaGate(transport, MemoryVerificationStore(), provider)
app.state.discord_webapi_captcha_gate = gate
app.include_router(build_captcha_router())

async def handle_verified(event):
    user = await bot.fetch_user(event.user_id)
    await user.send(f"Doğrulandı! {event.metadata['giveaway_id']} çekilişine katıldın.")

gate.on_verified(handle_verified)

@bot.hybrid_command(name="join")
async def join(ctx):
    request = await gate.create_verification(
        user_id=ctx.author.id, guild_id=ctx.guild.id,
        purpose="giveaway_entry", metadata={"giveaway_id": "spring-giveaway"},
    )
    url = f"https://yoursite.com/verify/{request.token}"
    await ctx.author.send(f"Doğrulamak için: {url}")
    await ctx.reply("Sana DM attım, linkten doğrula.", ephemeral=True)
```

**Doğrulama katmanları -- kompoz edilebilir (kek katları gibi):** bir
captcha "insan mı" der ama "hangi hesap" demez -- forwardlanmış bir link
başkası tarafından da çözülebilir. Gerçek güvenilirlik için doğrulamayı
gerçek Discord hesabına (kütüphanenin kendi OAuth girişi) bağlamak lazım.
`CaptchaGate` bunu birleştirilebilir "check" katmanlarıyla yapıyor -- her
biri bağımsız bir `VerificationCheck`, gate hepsinin geçmesini şart
koşuyor (mantıksal AND):

```python
# sadece captcha (varsayılan): insan mı -- ama hangi hesap belli değil
CaptchaGate(transport, store, provider)

# sadece hesap: görsel yok, kullanıcı sadece linkin ait olduğu Discord
# hesabıyla giriş yapmış olmalı ("linke tıkla, hesabınla doğrula, geç")
CaptchaGate(transport, store, require_captcha=False, require_account=True)

# ikisi birden ("safety mod")
CaptchaGate(transport, store, provider, require_captcha=True, require_account=True)

# sadece tıklama: tek-kullanımlık gizli linke sahip olmak tek kanıt
# (en düşük sürtünme, en zayıf)
CaptchaGate(transport, store, require_captcha=False, require_account=False)

# kendi katmanını ekle: bizim captcha'mız + senin kendi mantığın
# (tarayıcı parmak izi, davranışsal skor, "N gündür üye" ... -- kancayı
# biz veriyoruz, politikayı sen yazıyorsun)
async def kendi_kontrolun(ctx):
    return ctx.signals.get("fingerprint_score", 0) > 70

CaptchaGate(
    transport, store, provider,
    extra_checks=[PredicateCheck("fingerprint", kendi_kontrolun)],
)
```

`extra_checks`'e ister `PredicateCheck` (tek fonksiyon) ister `issue()`/
`run()`... `VerificationCheck` Protocol'ünü uygulayan kendi sınıfınızı
verirsiniz -- birinci-taraf ve üçüncü-taraf check'ler gate için ayırt
edilemez. Tüketici kekimizin katını da kullanır, kendininkini de ekler,
hiç kullanmaz, tamamen kendininkini koyar. `verify()` bir `CheckResult`
döndürüyor (`.verified`, hangi check patladı `.failed_check`, hangileri
geçti `.passed`) ve `captcha_verified` event'i `checks_passed` taşıyor --
bot ne kadar güçlü doğrulandığını bilerek tepki verebilir.

**"Kendi IP itibarı sistemimi ekleyebilir miyim?" -- evet, ve bunun için
özel olarak bir alan var.** `ctx.signals` istemci JS'inin gönderdiği bir
çanta -- IP adresi buraya konursa istemcinin "ben şu IP'denim" demesi
anlamına gelir, sahtelenebilir, güvenilmez. Bu yüzden `VerificationContext`
ayrıca **`client_ip`** taşıyor -- `build_captcha_router()`'ın kendisinin
`Request.client.host`'tan okuduğu, istemcinin asla değiştiremeyeceği
gerçek bağlantı IP'si:

```python
BLOCKLIST = {"1.2.3.4", "5.6.7.8"}  # ya da kendi itibar servisinize sorgu

async def ip_itibari_kontrolu(ctx):
    if ctx.client_ip in BLOCKLIST:
        return False
    # ya da: await my_reputation_service.check(ctx.client_ip)
    return True

CaptchaGate(
    transport, store, provider,
    extra_checks=[PredicateCheck("ip-reputation", ip_itibari_kontrolu)],
)
```

Kütüphane kendi IP itibar veritabanını/servisini SUNMUYOR (hangi
kaynağa güveneceğinize dair bir görüşü yok) -- ama artık gerçek,
sahtelenemeyen IP'yi check'lerinize ulaştırıyor, siz istediğiniz kaynakla
(kendi blocklist'iniz, bir 3.taraf reputation API'si, kendi
rate-limit/abuse geçmişiniz) birleştirebilirsiniz.

**Katman içi granülerlik -- tek tek özellik açıp kapatmak da mümkün, sadece
kat seviyesinde değil.** Yukarıdaki "bir check'i tamamen kullan/kullanma"
seçiminin bir seviye altında: her katmanın kendi içinde de neyi
kullanacağınızı seçebiliyorsunuz --

```python
# Davranışsal skorun İÇİNDE hangi sezgisellerin çalışacağını seçin --
# örn. mouse-kinematiğini istemiyorsanız listeden çıkarın, kendi
# sezgiselinizi ekleyin, ağırlıkları değiştirin:
from discord_webapi.captcha.scoring import ScoringHeuristic, default_behavior_heuristics

heuristics = [
    h for h in default_behavior_heuristics()
    if not h.name.startswith("mouse-")   # kinematik sezgiselleri tamamen çıkar
]
heuristics.append(ScoringHeuristic("kendi-sinyalim", 2.0, kendi_sezgiselim))
SignalScoreCheck(heuristics=heuristics)

# Kendi sağlayıcınızı/3. taraf servisinizi kullanın, bizimkini hiç
# kurmayın -- CaptchaProvider Protocol'ü herkese açık:
CaptchaGate(transport, store, provider=ReCaptchaProvider(site_key=..., secret_key=...))

# Ya da hiçbirini kullanmayın, tamamen kendi captcha kütüphanenizi
# CaptchaProvider Protocol'üyle sarın -- gate hangi implementasyon
# olduğunu hiç bilmiyor.
class MyCaptcha:
    kind = "my-captcha"
    async def issue(self): ...
    async def verify(self, challenge_id, response): ...
```

Yani "bu algoritmayı/özelliği istemiyorum, şunu istiyorum" ya da "zaten
3. taraf bir hizmet kullanacağım" dediğinizde hiçbir şeyi zorla dayatan
bir yer yok -- her katman (provider, check, hatta bir check'in içindeki
tek tek sezgiseller) bağımsız olarak değiştirilebilir/kaldırılabilir/
eklenebilir listeler ve Protocol'ler üzerine kurulu.

Not: tüketici bu check'leri ve eşikleri kendi yazabildiği için, ihtiyaçları
yoksa hiç captcha kullanmadan sadece hesap-doğrulamayla da geçebilirler,
ya da tamamen kendi doğrulama zincirlerini kurabilirler.

Kaba kuvvet koruması: her self-hosted challenge sınırlı sayıda yanlış
denemeden sonra geçersiz oluyor (`max_attempts`, varsayılan 5), tek
kullanımlık (doğru cevap bile ikinci kez kabul edilmiyor), ve süresi
doluyor (`ttl`, varsayılan 10-15 dakika). Consuming olan captcha check'i
her zaman en sona konuyor -- daha ucuz bir check (hesap, seninki) patlarsa
doğru çözülmüş captcha boşa gitmesin diye. Dashboard endpoint'leri de
(kimliksiz, herkese açık olduğu için IP bazlı) rate limit'li.

## Kuyruk sistemi (`discord_webapi.jobs`, opt-in)

Uzun süren işler (toplu moderasyon, export) için — request/response
döngüsünde beklenemeyecek işler:

```python
from discord_webapi.jobs import InProcessJobQueue

job_queue = InProcessJobQueue()
job_queue.register_worker("bulk_ban", handle_bulk_ban)

api = DiscordWebAPI(..., job_queue=job_queue)
api.install(app, enable_jobs=True)
```

- `POST /api/guilds/{guild_id}/jobs/{job_type}` — enqueue, 202 + `job_id`.
- `GET /api/guilds/{guild_id}/jobs/{job_id}` — durum sorgusu (pending →
  running → succeeded/failed).

Gerçek dağıtık kullanım için `RedisJobQueue` — detaylar `DAGITIM.md`'de.

## Çoklu veritabanı desteği

SQLite/Postgres/MySQL, `discord-webapi[sql-sqlite|sql-postgres|sql-mysql]`
extra'ları, `quickstart(database_url=...)`.

## `default_intents()` ve boilerplate azaltma

```python
from discord_webapi.bot import default_intents

bot = commands.Bot(command_prefix="!", intents=default_intents())
```

`Intents.default()` + `members=True` + `message_content=True` — dashboard
botlarının neredeyse her zaman ihtiyaç duyduğu iki intent'i tek satıra
indiriyor.
