# Geliştirici Notları (oturumlar arası kalıcı hafıza)

Bu dosya proje reposunun içinde tutuluyor (git ile push ediliyor) çünkü
oturum hafızası kalıcı değil ve bazen proje dizini dışına (plan dosyaları,
scratchpad vb.) yazılan notlar bir sonraki oturumda erişilemez hale
gelebiliyor. **Her yeni oturuma başlarken önce bu dosyayı ve
`CHANGELOG.md`'yi oku.** Bir şey unutulduysa/karışıksa buraya geri dön.

Ayrıca bkz: `/root/.claude/plans/encapsulated-nibbling-pnueli.md` (orijinal
v0.1 mimari planı, proje dışında — orada olmayabilir, bu yüzden kritik
kararlar buraya da yansıtılıyor).

## Şu ana kadarki durum (v0.3 tamamlandı, doğrulandı)

- Transport (InProcess + Redis, contract test'li, `unsubscribe()` dahil)
- Auth: opak session, cookie + mobil Bearer token, `HTTPConnection` tabanlı (websocket'te de çalışıyor)
- Commands: registry, canlı enable/disable, per-command cooldown, `invocation_count` dahili sayaç
- AppRole: bot-özel roller, `AuthzStore` (Memory/SQL)
- Guild-rol yetkilendirme: `require_guild_permission`, `GuildMemberCache`
- Çoklu DB: SQLite/Postgres/MySQL
- WebSocket canlı relay (opt-in)
- `quickstart()`, `default_intents()`, bundled dashboard HTML
- **Audit log** (`discord_webapi/audit/`): `AuditStore` (Memory/SQL), `AuditLogger`, `GET /api/guilds/{id}/audit-log`. Opt-in (`enable_audit_log=False` varsayılan). Şu an sadece komut override'ları (`command.set_override`) ve AppRole yazmaları (`app_role.set`/`app_role.delete`) kaydediliyor — auth login/logout kapsam dışı (kullanıcı bunu seçti).
- **Cookie/consent kaydı** (`discord_webapi/consent/`): `ConsentStore` (Memory/SQL, ayrı protokol — `Session`'a alan eklenmedi), `GET/POST /api/consent`. Opt-in (`enable_cookie_consent=False` varsayılan). Notice'ın metni/UI'ı tamamen tüketiciye bırakıldı — kütüphane sadece "kullanıcı X, Y versiyonunu Z zamanında onayladı" kaydını tutuyor.
- **`discord_webapi/builtins/`**: hazır, tam-özellikli, serbestçe import edilebilir komutlar için klasör. `_shared.py`'de ortak, bağımsız kullanılabilir parçalar (`check_role_hierarchy`, `notify_member_best_effort`) — kullanıcı isterse sadece bunları alıp sıfırdan yazdığı komuta gömebilir, isterse hazır komutu (`ban.py`/`kick.py`/`timeout.py`) olduğu gibi kullanır, isterse hibrit yapar (kullanıcının bu oturumda tam olarak istediği şey: "ayrı ayrı kullanmak isteyenler yerde kullanır ya da sıfırdan yazarlar ya da hibrit kullanırlar"). Şu an: `ban.py`, `kick.py`, `timeout.py` (Discord'un kendi native timeout'unu kullanıyor, ayrı mute-role sistemi yok) + `README.md`. Kalıcı veri gerektiren gelecekteki builtin'ler (ör. `warn.py`) `AuditStore`/`ConsentStore` ile aynı desende kendi `Store` protokolünü alacak — DB/cache/permission katmanları hep ayrı, birleştirilebilir parçalar olarak kalacak, tek bir dosyaya gizli bağımlılık gömülmeyecek.
- `TESTING.md`: fiziksel test kontrol listesi (kullanıcı henüz Termux'ta çalıştırmadı).

Tüm otomatik testler yeşil (128 passed, 20 skipped — skip'ler yerelde
MySQL servisi çalışmadığından; Postgres testleri geçiyor), `ruff check` ve
`mypy discord_webapi` temiz.

## Önemli kapsam kararı: builtin/eklenti sistemi bilinçli olarak küçültüldü

Kullanıcı aslında çok daha büyük bir şey tarif etti: üçüncü taraf
paket/eklenti formatı — `.json` manifest (isim, versiyon, yazar,
bağımlılıklar), bir "build/install" adımı, neredeyse bir mini app-store /
plugin-VM sistemi (kullanıcının benzetmesi: kütüphane "ana yemek değil,
yanında gelen kaliteli ikram" — Discord bot geliştirmenin FastAPI'si).

Bu, tek oturumda makul şekilde inşa edilemeyecek kadar büyük ve ayrı bir
tasarım gerektiren bir iş (paket formatı, resolver/installer, üçüncü taraf
kod çalıştırmanın güvenlik incelemesi, versiyonlama politikası) — zaten
orijinal v0.1 planında "core donunca, vakit geçirmek için eklenir" diye
ertelenmiş "extension/structure sistemi" fikriyle aynı kategoride.

**Bu oturumda teslim edilen/küçültülen versiyon**: `discord_webapi/builtins/`
klasörü, `_shared.py`'de ayrıştırılmış bağımsız parçalar +
`ban.py`/`kick.py`/`timeout.py`. Kullanıcıya kapsam daraltması söylendi ve
kullanıcı onayladı ("ertelemen iyi ama altyapısı iyi olsun, zaten süs bu,
ana yemek değil — meze; her şeyi ayrı ayrı kullanmak isteyenler kullanır,
sıfırdan yazarlar ya da hibrit yaparlar, kendileri bilir"). Manifest/
versiyon/installer sistemi hâlâ YOK ve hâlâ bilinçli olarak ertelendi —
`builtins/README.md`'nin son bölümünde neden ertelendiği açıklamasıyla
birlikte duruyor.

## builtins durumu (güncel)

- `_shared.py`: `check_role_hierarchy`, `notify_member_best_effort` (bağımsız kullanılabilir).
- `ban.py`, `kick.py`, `timeout.py`: stateless moderasyon komutları, `_shared.py`'i kullanıyor.
- `warn.py`: **ilk kalıcı-durumlu builtin**. `WarnStore` protokolü + `MemoryWarnStore` (varsayılan) + `SQLWarnStore` (kendi `create_all()`'ı, core `storage.sql.create_all()`'dan tamamen bağımsız — `dwa_builtin_warns` tablosu sadece `SQLWarnStore` gerçekten kullanılırsa oluşur). Opsiyonel `auto_timeout_after=N` ile otomatik timeout eskalasyonu (varsayılan kapalı).
- `welcome.py`: **ilk komut-olmayan builtin** — `on_member_join` event listener, `setup(bot, channel_id=..., dm_instead=...)`. Kanal asla tahmin edilmiyor, açıkça verilmesi gerekiyor.

Hepsi 154 test ile kapsanıyor (unit: ban/kick/timeout/warn/warn_sql/welcome/shared), ruff+mypy temiz. Commit: bkz. git log.

## Cookie-consent banner dashboard entegrasyonu (tamamlandı)

Kullanıcı builtin eklemeyi durdurup ("hazır komut eklemeyelim şuan zamanı
değil") ana plana dönmemizi istedi; plan dosyası (`/root/.claude/plans/
encapsulated-nibbling-pnueli.md`) v0.3'ün tamamını (audit/consent/builtins
kararları + bilinçli ertelenen paket sistemi) yansıtacak şekilde
güncellendi, sonra kullanıcı üç açık v0.3+ maddesinden ("cookie-consent
banner", "multi-bot/shard routing", "channel-level permission overwrite")
ilkiyle başlamayı seçti — **hepsini istiyor, sırayla ekleyeceğiz**.

- `discord_webapi/web/dashboard.html`: `<!--COOKIE_CONSENT_BANNER-->` ve
  `/*COOKIE_CONSENT_SCRIPT*/` yer tutucuları eklendi.
- `discord_webapi/web/dashboard.py`: `build_default_dashboard_router(
  enable_cookie_consent=, cookie_consent_message=, cookie_consent_version=)`
  — banner metni tamamen tüketiciye ait (varsayılan bir İngilizce cümle var
  ama serbestçe override edilebiliyor), `cookie_consent_version` değişince
  herkes tekrar onaylamak zorunda kalıyor (localStorage + `/api/consent`
  karşılaştırması `COOKIE_CONSENT_VERSION` üzerinden).
- Banner JS'i: giriş yapılmamışsa `/api/consent` 401 döner, bu durumda
  localStorage'a "reddedilmiş/kapatılmış" bayrağı yazıp göstermeye devam
  ediyor; "Accept" tıklanınca hem localStorage hem (giriş yapılmışsa)
  `POST /api/consent` ile kalıcı kayıt.
- `DiscordWebAPI.install()`/`quickstart()`'a `cookie_consent_message`/
  `cookie_consent_version` parametreleri eklendi, `enable_cookie_consent=True`
  olduğunda hem consent API'sini hem dashboard banner'ını aynı config'le
  bağlıyor.
- Testler: `test_default_dashboard.py`'de banner var/yok + özelleştirme
  testleri, `test_consent_api.py`'de banner+API'nin aynı versiyonu
  paylaştığını doğrulayan uçtan uca test. 158 test yeşil, ruff+mypy temiz.

## Termux fiziksel test sürecinde çıkan iki gerçek sorun (çözüldü)

1. **Kullanıcı projeyi Android paylaşılan depolamada (`/storage/emulated/0/...`)
   çalıştırıyordu** — bu Android FUSE katmanı symlink desteklemiyor, `python -m
   venv` bu yüzden `Permission denied: 'lib' -> '.venv/lib64'` hatası verdi, ve
   git clone bazı dosyaları (ör. `.env.example`) düzgün yazamadı. **Kod
   tarafında bir bug değildi** — çözüm: projeyi Termux'un kendi ev dizininde
   (`~`, yani `/data/data/com.termux/files/home/...`) çalıştırmak.
2. **`quickstart()`'ta `mobile_redirect_uri` parametresi yoktu** — kullanıcı
   `PATCH` gerektiren bir endpoint'i tarayıcı adres çubuğuna yazıp "Not
   Allowed" (405) aldı; asıl sorun mobilde PATCH+auth header göndermenin
   pratik bir yolu olmamasıydı (cookie mobil tarayıcıda kolay okunamıyor).
   **Fix**: `DiscordWebAPI.quickstart(mobile_redirect_uri=...)` eklendi,
   `examples/full_featured_bot/main.py`'de varsayılan olarak açıldı
   (`{base_url}/mobile-login-done` — gerçek bir sayfa yok, sadece
   `session_id`'yi URL'den okumak için). `TESTING.md` madde 2 ve 3 artık bu
   akışı ve somut `curl -X PATCH -H "Authorization: Bearer ..."` komutlarını
   içeriyor.

## `session_id` boş geliyor sorunu (çözüldü — kod bugı değildi)

Kullanıcı `/mobile-login-done`'da hep boş `session_id` gördü. uvicorn
access log'unu inceleyince asıl sebep ortaya çıktı: kullanıcı gerçek bir
OAuth yönlendirmesiyle değil, **URL'i elle yazarak/yapıştırarak** o
sayfaya gidiyordu; log'da bir de gerçek mobil giriş denemesinde
`GET /auth/discord/login?%20mobile=true` görüldü — `%20` bir boşluk,
yani `?mobile=true` değil `? mobile=true` yazılmış/yapıştırılmış, bu da
FastAPI'nin `mobile` parametresini tanımamasına (sessizce `mobile=False`
varsaymasına) yol açtı. Otomatik testler (`test_mobile_auth.py`)
kütüphanenin kendisinin bu konuda sorunsuz olduğunu zaten kanıtlıyordu —
sorun tamamen elle URL yazmaktan kaynaklanan bir kullanıcı hatasıydı.

**Kalıcı çözüm** (URL yazma ihtiyacını tamamen ortadan kaldırıyor):
- Bundled `dashboard.html`'e tıklanabilir bir **"Mobil giriş (session_id
  al)"** butonu eklendi (`/auth/discord/login?mobile=true`'ya gidiyor) —
  artık kimse bu URL'i elle yazmak zorunda değil.
- `examples/full_featured_bot/main.py`'ye gerçek bir `/mobile-login-done`
  sayfası eklendi (önceden 404'tü) — `session_id`'yi büyük, kolayca
  seçilebilir/kopyalanabilir bir kutuda gösteriyor; `session_id` boşsa
  "gerçek bir mobil login yönlendirmesiyle gelmedin, butona tekrar tıkla"
  diye açıkça uyarıyor (sessiz 404 yerine).
- `TESTING.md` madde 2 artık "URL'i elle yazma, butona tıkla" diyor.
- Yeni test: `test_dashboard_has_a_clickable_mobile_login_link`. 159 test
  yeşil, ruff+mypy temiz.

## v0.4 tamamlandı: Channel-level permission overwrite

Kullanıcı Termux/mobil test sürecinde çok kafası karıştığı için ("kafam
çok karışıyor") büyük, kapsamlı bir v0.4 güncellemesi istedi: yeni
özellikler + sağlamlaştırma, sonra kontrolleri yap, sonra **bölüm bölüm**
kurulum + test adımlarını ver (her bölümden sonra kullanıcı rapor verecek,
ben kontrol edip düzeltip bir sonraki bölümü vereceğim — bu bir sonraki
oturumda da devam edecek bir iş akışı, unutma).

- **`require_channel_permission`**: `require_guild_permission`'dan farkı,
  guild-level izne sahip olsan bile o kanala özel bir override (Discord'un
  "Kanal İzinleri" / channel overwrite sistemi) o izni geri alabiliyorsa
  reddediyor. `ChannelPermissionCache` (`authz/cache.py`, TTL'li — 30sn
  varsayılan, `AppRoleCache` ile aynı basit desende, push-invalidation
  yok çünkü channel overwrite'lar guild membership'ten çok daha az
  değişiyor). Bot tarafında `install_channel_permission_lookup`
  (`bot/extension.py`) — Discord'un kendi `channel.permissions_for(member)`'ını
  kullanıyor (guild rolleri + kanal overwrite'ları otomatik birleşiyor),
  ekstra REST çağrısı yok, aynı warm-Gateway-cache-only ilkesi.
  `commands/bridge.py`'de `get_channel_permissions()`.
- `DiscordWebAPI(channel_permission_cache_ttl_seconds=30.0)` yeni parametre.
- `full_featured_bot`'ta demo endpoint: `GET /api/guilds/{guild_id}/channels/{channel_id}/can-send`.
- Testler: `tests/unit/test_authz.py`'ye 3 yeni `ChannelPermissionCache`
  testi, yeni `tests/integration/test_channel_permissions.py` (4 test).
  166 test yeşil, ruff+mypy temiz.
- **Multi-bot/shard routing bilinçli olarak ertelendi** — üçüncü-taraf
  paket sistemiyle aynı gerekçe: birden fazla bot instance/shard'ın aynı
  dashboard'u paylaşması, `Transport`'un hangi guild'in hangi shard'a ait
  olduğunu nasıl bileceği gibi sorular kendi başına ayrı bir tasarım turu
  gerektiriyor. Kullanıcıya bu daraltma söylenmeli (henüz söylenmedi
  olabilir — sohbetin geri kalanını kontrol et).

## KRİTİK BUG BULUNDU VE DÜZELTİLDİ: slash komutlar hiç senkronize edilmiyordu

Bölüm 3'te kullanıcı `/ping` yazınca Discord'da slash komut hiç
görünmedi, `!ping` de cevap vermedi. Kod incelemesinde iki gerçek,
ciddi bug bulundu (kullanıcı hatası değil):

1. **`bot.tree.sync()` hiçbir yerde çağrılmıyordu.** discord.py, slash
   komutları `sync()` çağrılmadıkça Discord'a hiç göndermiyor — hatasız,
   sessizce. Bu, kütüphanenin en başından beri (v0.1'den) var olan bir
   eksiklik, hiçbir zaman fark edilmemiş çünkü hiçbir otomatik test gerçek
   bir Discord bağlantısı üzerinden `/komut` çalıştırmıyor.
   **Fix**: `DiscordWebAPI._on_ready()` artık `bot.tree.sync()`'i
   otomatik çağırıyor (`sync_commands: bool = True` yeni parametre,
   `DiscordWebAPI(...)` ve `quickstart(...)`'a eklendi). `on_ready` birden
   fazla kez tetiklenebileceği için (Gateway reconnect) sadece bir kez
   sync ediliyor (`self._commands_synced` guard). `sync_guild_id: int |
   None = None` yeni parametresiyle global sync yerine (ki ~1 saate kadar
   yayılma gecikmesi olabiliyor) tek bir test sunucusuna anında sync
   yapılabiliyor (`copy_global_to` + `sync(guild=...)`).
2. **`default_intents()` `message_content` intent'ini açmıyordu.** Bu
   olmadan discord.py mesaj metnini okuyamıyor, prefix komutlar
   (`!ping`) hiç eşleşmiyor. **Fix**: `default_intents()` artık
   `intents.message_content = True` da yapıyor; docstring Discord
   Developer Portal'da "Message Content Intent"i de açmak gerektiğini
   hatırlatıyor.

Testler: `tests/integration/test_facade.py`'ye 4 yeni test (sync
davranışı: varsayılan global, guild-scoped, kapalıyken hiç, birden fazla
`on_ready`'de sadece bir kez), `test_quickstart.py`'ye
`message_content` testi. `test_facade.py`'nin mevcut testi de
`sync_commands=False` ile güncellendi (o test gerçek bir Gateway
bağlantısı simüle etmiyor, `application_id` olmadan `sync()` zaten
patlardı — bu discord.py'nin kendi davranışı, kütüphane bugı değil).
171 test yeşil, ruff+mypy temiz.

`examples/full_featured_bot/main.py` ve `.env.example`'a `TEST_GUILD_ID`
env var'ı eklendi — doldurulursa `sync_guild_id`'ye geçiliyor.

**Bu, kullanıcının fiziksel testinin gerçek değerini kanıtlıyor** —
otomatik test paketi hiçbir zaman bunu yakalayamazdı, sadece gerçek bir
Discord sunucusunda gerçek bir bot çalıştırmak bunu ortaya çıkardı.

## İKİNCİ KRİTİK BUG: cooldown/invocation_count slash-hybrid'de çift işleniyordu

Bölüm 4'te kullanıcı `ping`'e "30 saniyede 1 kullanım" cooldown koyunca
komut **kalıcı olarak** cevap vermez oldu (2 dakika bekledi, hâlâ hiç
cevap yok). Kök neden analizi (discord.py kaynak kodu okunarak, tahmin
değil): `HybridCommand._check_can_run` (discord.py'nin kendi
`hybrid.py`'si) yorum satırında açıkça şunu söylüyor: "Bot global check
once / Bot global check" — yani bir hybrid komut **slash** olarak
çağrıldığında, `CommandTree._call` önce bizim wrap ettiğimiz
`interaction_check`'i çalıştırıyor, SONRA `HybridCommand.can_run` →
`_check_can_run` → `bot.can_run(ctx)` ile bizim `global_check`'imizi
**tekrar** çalıştırıyor — aynı tek çağrı için iki kez.

Sonuç: her gerçek `/ping` çağrısı cooldown bucket'ından 2 token
tüketiyordu (1 yerine), `invocation_count` 2'şer 2'şer artıyordu
(kullanıcının PATCH cevabında gördüğü `invocation_count: 6` tam olarak
3 gerçek çağrı × 2 ile eşleşiyor). "1 kullanımda 30sn" ayarlandığında
tek bir gerçek çağrı bucket'ı hemen negatife düşürüyor ve her yeni
deneme de (cooldown'dayken bile) `update_rate_limit()`'i tekrar
çağırarak `_last`'ı güncelliyor — pencere gerçekten sıfırlanana kadar
sürekli "hâlâ cooldown'dasın" durumuna dönüyordu, kullanıcı defalarca
deneyince bu neredeyse hiç bitmeyen bir döngüye benziyordu.

**Fix** (`discord_webapi/commands/registry.py`, `global_check`):
`ctx.interaction is not None` ise (yani bu zaten `interaction_check`
tarafından ele alınmış bir slash çağrısıysa) hiçbir şey yapmadan `True`
dön. Prefix-only çağrılar (`ctx.interaction is None`) hâlâ normal
şekilde kontrol ediliyor — onlar hiçbir zaman `interaction_check`'e
uğramıyor.

Yeni regresyon testi: `test_global_check_is_a_noop_for_slash_invoked_hybrid_commands`
(`tests/unit/test_command_cooldown.py`) — `global_check`'i art arda iki
kez çağırıp (discord.py'nin gerçekten yaptığı gibi) cooldown'un
tetiklenmediğini ve sayacın artmadığını doğruluyor. 172 test yeşil,
ruff+mypy temiz.

**Bu, kullanıcının ısrarla fiziksel test yapmasının değerini bir kez
daha kanıtlıyor** — hem sync bug'ı hem bu ikisi de hiçbir otomatik testte
yakalanamazdı, ikisi de gerçek Discord etkileşimi gerektiriyordu.

## Bölüm bölüm fiziksel test — durum (duraklatıldı, Bölüm 6'dan devam edilecek)

Kullanıcı `TESTING.md`'yi bölüm bölüm test etti (ben bölümü veriyorum,
o fiziksel olarak deniyor, rapor veriyor, ben kontrol edip düzeltiyorum,
sonra sıradaki bölümü veriyorum). **Şu ana kadar tamamlanan**:
- Bölüm 1 (kurulum): birkaç Termux'a özel sorun çıktı ve çözüldü (bkz.
  yukarıdaki "Termux fiziksel test sürecinde çıkan..." notu) — özetle:
  paylaşılan depolamada çalışmak (symlink desteklemiyor), venv
  aktivasyonunu unutmak, `--system-site-packages` sonrası `uvicorn`
  komutunun sistem kopyasını bulması (çözüm: `python -m uvicorn`).
- Bölüm 2 (auth: tarayıcı + mobil): sorunsuz geçti.
- Bölüm 3 (komut listeleme + enable/disable): **kritik bug bulundu**
  (slash komutlar hiç sync edilmiyordu + `message_content` intent eksikti)
  — ikisi de düzeltildi, sonra bölüm baştan tekrar denendi, sorunsuz geçti.
- Bölüm 4 (cooldown): **ikinci kritik bug bulundu** (hybrid komutlar slash
  olarak çağrılınca cooldown/invocation_count çift işleniyordu) —
  düzeltildi, tekrar denendi, sorunsuz geçti.
- Bölüm 5 (AppRole): sorunsuz geçti.
- **Bölüm 6'dan (guild-rol tabanlı yetkilendirme) itibaren henüz test
  edilmedi** — kullanıcı test sürecini duraklatıp mimari/felsefe
  konusunda bir endişesini konuştu (aşağıya bakın), sonra roadmap'ten
  devam etmeyi seçti. **Bir sonraki oturumda ya Bölüm 6'dan teste devam
  et, ya da kullanıcı başka bir şey isterse ona göre yönlen.**

## Kullanıcının mimari/felsefe endişesi (çözüldü, kod değişikliği gerekmedi)

Kullanıcı test sırasında "biz FastAPI gibi özgür değil de şablon/template
sistemi mi olduk" endişesi dile getirdi. Kök neden: bundled dashboard'da
komut enable/disable, cooldown ayarlama gibi işlemler için **hiç UI
yok** — bu yüzden test ederken curl/terminal kullanmak zorunda kalması
"böyle yapmalısınız" gibi hissettirmiş. Açıklandı ve kullanıcı kabul
etti: kütüphanenin kendisi (Protocol'ler, composable API, builtins'in
opt-in oluşu) gerçekten istenen özgür/FastAPI-gibi felsefede; sorun
sadece test aracının (bundled dashboard) bu spesifik işlemler için UI
sunmaması. **Kod değişikliği yapılmadı** — kullanıcı "şuan gerek yok"
dedi, ama gelecekte bundled dashboard'a enable/disable + cooldown UI'ı
eklemek roadmap'e not edildi (yukarıdaki v0.4+ aday listesine bakın).

## disnake/py-cord desteği: araştırıldı, kullanıcı kararıyla süresiz ertelendi

py-cord ayrı bir venv'de kurulup gerçek test paketimiz (172 test) onun
üstünde çalıştırıldı — **21 dosya import hatasıyla patladı**: py-cord'un
slash-komut mimarisi (`SlashCommand`/`ApplicationCommandMixin`,
`discord.app_commands`/`CommandTree` yok) discord.py'den kökten farklı.
"Aynı `discord` isim alanını kullanıyor, drop-in'dir" varsayımı somut
veriyle çürütüldü. Destek eklemek `commands/bridge.py` +
`commands/registry.py`'yi (kütüphanenin en kırılgan katmanı, az önce
tam da burada iki gerçek bug bulduk) iki ayrı mimariye göre yazmak
demek. **Kullanıcı kararı**: "discord.py'ye odaklanalım, py-cord/disnake
talebi çok daha küçük bir topluluk, ileride gerçek talep olursa
`discord-webapi-pycord` gibi ayrı bir paket çıkarılabilir, şimdi hiç
düşünmeyelim." Plan dosyasına da işlendi — bu madde artık v0.4+ aday
listesinde değil, kapalı bir karar olarak duruyor.

## Sıradaki adaylar (kullanıcı "roadmap'ten devam edelim" dedi, henüz seçim yapılmadı)

1. Bölüm 6+ fiziksel teste devam (yukarıya bakın).
2. Daha fazla builtin (`on_message` otomatik moderasyon, rol-atama komutu).
3. Multi-bot/shard routing tasarımına başlamak (büyük, ayrı bir tasarım
   turu gerektiriyor — üçüncü-taraf paket sistemiyle aynı kategori).
4. Bundled dashboard'a enable/disable + cooldown UI'ı eklemek.
Bir sonraki oturumda kullanıcıya hangisini istediğini sor (daha önce
`AskUserQuestion` ile sorulmuştu, disnake/py-cord seçilmiş ve şimdi
kapandı — geri kalan üç madde hâlâ açık).

## Genel süreç hatırlatmaları (tekrar unutulmasın diye)

- **Asla force-push yapma.** Push reddedilirse önce `git fetch` +
  `git log`/`git status` ile gerçek durumu anla, gerekirse yedek branch aç,
  sonra reconcile et.
- Her yeni özellik: pytest + ruff + mypy üçü de yeşil olmadan commit'leme.
- Sadece kullanıcı açıkça istediğinde commit/push yap.
- Bu sandbox'ta Postgres/MySQL servisleri fresh container'da kapalı
  başlıyor olabilir — `service postgresql start` / `service mariadb start`
  gerekebilir, testlerin skip/fail olması otomatik olarak kod regresyonu
  anlamına gelmez, önce servisleri kontrol et.
