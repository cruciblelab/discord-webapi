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

## Bir sonraki oturumda muhtemel işler (kullanıcı üçünü de istiyor, sırada)

1. **Multi-bot/shard routing** — birden fazla bot instance/shard'ın aynı
   dashboard'u paylaşması (orijinal v0.1 planının v0.3+ listesinden).
2. **Channel-level permission overwrite** — Discord'un kanal bazlı izin
   override sistemini authz katmanına yansıtmak.
3. Kullanıcının fiziksel test sonuçlarını bekle (`TESTING.md`).
4. Builtin eklemeye ara verildi ("şuan zamanı değil") — tekrar gündeme
   gelirse `on_message` otomatik moderasyon, rol-atama komutu gibi fikirler
   NOTES.md'nin önceki sürümünde vardı.
5. Kullanıcı gerçekten üçüncü-taraf paket/manifest sistemini şimdi mi
   istiyor yoksa uzun vadeli bir vizyon muydu — netleştirilmesi gerekebilir.

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
