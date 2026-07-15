# Geliştirici Notları (oturumlar arası kalıcı hafıza)

Bu dosya proje reposunun içinde tutuluyor (git ile push ediliyor) çünkü
oturum hafızası kalıcı değil ve bazen proje dizini dışına (plan dosyaları,
scratchpad vb.) yazılan notlar bir sonraki oturumda erişilemez hale
gelebiliyor. **Her yeni oturuma başlarken önce bu dosyayı ve
`CHANGELOG.md`'yi oku.** Bir şey unutulduysa/karışıksa buraya geri dön.

Ayrıca bkz: `/root/.claude/plans/encapsulated-nibbling-pnueli.md` (orijinal
v0.1 mimari planı, proje dışında — orada olmayabilir, bu yüzden kritik
kararlar buraya da yansıtılıyor).

## Şu ana kadarki durum (v0.2 tamamlandı, doğrulandı, push edildi)

Son commit: `233993f` (branch: `claude/fastapi-overview-mw9irq`).

- Transport (InProcess + Redis, contract test'li, `unsubscribe()` dahil)
- Auth: opak session, cookie + mobil Bearer token, `HTTPConnection` tabanlı (websocket'te de çalışıyor)
- Commands: registry, canlı enable/disable, per-command cooldown (discord.py'nin kendi Cooldown/CooldownMapping'i, özel `_per_user_bucket_key` ile Interaction desteği), `invocation_count` dahili sayaç
- AppRole: bot-özel roller, Discord'un kendi rol sisteminden bağımsız, `AuthzStore` (Memory/SQL)
- Guild-rol yetkilendirme: `require_guild_permission`, `GuildMemberCache` (TTL'li, Transport RPC üzerinden bot cache'inden)
- Çoklu DB: SQLAlchemy async, SQLite/Postgres/MySQL (`sql-sqlite`/`sql-postgres`/`sql-mysql` extra'ları), MySQL DATETIME mikrosaniye fix'i
- WebSocket canlı relay: **opt-in** (`enable_websocket=False` varsayılan), auth+guild-permission gate'li, `command_config_changed` event'ini push ediyor
- `quickstart()`, `default_intents()`, bundled dashboard HTML — boilerplate ~%80 azaltıldı
- `TESTING.md`: kullanıcının Termux'ta fiziksel olarak test etmesi için adım adım kontrol listesi (henüz kullanıcı tarafından çalıştırılmadı — "şuan müsait değilim" dedi, bir sonraki oturumda sonuçlarını bekle)

Tüm otomatik testler yeşil (132 passed, 3 skipped — skip'ler sadece yerelde
MySQL servisi çalışmadığı için), `ruff check` ve `mypy discord_webapi` temiz.

## Sıradaki iş: v0.3 planı (bu oturumda kullanıcıdan alınan talimatlar, henüz KOD YAZILMADI)

Kullanıcı fiziksel testi şimdilik yapamayacağını söyledi ("şuan müsait
değilim"). Bu yüzden bu oturumda **sadece not/plan** bırakılıyor, bir
sonraki oturumda kullanıcı ya test sonuçlarıyla ya da "v0.3'e başla" diyerek
dönecek. Kullanıcının verdiği talimatları (Türkçe, olduğu gibi yorumlanmış
haliyle) aşağıda madde madde:

### 1. Cookie/gizlilik bildirimi (yasal uyumluluk için, opsiyonel)

- Sadece **yasal bir zorunluluk olduğu için** sağlanacak bir özellik — kütüphane
  kullanıcıya "böyle yapmalısın" demiyor, sadece altyapıyı veriyor.
- **Aç/kapa configlenebilir** olmalı (`cookie_consent_enabled: bool = False` gibi
  bir bayrak; varsayılan muhtemelen kapalı, çünkü her bot/dashboard'un buna
  ihtiyacı yok — GDPR/KVKK kapsamında olan projeler açar).
- Bir "dahili cookie bildirimi" (banner/mesaj) — kullanıcı bunu
  **düzenleyebilmeli** (metin, stil, hangi cookie'ler için gösterileceği vs.)
  — sabit/hardcoded bir metin dayatılmayacak.
- Veritabanı tarafında yeni alan(lar) gerekebilir (ör. `consent_given_at`,
  `consent_version` gibi — kullanıcının onayını kaydetmek için, session veya
  ayrı bir `ConsentStore` altında). Tasarım netleşmedi — **bir sonraki
  oturumda önce küçük bir tasarım kararı gerekiyor**: consent bilgisini
  `Session` modeline mi eklemeli yoksa ayrı bir protokol/store mu olmalı?
  (Muhtemelen ayrı `ConsentStore` protokolü — Session'ın SQL şemasını her
  ihtiyacı olmayan proje için şişirmemek adına, tıpkı `AuthzStore`'un ayrı
  tutulması gibi.)

### 2. Audit log

- Komut enable/disable, cooldown değişikliği, AppRole atama/kaldırma gibi
  state-changing dashboard aksiyonlarının **kim/ne zaman/ne yaptı** şeklinde
  kaydı. v0.1 planındaki "v0.3+: Audit log" maddesiyle örtüşüyor — zaten
  roadmap'te vardı, şimdi önceliklendi.
  - Muhtemel şekil: `AuditStore` protokolü (Memory/SQL), her state-changing
    endpoint'te (zaten `updated_by_user_id` alanı `CommandOverride`'da var —
    bunun genel bir audit event'ine dönüştürülmesi mantıklı) bir
    `AuditLogEntry` (actor_user_id, guild_id, action, target, timestamp,
    detail/diff) yazılması.
  - Yine **configlenebilir aç/kapa** olmalı — herkes audit log istemez,
    zorunlu tutulmamalı.

### 3. Komut/Event sistemi — genişletilebilir eklenti mimarisi (en büyük madde)

Kullanıcının tarifi (yorumlanmış): Şu an sadece "komutlar" (discord.py
komutlarının dashboard'a yansıtılması) var; bunun ötesine geçip **event
listening**'i de (Discord Gateway event'leri — `on_message`, `on_member_join`
vb. — dashboard'dan görülebilir/yönetilebilir hale getirmek) aynı sisteme
dahil etmek istiyor. Kilit noktalar:

- **Ayrı bir alt klasörde** tutulacak (örn. `discord_webapi/builtins/` veya
  `discord_webapi/extensions/` — isim netleşmedi), içinde **her biri ayrı
  bir dosya** olacak şekilde hazır/dahili komutlar ve event handler'lar
  (kullanıcı "hazır verdiğimiz komutlar" dedi — yani kütüphane bazı
  varsayılan/örnek komutları/event listener'ları kendi içinde sunacak).
- Bu dahili komut/event dosyaları **kullanıcı tarafından da import
  edilebilir** olmalı — yani sadece "dahili, gizli" bir mekanizma değil,
  public API'nin bir parçası; isteyen kendi botunda bunlardan birini
  `from discord_webapi.builtins.moderation import kick_command` gibi
  import edip kullanabilmeli veya kendi versiyonuyla değiştirebilmeli.
- **Sınırlama olmadan configlenebilir**: kullanıcı "biz komutları/event'leri
  nasıl istiyorlarsa öyle kullansınlar, kısıtlama getirmeyelim" dedi — yani
  builtin'ler birer **öneri/varsayılan**, zorunlu bir şablon değil (v0.1
  planındaki FastAPI-gibi-özgür felsefesiyle birebir aynı ilke, RedisTransport
  Streams kararında da aynı ilke uygulanmıştı).
  - Pratikte muhtemelen: her builtin dosyası bağımsız, kendi başına
    import edilebilir bir `discord.ext.commands.Cog` veya düz fonksiyon +
    `CommandRegistry.command_meta` dekoratörü kombinasyonu olacak;
    kullanıcı hangi builtin'leri bot'una ekleyeceğini kendisi seçer
    (hepsini otomatik yüklemek YOK, opt-in import).
- **Permission kontrolleri** ile ilgili de bir madde geçti ("permision
  kontroller" — muhtemelen yeni alanların/butonların yetkilendirme
  kontrolüne tabi olması, ya da builtin komutların kendi
  varsayılan permission gereksinimlerini tanımlayabilmesi). Netleşmedi —
  bir sonraki oturumda kullanıcıya şunu sormak gerekebilir: "Permission
  kontrolleri derken mevcut `require_guild_permission`/`require_app_role`'un
  bu yeni builtin komut/event sistemine nasıl entegre olacağını mı
  kastediyorsun, yoksa dashboard'da yeni bir 'bu komut şu permission'ı
  gerektirir' configi mi?"

### Netleşmemiş / bir sonraki oturumda sorulması gereken sorular

1. Cookie consent verisi nerede tutulacak: `Session`'a alan mı eklensin,
   yoksa ayrı `ConsentStore` mu?
2. Audit log hangi aksiyonları kapsayacak — sadece commands/app-roles mı,
   yoksa auth login/logout gibi olaylar da mı?
3. Builtin komut/event klasörünün adı ve tam iskeleti ne olacak
   (`discord_webapi/builtins/` vs `discord_webapi/extensions/`)?
4. "Permission kontroller" ifadesiyle tam olarak ne kastedildi — yukarıya
   bak.
5. Bu üç madde (consent, audit, builtin sistem) aynı release'de mi (v0.3)
   yoksa ayrı ayrı mı teslim edilecek? Kullanıcı sıralama belirtmedi bu
   sefer — v0.2'de olduğu gibi net bir öncelik sırası istenirse tekrar
   sorulmalı.

## Genel süreç hatırlatmaları (tekrar unutulmasın diye)

- **Asla force-push yapma.** Push reddedilirse önce `git fetch` +
  `git log`/`git status` ile gerçek durumu anla, gerekirse yedek branch aç,
  sonra reconcile et.
- Her yeni özellik: pytest + ruff + mypy üçü de yeşil olmadan commit'leme.
- Sadece kullanıcı açıkça istediğinde commit/push yap.
- v0.3 fikirleri (extension/structure sistemi, "abc auth" gibi override
  edilebilir yapılar) v0.1 planında zaten "core donunca, vakit geçirmek için"
  notuyla ertelenmişti — bu oturumdaki builtin komut/event klasörü fikri
  onunla akraba ama daha somut ve öncelikli, karıştırma.
