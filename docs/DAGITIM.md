# Dağıtımımız (Deployment)

## 1. Tek process (varsayılanımız, çoğu bot için yeterli)

```python
app = DiscordWebAPI.quickstart(bot=bot)
```

Bot ve FastAPI aynı process'te, aynı asyncio event loop'unu paylaşır
(`InProcessTransport`'umuz). Sıfır ek altyapı — Redis bile gerekmez.
Küçük ve orta ölçekli botların büyük çoğunluğu için bu bizim önerdiğimiz
kurulum yeterli.

Bkz. bizim `examples/single_process_bot/`, `examples/full_featured_bot/`
örneklerimiz.

## 2. Çoklu sunucu/makine (büyük botlar için sunduğumuz seçenek)

Botun Discord Gateway bağlantısı **tek bir process** olmak zorunda, ama
dashboard'unuzun HTTP trafiği bundan bağımsız olarak yatay
ölçeklenebilir. Bunun için bizim sunduğumuz iki yarı:

```python
# bot_process.py — tek bir process, Discord'a bağlı
api = DiscordWebAPI.for_bot_process(bot=bot, transport=RedisTransport(redis_url))
async with api.lifespan(token):
    await asyncio.Event().wait()
```

```python
# web_process.py — istediğiniz kadar replica/makine
api = DiscordWebAPI.for_web_process(transport=RedisTransport(redis_url), auth=auth)
api.install(app)
```

Her iki yarı da **aynı `DiscordWebAPI` sınıfımız ve aynı route'larımız**
— hiçbir route/dependency'nizin ayrı yazılmasına gerek yok, çünkü hepsi
zaten sadece bizim `Transport`'umuz üzerinden konuşuyordu.

**Dikkat**: bizim `RedisTransport`'umuzun "bir komuta tek handler"
kuralımız geçerli — tam olarak **bir** `bot_process.py` çalıştırın
(bot/token başına). Bu kural web tarafınızı etkilemiyor —
`web_process.py`'nizi istediğiniz kadar çoğaltabilirsiniz, load balancer
arkasında.

**Şema oluşturma**: Sadece `bot_process.py`'niz (ya da ayrı bir migration
adımı) `create_all(engine)` çağırmalı — web replica'larınız başlamadan
önce şema hazır olmalı.

Çalıştırılabilir tam örneğimiz: `examples/split_deployment/` (README
dahil).

## 3. Kuyruk sistemimiz (opsiyonel üçüncü parça)

Dashboard'unuzdan tetiklenen, request/response döngüsünde
beklenemeyecek uzun işler için (toplu moderasyon, export) sunduğumuz
sistem:

```python
# worker_process.py — istediğiniz kadar, herhangi bir makinede
from discord_webapi import RedisJobQueue
from discord_webapi.jobs import run_worker

queue = RedisJobQueue(redis_url)
queue.register_worker("bulk_action", handle_bulk_action)

if __name__ == "__main__":
    asyncio.run(run_worker(queue))
```

```python
# web_process.py'de
api = DiscordWebAPI.for_web_process(..., job_queue=RedisJobQueue(redis_url))
api.install(app, enable_jobs=True)
```

`RedisJobQueue`'muz, `RedisTransport`'umuzun aksine **gerçek**
competing-consumer semantiği veriyor (Redis list'ler, `RPUSH`/`BLPOP`) —
kaç `worker_process.py` çalıştırırsanız çalıştırın, Redis aynı job'ı iki
worker'a birden vermemeyi garanti ediyor. Job throughput'unu artırmak,
sadece daha fazla worker process çalıştırmak demek.

Tek-process kurulumumuzda da kullanılabilir (`InProcessJobQueue`,
`DiscordWebAPI(job_queue=InProcessJobQueue())`) — `lifespan()`/
`web_lifespan()`'ımız queue'yu otomatik start/stop ediyor, ekstra
boilerplate gerekmiyor.

**Önemli**: `register_worker()`'ınızı her zaman `start()`'tan ÖNCE
çağırmalısınız — `RedisJobQueue`'muz bu sırayı zorunlu kılıyor
(`start()`'tan sonra `register_worker()` çağırmak `RuntimeError`
fırlatır), çünkü worker'ların dinlediği kuyruk listesi `start()` anında
sabitleniyor.

## 4. Veritabanı taşımamız (ör. SQLite → MariaDB/Postgres)

**MySQL/MariaDB'yi, Postgres ile birebir aynı garantilerle destekliyoruz**
— bizde ikinci sınıf bir arka uç değil:
- `_commit_upsert`'imiz (get-or-create yazma yolundaki concurrent-insert
  korumamız, `discord_webapi/storage/sql.py` ve `escalation/sql.py`) her
  ikisinde de aynı şekilde çalışır — SQLAlchemy'nin driver-agnostik
  `IntegrityError`'ını yakalayıp kaybeden isteği "sanki diğerinin
  yazdığı satırı güncelliyormuş gibi" devam ettirir, hangi veritabanı
  olduğuna bakmaz.
