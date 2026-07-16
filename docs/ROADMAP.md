# discord-webapi — Yol Haritası (v0.7+)

> Bu dosya, `NOTES.md` (oturumlar arası kalıcı geliştirici notu) ve
> `CHANGELOG.md` (sürüm geçmişi) ile birlikte projenin canlı planlama
> belgesidir. Mimari "neden"ler için `/root/.claude/plans/` altındaki
> orijinal plan dosyasına bakılır; **güncel öncelik sırası burasıdır.**

## 0. Konumlandırma (değişmez çekirdek ilke)

**discord-webapi, Discord bot geliştirmenin FastAPI'sidir.** Amaç:
discord.py'nin Gateway/REST'i soyutlaması gibi, "bot + web dashboard"
ikilisinin arasındaki tekrar eden işi (OAuth2, guild-rol yetkilendirme,
komut↔dashboard köprüsü, canlı config, transport) soyutlamak. FastAPI'ye
ya da discord.py'ye rakip değil; ikisinin üstüne oturan dar, opinionated
bir katman.

**Kilitli kararlar (tekrar tartışılmayacak):**
- **Backend odaklı. UI YOK.** Gömülü dashboard bilerek minimal bir demo
  olarak kalır; gerçek panel tüketiciye ait. UI eklemek "ekstra yük" ve
  amaçtan sapma. (v1.0'a kadar ertelendi, muhtemelen hiç yapılmayacak.)
- **Dokümantasyon şimdilik Türkçe.** İngilizce çeviri, proje gerçekten
  dışarı açılacağı gün yapılır — şu an adoption yok, erken yatırım.
- **`extras` = "yan yemek", çekirdek değil.** Yeni özellik önceliği
  altyapıya (auth/authz/transport/ratelimits/escalation) gider; yeni bir
  hazır komut ancak altyapıda gerçek boşluk yoksa eklenir.
- **Üçüncü-taraf = paylaşılabilir paket konvansiyonu, plugin VM DEĞİL.**
  (Bkz. §4 — bu kararın gerekçesi kullanıcı tarafından net verildi.)

## 1. Mevcut durum değerlendirmesi (bu oturumdaki kapsamlı inceleme)

### Güçlü yönler (korunacak)
- **Tutarlı mimari desen**: her alt sistem (commands, ratelimits,
  escalation, jobs) aynı şablonu kullanıyor — Store Protocol + Memory/SQL
  + Transport event ile restart'sız canlı invalidation. Bir kez öğrenilen
  desen her yerde geçerli.
- **`rate_limiter` ve `escalation_engine` her zaman construct ediliyor**
  (dashboard API'si opt-in olsa bile), böylece bot-süreci kodundan direkt
  kullanılabiliyor. Doğru karar.
- **`skeletons` yaklaşımı** (tam komut yerine ince decorator) vizyonla
  birebir uyumlu; `extras/` altında birleştirme temizledi.
- **Tip güvenliği**: strict mypy temiz, 85 kaynak dosya.
- **Test disiplini**: 395 test (1'i ortam-bağımlı Postgres hariç yeşil).
- **Güvenlik**: her genişleme turundan sonra denetim yapılmış, gerçek
  bug'lar bulunup düzeltilmiş (refresh-lock sızıntısı, Redis reconnect,
  SQL upsert race, kaybolan pending job'lar, ve bu oturumda 4 `extras`
  bug'ı + `required_app_role` ölü alanı + ratelimit isim çakışması).

### Zaten çözülmüş (Grok'un değindiği ama artık geçerli olmayan)
- **Magic string'ler**: RPC komutları zaten sabit (`COMMAND_GET_MEMBER`,
  `COMMAND_LIST_COMMAND_STATUS` ...), `EscalationAction` zaten `StrEnum`.
  Ek Enum/Literal çalışması gereksiz.
- **`_commit_upsert` race'i**: Postgres+MySQL için çözülmüş ve test var
  (sadece dokümantasyonda vurgulanacak — bkz. P1).
- **Redis namespace**: multi-tenant izolasyon için eklendi (dokümantasyon
  netleştirilecek — bkz. P1).

### Açık boşluklar (bu yol haritasının konusu)
Aşağıda önceliklendirildi.

---

## 2. Öncelik sıralı yol haritası

### P0 — Kritik bug/eksik
_Şu an boş._ Bilinen tüm gerçek bug'lar bu oturumda kapatıldı.

### P1 — DX + eksikler

**P1.1 — `extras` ergonomik export'ları.** ✅ **TAMAMLANDI.**
`extras/__init__.py`'ye lazy `__getattr__` + `__all__` + `__dir__` eklendi:
`from discord_webapi.extras import ban, warn` (zaten çalışıyordu) VE
`discord_webapi.extras.ban` (yeni, attribute erişimi) + tab-completion,
submodülleri eager import etmeden ("import registers nothing" korundu —
her submodül ancak ilk dokunuşta import ediliyor).

**P1.2 — Daha net hata rehberliği.** ✅ **TAMAMLANDI.**
`enable_jobs=True`/`job_queue=None` mesajı zaten net'ti (dokunulmadı).
Asıl sessiz-hata boşluğu kapatıldı: `required_app_role` ayarlı ama
`app_role_cache` yoksa artık fail-closed'a ek olarak bir `WARNING` log'u
atıyor ("neden komutum hep reddediliyor?" sessiz bug'ı yerine).

**P1.3 — İki eksik örnek.** ✅ **TAMAMLANDI.**
- `examples/skeleton_custom_command/`: `skeletons.rate_limited` ile kendi
  `rate_limit_key`'ini kullanarak sıfırdan komut yazma.
- `examples/hybrid_moderation/`: `automod` (`on_violation`) → `warn` +
  `EscalationEngine` üçlüsü — her biri kendi şeridinde, punishment ladder'ı
  %100 dashboard'dan yapılandırılabilir. İkisi de fake env ile uçtan uca
  build doğrulandı (app + komutlar + listener'lar kuruluyor).

**P1.4 — Audit log kapsamını genişlet (opt-in).** ✅ **TAMAMLANDI.**
Bot-tarafı moderasyon aksiyonları artık opsiyonel olarak audit'leniyor:
- `EscalationEngine`: bir rung tetiklenince `escalation.<action>` kaydı
  (`actor_user_id=0` = otomatik aksiyon). Facade `enable_audit_log=True`
  ile motoru kendi `audit_logger`'ına otomatik bağlıyor — dashboard yazma
  audit'i ile aynı store'a, böylece `GET /audit-log` ikisini de gösteriyor.
- `extras.warn.setup(bot, ..., audit_logger=)`: her uyarıda `warn` kaydı
  (actor = moderatör).
- `extras.automod.setup(bot, ..., audit_logger=)`: her ihlalde
  `automod.violation` kaydı (`actor_user_id=0`).
Hepsi tam opt-in (`audit_logger` verilmezse no-op, gizli bağımlılık yok).
8 yeni test. warn/automod audit'i composable API ya da kendi
`AuditLogger`'ınla bağlanır (quickstart'ta engine gizli); escalation
audit'i quickstart'ta bile `enable_audit_log` ile çalışıyor.

**P1.5 — Dokümantasyon netleştirmeleri (kod değişikliği yok).**
- `docs/GUVENLIK.md`: Redis namespace "namespacing ≠ authentication;
  gerçek mutually-untrusted-tenant izolasyonu için ayrı Redis DB/ACL şart"
  uyarısını belirginleştir.
- `docs/DAGITIM.md`: MySQL/MariaDB'nin `_commit_upsert` garantisinin
  Postgres ile aynı olduğunu ve `DATETIME(fsp=6)` mikrosaniye çözümünü
  vurgula.

### P1.5 — Observability (opt-in, üretim için)
Transport RPC'leri, job execution, escalation tetiklenmeleri, komut
invocation'ları için **opsiyonel** metrik/tracing kancaları. Ağır bir
bağımlılık dayatmadan: basit bir `MetricsSink` Protocol'ü (no-op default),
isteyene `PrometheusMetricsSink` / OpenTelemetry adaptörü. "Kaç job
çalıştı, kaç escalation tetiklendi, RPC latency" üretimde çok istenen
şeyler. `discord-webapi[metrics]` extra'sı olarak. **Diğer her şey gibi:
default kapalı, çekirdeğe bağımlılık eklemez.**

### P2 — Teknik borç
**P2.1 — `DiscordWebAPI.__init__` (179 satır) ve `quickstart` refactor.**
Store kurulumunu (`_build_stores`), engine kurulumunu (`_create_engine`)
yardımcı metodlara böl. Davranış değişmez, sadece okunabilirlik.

**P2.2 — `SimpleNamespace` fake'lemesini prod kodundan ayıkla.**
Çoğu zaten test'te (kabul edilebilir); prod kodunda kalan varsa gerçek
tiplerle değiştir.

**P2.3 — Sürüm numarasını gerçek olgunlukla senkronla.**
`pyproject.toml` hâlâ `0.1.0` ama CHANGELOG "v0.6" vizyonunda. Bir `v1.0`
API-stabilite hedefi belirle: hangi public API'lerin kırılmayacağını
dokümante et (framework olarak adoption bunu gerektirir). **Not: bu, PyPI
publish kararıyla birlikte kullanıcı tarafından ayrı repoda ele alınacak
— şimdilik sadece "hangi API stabil" listesini hazırla.**

---

## 3. v0.7 — Üçüncü-taraf uyumlu paket ekosistemi (plugin DEĞİL)

**Kullanıcının net vizyonu:** İnsanlar bizim `extras`'ta yaptığımız gibi
tam kapasite bot altyapıları yazabilsin — bir "eğlence botu altyapısı",
"genel bot altyapısı", profesyonel botlara kadar — ve bunları paylaşıp,
başkaları komut satırıyla projesine yükleyip import edebilsin.

**Kritik kısıt (kullanıcı kararı):** Bu bir **plugin VM / runtime izolasyon
sistemi DEĞİL.** Üçüncü-taraf kod çekirdeğe (core internals'a) erişemez,
özel bir runtime'a ihtiyaç duymaz, "ağır makineler/sistemler" gerektirmez.
Bunun yerine:

**Mimari içgörü — neden bu "bedava" geliyor:** Bizim kendi `extras`
paketimiz zaten yalnızca **public API** kullanıyor (`setup(bot, **kwargs)`,
`GuildRateLimiter`, `EscalationEngine`, Store Protocol'leri, `skeletons`
decorator'ları). Yani üçüncü-taraf bir paket, mimari olarak birinci-taraf
bir paketten **ayırt edilemez** — ikisi de aynı sözleşmeyi izler, ikisi de
sadece dışa açık yüzeyi kullanır. Bu yüzden "plugin sistemi" diye ayrı bir
runtime'a gerek yok: üçüncü-taraf paket sadece, dokümante edilmiş
konvansiyonu izleyen **sıradan bir Python paketi**.

**v0.7 kapsamı (aşamalı):**
1. **Konvansiyonu resmîleştir** (`docs/PAKET_YAZMA.md`) — ✅ **TAMAMLANDI.**
2. **`discord_webapi.extensions` paketi** — ✅ **TAMAMLANDI.**
   `ExtensionManifest` (metadata), `Extension` (manifest + `setup`),
   `ExtensionRegistry.discover()` (entry-point keşfi + sürüm uyumluluk
   kontrolü, `setup`'ı asla otomatik çağırmadan), `sdk.py` (kararlı
   re-export yüzeyi — bir extension'ın karşı yazacağı public API).
3. **Scaffold CLI** — ✅ **TAMAMLANDI.**
   `discord-webapi-scaffold new <isim>` (ya da `python -m
   discord_webapi.extensions.scaffold new <isim>`): çalışan, kurulabilir,
   keşfedilebilir bir iskelet paket üretir (örnek `/roll` komutu, manifest,
   entry point, geçen test).
4. **Hafif manifest** — ✅ **TAMAMLANDI.** `pyproject` entry-point
   konvansiyonu (`[project.entry-points."discord_webapi.extensions"]`).
   Discovery için, kod çalıştırma/izolasyon için DEĞİL. Kurulum sıradan
   `pip install <paket>`.
5. **(Uzun vade, opsiyonel, HENÜZ YOK) Topluluk index'i**: paketleri
   listeleyen bir dizin (bizim host etmediğimiz, kod çalıştırmayan — sadece
   "şu paketler var" diyen bir metadata listesi). Güvenlik yüzeyi minimal
   çünkü biz kod barındırmıyoruz; kurulum `pip`'in kendi güven modeliyle.

**v0.7 çekirdeği (1-4) bu oturumda tamamlandı ve push edildi.** Kalan
opsiyonel adım sadece topluluk index'i (talep olunca).

**Bilinçli olarak KAPSAM DIŞI:**
- Manifest'ten kod çalıştıran bir installer/resolver VM.
- Çekirdek internals'a erişim veren bir plugin API'si.
- Sandbox'lı üçüncü-taraf kod yürütme.
Bunların hepsi "ağır sistem" — kullanıcı bunları istemiyor ve güvenlik
maliyeti değeri aşıyor.

---

## 4. Uzun vade / bilinçli olarak ertelenen

| Madde | Durum | Gerekçe |
|---|---|---|
| **Gömülü dashboard UI** (enable/disable + cooldown paneli) | Ertelendi (belki hiç) | Backend odak; UI ekstra bakım yükü, amaçtan sapma. |
| **İngilizce dokümantasyon** | Ertelendi | Adoption yok; proje dışa açılınca yapılır. |
| **Tam plugin/manifest VM** | Reddedildi | Güvenlik + karmaşıklık yüksek; §3'teki hafif konvansiyon yeterli. |
| **Multi-bot routing** (tek dashboard'dan N farklı bot) | Ertelendi | Ayrı tasarım turu (guild_id→bot routing) gerektirir; gerçek talep yok. |
| **Discord sharding** (`AutoShardedClient`) | Ertelendi | Henüz talep yok. |
| **RedisTransport → Streams** (competing-consumer) | Ertelendi | Mevcut pub/sub yeterli; gerçek çoklu-instance ihtiyacı doğunca. |
| **JWT/stateless bearer** (mobil/3rd-party) | Opsiyonel ek | Mevcut opak-session tek yol; talep olursa `auth/jwt.py`. |

---

## 5. Önerilen yürütme sırası (bir sonraki turlar)

1. **P1.1 + P1.2** (extras export'ları + hata rehberliği) — ucuz, yüksek DX getirisi, düşük risk.
2. **P1.3** (iki örnek) — vizyonu somutlaştırır, öğreticidir.
3. **P1.4** (audit genişletme) — "profesyonel bot" yönü.
4. **P1.5 + P1.5-obs** (docs + opsiyonel metrics) — üretim olgunluğu.
5. **P2** (refactor + versiyon disiplini) — teknik borç.
6. **v0.7** (üçüncü-taraf konvansiyon + scaffold CLI) — ekosistem tohumu.

Her madde her zamanki gibi: tam test + ruff + mypy temiz, ayrı commit,
CHANGELOG/NOTES güncel.
