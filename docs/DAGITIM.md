# Dağıtım (Deployment)

## 1. Tek process (varsayılan, çoğu bot için yeterli)

```python
app = DiscordWebAPI.quickstart(bot=bot)
```

Bot ve FastAPI aynı process'te, aynı asyncio event loop'unu paylaşır
(`InProcessTransport`). Sıfır ek altyapı — Redis bile gerekmez. Küçük ve
orta ölçekli botların büyük çoğunluğu için bu yeterli.

Bkz. `examples/single_process_bot/`, `examples/full_featured_bot/`.

## 2. Çoklu sunucu/makine (büyük botlar için)

Botun Discord Gateway bağlantısı **tek bir process** olmak zorunda, ama
dashboard'un HTTP trafiği bundan bağımsız olarak yatay ölçeklenebilir.
Bunun için:

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

Her iki yarı da **aynı `DiscordWebAPI` sınıfı ve aynı route'lar** — hiçbir
route/dependency'nin ayrı yazılmasına gerek yok, çünkü hepsi zaten sadece
`Transport` üzerinden konuşuyordu.

**Dikkat**: `RedisTransport`'un "bir komuta tek handler" kuralı geçerli —
tam olarak **bir** `bot_process.py` çalıştırın (bot/token başına). Bu
kural web tarafını etkilemiyor — `web_process.py`'yi istediğiniz kadar
çoğaltabilirsiniz, load balancer arkasında.

**Şema oluşturma**: Sadece `bot_process.py` (ya da ayrı bir migration
adımı) `create_all(engine)` çağırmalı — web replica'ları başlamadan önce
şema hazır olmalı.

Çalıştırılabilir tam örnek: `examples/split_deployment/` (README dahil).

## 3. Kuyruk sistemi (opsiyonel üçüncü parça)

Dashboard'dan tetiklenen, request/response döngüsünde beklenemeyecek
uzun işler için (toplu moderasyon, export):

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

`RedisJobQueue`, `RedisTransport`'un aksine **gerçek** competing-consumer
semantiği veriyor (Redis list'ler, `RPUSH`/`BLPOP`) — kaç
`worker_process.py` çalıştırırsanız çalıştırın, Redis aynı job'ı iki
worker'a birden vermemeyi garanti ediyor. Job throughput'unu artırmak,
sadece daha fazla worker process çalıştırmak demek.

Tek-process kurulumda da kullanılabilir (`InProcessJobQueue`,
`DiscordWebAPI(job_queue=InProcessJobQueue())`) — `lifespan()`/
`web_lifespan()` queue'yu otomatik start/stop ediyor, ekstra boilerplate
gerekmiyor.

**Önemli**: `register_worker()` her zaman `start()`'tan ÖNCE çağrılmalı
— `RedisJobQueue` bu sırayı zorunlu kılıyor (`start()`'tan sonra
`register_worker()` çağırmak `RuntimeError` fırlatır), çünkü worker'ların
dinlediği kuyruk listesi `start()` anında sabitleniyor.

## 4. Veritabanı taşıma (ör. SQLite → MariaDB/Postgres)

`discord-webapi-migrate` (`discord_webapi.tools.migrate`) — geliştirme
sırasında kullandığın SQLite dosyasından üretim veritabanına (MariaDB,
MySQL, Postgres) tek seferlik veri taşıması için. Şema/tablo bilgisini
hardcode etmez — kaynak veritabanında ne varsa (çekirdek store'lar,
`escalation`, `extras.warn`'ın `SQLWarnStore`'u, hatta üçüncü-taraf bir
extension'ın kendi tablosu) SQLAlchemy'nin kendi introspection'ıyla
bulur ve kopyalar.

```bash
pip install "discord-webapi[sql-mysql]"   # hedefin sürücüsü
discord-webapi-migrate run \
  --from sqlite+aiosqlite:///dashboard.sqlite3 \
  --to mysql+aiomysql://kullanici:sifre@host/veritabani
```

Güvenlik tasarımı:
- **Kaynağa asla yazmaz**, sadece okur.
- `--yes` verilmedikçe **onay ister** (satır sayılarını gösterip sorar).
- **Checkpoint varsayılan olarak açık**: yazmadan önce hedefte o an ne
  varsa (yeniden çalıştırıyorsan boş olmayabilir) yerel bir JSON dosyasına
  kaydeder. Bir şeyler ters giderse:
  ```bash
  discord-webapi-migrate restore dwa_migrate_checkpoint_....json --to <hedef-url>
  ```
  ile hedefi tam o ana geri döndürürsün. Tekrarlanan/zararsız çalıştırmalar
  için `--no-checkpoint` ile kapatılabilir.
- **Checkpoint, genel bir veritabanı yedeği DEĞİL** — sadece
  discord-webapi'nin kendi tablolarını kapsar. Kritik bir taşımadan önce
  yine de veritabanının kendi yedekleme aracıyla (`mysqldump`/`pg_dump`/
  dosya kopyası) tam bir yedek al.

Kendi veritabanı sistemini (MongoDB, kendi API'n, ne istersen) kullanmak
istersen bu araca hiç ihtiyacın yok — her `Store` bir `Protocol`
(`discord_webapi/storage/base.py`), miras almadan aynı metodları
uygulayan bir sınıf yazıp constructor'a (`session_store=`, `rate_limit_store=`,
...) geçmen yeterli; kütüphanenin geri kalanı hiç fark etmez.

## Özet tablo

| Senaryo | Transport | Süreçler |
|---|---|---|
| Küçük/orta bot | `InProcessTransport` | 1 (bot+web birlikte) |
| Büyük bot, ölçeklenen dashboard | `RedisTransport` | 1 bot + N web replica |
| + uzun süren işler | + `RedisJobQueue` | + N worker process |

Üçü de aynı kod tabanı, aynı route'lar — hangisini seçtiğiniz sadece
`Transport`/`JobQueue` implementasyonu ve kaç process çalıştırdığınızla
ilgili, route/dependency kodu hiç değişmiyor.