- MySQL/MariaDB'nin varsayılan `DATETIME` sütunu mikrosaniyeyi
  **kesiyor** (Postgres'in `timestamptz`'ı kesmez) — biz bunu
  `_TIMESTAMP` tipimizle (`storage/sql.py`) `DateTime(timezone=True).
  with_variant(mysql.DATETIME(fsp=6), "mysql")` ile MySQL'e özel olarak
  mikrosaniye hassasiyetini (`fsp=6`) açıkça isteyerek çözdük — aksi
  halde iki hızlı ardışık yazma aynı saniyeye denk gelip sıralama/TTL
  karşılaştırmalarını bozabilirdi. Bu düzeltmemiz zaten mevcut, ekstra
  bir yapılandırma gerektirmiyor.

`discord-webapi-migrate` (`discord_webapi.tools.migrate`) — bizim
sunduğumuz, geliştirme sırasında kullandığınız SQLite dosyasından
üretim veritabanınıza (MariaDB, MySQL, Postgres) tek seferlik veri
taşıma aracımız. Şema/tablo bilgisini hardcode etmiyoruz — kaynak
veritabanında ne varsa (çekirdek store'larımız, `escalation`,
`extras.warn`'ımızın `SQLWarnStore`'u, hatta üçüncü-taraf bir
extension'ın kendi tablosu) SQLAlchemy'nin kendi introspection'ıyla
buluyor ve kopyalıyoruz.

```bash
pip install "discord-webapi[sql-mysql]"   # hedefin sürücüsü
discord-webapi-migrate run \
  --from sqlite+aiosqlite:///dashboard.sqlite3 \
  --to mysql+aiomysql://kullanici:sifre@host/veritabani
```

Güvenlik tasarımımız:
- **Kaynağa asla yazmıyoruz**, sadece okuyoruz.
- `--yes` verilmedikçe **onay istiyoruz** (satır sayılarını gösterip
  soruyoruz).
- **Checkpoint'imiz varsayılan olarak açık**: yazmadan önce hedefte o an
  ne varsa (yeniden çalıştırıyorsanız boş olmayabilir) yerel bir JSON
  dosyasına kaydediyoruz. Bir şeyler ters giderse:
  ```bash
  discord-webapi-migrate restore dwa_migrate_checkpoint_....json --to <hedef-url>
  ```
  ile hedefi tam o ana geri döndürebilirsiniz. Tekrarlanan/zararsız
  çalıştırmalar için `--no-checkpoint` ile kapatılabilir.
- **Checkpoint'imiz, genel bir veritabanı yedeği DEĞİL** — sadece
  discord-webapi'nin kendi tablolarını kapsıyor. Kritik bir taşımadan
  önce yine de veritabanınızın kendi yedekleme aracıyla
  (`mysqldump`/`pg_dump`/dosya kopyası) tam bir yedek alın.

Kendi veritabanı sisteminizi (MongoDB, kendi API'niz, ne isterseniz)
kullanmak isterseniz bizim bu aracımıza hiç ihtiyacınız yok — sunduğumuz
her `Store` bir `Protocol`'ümüz (`discord_webapi/storage/base.py`),
miras almadan aynı metodları uygulayan bir sınıf yazıp constructor'a
(`session_store=`, `rate_limit_store=`, ...) geçmeniz yeterli;
kütüphanemizin geri kalanı hiç fark etmez.

## 5. Yedek alma aracımız

`discord-webapi-backup` (`discord_webapi.tools.backup`) — bir
migrasyona bağlı olmadan, elinizde bağımsız tutabileceğiniz bir yedek
dosyası oluşturan aracımız. Aynı şema-agnostik yaklaşımımız: `migrate`
gibi kaynak veritabanında ne tablo varsa SQLAlchemy introspection'ıyla
buluyoruz, hiçbir ORM sınıfını hardcode etmiyoruz.

Sunduğumuz üç kapsam, birleştirilebilir:
- **Tam yedek** (varsayılanımız, filtre verilmezse).
- **Guild bazlı** (`--guild-id N`): sadece `guild_id` sütunu olan
  tablolardan o guild'e ait satırlar (`dwa_sessions` gibi guild
  sütunu olmayan tablolar tam alınır).
- **Tarih bazlı** (`--since`/`--until`, ISO 8601): her tablonun sahip
  olduğu `created_at`/`updated_at`/`given_at`/`expires_at`
  sütunlarından hangisi varsa ona göre filtrelenir; hiçbiri yoksa tam
  alınır.

```bash
discord-webapi-backup create \
  --from sqlite+aiosqlite:///dashboard.sqlite3 \
  --out yedekler/tam_yedek.json

# sadece bir guild, sadece son 7 gün
discord-webapi-backup create \
  --from sqlite+aiosqlite:///dashboard.sqlite3 \
  --out yedekler/guild123_son_hafta.json \
  --guild-id 123 --since 2026-07-09T00:00:00

discord-webapi-backup list yedekler/tam_yedek.json

discord-webapi-backup restore yedekler/tam_yedek.json \
  --to mysql+aiomysql://kullanici:sifre@host/veritabani
```

Güvenlik tasarımımız `migrate` ile aynı: kaynağa asla yazmıyoruz,
`--yes` verilmedikçe onay istiyoruz, DB URL'lerindeki şifreler
terminale basılmadan önce gizleniyor. Tek fark: bir yedek dosyamız
sadece satır verisi tutuyor, şema/sütun tipi bilgisi tutmuyor -- bu
yüzden `restore`'umuz, hedefte olmayan bir tabloyu **oluşturamaz**,
sadece atlayıp devam eder (hedefin botun en az bir kez çalışıp
`create_all()`/`quickstart()` ile tabloları oluşturmuş olması gerekir).

## 6. Health check aracımız (deployment sonrası / cron)

`discord-webapi-healthcheck` (`discord_webapi.tools.healthcheck`) —
veritabanınızın, (varsa) Redis'inizin ve (varsa) kendi HTTP
endpoint'inizin (dashboard'unuzun kendi health route'u, ya da bot
sürecinizin) gerçekten erişilebilir olduğunu kontrol eden bağımsız
CLI'ımız. Cron/monitoring/container-orchestrator kullanımınız için: tüm
istenen kontroller geçerse `0`, herhangi biri başarısız olursa `1` ile
çıkar.

