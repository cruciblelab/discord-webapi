# Üçüncü-taraf paket (extension) yazma rehberi

Bu, "discord-webapi uyumlu" bir paketin nasıl yazılıp paylaşılacağını
anlatır: kendi tam-kapasite bot altyapını (eğlence botu, moderasyon paketi,
seviye sistemi, ne istersen) yazıp, başkalarının `pip install` ile kurup
projesine takabileceği bir paket olarak yayınlamak.

## Felsefe: bu bir "plugin sistemi" değil

Ağır bir plugin runtime'ı, sandbox'ı ya da çekirdeğe özel erişim veren bir
API'si **yok** — ve bilerek yok. Anahtar içgörü şu:

> discord-webapi'nin kendi `extras`'ı (ban, warn, automod, skeletons...)
> zaten yalnızca **public API** kullanıyor. Yani senin yazdığın üçüncü-taraf
> bir paket, mimari olarak bizim birinci-taraf paketimizden **ayırt
> edilemez** — aynı yüzeyi kullanır, aynı yetkilere sahiptir, aynı
> sınırlara tabidir.

Bu yüzden özel bir çalıştırma ortamına gerek yok. Bir extension, dokümante
edilmiş bir konvansiyonu izleyen **sıradan bir Python paketidir**. Kurulum
`pip`'in kendi güven modelidir (bir extension kurmak, herhangi bir bağımlılık
kurmakla aynı güven kararıdır). discord-webapi senin açıkça kurmadığın ve
sonra açıkça çağırmadığın hiçbir kodu çalıştırmaz.

## En hızlı başlangıç: scaffold

```bash
pip install discord-webapi
discord-webapi-scaffold new funbot
# ya da: python -m discord_webapi.extensions.scaffold new funbot
cd funbot
pip install -e ".[dev]"
python -m pytest        # üretilen örnek test geçer
```

Bu sana çalışan, kurulabilir, keşfedilebilir bir iskelet paket verir:
`/roll` komutu (SDK'daki `rate_limited` ile), manifest, entry point,
geçen bir test.

## Bir extension'ın anatomisi

### 1. `setup` fonksiyonun (asıl davranış)

Sadece `discord_webapi.extensions.sdk`'ya karşı yaz — bizim `extras`'ımızın
kullandığı **tam olarak aynı** kararlı yüzey:

```python
# funbot/commands.py
from discord.ext import commands
from discord_webapi.extensions.sdk import GuildRateLimiter, rate_limited

def setup(bot: commands.Bot, *, rate_limiter: GuildRateLimiter | None = None):
    @bot.hybrid_command(name="roll", description="Zar at")
    @rate_limited("roll", rate_limiter=rate_limiter)
    async def roll(ctx):
        await ctx.reply("...")
    return roll
```

**Konvansiyon — host altyapıyı enjekte eder**: Rate limit, escalation gibi
altyapı *nesnelerine* ihtiyacın varsa bunları kendin construct etme; host
uygulamanın zaten bir `DiscordWebAPI`'si var ve sana `setup(bot, *,
rate_limiter=api.rate_limiter, escalation_engine=api.escalation_engine)`
ile geçer. SDK bu nesnelerin *tiplerini* re-export eder (annotation ve nadir
"kendi instance'ını isteyen" durum için), ama olağan yol enjeksiyondur.

### 2. Manifest + `Extension` (kimlik kartın)

```python
# funbot/__init__.py
from discord_webapi.extensions.sdk import Extension, ExtensionManifest
from funbot.commands import setup

extension = Extension(
    manifest=ExtensionManifest(
        name="funbot",
        version="1.0.0",
        author="Jack",
        description="Kapsamlı bir eğlence botu altyapısı",
        discord_webapi_requires=">=0.6,<1.0",   # hangi discord-webapi'lerle çalışır
        provides=["command:roll", "command:8ball"],   # sadece bilgi amaçlı
    ),
    setup=setup,
)
```

Manifest hiçbir ayrıcalık vermez — tamamen bilgilendiricidir. Tek istisna
`discord_webapi_requires`: keşif anında kurulu discord-webapi sürümüne karşı
kontrol edilir, böylece uyumsuz bir extension `setup()`'ın derinliklerinde
kafa karıştırıcı bir hatayla değil, net bir "uyumsuz" işaretiyle görünür.

### 3. Entry point (ön kapın)

`pyproject.toml`'de bir `discord_webapi.extensions` entry point'i tanımla —
paketi keşfedilebilir yapan tek şey budur:

```toml
[project.entry-points."discord_webapi.extensions"]
funbot = "funbot:extension"

dependencies = ["discord-webapi>=0.6"]
```

## Kullanıcı tarafı: bir extension'ı keşfetmek ve kullanmak

```python
from discord_webapi.extensions import ExtensionRegistry

reg = ExtensionRegistry.discover()      # kurulu extension'ları okur (setup ÇALIŞTIRMAZ)

for d in reg.list():
    print(d.extension.manifest.name, d.extension.manifest.version, d.compatible)

ext = reg.get("funbot")
if ext.compatible:
    ext.extension.setup(bot, rate_limiter=api.rate_limiter)   # SEN açıkça çağırırsın

for err in reg.errors:                  # kırık/uyumsuz extension'lar sessizce atlanır
    print("yüklenemedi:", err.entry_point_name, err.message)
```

Ya da hiç keşif kullanmadan, sıradan bir paket gibi doğrudan import et:

```python
from funbot.commands import setup as setup_roll
setup_roll(bot, rate_limiter=api.rate_limiter)
```

`ExtensionRegistry` **asla** bir extension'ın `setup`'ını kendisi çağırmaz —
sadece keşfeder, uyumluluğunu kontrol eder ve sana geri verir. Bir
extension'ı gerçekten kurmak (kodunu çağırmak) her zaman senin açık kararın.

## Konvansiyon kuralları (uyumlu sayılmak için)

Bunlar bizim `extras`'ta zaten uyguladığımız kurallar — üçüncü-taraf için de
aynısı:

1. **Tek giriş noktası**: bir `setup(bot, **kwargs)` fonksiyonu (ya da bir
   decorator, skeleton-tarzı).
2. **Import yan etkisiz**: paketini import etmek hiçbir şey kaydetmez/
   çalıştırmaz; her şey `setup` çağrılınca olur.
3. **Gizli bağımlılık yok**: kendi kalıcı durumun varsa kendi `Store`
   Protocol'ünü + Memory/SQL çiftini yaz (bizim `WarnStore`/`RateLimitStore`
   deseni), kendi `create_all()`'ınla — çekirdek şemaya dokunma.
4. **Sadece public API**: `discord_webapi.extensions.sdk`'ya karşı yaz.
   `discord_webapi._private` ya da re-export edilmemiş içsel bir şeye
   dayanma — onlar sürümler arası değişebilir.
5. **Uyumluluğunu bildir**: `discord_webapi_requires` ile hangi sürümlerle
   çalıştığını söyle.

## Stabilite sözü

`discord_webapi.extensions.sdk`'da re-export edilen her isim public,
stabilite-garantili API'dir — bunlar ve arkalarındaki davranış, bir
extension'ın güvenebileceği şeylerdir. Orada re-export edilmeyen hiçbir şey
(bir modülün private içselleri, dokümante edilmemiş bir attribute) sürümler
arası değişebilir ve bir extension bunlara dayanmamalıdır. (v1.0 API-stabilite
hedefi için `docs/ROADMAP.md`'ye bakın.)