```bash
discord-webapi-healthcheck \
  --database-url sqlite+aiosqlite:///dashboard.sqlite3 \
  --redis-url redis://localhost:6379/0 \
  --http-url https://dashboard.example.com/health \
  --json
```

- Her kontrolümüz bağımsız ve opsiyonel — sadece elinizdeki URL'leri
  verin, hiç bayrak verilmezse hiçbir şey kontrol edilmez (yapılacak
  bir şey yok).
- `--timeout` (varsayılanımız 5sn) her kontrole ayrı ayrı uygulanır.
- `--json` insan-okunur metin yerine satır başına bir JSON nesnesi basar
  (log toplama/monitoring pipeline'larınız için).
- Redis kontrolümüz `discord-webapi[redis]` extra'mızı gerektirir; onsuz
  sadece `--redis-url` verilmezse çalışır (import lazy, sadece o kontrol
  çağrıldığında yapılıyor).

## Özet tablomuz

| Senaryo | Transport | Süreçler |
|---|---|---|
| Küçük/orta bot | `InProcessTransport` | 1 (bot+web birlikte) |
| Büyük bot, ölçeklenen dashboard | `RedisTransport` | 1 bot + N web replica |
| + uzun süren işler | + `RedisJobQueue` | + N worker process |

Üçü de bizim aynı kod tabanımız, aynı route'larımız — hangisini
seçtiğiniz sadece `Transport`/`JobQueue` implementasyonu ve kaç process
çalıştırdığınızla ilgili, route/dependency kodumuz hiç değişmiyor.
