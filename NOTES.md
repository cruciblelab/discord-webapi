# Geliştirici Notları (oturumlar arası kalıcı hafıza)

## Path-Trace: hız/zamanlama kinematiği + şüpheli-ise-daha-sıkı-tolerans (bu oturum, devam)

Kullanıcının canvas-ölçek düzeltmesinin hemen ardından gelen isteği
(birebir, yorumlanmış): "birebir aynı çizmek önemli değil, hafif
sapmalar sorun değil, AMA aşırı kusursuz takip -- milisaniye/saliyelik
bile ardışık hız değişmeyen, aynı ritim, aynı pürüzsüzlük -- şüpheli
sayılmalı ve bir algoritmaya eklenmeli. Sistem bunu güvenilmez bulursa
ikinci kez, bu sefer daha ince bir çizgiden (daha sıkı toleransla) test
etsin. Hep aynı çizgi çıkması da riskli geliyor."

**"Hep aynı çizgi" kısmı** bir önceki notta zaten netleştirildi (kasıtlı
tasarım: `max_attempts` boyunca aynı challenge tekrar denenir, her
denemede yeni eğri vermek "kaç hakkın kaldı" mantığını bozardı) --
tekrar açıklamadım, kullanıcı zaten kabul etmişti.

**Asıl istek**: mevcut Path-Trace kontrolü SADECE geometriye bakıyordu
(çizgiye yakınlık + köşe kapsaması) -- izin NASIL üretildiğine (insan
eli mi, sabit hızlı bir script mi) hiç bakmıyordu. Bu, `captcha/
scoring.py`'nin tıklama-öncesi fare hareketi için zaten yaptığı ("insan
reach hareketi çan eğrisi hız profiline sahiptir, script sabit hızlıdır"
-- minimum-jerk model, Flash & Hogan 1985) ayrımın path-trace'e hiç
uygulanmamış olmasıydı. Kullanıcının önerisi de tam olarak bu bilimsel
gerekçeyle örtüşüyor.

**Uygulama**:
1. `widget.js`'in `toCanvasPoint(e)`'i artık `performance.now()` zaman
   damgası da ekliyor (`[x, y, t_ms]`) -- `scoring.py`'nin
   `mouse_trajectory` formatıyla aynı. Eski istemciler (2 elemanlı nokta
   gönderenler) sadece kinematik kontrolü çekimser bırakıyor.
2. `path_trace.py`'de `_looks_suspiciously_uniform(trace)`: segment
   hızlarının VE örnekler-arası zaman aralıklarının varyasyon katsayısını
   (coefficient of variation, `scoring.py`'nin `_mouse_velocity_variance`/
   `_mouse_timing_variance`'ıyla aynı istatistik) hesaplıyor. İKİSİ DE
   çok düşükse (< 0.05) şüpheli -- SADECE biri düşükse değil (yavaş ama
   kararlı bir insan hareketi tek eksende doğal olarak düşük varyansa
   sahip olabilir, iki eksende BİRDEN sıfıra yakın olmak asıl bot
   imzası).
3. `verify()`: şüpheli bulunursa DOĞRUDAN reddetmiyor (kullanıcının
   özellikle istediği şey buydu -- "güvenilmez derse... 2. kez... daha
   ince çizgiden geçiririz") -- bunun yerine (a)/(b) geometrik
   kontrollerini `tolerance / 2` ile TEKRAR çalıştırıyor. Gerçekten çok
   düzgün AMA aynı zamanda o kadar hassas bir el (stylus, çok kararlı bir
   kullanıcı, yardımcı teknoloji) yine geçiyor -- kusursuzluk tek başına
   cezalandırılmıyor, sadece daha yüksek hassasiyet isteniyor.

**Dürüstlük notu** (docstring'e eklendi, `scoring.py`'nin aynı ilkesiyle
tutarlı): bu da yumuşak bir sezgisel, bir "bot dedektörü" değil -- gerçek
bir insan izinin kaydedilip zaman damgalarıyla birebir tekrar
oynatılmasını (replay) yakalayamaz, modülün en üstteki docstring'i zaten
bunu ("çizgi istemciye teslim ediliyor, kararlı bir script eşleşen bir
iz üretebilir") dürüstçe kabul ediyor.

**Doğrulama**: 4 yeni test yazıldı -- gerçek geometri kullanılarak
(rastgele `provider.issue()` ile üretilen gerçek eğriler üzerinde,
mock'lanmamış):
- Geometrik olarak tam tolerans (24px) içinde ama YARISININ (12px)
  dışında, SABİT hız+zamanlamayla (`_with_constant_velocity_and_timing`,
  eşit yay-uzunluğu aralıklı noktalar + sabit `dt`) üretilen bir iz
  REDDEDİLİYOR.
- Aynı geometrik sapmaya sahip ama DOĞAL (düzensiz, alternatif
  hızlı/yavaş) zamanlamalı bir iz (`_with_natural_jitter_timing`) KABUL
  EDİLİYOR -- kinematik şüpheli değilse tolerans sıkılaştırılmıyor.
- Sabit hız+zamanlama AMA çizginin tam üzerinde (offset=0) bir iz yine
  KABUL EDİLİYOR -- kusursuzluk TEK BAŞINA reddetmiyor.
- Yetersiz zaman damgalı örnekte (`_looks_suspiciously_uniform`
  doğrudan) kontrol çekimser kalıyor (`False` -- ceza yok).

Ayrıca gerçek headless Chromium (Playwright) ile GERÇEK bir fare
sürüklemesi (tarayıcının kendi event-loop zamanlamasıyla, sentetik sabit
adım değil) normal şekilde geçtiğini doğruladım -- yeni kontrol gerçek
insan kullanımını yanlışlıkla cezalandırmıyor. `_resample_equal_arc_
length` adlı yeni bir test yardımcısı yazıldı (`_sample_along`'dan
farklı olarak segment uzunluklarına göre değil, gerçek yay uzunluğuna
göre eşit aralıklı noktalar üretiyor -- "sabit hız" iddiasının
matematiksel olarak doğru olması için gerekli).

## Path-Trace: canvas ölçek uyuşmazlığı -- gerçek çizgi bile reddediliyordu (bu oturum, devam)

Sıralı test planının 3. adımında kullanıcı bildirdi: "baya farklı şey
denedim hepsi reddedildi ama normal şekilde yapıyorum yine
reddediliyor... hep aynı çizgi çıkıyor ve çizdiğim çizgiyi düzleştirme
yapıyor heralde." Bu, önceki turda düzelttiğim "düz kısayol" bug'ından
TAMAMEN FARKLI, yeni ve gerçek bir bug'dı -- kullanıcının şüphesi
("düzleştiriyor") doğru çıktı.

**Kök neden**: `widget.js`'in path-trace canvas'ı, `pointerdown`/
`pointermove`'da `canvas.getBoundingClientRect()`'ten (canvas'ın CSS'te
GÖRÜNDÜĞÜ boyut) fare koordinatlarını alıp DOĞRUDAN, hiçbir ölçek
düzeltmesi yapmadan, çizginin sunucu tarafındaki native koordinat
uzayıyla (canvas'ın `width="320" height="160"` HTML attribute'ları)
karşılaştırıyordu. Bu ikisi eşit OLMAK ZORUNDA değil --
`.dwa-captcha-widget{max-width:300px}` zaten canvas'ın native 320px'inden
dar bir konteyner, host sayfanın kendi CSS'i (responsive bir
`canvas{max-width:100%}` reset'i, dar bir konteyner, tarayıcı zoom'u,
mobil cihaz) bunu daha da küçültüp/büyütebilir. Kullanıcı GÖRDÜĞÜ
(küçültülmüş) çizgiyi tam sadakatle takip etse bile, kaydedilen
noktalar yanlış ölçekte olduğundan sunucuya sistematik olarak kaymış/
"düzleşmiş" bir iz gönderiliyor, 24px tolerans kontrolü rastgele
başarısız oluyordu (host'un CSS'ine, cihaz genişliğine, zoom'a göre
değişken -- bu yüzden kullanıcı "bazen oluyor, çok takmadım" dedi).

**"hep aynı çizgi çıkıyor" kısmı bir bug DEĞİL**: aynı token/challenge
üzerinde tekrar denemeler (max_attempts=5) kasıtlı olarak AYNI eğriyi
tekrar gösteriyor -- her başarısız denemede yeni bir eğri sunmak,
"kaç deneme hakkın kaldı" mantığını anlamsızlaştırırdı. Bu tasarım
gereği, sorun değil.

**Düzeltme**: `renderPathTraceChallenge`'a `toCanvasPoint(e)` eklendi --
`canvas.width / rect.width` ve `canvas.height / rect.height` oranlarıyla
her noktayı canvas'ın NATIVE çizim uzayına çeviriyor.
`pointerdown`/`pointermove` artık bunu kullanıyor. Ölçekleme yoksa oran
1, davranış aynı; ölçeklemede artık doğru.

**Doğrulama -- gerçek tarayıcı, kök nedeni kanıtlayacak şekilde**:
Playwright ile canvas'ı host-sayfa-CSS'i taklit ederek kasıtlı olarak
320x160 native'den 222x112 CSS boyutuna küçülttüm (`.dwa-cw-canvas{width:
220px!important;height:110px!important}`), gerçek fareyle GÖRÜNEN
(küçültülmüş) eğrinin üzerinden ekran koordinatlarını doğru
hesaplayarak sadakatle geçtim (gerçek bir kullanıcının GÖRDÜĞÜ şeyi
takip etmesini simüle ederek). Sonuçlar:
- **Eski kod (bu düzeltmeden önceki `HEAD` commit'i, `git show HEAD:...`
  ile ayrı serve edildi) aynı senaryoda REDDETTİ** ("the captcha answer
  was wrong") -- kullanıcının bildirdiği bug'ı birebir yeniden üretti.
- **Yeni kod aynı senaryoda KABUL ETTİ** ("Doğrulandı").

Bu, kök nedenin gerçekten canvas ölçek uyuşmazlığı olduğunu ve
düzeltmenin çalıştığını doğrudan kanıtlıyor -- daha önceki turlardaki
Playwright testlerimin bu bug'ı YAKALAMAMASININ sebebi de netleşti:
o testler geniş, varsayılan bir viewport'ta çalıştığı için canvas hiç
küçültülmemişti (`rect.width === canvas.width`), yani sorun hiç
tetiklenmemişti -- kullanıcının gerçek cihazında/tarayıcısında bir
şekilde canvas küçültülüyor olmalı.

## /appeal'da da aynı "DM onayı yok" bug'ı bulundu (bu oturum, devam)

Sıralı test planının 1. adımını takip ederken kullanıcı bildirdi:
`/simulate-ban` 3 kez, `/appeal` doğrulama linki verdi, web'de widget'ı
çözdü, ama Discord'a hiç DM gelmedi; geri dönüp `/appeal`'i tekrar
çalıştırınca doğrulama istemeden "kaydedildi" dedi. Bu ikinci kısım
DOĞRU davranış (bir kez doğrulanan kullanıcı muaf) -- eksik olan
sadece ilk doğrulamadan sonraki geri bildirimdi.

Bu, bir önceki turda `/giveaway-test`'te bulduğum bug'ın BİREBİR
AYNISI: `_on_appeal_verified` handler'ı sadece `_appeal_verified_users`
setine ekliyordu, hiçbir DM yoktu. Aynı düzeltmeyi buraya da uyguladım:
doğrulama başarılı olunca "Doğrulandın! Artık `/appeal` komutunu tekrar
çalıştırıp itirazını gönderebilirsin." DM'i gidiyor
(`bot.fetch_user`/`user.send`, `discord.Forbidden`'a karşı
`contextlib.suppress` ile korunmuş -- aynı desen).

**Ders**: bu üçüncü kez aynı kategori bug (giveaway-test, appeal, ve
muhtemelen ileride farkedilecek başka handler'lar) -- `on_verified()`
handler'ı ekleyen her yeni senaryoda "kullanıcıya bir geri bildirim
gönderiyor mu" kontrolünü baştan bir checklist maddesi yapmalıyım,
tek tek kullanıcı raporu bekleyerek değil.

**Test zorluğu**: appeal_gate `ProofOfWorkProvider` kullanıyor (Math
değil), bu yüzden test scriptimde ilk denemede `_captcha_store`'dan
ham `pending.answer`'ı cevap olarak yollamaya çalıştım -- bu PoW için
anlamsız (PoW'un "answer"ı gerçek bir nonce, saklanan challenge verisi
değil), test `verified: False` döndü. `providers/proof_of_work.py`'nin
kendi test dosyasındaki `_solve_pow` desenini (gerçek hashcash arama)
kullanınca doğru şekilde geçti ve DM'in gönderildiği kanıtlandı --
bir CaptchaGate'in hangi provider'ı kullandığını (Math/PoW/PathTrace)
kontrol etmeden "cevap" uydurmanın yanlış test sonucuna yol açabileceği
küçük ama somut bir hatırlatma.

## dörtlü fiziksel test raporu -- ayrıştırma + 2 gerçek bug + 2 netleştirme (bu oturum, devam)

Kullanıcının tek mesajda bildirdiği dört ayrı gözlem, tek tek incelenip
ayrıştırıldı (hepsini aynı torbaya koymadan):

**1. Gerçek bug: `/join-adaptive`'e "giriş yapmama gerek olmadan captcha
oldu".** Kod incelemesi: `_verify_page` `require_account=True` olan
gate'lerde bile widget'ı HER ZAMAN render ediyordu, login yoksa sadece
YANINDA bir login linki gösteriyordu -- yani giriş yapmadan bir Math
captcha çözmek veya PoW'u beklemek mümkündü, sadece en sonunda
`AccountMatchCheck` başarısız oluyordu (`verify()` anında). Bu, hem
zaman/kaynak israfı hem kafa karıştırıcı bir UX -- kullanıcı captcha'yı
çözdü ama neden işe yaramadığını anlamıyor. `/giveaway-test/verify`
zaten doğru davranıyordu (`if user is None: return login-only page`) --
o deseni `_verify_page`'e de taşıdım: `if gate.require_account and user
is None: return _login_required_page()`. Doğrudan doğrulandı: giriş
yapılmadan `/verify/adaptive/{token}` artık `dwa-captcha-widget` hiç
içermiyor.

**2. Gerçek bug: `/giveaway-test`'te "2sinde de captcha çözdüm ama bir
şey olmuyor, ama `/giveaway-test-participants` beni listeliyor".** Bu
ifade aslında mekanizmanın ÇALIŞTIĞINI kanıtlıyor (katılımcı kaydı doğru)
-- eksik olan sadece kullanıcıya geri bildirimdi. `_on_giveaway_test_
joined` handler'ı sadece `_giveaway_test_participants` dict'ine
ekliyordu, hiçbir DM/mesaj yoktu -- Scenario 1'in `_on_giveaway_verified`'ı
her zaman "Doğrulandı! ... çekilişine katıldın." DM'i atarken, Scenario
4'ün handler'ı sessizdi. Düzeltme: aynı deseni ekledim -- `bot.fetch_
user` + `user.send("Katıldın! **{title}** için doğrulaman başarıyla
tamamlandı.")`, sadece İLK başarılı doğrulamada (idempotent ikinci
`verify()` çağrısında tekrar göndermemek için `is_new` kontrolü),
`discord.Forbidden`'a karşı `contextlib.suppress` ile korunmuş (DM'leri
kapalı kullanıcı sessizce atlanıyor, tüm akış patlamıyor). Doğrudan
doğrulandı: `bot.fetch_user`/`user.send` mock'lanıp `verify()` çağrıldı,
DM'in gerçekten gönderildiği ve "Katıldın! **Test Çekilişi**..." içeriğini
taşıdığı kanıtlandı.

**3. Netleştirme, bug değil: `/test-join` (Scenario 3).** Kullanıcı ısrarla
"katıldım, otomatik katılma mesajı gelmedi" diye bildirmeye devam etti
(bu üçüncü kez aynı konu) -- ama Scenario 3 TASARIM GEREĞİ gerçek bir
katılım akışı değil, üç captcha türünü karşılaştırma demosu (README'de
zaten böyle belgeliydi). Sorun koddan değil, "Katıl" butonu/`test-join`
komut adının kendisinin yanlış beklenti yaratmasından kaynaklanıyordu --
üç kez aynı yanlış anlaşılma yaşanınca bunu koddan çözmeye karar verdim:
komut `/test-compare-captchas`'a, view sınıfı `_JoinTestView` ->
`_CompareCaptchaTypesView`'a, buton "Katıl" -> "Karşılaştır"a yeniden
adlandırıldı, ephemeral cevaba "bu gerçek bir katılım değil, giriş
gerektirmiyor, onay mesajı gelmeyecek, gerçek akış için /giveaway-test'e
bak" notu eklendi. README'nin Scenario 3 bölümü de bunu açıkça
belirtecek şekilde güncellendi.

**4. Netleştirme, kasıtlı tasarım: `/join`'e rastgele isim yazınca
kabul ediyor.** Kullanıcı "bazıları bilerek testte absürt tutulan
yerler mi" diye sordu -- evet, bu biri. `giveaway_name` bu demo'da
sadece DM mesajında gösterilen bir metadata alanı, gerçek bir çekiliş
kataloğu/kayıt sistemi yok (Scenario 1'in amacı hesap-bağlama+PoW+
davranış gate'ini göstermek, çekiliş yönetimi değil). Koda açıklayıcı
bir yorum eklendi, davranış değiştirilmedi.

**Doğrulama özeti**: `TestClient` ile giriş-öncesi/sonrası widget
görünürlüğü doğrudan test edildi; `giveaway_test_original_gate.verify()`
doğrudan çağrılıp mock'lanmış `bot.fetch_user`/`user.send` ile DM'in
gerçekten gittiği kanıtlandı; `ruff`/`mypy` temiz, `pytest` 702 passed
(bilinen Postgres testi hariç).

## verify sayfaları: kullanıcı adı gösterimi + erken hesap-sahiplik kontrolü (bu oturum, devam)

Kullanıcının isteği (sıralı test planına geçmeden önce): "Ondan önce
zaten yetkilendirme yapıldıysa orada kullanıcı ismi gözüksün ve token
kontrolü vesaireler yapılsın başka hesabın linkini doğrulamaya
çalışmasın."

**Zaten var olan güvenlik**: `AccountMatchCheck` (`checks.py`) yanlış
hesabı `verify()` çağrısında zaten reddediyordu (`require_account=True`
olan her gate'te) -- yani gerçek bir güvenlik açığı yoktu. Ama bu kontrol
sadece captcha çözülüp gönderildikten SONRA çalışıyordu; kullanıcı yanlış
hesapla giriş yapmışsa bunu ancak denedikten sonra öğreniyordu, ki bu
kafa karıştırıcı (captcha'nın kendisi bozukmuş gibi görünebilir).

**Eklenen**: `_expected_user_id(gate, token)` -- `gate.store.get(token)`
ile token'ın hangi kullanıcı için kesildiğini okuyor (hem `CaptchaGate`
hem `AdaptiveCaptchaGate` `.store` attribute'una sahip olduğundan ikisi
için de çalışıyor). `_wrong_account_page(username)` -- "Bu link sana ait
değil" + çıkış yap linki, captcha hiç render edilmiyor.
`_verify_page(token, api_base, gate, user)` artık `user` parametresi
alıyor (route'lar `Depends(get_current_user_optional)` ile çekip
geçiriyor -- global bir hack yerine düz parametre geçişi, ilk
denemede bir closure/global-mutation hilesi yazmıştım ama bunun
eşzamanlı isteklerde race condition'a açık olduğunu fark edip düz
parametreye çevirdim): giriş yapılmışsa önce sahiplik kontrolü, uyuşmazsa
blokla; uyuşuyorsa "Giriş yaptın: **username**" + widget; giriş
yapılmamışsa eskisi gibi login linki. `giveaway_test_verify_page` zaten
kullanıcı adını gösteriyordu, ona da aynı sahiplik kontrolü eklendi
(üç token'dan birini kontrol etmek yeterli, hepsi aynı buton
tıklamasında aynı kullanıcı için kesiliyor).

**Doğrulama**: `TestClient` + `app.dependency_overrides[get_current_
user_optional]` ile üç durum ayrı ayrı doğrudan test edildi: (1) giriş
yok -> login linki, widget yok; (2) yanlış hesap (`user_id=999`,
token `user_id=111` için) -> "Bu link sana ait değil" sayfası, widget
YOK; (3) doğru hesap -> kullanıcı adı + widget VAR. Üçü de beklenen
gibi çalıştı.

## get_info: doğrulanmış link sayfa yenilemede "geçersiz/süresi dolmuş" görünüyor (bu oturum, devam)

Kullanıcı "sıralı test edelim" dedi, 1. adımı (widget donma düzeltmesi)
denerken YENİ bir bug bildirdi: "captcha çözdüm doğrulama linki
geçersiz veya süresi dolmuş diyor, yine tıklıyorum yine de doğruluyor,
tekrar tekrar sayfayı yenileyince yazıyor ama yine de kutucuğa
tıklanıyor." Bunu inceleyip gerçek kök nedeni buldum.

**Kök neden**: `CaptchaGate.get_info()` "token yok/süresi dolmuş" ile
"token zaten doğrulandı" durumlarını tek bir `None` dönüş değeriyle
birleştiriyordu:
```python
request = await self._get_live(token)
if request is None or request.verified:
    return None
```
API katmanında bu `None` -> 404'e dönüşüyor, widget'ın `loadInfo()`'su
da `!resp.ok` görünce `showFatalError('Doğrulama linki geçersiz veya
süresi dolmuş.')` çağırıyordu. Yani bir önceki turda widget'ı
"başarıda donacak" şekilde düzelttim ama SAYFA YENİLEME senaryosunu
(widget'ın constructor'da her zaman çalıştırdığı `loadInfo()`'nun
sunucudan TEKRAR bilgi çekmesi) hiç düşünmemiştim -- sunucu "zaten
doğrulandı"yı "hiç var olmadı" ile aynı kefeye koyduğu için widget'ın
kendi başarı state'i sıfırlanıp yanlış hata mesajına düşüyordu.

`AdaptiveCaptchaGate.get_info()`'da da birebir aynı desen vardı --
ikisi de düzeltildi.

**Düzeltme**: `GateInfo` modeline `verified: bool = False` eklendi;
her iki gate'in `get_info()`'u artık `request is None` (gerçek
gone/expired) ile `request.verified` (zaten doğrulandı) durumlarını
AYRI dönüyor -- ikincisi artık `None` değil, `{"verified": True,
"challenge": None, ...}` gibi gerçek bir bilgi nesnesi. `widget.js`'e
`showAlreadyVerified()` eklendi: `loadInfo()` artık `info.verified`
görünce kutuyu "Zaten doğrulandı" + yeşil tik ile kalıcı olarak
dondurur (bir önceki turdaki "başarıda donma" mantığıyla tutarlı),
`showFatalError`'a hiç düşmez.

**Regresyon yakalandı ve düzeltildi**: mevcut
`test_gate_verify_solves_the_giveaway_scenario` testi TAM OLARAK eski,
hatalı davranışı (`followup.status_code == 404`) doğruluyordu -- yani
bu bug'ın kendisi zımnen bir test tarafından "doğru" sayılıyordu. Bunu
`200` + `verified: true` bekleyecek şekilde güncelledim, ve hem
`CaptchaGate` hem `AdaptiveCaptchaGate` için ayrı regresyon testleri
ekledim (`test_get_info_distinguishes_already_verified_from_gone`).

**Doğrulama -- gerçek tarayıcı, tam senaryo**: Playwright ile Math
captcha çözüldü, 4 saniye beklendi (hâlâ "Doğrulandı"), **sonra
`page.reload()` ile sayfa gerçekten yenilendi** -- widget "Zaten
doğrulandı" gösterdi, "geçersiz"/"süresi dolmuş" YAZMADI. (İlk
denemede test scriptimin kendi string kontrolü büyük/küçük harf
duyarlılığı yüzünden yanlış FAIL verdi -- gerçek davranış baştan beri
doğruydu, sadece benim doğrulama scriptim hataliydi; düzeltip tekrar
teyit ettim.)

**Kullanıcının aynı mesajdaki diğer notları -- henüz ele alınmadı,
sıradaki adımlar**: "/test-widgets sayfasında hâlâ 2 tane captcha var,
3. yok" (kullanıcı ısrarla bunu bildiriyor, ben kod incelemesinde 3 div
buluyorum -- bir sonraki adım gerçek ekran görüntüsü istemek veya
sayfayı doğrudan ben açıp gözlemlemek), ve "/giveaway-test hâlâ aynı
çalışmıyor" (muhtemelen yukarıdaki get_info bug'ının bir başka
tezahürü olabilir -- giveaway-test/verify sayfası da aynı `get_info`
endpoint'ini kullandığından, bu düzeltme onu da düzeltmiş olabilir;
kullanıcıdan tekrar denemesi istenecek, sıralı test planının 1.
adımından devam).

## widget: başarıdan sonra sıfırlanıp tekrar captcha sorma bug'ı (bu oturum)

Kullanıcının fiziksel test bildirimi (birebir özet): "test-join
komutunu kullandım, katıl butonuna tıkladım, url verdi, 2 captcha vardı,
çözdüm, ikisi de doğru dedi, geri döndüm Discord'a, otomatik katılma
mesajı gelmediği için tekrar katıl dedim, yine captcha çöz dedi, aynı
url'de captchayı tekrar çözüyoruz, hepsinde 'tamamlandı' diyip 1 saniye
sonra tekrar captcha geliyor. Öyle olmasın, test-join'de captcha
başarılıya orası artık başarılı gözüksün, tekrar tekrar captcha
çözmeyelim, potansiyel saldırı açığı, testte olsa gözden kaçırmamak
gerekli."

**Kök neden -- gerçek bug, bundled widget'ta.** `widget.js`'in
`runVerification`'ı fetch cevabından sonra, başarı/başarısızlık ayrımı
yapmadan, her durumda `setTimeout(re-arm, 2500)` ile kutuyu 2.5 saniye
sonra "tekrar dene" durumuna sıfırlıyordu. Doğrulanmış bir token için
bile kutu yeniden tıklanabilir hale geliyor, kullanıcı aynı captcha'yı
sonsuz kez çözebiliyordu. Kullanıcının gördüğü "tamamlandı, 1 saniye
sonra tekrar captcha" tam olarak buydu.

**Sunucu tarafı zaten güvenliydi (önce bunu doğruladım).** `gate.py`
`verify()`: `if request.verified: return CheckResult(verified=True, ...)`
-- doğrulanmış token ikinci çağrıda kontrolleri TEKRAR ÇALIŞTIRMADAN
idempotent başarı döndürüyor, ve `transport.publish(captcha_verified)`
yalnızca ilk (henüz verified=False) doğrulamada çalışıyor. Yani widget
sıfırlanıp kullanıcı tekrar çözse bile: (1) çift katılım/çift sayım YOK
(`on_verified` bir daha fire etmiyor), (2) captcha cevabı bir daha
tüketilmiyor. Gerçek bir exploit değildi -- ama kullanıcının içgüdüsü
haklı, bir captcha'yı tekrar tekrar "çöz" diye sunmak kötü desen.

**Düzeltme.** Başarıda widget artık kalıcı olarak donuyor:
`this.verified = true`, yeşil tik + "Doğrulandı" kalıyor, challenge
paneli (`expandEl`) kapatılıp içi boşaltılıyor (harcanmış submit butonu
gitsin), `return` ile re-arm setTimeout'una hiç girilmiyor, `busy` da
kalıcı true kalıyor. `onBoxClick` ve `runVerification`'a `|| this.verified`
guard'ı, constructor'a `this.verified = false` eklendi. YALNIZCA
başarısızlık yolu eskisi gibi 2.5s sonra re-arm ediyor (yanlış cevap/
özensiz çizim retry'ı korunsun diye).

**Doğrulama -- gerçek tarayıcı.** Playwright + pre-installed Chromium
(`/opt/pw-browsers/chromium-1194/chrome-linux/chrome`, `--no-sandbox`)
ile uçtan uca sürüldü: (a) Math doğru cevap → kutu "Doğrulandı"da kalıyor,
4sn sonra (eski 2.5s sıfırlamanın ötesinde) hâlâ yeşil + panel kapalı;
(b) yanlış cevap → "Doğrulanamadı", 3sn sonra "Tekrar deneyin"e dönüyor
(retry çalışıyor). Bundled widget'ı kullanan TÜM akışları birden
düzeltiyor. `tests/unit/test_captcha_widget.py` sadece serving
kontratını test ediyor (JS davranışı unit test'le sürülemez, bu yüzden
gerçek tarayıcı doğrulaması manuel yapıldı -- dosyanın kendi docstring'i
de bunu söylüyor).

**Hâlâ açık (kullanıcıya sorulacak).** "otomatik katılma mesajı gelmedi"
-- `/test-join` (Scenario 3) bir KARŞILAŞTIRMA demosu, gerçek katılım
akışı değil; widget artık başarıda "Doğrulandı" gösterip donduğu için
en azından her widget'ın kendi başarı geri bildirimi net. Gerçek
otomatik-katıl akışı `/giveaway-test`'te. Test sayfalarının çokluğu/
isim karışıklığı bu kafa karışıklığının kaynağı -- sonraki adım olarak
kullanıcı onayıyla test sayfalarını sadeleştirmek gündemde.


## Fiziksel test geri bildirimi: 4 gerçek bug/tasarım hatası (bu oturum)

Kullanıcı bir önceki turda eklenen 5 test sayfasını gerçekten fiziksel
olarak deneyip birebir şu geri bildirimi verdi (yazım hatalarıyla):
"Şimdi 1. Testte sadece mouse tıklama hareketlerine bakıyorsa bu yanlış
bu kadar bsait birşeyden sadece birşey çıkarmak çok hatalı olurdu 2.de
çizgi çok düzleştiriyor olduğu gibi almalı işlemeli yada kullanıcılar mı
çok düz görüyor 3. Slash giveaway testi yazdım mesaj geldi butona
tıkladım etkileşim başarısız oldu dedi 4. 2 kontrol yapmayalım ilk
tıklamada tıklamaya kadar ilk kontrol 2. Kontrol capctha testi görsel
olan böyle saçma olur profosyonel olmaz ... birde /test-join de hata var
3 captcha diyiyor sayfada 2 tane var 2sinide doğru yapıp katıl diyiyorum
katılmıyor ve otomatik katılmalı ... birde yetkilendirme istemedi discord
hesabına."

**#1 -- gerçek bug, doğrulandı ve düzeltildi.** Test 1
(`test1_behavior_gate`) `require_captcha=False` ile SADECE
`SignalScoreCheck`'i (davranış skoru) tek başına gate olarak
kullanıyordu. Bu, `discord_webapi/captcha/scoring.py`'nin kendi
docstring'inde defalarca vurgulanan uyarının bizzat bu kütüphanenin bir
demo dosyasında ihlal edilmesiydi: "istemci sinyalleri asla tek başına
insan/robot hükmü değil, PoW/hesap-bağlama'nın yanında bir speed bump
olarak çalışmalı." Bunu somut olarak kanıtladım: `TestClient` ile elle
gerçekçi bir sahte fare izi uydurdum (eğri, hız varyansı, zaman varyansı
hepsi "insan" aralığında, ama tamamen program tarafından üretilmiş) ve
düzeltmeden önce bu, `require_captcha=False` gate'ini TEK BAŞINA
geçiyordu -- kullanıcının tam olarak şüphelendiği şey. Düzeltme: Test
1 artık her yerdeki diğer "görünmez" gate'ler gibi (`giveaway_gate`,
`giveaway_test_invisible_gate`, ...) gerçek `ProofOfWorkProvider` +
davranış skorunu BİRLİKTE istiyor. Aynı sahte-iyi sinyaller artık PoW
çözümü olmadan `"captcha"` kontrolünde reddediliyor -- doğrudan
doğrulandı (`{"verified": false, "failed_check": "captcha", "detail":
"no captcha answer was submitted"}`).

**#2 -- gerçek bug, ama İLK DÜZELTMESİ BOZUKTU; "emin olalım" turunda
yakalanıp düzgün düzeltildi.** Kullanıcının sorusu ("biz mi
düzleştiriyoruz yoksa kullanıcı mı düz çiziyor") araştırılınca gerçek bir
doğrulama zafiyeti ortaya çıktı: `path_trace.py`'nin `verify()`'ı sadece
(a) her çizilen nokta polyline'a `tolerance` (24px) içinde mi ve (b)
eğrinin her köşesine yakın bir çizilen nokta var mı kontrol ediyordu.
Eğrinin kendi kirişinden sapması (bulge) `tolerance`'tan küçük kaldığında,
başlangıç-bitiş arasına düz köşegen çizmek de bu ikisini geçiyordu --
eğriyi HİÇ takip etmeden. Yani soru "kullanıcı düz görüyor" değil,
"sunucu düz kısayolu bazen kabul ediyordu" -- gerçek bug.

**İlk düzeltme denemem ÖLÜ KOD'du (önemli ders).** verify'a üçüncü bir
kontrol ekledim: "çizilen izin kirişten sapması, gerçek eğrinin
sapmasına `tolerance` kadar yakın olmalı" (`if curve_bulge > tolerance:
if trace_bulge < curve_bulge - tolerance: return False`). İki nedenle
tamamen işe yaramazdı: (1) kontrol (b) geçtiğinde, tepe köşeye
`tolerance` içinde bir iz noktası olması ZORUNLU olduğundan, üçgen
eşitsizliğiyle `trace_bulge >= curve_bulge - tolerance` zaten garantidir
-- yani üçüncü kontrolün red koşulu (b) geçince ASLA sağlanamaz; (2)
gerçek bug durumunda (bulge <= tolerance) dış `if curve_bulge >
tolerance` false olduğundan kontrol büsbütün atlanıyordu. Kullanıcı "emin
olalım hepsini tekrar kontrol et" deyince doğrudan ölçtüm: ilk
"düzeltme"den sonra bile 2000 challenge'da düz kısayolların **89'u hâlâ
kabul ediliyordu** (curve_bulge'ün 17-24px'e düştüğü durumlar). Bu, bir
düzeltmeyi "yeşil test" gördüğüm için doğru sanmanın klasik tuzağıydı --
test (`...rejects_a_straight_shortcut...`) geçiyordu ama benim ölü
kontrolüm sayesinde DEĞİL, zaten var olan kontrol (b) sayesinde (o tek
challenge'da curve_bulge tesadüfen > tolerance'tı). Tek örnekli test,
%4-5 olasılıkla gerçekleşen bug'ı gizliyordu.

**Gerçek düzeltme üretim tarafında.** `_make_path` iki parçaya bölündü:
`_random_wave` (eski sinüs gövdesi) + `_make_path` artık dalgayı, kendi
start->end kirişinden en az `tolerance * 1.5` (=36px) sapana dek yeniden
üretiyor (bounded retry, 50 deneme -- rastgele dalga bu barajı çoğu
zaman ilk denemede aşıyor). Modül düzeyinde `_chord_bulge` yardımcısı
eklendi. Bu garantiyle tepe köşeler kirişten `tolerance`'tan uzakta
kalıyor, dolayısıyla kontrol (b) düz kısayolu DOĞASI GEREĞİ reddediyor;
ölü üçüncü kontrol verify'dan kaldırıldı (yorumda neden ölü olduğu
açıklandı ki biri tekrar eklemeye kalkmasın). Somut doğrulama (3000
challenge): düz kısayol kabul = **0** (öncesi 89/2000), min bulge tam
36.0, tüm sadık izler kabul, hiçbir vertex 160px canvas dışına taşmıyor
(retry eski üreticiyi kullandığı için canvas sınırları korunuyor). İki
yeni test: `test_path_trace_rejects_a_straight_shortcut_across_many_
issues` (200 challenge -- tek örnek yerine döngü, tam da ilk testin
kaçırdığı şeyi yakalıyor) ve `test_path_trace_issued_wave_always_
bulges_past_tolerance` (üretim garantisi).

**#3 -- muhtemel bug, kod incelemesiyle en olası kök nedene göre
düzeltildi (canlı Discord olmadan kesin tekrar üretilemedi).**
`_GiveawayTestJoinView.join_button`'da üç ayrı `create_verification()`
çağrısı, Discord'un ~3 saniyelik etkileşim yanıt penceresi içinde
`interaction.response.send_message()`'dan ÖNCE bekleniyordu -- bu üç
çağrının herhangi birinde ufak bir gecikme/hata bu pencereyi kaçırıp tam
olarak kullanıcının gördüğü "etkileşim başarısız oldu"ya sebep olurdu.
Düzeltme: fonksiyonun en başında `interaction.response.defer(ephemeral=
True, thinking=True)` çağrılıyor (yanıt penceresini hemen kapatıyor,
Discord kullanıcıya "düşünüyor..." gösteriyor), asıl iş (üç
create_verification + DM) bittikten sonra `interaction.followup.send()`
ile gerçek mesaj gönderiliyor. Ayrıca DM gönderimi artık
`discord.Forbidden`'a karşı korunuyor -- bir kullanıcının DM'leri kapalıysa
sessizce patlamak yerine linki ephemeral cevapta da gösteriyor (önceki
kodda bu durumda kullanıcı hiçbir link almadan kalırdı, hatasız ama
sessizce başarısız).

**#4 -- kullanıcı haklı, tasarım hatası, kaldırıldı.** `/test-cloudflare`
sayfasına önceki turda "çift eskalasyon" göstermek için eklenen üçüncü,
"daha katı sessiz ikinci kontrol" (`test4_strict_gate`) gerçek bir
savunma katmanı değildi -- kullanıcının dediği gibi "saçma, profesyonel
değil": bir bot zaten geçtiği sessiz bir kontrolü ikinci kez sessizce
tekrar çalıştırmak hiçbir yeni ayırt edici bilgi vermiyor, sadece gerçek
bir kullanıcıya anlamsız bir ekstra adım ekliyordu. `test4_strict_gate`
ve üçüncü Path-Trace fallback'i tamamen kaldırıldı. `/test-cloudflare`
artık sadece `test4_adaptive_gate`'i (bir `AdaptiveCaptchaGate`)
kullanıyor -- bu zaten kendi başına, hiçbir sayfa-JS zincirlemesi
olmadan, tam olarak istenen iki katmanlı deseni uyguluyor: IP temizse
sessizce geç, kara listedeyse TEK bir gerçek Math captcha'sı göster.

**Doğrulanamayan iki nokta -- "emin olalım" turunda tekrar somut olarak
ölçüldü, kod tarafında bir hata bulunamadı; kullanıcının hangi sayfada
olduğu hâlâ net değil.** (a) "`/test-join`'de 3 captcha diyor ama 2 tane
var": `TestClient` ile `/test-widgets` sayfasının HTML'i çekildi ve tam
**3** adet `dwa-captcha-widget` div'i içerdiği doğrulandı (DM metni ve
başlık da "üç" diyor -- tutarlı). Sunucu tarafında eksik yok; kullanıcı 2
görüyorsa üçünden biri istemci tarafında render edilememiş olmalı (JS
hatası, süresi dolmuş token, vs.) -- canlı tarayıcı/ekran görüntüsü
olmadan tekrar üretilemedi. NOT: `/giveaway-test/verify` sayfası
BAŞLANGIÇTA 2 widget gösteriyor (invisible + original); üçüncüsü
(pathtrace) sadece eskalasyonda beliriyor -- URL'de 3 token olduğu için
kullanıcı burada "3 ama 2 görünüyor" diye yorumlamış olabilir, ki bu
tasarım gereği. (b) "captcha geçince otomatik katılmalı": `/giveaway-
test` akışında gerçekten otomatik katılımı DOĞRUDAN test ettim --
`giveaway_test_original_gate.verify()`'ı doğru cevapla + `authenticated_
user_id` ile çağırdım, `on_verified` fire-and-forget handler'ının
çalışmasını bekledim, ve kullanıcı `_giveaway_test_participants[gid]`'e
gerçekten eklendi (ekstra "katıl" butonu YOK -- captcha geçmek tek başına
katılım demek). Yani mekanizma çalışıyor; kullanıcının "katılmıyor"
demesi büyük olasılıkla ya login olmadan denemesinden (gate'ler
`require_account=True`, giriş yoksa "account" kontrolünde takılır) ya da
gerçek-katıl akışı olan `/giveaway-test` yerine karşılaştırma-demosu olan
`/test-join`'de olmasından. "yetkilendirme istemedi" ipucu bunu
destekliyor: `/test-join`/`/test-widgets` bilerek login İSTEMEZ (captcha
türü karşılaştırması, hesap-bağlama değil); gerçek login-zorunlu akış
`/giveaway-test/verify`. Sonraki turda kullanıcıdan ekran görüntüsü + tam
adım sırası istenip hangi sayfada olduğu netleştirilecek -- muhtemel
gerçek iş: test sayfalarının sayısını azaltıp isim/amaç karışıklığını
gidermek (kullanıcı onayıyla).

## examples/captcha_gate_bot: 5 test sayfası + gerçek katılımcı kaydı + kendi "Cloudflare"imiz

Kullanıcının tam isteği (birebir, yazım hatalarıyla): "Şimdi 5 farklı test
sayfası oekle veya uygun gördüğün şekilde examples/captcha_gate_bot'a ek
testte biri direk widget olacak kutucuğa tıklayacak normal şekilde
insansa başarılı diyecek başarısız olursa çizgi captchasını soracak yeni
bir sayfada widgete tıklayacaksın ama normalde olsa anormal sayacak teste
tabi tutacak maksat denemek için sahte veri yollayacaz ona 3. Test
fiscordda o giveway yaptığımız test varya en son çekiliş mesajı givi buton
ve test komutlu capctha başarılı olunca bot katılmayı gerçekleştirecek
veritabanı şeyleri komutta o mesajda katılımcılara eklenecek diğerinde o
sayfa blokeli kara listeye ekleyinc ekendikimiiz cloudflare gibi bir ekran
dofurlanihor eğer şüpheliye captchaya tıkla yine şüpheliyse teste tabi
tut ... Ve notlarını güncellemeyi unuttuysan önceki şeylerde felan
tamamen güncelle."

Yorumlanışı: (1) sadece widget, insansa direkt başarılı, robotsa
Path-Trace'e yükselt; (2) aynı akış ama sayfa bilerek sahte/kötü veri
yollasın, tespitin gerçekten çalıştığını kanıtlasın; (3) `/giveaway-test`
akışında captcha başarılı olunca gerçekten katılımcı listesine eklensin
(veritabanı/bellek düzeyinde, sadece log değil); (4) kendi IP'ni kara
listeye ekleyince Cloudflare tarzı "insan mısın" ekranı çıksın, geçilse
bile hâlâ şüpheliyse ikinci bir teste tabi tutulsun (çift eskalasyon);
(5, kendi eklediğim) tüm bunları bağlayan bir index sayfası.

**Test 3 zaten yapılmıştı**: bu isteğin gelmesinden hemen önceki bir
düzenlemede `_giveaway_test_participants: dict[int, set[int]]`
(giveaway_id anahtarlı), `_on_giveaway_test_joined` handler'ı (üç
Scenario-4 gate'inin hepsine `purpose=` filtresiyle bağlı) ve
`/giveaway-test-participants giveaway_id:N` komutu zaten eklenmişti;
`/giveaway-test` artık bir `title` parametresi alıp her çağrıda yeni bir
`giveaway_id` atıyor. Bu turda sadece README/module docstring'e
eklendiğinden emin olundu -- kod bu turda değişmedi.

**Test 1/2 mimari kararı**: `test1_behavior_gate`
(`require_captcha=False`, `extra_checks=_behavior_checks()`) ve
`test1_pathtrace_gate` (Path-Trace) -- ikisi de `require_account=False`,
kasıtlı: bu iki sayfa *tespiti* test ediyor, hesap-bağlamayı değil (o
zaten giveaway/appeal gate'lerinde kanıtlanmış). Sayfa 1'de widget'ın
`onWidgetVerified` callback'i üzerinden JS, başarısızlıkta ikinci bir
Path-Trace widget'ını DOM'a ekliyor -- `giveaway-test/verify`'de zaten
kullanılan aynı "iki gate'i sayfa JS'iyle zincirle" deseni, `_escalation_page`
adlı küçük bir yardımcıya çıkarıldı (3 sayfa da aynı JS iskeletini
kullanıyor). Sayfa 2 aynı iki gate'i paylaşıyor ama widget'ı hiç
çağırmıyor -- `fetch()` ile doğrudan `/test1-behavior/api/captcha/gate/
{token}/verify`'a `{webdriver: true, pointer_moves: 0, interaction_ms: 1,
mouse_trajectory: []}` gönderiyor. Bu, önceki bir turda "insan-benzeri
sinyaller simüle edilip geçti, bu kötü değil mi" sorusuna verdiğim
cevabın tam tersi yönde bir test: burada KÖTÜ sinyal gönderiliyor ve
REDDEDİLMESİ bekleniyor -- `TestClient` ile doğrudan doğrulandı, cevap
her zaman `{"verified": false, "failed_check": "no-webdriver", "detail":
"navigator.webdriver was true"}`.

**Test 4 mimari kararı**: `/join-adaptive`'in kullandığı AYNI paylaşılan
`blocklist` (`StaticBlocklistReputationChecker`) nesnesi tekrar
kullanıldı (`/api/test/block-my-ip` iki senaryoyu da aynı anda etkiliyor
-- bu kasıtlı, ayrı bir blocklist açmak "kendi IP'ni engelle" testini
gereksiz yere iki debug endpoint'e bölerdi). Ama `/join-adaptive`'in
aksine bu sayfa hesap/login istemiyor -- gerçek bir Cloudflare tarzı
ekran anonim, henüz kimliği belirsiz trafiğin önünde çalışır, bu yüzden
ayrı, login gerektirmeyen ikinci bir `AdaptiveCaptchaGate`
(`test4_adaptive_gate`, `require_account=False`) kullanıldı.
"Geçilse bile yine şüpheliyse teste tabi tut" isteği tam olarak
uygulandı: `test4_adaptive_gate`'i geçmek tek başına yetmiyor, ardından
daha katı bir ikinci, sadece-davranış gate'i (`test4_strict_gate`)
devreye giriyor; o da başarısız olursa üçüncü ve son adım olarak bir
Path-Trace gate'i (`test4_pathtrace_gate`) çıkıyor -- gerçek, üç
aşamalı bir zincir, tek bir "geç/kal" değil. `TestClient` ile
doğrulandı: `/api/test/block-my-ip` çağrısından sonra `/test-cloudflare`
sayfasının ilk widget'ı gerçekten bir Math challenge istiyor (aynı
`/join-adaptive` testinde kanıtlanan mekanizma, farklı bir gate
üzerinden).

**Test 5**: kullanıcının "veya uygun gördüğün şekilde" notuyla eklediğim
tek ekleme -- `/test-index`, yukarıdaki 4 test sayfasını ve ilgili
Discord komutlarını (`/join`, `/appeal`, `/test-join`, `/join-adaptive`)
tek bir linkler listesinde toplayan basit bir hub sayfası.

**Doğrulama** (`TestClient`, canlı Discord bağlantısı gerekmeden --
bu 5 sayfanın hiçbiri login istemiyor): `/test-instant-widget`,
`/test-forced-bad-data`, `/test-cloudflare`, `/test-index` hepsi 200
dönüyor ve beklenen HTML/JS parçalarını içeriyor; `test1-behavior`
gate'i sahte-kötü sinyalleri her seferinde reddediyor;
`/api/test/block-my-ip` gerçekten `test4_adaptive_gate`'in
`requires_captcha`'sını etkiliyor. `ruff check discord_webapi tests
examples` temiz, `mypy discord_webapi` 121 dosyada temiz (mypy'nin
kütüphane dışına -- örnek dosyalara -- uygulanmadığı doğrulandı, bu
zaten önceki turlarda da böyleydi), `pytest -q` 698 passed / 7 skipped
(bilinen `test_quickstart_database_url_wires_up_postgres` ortam
bağımlılığı hariç -- Postgres servisi olmayan bu ortamda beklenen tek
hata, önceki turlarda da aynı şekilde belgelendi).

**Önceki turların notları gözden geçirildi** (kullanıcının açık isteği:
"notlarını güncellemeyi unuttuysan önceki şeylerde felan tamamen
güncelle"): mouse-kinematics, replay-guard, captcha_playground, widget'ın
dahili hale getirilmesi, `build_captcha_router(gate=...)` çoklu-mount
düzeltmesi, `on_verified(purpose=...)` cross-gate sızıntı düzeltmesi,
Math captcha zorluk düzeltmesi, giveaway-test adaptif eskalasyon
simülasyonu, PoW sertleştirmesi, SQL rate-limit race condition + timing
side-channel güvenlik düzeltmeleri, `client_ip`/IP itibarı kancası, ve
`AdaptiveCaptchaGate`'in kendisi -- hepsi zaten bu dosyada ayrıntılı
olarak mevcuttu, eksik bulunmadı. Tek eksik, bu son turun (5 test
sayfası) kendisiydi, şimdi eklendi.

## captcha: AdaptiveCaptchaGate -- Cloudflare "Under Attack Mode" deseni (bu oturumda, devam)

Kullanıcının isteği (bir önceki turdaki IP itibarı hook'unun doğal
devamı): "IP itibarı kötüyse otomatik olarak captcha testi tetiklensin,
temizse hiç sorulmasın (rahatsız edici olmasın), geçince bir süre
kaydedilip tekrar sorulmasın; bu ayrı, isteğe bağlı bir modül olsun, dahili
captcha'ları veya reCAPTCHA/hCaptcha'yı da kullanabilsin, hiç
kullanmayabilsin de." Bunu inşa etmeden önce mimari bir tercih sunup onay
istedim (`CaptchaGate`'i büyütmek mi, yanına yeni bir sınıf mı) --
kullanıcı onayladı.

**Mimari karar**: `CaptchaGate.require_captcha` inşa anında sabit --
bunu dinamikleştirmek ya o sınıfa büyük bir koşullu-dallanma yükü
bindirir ya da mevcut, iyi test edilmiş davranışı riske atar. Bunun
yerine `AdaptiveCaptchaGate` diye YENİ, ayrı bir sınıf yazdım --
kütüphanenin her yerindeki "büyütmek yerine yanına küçük bir parça koy"
ilkesinin aynısı.

**Nasıl çalışıyor**:
- `create_verification()` hiçbir şey karar vermeden bir token basıyor.
- Linkin ilk açıldığı an (`get_info()`/`verify()`, bağlanan IP artık
  belli) -- önce `trust_store`'a bakılıyor (hesap zaten güvenilir mi),
  değilse `reputation.is_suspicious(ip)` soruluyor. Şüpheliyse
  `escalation_provider`'dan gerçek bir challenge issue edilip zorunlu
  kılınıyor; değilse hiç captcha yok.
- Karar `decision_store`'da (YENİ, ayrı bir store) kalıcı tutuluyor --
  `VerificationRequest`/`VerificationStore`'a HİÇ dokunmadım (invaziv bir
  protokol değişikliği yerine küçük, bağımsız bir store daha ekledim,
  `TrajectoryFingerprintStore`'la aynı desen).
- Başarılı doğrulamada `trust_store` varsa kullanıcı `trust_ttl` boyunca
  işaretleniyor -- gerçek Discord hesabına (`user_id`) bağlı, sahtelenebilir
  bir cihaz sinyaline değil (bilinçli tercih -- `AccountMatchCheck`'in
  kullandığı aynı güven çapası).
- `CaptchaCheck`'in `ctx.request.challenge`'a ihtiyacı var ama
  `AdaptiveDecision` ayrı store'da tutulduğu için, `verify()` içinde
  fetch edilen `VerificationRequest` nesnesine `challenge`'ı SADECE o
  çağrı için (bellekte, kalıcı olmadan) atıyorum -- bu sayede
  `VerificationStore` Protocol'ünü hiç genişletmeden çalışıyor.

**Bundled widget'a HİÇBİR dokunuş gerekmedi** -- zaten `get_info()`'nun
döndürdüğü `requires_captcha`'ya bakıp kendi UI'sını seçiyordu, adaptif
bir gate'in arkasında olduğunu bilmesi gerekmiyor. Bu, önceki tasarımın
(widget'ın sunucudan gelen bilgiye göre kendi kendine karar vermesi) ne
kadar isabetli olduğunun kanıtı.

**`build_captcha_router()`'ı hem `CaptchaGate` hem `AdaptiveCaptchaGate`
ile çalıştırmak için**: `api.py`'de yeni bir `GateLike` Protocol (yapısal
tip) tanımladım -- `adaptive.py`'ı `api.py`'ye import ETMEDEN, sadece
`get_info`/`verify` imzalarını eşleştirerek. Böylece adaptive gate'i hiç
kullanmayan biri onun bağımlılıklarını (yok zaten, ama prensip olarak)
hiç görmüyor. `CaptchaGate.get_info()`'ya da kullanılmayan bir
`client_ip` parametresi eklendim -- router'ın iki tipi de aynı şekilde
çağırabilmesi için (arayüz simetrisi).

**SQL tarafı**: `SQLAdaptiveDecisionStore`, `SQLTrustStore` -- diğer her
store'la aynı Protocol + Memory/SQL desende, kendi bağımsız tabloları
(`dwa_captcha_adaptive_decisions`, `dwa_captcha_trust`).

**`examples/captcha_gate_bot`'a gerçek bir demo eklendi** (`/join-adaptive`):
Scenario 4'teki elle-yazılmış "görünmez gate + JS zinciriyle ikinci
widget'ı açığa çıkar" deseninin (davranış-skoru tabanlı) IP-itibarı
versiyonu, ama şimdi gerçek kütüphane primitifiyle, sunucu tarafında
karar veren. `GET /api/test/block-my-ip`/`unblock-my-ip` debug
endpoint'leri kendi IP'nizi bloke/serbest bırakıp escalation'ı canlı
izlemenizi sağlıyor -- kozmetik olmadığını `TestClient` ile doğruladım:
temiz IP'de `requires_captcha: false`, blokladıktan sonra fresh bir
token'da `true` + gerçek bir Math challenge, unblock sonrası tekrar
`false`.

25 yeni test: `test_captcha_adaptive.py` (yeni dosya -- karar bir kez
verilip kalıcı kalması, temiz/şüpheli IP ayrımı, `require_account`/
`extra_checks`'in IP kararından bağımsız hâlâ zorunlu olması,
trust-store'un tekrar sormaması ve TTL dolunca sormaya dönmesi, bilinmeyen
token, idempotency, `on_verified`'ın `purpose` filtresiyle çalışması,
IP bilinmiyorsa çekimser -- cezalandırmayan -- davranış), yeni
`test_captcha_reputation.py` (`StaticBlocklistReputationChecker`'ın
IP/CIDR eşleşmesi, bozuk IP girdisinde hata fırlatmaması, canlı
block/unblock), yeni SQL store testleri, ve gerçek HTTP üzerinden bir
entegrasyon testi (`TestClient(client=(ip, port))` ile iki farklı "IP"
simüle edilip gerçek uçtan uca akış doğrulandı). Tüm suite yeşil (bilinen
Postgres ortam hatası hariç), ruff+mypy temiz.

## captcha: gerçek güvenlik araştırması -- 2 gerçek bug + IP itibarı hook'u (bu oturumda, devam)

Kullanıcının isteği üç parçalıydı: (1) captcha'ya kapsamlı bir araştırma
yap, hem internette hem kodda, (2) hata olmaması gereken yerleri tespit
edip düzelt, (3) "kendi skor sistemlerini (örn. IP itibarı) ekleyebilirler
mi" sorusuna cevap ver.

**İnternet araştırması** (WebSearch, iki ayrı sorgu): modern anti-bot
yığınlarının (Cloudflare/Akamai/DataDome/PerimeterX) TLS parmak izi, IP
itibarı, header sırası, JS çalıştırma, mouse hareketi, cookie, zamanlama
gibi düzinelerce sinyali birlikte değerlendirdiğini; davranışsal
biyometriğin tek başına reCAPTCHA v3/Turnstile'dan daha iyi performans
gösterdiğini ama 2026'da AI-tabanlı botların davranışsal telemetriyi
taklit etmeye başladığını (bizim "replay saldırısı" bulgumuzla aynı
kategori); ve ÖNEMLİSİ, captcha implementasyonlarında yaygın bir
güvenlik açığı sınıfının **"race condition ile rate-limit/deneme-sayısı
atlatma"** olduğunu (birden fazla makale/writeup bunu belgeliyor)
öğrendim. Bu son bulgu doğrudan kod incelemesine yön verdi ve gerçek bir
bug buldurdu.

**Bug 1 -- `SQLCaptchaStore.increment_attempts` race condition (ciddi)**:
Eski kod `row = await db.get(...); row.attempts += 1; await db.commit()`
şeklindeydi -- SELECT-sonra-mutate-sonra-commit, klasik "lost update"
deseni. Eşzamanlı yanlış tahminler aynı ön-artış sayısını okuyup
birbirinin artışını kaybedebilir. **Bunu varsaymadım, gerçekten test
ettim**: izole bir script'te eski kodu 20 eşzamanlı `increment_attempts`
çağrısına karşı çalıştırdım -- nihai sayı 1 çıktı (20 değil). Yani bir
saldırgan aynı challenge_id'ye onlarca paralel tahmin göndererek
`max_attempts` sınırını fiilen etkisiz kılabilirdi -- tam olarak
araştırmada okuduğum "captcha rate-limit'i race condition ile atlatma"
zafiyet sınıfının kendisi. Düzeltme: `sqlalchemy.update()` ile tek atomik
`UPDATE ... SET attempts = attempts + 1` (MySQL `RETURNING`
desteklemediği için ayrı bir read-back ile, ama artışın kendisi artık
bölünemez tek adım). `_shared.check_pending_challenge` da "kontrol et,
başarısızsa artır" yerine "önce atomik artır, sonra kontrol et" sırasına
değiştirildi -- read-then-write aralığı tamamen kapandı. Düzeltilmiş
kodu aynı 20-eşzamanlı testte çalıştırıp tam 20 aldığımı doğruladım.

**Bug 2 -- zamanlamaya duyarlı cevap karşılaştırması (düşük önem, bedava
düzeltme)**: `verify_pending_challenge` düz `==` kullanıyordu. Küçük
cevap uzayı + zaten var olan deneme sınırı yüzünden pratik risk düşük,
ama `hmac.compare_digest` bedava ve doğru olan şey, değiştirdim.

**IP itibarı sorusu -- dürüst cevap: ŞU ANA KADAR HAYIR, artık EVET**.
Kod incelemesi gösterdi ki `VerificationContext`'in `signals` alanı
tamamen istemci JS'inin gönderdiği bir çanta -- oraya bir IP koymanın
hiçbir anlamı yok (istemci "ben şu IP'denim" diyebilir, sahte). Gerçek
bağlantı IP'si (`Request.client.host`) hiçbir check'e ULAŞMIYORDU bile --
kullanıcı IP itibarı eklemek istese bile elinde çalışacak bir malzeme
yoktu. Bunu gerçek bir mimari eksiklik olarak ele alıp düzelttim:
`VerificationContext.client_ip` (yeni alan) + `CaptchaGate.verify(...,
client_ip=)` (yeni parametre) + `build_captcha_router()`'ın
`Request.client.host`'u otomatik okuyup geçmesi. Kütüphane kendi IP
itibar kaynağını sunmuyor (bilinçli -- hangi servise güveneceğinize dair
görüşümüz yok) ama artık gerçek, sahtelenemez IP `extra_checks`'e
ulaşıyor. `docs/OZELLIKLER.md`'ye somut bir `PredicateCheck` örneği
eklendi (blocklist ya da kendi itibar servisinizi çağırma).

11 yeni test: yeni `test_captcha_shared.py` dosyası (check_pending_challenge/
verify_pending_challenge'ı doğrudan, izole test ediyor -- doğru/yanlış
cevap, tam-limit-sonra-kilitlenme, süre dolması, bilinmeyen id, limit
aşılınca verifier'ın hiç çağrılmadığı, normalize, eşzamanlı yanlış
tahminlerin limiti aşamadığı), SQL store'un atomiklik testi (20 eşzamanlı
artış = tam 20), IP itibarı hook'unun hem gate seviyesinde hem gerçek
HTTP isteği üzerinden çalıştığını kanıtlayan 2 test. Mevcut tüm
attempt-limit testleri (ör. "3 yanlış sonra doğru cevap bile reddedilir")
davranış değişmeden geçti. Tüm suite yeşil (bilinen Postgres hatası
hariç), ruff+mypy temiz.

## captcha: "insan-benzeri sinyaller geçti, kötü değil mi" sorusu -- demo'nun gerçek eksiğini buldu (bu oturumda, devam)

Kullanıcının sorusu birebir: "Bu kötü değil mi insan benzeri sinayelleri
simüle ettin ve geçti normalde hiçbir şekilde geçmemesi gerekmez mi?"

**Cevap, iki parçalı**: (1) Hayır, bu yeni bir açık değil -- davranış
skorunun en baştan beri (bu oturumun ilk fazlarından itibaren)
belgelenen, kasıtlı sınırı bu. `scoring.py`'nin docstring'i açıkça
"kuralları bilen kararlı bir bot insan-gibi puanlanan sinyaller
gönderebilir" diyor. Ben o testte `good_signals`'ı elle, kontrol
kurallarını bilerek yazdım (`webdriver:false, pointer_moves:20, ...`) --
bu tam olarak "sahtelenebilirlik" kavramının canlı kanıtı, davranış
sinyalleri istemci tarafından gönderiliyor, istemci kim olursa olsun.
(2) AMA kullanıcı gerçek bir eksiği de yakaladı: `/giveaway-test`'in
"uyarlanabilir" gate'i (`giveaway_test_invisible_gate`)
`require_captcha=False` ile kurulmuştu -- yani SADECE hesap-bağlama +
davranış skoru vardı, diğer gate'lerdeki (`giveaway_gate`/`appeal_gate`)
gerçek PoW maliyeti hiç yoktu. Bu, demo'nun (kütüphanenin değil) gerçek
bir zayıflığıydı -- "invisible" derken PoW'suz bırakmışım.

**Düzeltme**: `giveaway_test_invisible_gate`'e `ProofOfWorkProvider`
eklendi (`require_captcha=False` yerine). "Görünmez" olmak, maliyetsiz
olmak demek değil -- sadece görünür bir bulmaca olmaması demek (tıpkı
`giveaway_gate`/`appeal_gate`'in zaten yaptığı gibi). Sayfadaki açıklama
metni de güncellendi: davranış sinyallerinin tek başına sahtelenebilir
olduğunu, PoW'un sahtelenemeyen kısım olduğunu açıkça yazıyor artık.

**Yeniden doğrulama**: bot-benzeri sinyaller hâlâ anında reddediliyor
(PoW'a gerek kalmadan, `no-webdriver` check'inde). Elle hazırlanmış
insan-benzeri sinyaller AMA PoW çözülmemişse artık GEÇMİYOR --
`"captcha"` check'inde reddediliyor. Sadece insan-benzeri sinyaller +
gerçekten çözülmüş bir PoW nonce'u birlikte geçiyor
(`passed=['account','no-webdriver','behavior-score','no-repeated-movement','captcha']`).
Yani kullanıcının sorusu gerçek bir konfigürasyon zayıflığı buldu, sadece
teorik bir soru sormadı -- bu turda düzeltildi.

Kütüphaneye dokunulmadı, sadece örnek dosyası (`examples/captcha_gate_bot/main.py`)
ve doküman metinleri değişti. Tüm suite yeşil, ruff+mypy temiz.

## captcha: gerçek çekiliş simülasyonu (adaptive escalation) + math zorluk bug'ı (bu oturumda, devam)

Kullanıcının geri bildirimi iki parçaydı: "16×19 sordu ciddi misin"
(math captcha'nın zorluğu hakkında haklı bir şikayet) ve "normal widgetli
testi kastetmiştim" (bir önceki 3'lü-karşılaştırma testi yanlış
anlaşılmıştı) -- asıl istediği: gerçek bir çekiliş botu simülasyonu,
kanalda buton, ephemeral+DM akışı, giriş sonrası captcha, 2 widget (biri
şüpheli bulup çizgi-çizme'ye yükselen uyarlanabilir bir akış, diğeri sade
orijinal).

**Math zorluk bug'ı (gerçek, basit)**: `MathCaptchaProvider`'ın
docstring'i "1-20 arası, insan için kolay" diyordu ama `*` operatörü de
aynı 1-20 aralığını kullanıyordu -- `random.randint(1,20)` iki kere
çekilip çarpılınca `16*19=304` gibi gerçekte hiç kolay olmayan bir soru
çıkabiliyordu. Docstring'in iddiası ile gerçek davranış arasında
uyuşmazlık vardı. Düzeltme: `operator == "*"` ise operandlar 1-9 aralığına
(en fazla 9×9=81) sınırlandı, toplama/çıkarma hâlâ 1-20. `monkeypatch` ile
operatörü zorla `*` yapıp 50 deneme boyunca cevabın hep ≤81 kaldığını
doğrulayan bir test eklendi.

**Gerçek çekiliş simülasyonu** (`examples/captcha_gate_bot`, `/giveaway-test`):
- Kanala embed + "Katıl" butonlu (`discord.ui.View`, `custom_id` ile) bir
  mesaj atıyor -- gerçek bir çekiliş botu postu gibi.
- Butona tıklayınca: `interaction.response.send_message(..., ephemeral=True)`
  (kanaldaki herkesten gizli) + `interaction.user.send(...)` (DM'den
  link) -- kullanıcının "görünmez mesajı ve dmden linki" isteğinin birebir
  karşılığı.
- Verify sayfası `get_current_user_optional` dependency'sini kullanıp
  sunucu tarafında giriş kontrolü yapıyor -- giriş yoksa SADECE giriş
  linki gösteriliyor, hiçbir captcha/widget render edilmiyor. Giriş
  sonrası (kullanıcının "girdikten sonra capctha ekranı açılsın" isteğinin
  birebir karşılığı) 2 widget'lı sayfa açılıyor.
- **Uyarlanabilir widget**: `require_captcha=False` bir gate (sadece
  davranış skoru) + `require_captcha=True` bir Path-Trace gate'i --
  ikisi ayrı `CaptchaGate` nesnesi. Sayfanın kendi JS'i önce görünmez
  olanı dener (`data-callback` -- widget script'inin TEK bir global
  callback'i var, `result.token`'a bakarak hangi widget'ın sonucu olduğunu
  ayırt ediyorum, bu önemli bir detaydı: `data-callback` widget div'inde
  değil `<script>` etiketinde okunuyor). Başarısız olursa
  `window.dwaCaptchaWidgetInit()` çağrılıp ikinci (çizgi-takip) widget
  DOM'a ekleniyor. `CaptchaGate`'in kendisinde escalation YOK -- bu iki
  ayrı gate'in sayfa JS'iyle birleştirilmesi, kütüphanenin "kendi
  kompozisyonunu kur" felsefesinin doğal bir uzantısı, çekirdeğe yeni bir
  özellik eklemedim.
- **Orijinal widget**: sade, tek başına (artık düzeltilmiş zorlukta)
  Math captcha.

**Doğrulama**: Gerçek bir OAuth round-trip tarayıcı gerektirdiğinden
(quickstart SQL session store kullanıyor, sahte respx mock'u bu oturumda
kurmadım), escalation MANTIĞINI gate'lere doğrudan Python seviyesinde
karşı test ettim: bot-benzeri sinyaller (`webdriver=true`, `pointer_moves=0`,
`interaction_ms=1`) görünmez gate'i gerçekten reddetti; insan-benzeri
sinyaller (gerçekçi dil/saat dilimi/tıklama-ofseti/süre) geçti; çizgi-takip
fallback'i gerçek bir yoğun-örneklenmiş çizilmiş yolla gerçekten
doğrulandı. Ayrıca `TestClient` ile giriş yapmadan sayfanın hiçbir
`dwa-captcha-widget` içermediğini, sadece giriş linkini gösterdiğini
doğruladım. Tüm suite yeşil (bilinen Postgres hatası hariç), ruff+mypy
temiz.

## captcha: on_verified() çapraz-gate sızıntısı -- ikinci gerçek bug bu oturumda (devam)

Kullanıcı bir önceki turda eklediğim çoklu-gate desteğini ("bununla da
test oluştur") gerçekten test etmemi istedi: web + bot, 3 captcha türü
alt alta (çizgi-takip / başarılı dönse de robot doğrulaması isteyen
güvenli mod / orijinal sade), test komutu, DM'e buton gönderen mesaj,
2 katılımcı ile sağlam bir test. Talimat oldukça yazım hatalı/dağınıktı
ama niyeti netti: gerçek bir uçtan uca senaryoyla kanıtla.

**İkinci gerçek bug bu turda bulundu** (birincisi önceki turdaki tek-gate
sınırıydı): `examples/captcha_gate_bot`'a 3 yeni test gate'i ekleyip
2 sahte kullanıcıyla (`111`, `222`) her birini gerçekten doğrulattığımda
katılımcı sayısı 2 değil **6** çıktı, ve ayrıca çekiliş gate'inin
`on_verified` handler'ı (`bot.fetch_user` çağıran) test gate'lerinin
doğrulamaları için de tetiklenip hata fırlattı. Sebep: bu örnekteki TÜM
gate'ler (çekiliş, itiraz, 3 test gate'i -- 5 tane) aynı `Transport`'u
paylaşıyor (`app.state.discord_webapi_transport`, `quickstart()`'tan),
ve `captcha_verified` HEPSİ için aynı, tek bir event type. `on_verified()`
hiçbir filtre yapmıyordu -- bir gate'e abone olmak, o transport üzerindeki
DİĞER TÜM gate'lerin doğrulamalarını da alıyordu. Bu, önceki turda
playground'da bir kez rastladığım "tek global gate" sınırından farklı,
ondan bağımsız ikinci bir gerçek tuzak -- bu sefer `build_captcha_router`
değil, `CaptchaGate.on_verified()`'ın kendisinde.

**Düzeltme** (`discord_webapi/captcha/gate.py`): `on_verified(handler, *,
purpose: str | None = None)` -- `purpose` verilirse event'in
`payload.purpose`'u eşleşmiyorsa handler hiç çağrılmıyor. `purpose=None`
(varsayılan) eski davranışın birebir aynısı -- geriye dönük tam uyumlu,
mevcut testler değişmeden geçti. Docstring'e büyük harflerle "birden
fazla gate aynı transport'ta ise bunu mutlaka kullan" uyarısı eklendi.
2 yeni birim testi: filtresiz eski davranışın (çapraz sızıntı dahil)
hâlâ çalıştığını, `purpose=` ile sızıntının önlendiğini kanıtlıyor.

**`examples/captcha_gate_bot`'a eklenenler**:
- 3 yeni demo gate + `/test-path-trace`, `/test-safety`, `/test-original`
  prefix'leri: Path-Trace (görünmez katman yok), "safety mode" (Math
  captcha VE davranış skoru ikisi de şart -- davranış skoru insan-gibi
  olsa bile yanlış Math cevabı hâlâ `"captcha"` check'inde reddediliyor,
  gerçekten test ettim), "orijinal" (sade Math). Kullanıcının "başarılı
  dönse de robot doğrulaması isteyecek" tarifinin birebir karşılığı.
- `/test-join`: DM'e `discord.ui.Button` ("Katıl") -- tıklanınca 3 token
  mint edilip tek bir `/test-widgets` linki dönüyor (kullanıcının "test
  butonlu mesaj, butona tıkla dmden" isteğinin karşılığı).
- `/test-widgets`: üç widget'ı alt alta gösteren sayfa.
- `/test-participants`: katılımcı listesi/sayısı (kullanıcının "katılanlar
  2 olacak" isteğinin doğrulanabilir karşılığı).
- Her üç test gate'i ayrı `purpose` string'i kullanıyor
  (`test_widgets_path_trace`/`_safety`/`_original`) -- yeni `purpose=`
  filtresinin doğru çalışması için şart, aksi halde üçü de aynı etikette
  toplanırdı.

**Doğrulama**: `TestClient` ile 2 sahte kullanıcıyı (`111`, `222`) üç test
gate'inin her birinden gerçekten geçirdim. Düzeltmeden ÖNCE katılımcı
sayısı 6 (yanlış, çapraz sızıntı), düzeltmeden SONRA tam olarak 2 (doğru,
`{("test_widgets_original", 111), ("test_widgets_original", 222)}`).
Path-trace gerçek yoğun bir trace ile geçti; safety-mode'da davranış
sinyalleri kusursuzca insan-gibi tutulup Math cevabı bilerek yanlış
gönderildi -- yine de reddedildi, spesifik olarak `"captcha"` check'inde
(davranış check'inde değil) -- yani "ikisi de şart, biri diğerinin yerine
geçmiyor" iddiası gerçekten doğrulandı, varsayılmadı.

2 yeni test (`test_captcha_gate.py`), tüm suite yeşil (bilinen Postgres
hatası hariç), ruff+mypy temiz.

## captcha: "komutlarda gerçekten çalışıyor mu" sorusu gerçek bir mimari sınır ortaya çıkardı (bu oturumda)

Kullanıcının sorusu birebir: "Peki komutlsrda şeylerde çalışıyor mu
dediimya örnek seneryo verdim giveway botunda çekilişe katılmak için
tıklarlar robot doğrulaması ister özel url giriş yapmalı veya komutlsrda
mesela çok ban attı capctha doğrulaması devam için seneryo bunlar
oluyormu şuan". Yani: playground'da test ettiğim şeyler (sahte
`user_id=0` ile) gerçek bot komutlarında da çalışıyor mu, özellikle iki
somut senaryo -- çekiliş botu `/join` ve "çok ban yemiş kullanıcı devam
etmeden önce doğrulasın" gibi bir escalation-gate senaryosu.

**Dürüst yaklaşım**: varsayımla "evet çalışıyor" demek yerine gerçekten
inşa etmeye çalıştım -- ve bu, önceden fark edilmemiş gerçek bir mimari
sınırı ortaya çıkardı: `build_captcha_router()`'ın `/api/captcha/gate/
{token}` endpoint'i TEK bir `app.state.discord_webapi_captcha_gate`
okuyor. Kullanıcının sorduğu senaryo tam olarak İKİ ayrı gate amacı
gerektiriyor (çekiliş gate'i + itiraz gate'i) -- bunlar aynı anda mount
edilemiyordu, ikincisi birincisinin üstüne yazardı. Bu, playground'da
zaten bir kez karşılaştığım "tek global gate" sınırının (o zaman
app.state'i token-mint anında değiştiren bir hack ile geçiştirmiştim,
sadece tek-operatörlü yerel demo için uygun olduğunu not düşerek) gerçek
bir production senaryosunda tekrar karşıma çıkması -- bu sefer hack kabul
edilemezdi, gerçek bir kütüphane düzeltmesi gerekiyordu.

**Yapılan düzeltme** (`discord_webapi/captcha/api.py`):
- `build_captcha_router(*, gate: CaptchaGate | None = None, ...)` --
  `gate` verilirse app.state yerine doğrudan o gate'e bağlanıyor (closure
  üzerinden), `gate=None` (varsayılan) eski davranışın birebir aynısı
  (geriye dönük tam uyumlu, mevcut tüm testler değişmeden geçti). Artık
  router birden fazla kez, her biri kendi `prefix`'i ve kendi `gate`'iyle
  mount edilebiliyor:
  ```python
  app.include_router(build_captcha_router(gate=giveaway_gate), prefix="/giveaway")
  app.include_router(build_captcha_router(gate=appeal_gate), prefix="/appeal")
  ```
- `widget.js`'e `data-api-base` özniteliği eklendi -- widget'ın hangi
  prefix altındaki gate'e konuşacağını bilmesi için (`this.apiBase + '/api/captcha/gate/' + token`).
- 4 yeni entegrasyon testi: iki gate'in çakışmadan aynı anda mount
  edilmesi, bir gate'in token'ının DİĞER gate'in prefix'i altında 404
  dönmesi (gerçek izolasyon kanıtı), `gate=`'nin app.state'e göre önceliği.

**`examples/captcha_gate_bot/`** (yeni, gerçek bir bot): kullanıcının
sorduğu iki senaryoyu birebir, gerçek bir discord.py `commands.Bot`'una
ve gerçek Discord OAuth hesap-bağlamasına (`require_account=True`) karşı
kuruyor -- playground'un sahte `user_id=0`'ının aksine:
1. `/join giveaway_name:...` -- `giveaway_gate.create_verification()`,
   DM ile link, web tarafında görünmez PoW + davranış skoru + gerçek
   hesap eşleşmesi, `on_verified` ile "katıldın!" DM'i.
2. `/simulate-ban @kullanıcı` (demo-only sayaç) + `/appeal reason:...` --
   `BAN_THRESHOLD`'u geçen kullanıcı, `appeal_gate` üzerinden AYRICA
   doğrulanmadan komutu kullanamıyor; bir kez doğrulanınca
   `_appeal_verified_users` setinde kalıyor (gerçek bir bot bunu
   kalıcı tutar, in-memory set değil).

Her iki gate `/giveaway` ve `/appeal` prefix'leri altında ayrı ayrı mount
ediliyor, widget'ların `data-api-base`'i buna göre ayarlanıyor. Bir de
basit bir `/verify/{purpose}/{token}` HTML sayfası (Discord login linki +
widget) -- gerçek `login_success_redirect`'in sabit olduğunu (dinamik
`redirect_uri` query param'ı YOK, `DiscordAuth`'un gerçek API'sinde böyle
bir şey yok) keşfedip sayfayı ona göre düzelttim (giriş yap, aynı linke
geri dön, widget'a tıkla -- tek adımlık "redirect_uri" varsayımım yanlış
çıkmıştı, koda bakıp düzelttim).

**Doğrulama (gerçek Discord bağlantısı olmadan)**: modülü gerçek env
değişkenleriyle import edip `FastAPI` route listesinde her iki prefix'in
de doğru göründüğünü doğruladım; `TestClient` ile: `/giveaway` prefix'i
altında mint edilen bir token'ın `/appeal` prefix'inde 404 döndüğünü (ve
tersi) -- yani gerçek izolasyon; gerçek bir PoW challenge'ının issue
edildiğini; `require_account=True` olduğu için oturum açmadan verify
çağrısının doğru şekilde `failed_check="account"` döndürdüğünü; widget
script'inin servis edildiğini kontrol ettim. Gateway bağlantısı gerektiren
kısım (komutların gerçekten Discord'dan tetiklenmesi) bu repodaki her
örnek bot için zaten var olan "fiziksel test" adımı olarak kaldı --
bunu açıkça söyledim, "tamamen test edildi" gibi göstermedim.

## captcha: hazır, dahili widget -- ilk kez UI kütüphanenin kendisine giriyor (bu oturumda)

Kullanıcının isteği birebir: playground'daki elle-yazılmış doğrulama
kutusu "aşırı yapay, 2010lardan fırlama" duruyordu (haklıydı -- düz
dikdörtgen, kalın gri kenarlık, metin karakteriyle tik/çarpı). Ama asıl
önemli kısım ikinciydi: "birde dahili değil mi bu capctha dikdörtgenin
uisi dahili yapalım ... hem alt yapıyı verelim hemde hızlı kullanmak
isterler diye hazır direk kullanım için seçilen özellikler ile ui sinide
verek". Yani: bu artık playground'a özel bir demo değil, kütüphanenin
kendisinin sunduğu bir bileşen olmalı.

**Önemli karar/gerginlik notu**: proje planında ("encapsulated-nibbling-
pnueli.md") şu kayıtlı: "Dashboard UI genişletmesi: reddedildi (kullanıcı
kararı, kalıcı)" -- kütüphane bilinçli olarak "sadece backend, frontend'i
herkes kendi yazar" ilkesini benimsemişti. Bu yeni istek görünüşte bunu
çiğniyor gibi dursa da, aslında AYNI ilkenin devamı: `discord_webapi.web.
dashboard.py`'nin zaten yaptığı şeyin (bundled, opt-in, minimal bir HTML
sayfası -- asla zorunlu, asla `install()`'a otomatik bağlı) captcha
alanındaki karşılığı. Reddedilen şey "kapsamlı bir admin paneli/tam bir
ürün UI'sı" idi, bu ise dar kapsamlı, tek-amaçlı, opsiyonel bir widget --
aynı "bundled dashboard" presedansına uyuyor, onu genişletmiyor. Yine de
bu gerilimi burada açıkça not düşüyorum ki gelecekte biri "UI eklemeyiz"
kararını hatırlayıp bu widget'ı çelişki sanmasın.

**Yapılan** (`discord_webapi/captcha/widget.py` + `widget.js`, yeni
modül, `discord_webapi/web/dashboard.py`'nin `Path(__file__).parent /
"....html"` okuma deseniyle birebir aynı):
- `build_captcha_widget_router(mount_path=...)`: widget script'ini
  `GET /static/discord-webapi-captcha-widget.js` (özelleştirilebilir yol)
  üzerinden `application/javascript` olarak servis ediyor.
- `widget.js`: `.dwa-captcha-widget` class'lı her `<div data-token="...">`
  için bir `CaptchaWidget` instance'ı kuruyor. Akış: `GET /api/captcha/
  gate/{token}` ile challenge bilgisini çekiyor, `challenge.kind`'a göre
  kendi UI'sını seçiyor (captcha yok -> sade checkbox; math/text ->
  görsel+input+kendi submit butonu; pow -> tamamen otomatik arka plan
  hashcash araması, bitince checkbox aktifleşiyor; path-trace -> gömülü
  canvas; recaptcha/hcaptcha -> onların script'ini enjekte edip kendi
  submit butonuyla token okuyor). Path-trace geometrisi
  (`_dist_point_to_segment`/`_dist_point_to_polyline`) sunucudakiyle
  birebir aynı mantıkla JS'e taşındı (playground'da zaten yazılmıştı,
  buraya genelleştirilip taşındı). Mouse/dokunma sinyallerini sayfa
  yüklendiği andan itibaren kendisi topluyor (playground'daki
  `currentSignals()` deseninin genelleştirilmiş hali).
- **Diagnostics tasarımı**: widget host sayfasının bir `#log` div'i
  olduğunu VARSAYMIYOR (playground'a özel bir bağımlılık kurmamak için)
  -- bunun yerine her adımda `document`'a bir `dwa-captcha-widget-log`
  CustomEvent'i (`{token, message, ok, detail}`) yayınlıyor. Herhangi bir
  host sayfası isterse dinler, istemezse görmezden gelir. `data-callback`
  özniteliği (reCAPTCHA/hCaptcha'nın kendi `data-callback` desenine
  paralel) doğrulama bitince çağrılacak global fonksiyonun adını taşıyor.
  `window.dwaCaptchaWidgetInit` dışa açıldı -- dinamik olarak sonradan
  eklenen widget div'lerini (örn. yeni bir token alındığında) sayfa
  yenilenmeden tekrar taratmak için.
- **Modernizasyon**: yuvarlatılmış köşeler (12px), ince/yumuşak gölge,
  hover'da hafif yükselme, SVG path ile çizilen tik/çarpı (opacity+scale
  geçişli), conic-gradient tabanlı yumuşak dönen spinner (kalın çizgili
  eski spinner yerine), sistem font stack'i, `prefers-color-scheme` ile
  koyu tema desteği. Playwright ile ekran görüntüsü alıp göz kontrolü
  yaptım -- eski "kalın gri kenarlıklı düz kutu" görünümü tamamen gitti.

**`examples/captcha_playground`'a dogfooding**: eski elle-yazılmış widget
IIFE'si (yaklaşık 100 satır) tamamen silindi, yerine gerçek
`<div class="dwa-captcha-widget">` + bir `CaptchaGate` konfigürasyonu
seçme dropdown'u (`none`/`math`/`text`/`pow`/`path-trace`/varsa
`recaptcha`/`hcaptcha`) geldi. Playground artık widget'ın KENDİ
`dwa-captcha-widget-log` event'lerini dinleyip mevcut log paneline
yazıyor -- playground tarafında widget mantığının hiçbir kopyası yok.

**Bulunan gerçek bug**: `main.py`'de her kind için ayrı bir `CaptchaGate`
kurdum ama `build_captcha_router()`'ın `/api/captcha/gate/{token}`
endpoint'i TEK bir `app.state.discord_webapi_captcha_gate`'i okuyor
(gerçek bir deploy'da doğru tasarım -- bir entegrasyon, bir gate). Onu
hiç atamamıştım, widget her zaman 404/hata alıyordu. Bunu Playwright ile
gerçek bir tarayıcıda test ederken yakaladım (log'da "Doğrulama linki
geçersiz veya süresi dolmuş" ve ardından "No CaptchaGate configured"
hatası çıktı). Düzeltme: playground'un token-mint endpoint'i artık token
verirken ilgili gate'i `app.state`'e de atıyor -- yalnızca tek-operatörlü
yerel demo için uygun (gerçek çoklu-kullanıcılı bir deploy'da tek bir
gate seçilmeli, koda bunu açıkça yazdım).

**Uçtan uca doğrulama** (Playwright, gerçek headless Chromium,
`/opt/pw-browsers/chromium-1194`): "none" gate'inde davranış katmanı
çalıştı ve Playwright'ın kendi `navigator.webdriver=true` izini doğru
şekilde yakalayıp reddetti; Math gate'inde görsel+input+yanlış-cevap
submit akışı çöküşsüz tamamlandı (`pageerror` hiç görülmedi); PoW
gate'inde arka plan hashcash araması gerçekten çalışıp birkaç saniye
içinde checkbox'ı otomatik aktif etti; Path-trace gate'inde canvas
doğru boyutlarda render edildi. Ekran görüntüsüyle görsel kontrol de
yapıldı.

3 yeni test (widget script'in servis edilmesi, özel mount path, gerçek
endpoint'lere referans kontrolü). Tüm suite yeşil (bilinen Postgres
hatası hariç), ruff+mypy temiz (119 dosya, yeni `widget.py` dahil).

## captcha: homing-correction'ı yine de ekle + tıklanabilir test sitesi (bu oturumda)

Kullanıcının isteği: önceki turda test edip "bağımsız değer katmıyor,
eklemiyorum" dediğim homing-correction sezgiselini yine de ekleyeyim,
kendisi test etsin ("belki yanlış anlamışsındır"); ayrıca tüm captcha
sistemini (görsel + PoW + path-trace + davranış katmanı + replay-tespiti)
kendi tarayıcısından tıklayarak deneyebileceği bir sayfa isteyip
sonuçları PASS/FAIL loglayıp bana geri vereceğini söyledi.

**Homing-correction, dürüstlüğü koruyarak eklendi**: önceki bulgu (kendi
insan-örneğimde bile sıfır overshoot çıkması) hâlâ geçerli, o yüzden
sezgiseli **asla ceza vermeyecek** şekilde tasarladım -- overshoot
bulursa `1.0`, bulamazsa `0.0` değil **`None` (çekimser)**. Yani bu artık
"varsa bonus kanıt, yoksa nötr" mantığında; önceki turda tespit ettiğim
yanlış-pozitif riski (düzgün, overshoot'suz gerçek insan hareketlerini
cezalandırma) ortadan kalkıyor. Test edip doğruladım: gerçek overshoot'lu
elle kurulmuş bir trajectory `1.0` veriyor, önceki "düzgün insan"
örneğim ve lineer bot örneğim ikisi de `None` (çekimser) -- ikisi de
overshoot içermiyor, ikisi de haksız cezalandırılmıyor. `default_behavior_heuristics()`'e
ağırlık 1.0 (düşük -- durumsal bir sinyal) ile eklendi.

**`examples/captcha_playground/`** (yeni): Discord bot'u/OAuth'u
GEREKTİRMEYEN, tek sayfalık, gerçekten çalışan bir test sitesi:
- `main.py`: `MathCaptchaProvider`/`TextCaptchaProvider`/`ProofOfWorkProvider`/
  `PathTraceProvider`'ı `build_captcha_router()` üzerinden sunuyor;
  isteğe bağlı `RECAPTCHA_SITE_KEY`/`HCAPTCHA_SITE_KEY` env'leri varsa
  onları da ekliyor. Davranış katmanı için `CaptchaGate` kurmadan, direkt
  `VerificationCheck.run()` çağıran hafif bir `/api/playground/behavior-check`
  endpoint'i -- `reject_webdriver`, `require_min_interaction_ms`,
  `SignalScoreCheck` (tüm sezgiseller dahil mouse-kinematiği +
  homing-correction), `RepeatedMovementCheck` sırayla çalışıp her birinin
  PASS/FAIL + detay'ı ayrı ayrı dönüyor.
- `playground.html`: sayfa yüklendiği andan itibaren gerçek
  `pointermove`/`pointerdown` olaylarından `mouse_trajectory` topluyor;
  PoW için gerçek hashcash aramasını tarayıcının kendi
  `crypto.subtle.digest`'ıyla yapıyor (mock değil, gerçek iş); path-trace
  için gerçek bir `<canvas>` üzerinde çizilen yolu yakalıyor; "aynı
  hareketi tekrar gönder" butonu `RepeatedMovementCheck`'in ikinci
  gönderimde FAIL'e dönmesini canlı gösteriyor. Her sonuç ekrandaki log
  paneline yazılıyor + "logu kopyala" butonu var.

**Elle uçtan uca doğrulama yaptım** (kullanıcıya vermeden önce): sunucuyu
gerçekten ayağa kaldırıp (`uvicorn`) curl/Python ile her endpoint'i tek
tek denedim -- math doğru/yanlış cevap, gerçek PoW nonce araması (Python
tarafında JS'in yapacağı aynı hashcash aramasını taklit ederek) ve
doğrulama, path-trace geçerli/geçersiz iz, ve en önemlisi
behavior-check + replay: aynı `mouse_trajectory` ikinci kez
gönderildiğinde `no-repeated-movement` check'i gerçekten FAIL'e döndü,
ilkinde PASS'ti. Hepsi beklenen sonucu verdi, sunucu kapatıldı
(kullanıcı kendi ortamında çalıştıracak).

3 yeni test (homing-correction: gerçek overshoot'u puanlıyor, düzgün
insan hareketinde/lineer bot hareketinde çekimser kalıyor -- ikisinde de
ceza yok). Tüm suite yeşil (bilinen Postgres ortam hatası hariç),
ruff+mypy temiz (`examples/captcha_playground` dahil).

## captcha: replay-tespiti (RepeatedMovementCheck) + granülerlik netliği (bu oturumda)

Kullanıcının önceki mesajdaki ChatGPT önerilerine verdiğim cevaptan sonra
iki yeni istek geldi: (1) her algoritmanın/özelliğin tek tek açılıp
kapatılabilir olmasını istiyor -- "bu algoritmayı istemiyorum, şunu
istiyorum ya da zaten 3. taraf hizmet kullanacağım" senaryosu; bunun
zaten mevcut olduğunu doğrulayıp somut örneklerle dokümante ettim
(`heuristics=[...]` listesinden istediğinizi çıkarın/ekleyin,
`CaptchaProvider` Protocol'üyle kendi/3.taraf sağlayıcınızı hiç bizim
kodumuza dokunmadan kullanın). (2) Daha önemlisi: "aynı hareket hiç
değişmeden tekrarlanıyorsa, telefonda hep aynı piksele dokunuyorsa,
mouse hiç hareket etmeden captcha yüklenirken bile orada beliriyorsa,
başka cihaz/IP'lerde de aynı şeyi tekrarlıyorsa şüpheli değil mi" diye
sordu.

**Bu ikinci soru gerçekten önemli bir gedik yakalamış**: önceki turda
"tek istekli kinematik analiz replay saldırısını yakalayamaz, bu yapısal
bir sınır" dedim -- ve bu hâlâ doğru, AMA kullanıcının önerdiği şey tek
istekli değil, **geçmişe bakan (cross-request)** bir kontrol. Aynı kaydı
tekrar tekrar oynatan bir bot -- hatta farklı hesap/cihaz/IP'ler
altında -- her seferinde aynı şekli bırakır. Bu, tek isteğin kinematik
analizinin göremediği ama bir *tarih*in görebileceği tam olarak o şey.
Yani kullanıcı, önceki dürüst sınırlamamın "aşılamaz" kısmına değil,
"tek istekli analiz" kısmına itiraz etmiş oldu -- ve haklı, cross-request
katmanı gerçekten ek koruma sağlıyor (daha önce "aggregate/cross-request
anomaly detection" olarak bahsettiğim ama uygulamadığım katmanın somut
bir versiyonu).

**Yapılan** (`discord_webapi/captcha/replay_guard.py`, yeni modül):
- `fingerprint_trajectory(trajectory)`: `mouse_trajectory`'den kaba,
  **öteleme-bağımsız** bir parmak izi çıkarıyor -- ilk örneğe göre
  normalize edilmiş `(dx, dy, dt)` deltalarını kuantize edip (6px/25ms
  grid) hash'liyor. Öteleme-bağımsız olması kritik: aynı kayıt farklı bir
  widget konumuna/zamanına karşı replay edilse bile parmak izi aynı kalır
  (test'le doğrulandı). Kaba kuantizasyon sayesinde iki *farklı* gerçek
  insan hareketi neredeyse hiç çakışmıyor (doğal jitter yeterince farklı
  kalıyor), ama tam replay her zaman çakışıyor.
- `TrajectoryFingerprintStore` Protocol + `MemoryTrajectoryFingerprintStore`
  (varsayılan, tek process) + `SQLTrajectoryFingerprintStore` (çoklu web
  replica'sı için -- diğer store'larla aynı desende, `captcha/sql.py`'ye
  eklendi, kendi tablosu `dwa_captcha_trajectory_fingerprints`).
- `RepeatedMovementCheck` (`VerificationCheck`): parmak izi yakın zamanda
  görülmüşse reddediyor. **Bilerek global** -- kullanıcı/IP/oturum bazlı
  DEĞİL, çünkü asıl yakalamak istediği "aynı kayıt başka bir kimlik
  altında tekrar geliyor" senaryosu; per-hesap/per-IP rate limit bunu
  göremez (bu, kullanıcının "başka cihazlar başka IP'lerde yapıyorsa"
  cümlesinin birebir karşılığı). Sinyal eksikse/dokunmatikse fail-open
  (geçer) -- bu sinyali göndermeyen bir istemciyi asla bloklamıyor.
  Varsayılan olarak hiçbir gate'e bağlı değil, `extra_checks=[...]` ile
  isteğe bağlı ekleniyor -- diğer her şeyle aynı "kullan/kullanma"
  felsefesi.

**Denenip eklenmeyen**: kullanıcının/ChatGPT'nin önerdiği "hedefe
yaklaşırken overshoot-düzeltme" (homing dynamics) sinyalini gerçek veriyle
test ettim (`e(t) = hedef - x(t)`, artış var mı diye baktım) -- kendi elle
kurduğum, minimum-jerk modeline dayanan "insan" trajectory'sinde bile SIFIR
overshoot çıktı. Sebebi mantıklı: minimum-jerk modeli zaten monoton bir
eğri, overshoot sadece hızlı/balistik hareketlerde ortaya çıkan ikincil bir
olgu, yavaş/hassas fare hareketlerinde hiç yok. İkili (var/yok) yapılırsa
meşru düzgün insan hareketlerinin çoğunu "bot gibi" işaretler (yanlış
pozitif riski -- tam olarak bu projede baştan beri kaçınılan şey); dereceli
yapılırsa zaten var olan `mouse-velocity-variance` ile neredeyse aynı
bilgiyi tekrarlıyor, bağımsız değer katmıyor. Test etmeden eklemek yerine
sonucu kullanıcıya dürüstçe raporlayıp geri çektim -- bu projenin baştan
beri sürdürdüğü "iddia etmeden önce doğrula" disiplininin aynısı.

**Granülerlik dokümantasyonu**: `docs/OZELLIKLER.md`'ye, "check seviyesinde
aç/kapa" örneğinin bir altına, bir check'in İÇİNDEKİ tek tek özelliklerin
de (belirli bir `ScoringHeuristic`'i listeden çıkarmak, kendi/3.taraf
provider'ı hiç bizim kodumuza dokunmadan kullanmak) nasıl seçilebileceğini
gösteren somut kod örnekleri eklendi. Bu zaten var olan bir yetenekti
(`heuristics=[...]` her zaman değiştirilebilir bir liste, `CaptchaProvider`
Protocol'ü zaten "kendi getir" deseni) -- yeni bir mekanizma eklemedim,
sadece netleştirdim.

15 yeni test, tüm suite yeşil (bilinen Postgres ortam hatası hariç),
ruff+mypy temiz.

## captcha: mouse kinematiği skoru -- araştırma + uygulama (bu oturumda)

Kullanıcının sorusu birebir: "Mousede ardışık hareketler ardışık hızlanma
yavaşlama gibi şeylerlede puan ölçülebilir mi insanı bot sanma ihtimali
minimum yapılabiliyorsa imkansıza yakın ama botları otomatik sistemleri
felan iyi tespit eden birşey olmalı bunun için iyice araştırma ve
hesaplama yapıp karar verir misin." Yani: tahmin değil, gerçek
araştırma/hesaplama istedi ve dürüst bir karar bekledi.

**Yapılan araştırma**: `/tmp/.../scratchpad/kinematics_research.py`
scriptinde iki sentetik model yazıp karşılaştırdım:
- **İnsan modeli**: minimum-jerk motor-kontrol modeli (Flash & Hogan,
  1985) -- `ease = 10s³-15s⁴+6s⁵`, çan-eğrisi hız profili veriyor. Buna
  dikey sinüs-eğrisi bulge (doğal kavis), pozisyonel Gauss jitter (el
  titremesi), zamanlama jitter'ı eklendi.
- **Bot modeli**: naive otomasyonun en yaygın deseni -- sabit adımlarla
  düz çizgi lineer interpolasyon, sabit zaman aralığı.
- 20 deneme her biri için üç istatistik ölçüldü: **eğrilik oranı** (kat
  edilen yol / düz mesafe), **hız değişkenlik katsayısı** (std/mean),
  **zamanlama değişkenlik katsayısı**.
- **Sonuç -- temiz ayrışma, örtüşme yok**: İnsan eğrilik 1.011-1.051, hız
  CV 0.591-0.658, zamanlama CV 0.071-0.099. Bot(linear) üçünde de tam
  olarak 0.000/1.000 (sıfır varyans, tam düz çizgi).

**Dürüst karar (kullanıcının asıl sorduğu şey)**: Evet, ölçülebilir ve
gerçek bir sinyal -- ekledim. Hayır, "insanı bot sanma ihtimalini
imkansıza yakın" yapılamaz, ve bu ayar/eşik meselesi değil, **yapısal bir
sınır**: bir bot, gerçek ve önceden kaydedilmiş bir insan fare hareketini
**replay** edebilir (kendi operatörünün ya da başka yerden alınmış).
Replay edilen veri gerçek insan hareketi *olduğu için* herhangi bir
kinematik kontrolü kusursuz geçer -- tek bir isteğin analizi "insan şimdi
hareket etti" ile "bu kaydın replay'i şimdi oynatılıyor" arasını asla
ayıramaz. Bu prensipte kanıtlanamaz değil, çünkü replay verisi ve gerçek
veri istatistiksel olarak özdeş (aynı veri). Ayrıca bunu atlatmaya özel
yazılmış halka açık "insan gibi fare yolu" üretici araçlar (Bezier-eğrisi +
jitter) zaten var. Bu yüzden bu sinyal de aynı "şeffaf, dürüst sezgisel"
kovasında kalıyor -- naive/düşük-emekli otomasyonun (ki gerçekte
karşılaşılanın büyük kısmı budur) maliyetini ciddi yükseltiyor, ama PoW
(gerçek maliyet) + hesap-bağlama (gerçek kimlik) yerine geçmiyor.

**Uygulama** (`captcha/scoring.py`): üç yeni `ScoringHeuristic` --
`mouse-curvature` (ağırlık 2.0), `mouse-velocity-variance` (ağırlık 2.5,
en güçlü sinyal), `mouse-timing-variance` (ağırlık 1.0, en zayıf/en kolay
taklit edilebilir -- düşük weight bilinçli). Yeni `signals["mouse_trajectory"]`
girdisi: `[x, y, t_ms]` örnekleri, widget'a **yaklaşırken** toplanmaya
başlanır (diğer sezgisellerle aynı "tıklama-öncesi" kuralı). Skorlar
[0,1] aralığında **graded** (ikili değil) -- `(oran - eşik) / span`
şeklinde ölçekleniyor, span sabitleri sentetik insan aralığının içine
(kenarına değil) bilerek konuldu ki gürültülü/seyrek gerçek insan verisi
haksız yere sıfırlanmasın. Çekimser (`None`) durumları: touch/pen pointer,
`mouse_trajectory` eksik, 5'ten az örnek, bozuk veri şekli, çok kısa
hareket (<20px -- yol şeklinin bir anlamı olmadığı durum). Aşırı büyük bir
liste (`_MAX_TRAJECTORY_POINTS=2000`) DoS'a karşı ilk N örnekle
sınırlanıyor, hata vermeden.

Gerçek hesaplanmış değerlerle doğrulandı (Bash ile modülü import edip
gerçek fonksiyonları çalıştırarak, tahmin değil): el yapımı insan-benzeri
trajectory üç sezgiselde de tam 1.0'a satüre oluyor, el yapımı bot
trajectory'si üçünde de ~0.0 (float gürültüsü dışında tam sıfır). Hafif
kavisli bir trajectory ile graded (0 ile 1 arası) skor doğrulandı --
ikili değil. 21 yeni test eklendi (ayrışma her üç sezgiselde; graded
skorlama; touch/eksik/az-örnek/bozuk-veri/çok-kısa-hareket çekimser;
200.000 örneklik payload'da çökmeden/asılmadan sınırlama; breakdown'da
görünme; sahte bot trajectory'sinin skoru kurtarmaması; gate'e
extra_check olarak oturma). Tüm suite yeşil (bilinen Postgres ortam hatası
hariç), ruff+mypy temiz. Docstring'e (İngilizce, dosyanın geri kalanıyla
tutarlı) ve `docs/OZELLIKLER.md`'ye aynı dürüst araştırma sonucu yazıldı.

## captcha: davranışsal skor + flash-tap kaldırıldı (bu oturumda)

Kullanıcı flash-tap'i (yanıp-sönen nokta) "saçma" bulup kaldırmamı,
görünmez backend katmanını sağlamlaştırmamı ve *davranışsal* bir skor
tablosu eklememi istedi (skorlama tıklamada değil mouse'un widget'a
yaklaşımında başlar; tıklama konumu -- tam ortaya tıklamak bot şüphesi --,
dil, saat dilimi vb.). Bug/kırılma taraması da istedi.

**Yapılanlar**:
- **`FlashTapProvider` silindi** (dosya, export, testler, docs). Doğru
  karar: challenge verisi (nokta düzeni + sekans) zaten istemciye
  gidiyordu, yani gerçek bir güvenlik değeri yoktu, sadece karmaşıklıktı.
- **Bug taraması**: captcha kodunu (PoW/gate/checks/_shared) tekrar okudum;
  gerçek bir bug çıkmadı (kapsamlı test edilmişti). Tek gerçek sertleştirme:
  `PathTraceProvider`'a `json.loads`'tan önce ham yanıt boyut sınırı
  (`_MAX_RESPONSE_CHARS`) -- çok-megabaytlık bir gövdeyi ayrıştırmaya
  zorlanma (DoS) önlendi. (PoW'un `_leading_zero_bits`'i, one-time-use,
  expiry, attempts hepsi doğru; concurrency non-atomic ama in-memory için
  kabul edilebilir ve one-time-use delete asıl koruma.)
- **`SignalScoreCheck`** (`captcha/scoring.py`): kullanıcının "skor tablosu"
  isteği. `signals` bag'i üzerinde ağırlıklı, çekimser-olabilen sezgisellerle
  bir skor [0,1] üretip eşiği geçip geçmediğine bakan bir `VerificationCheck`.
  Sezgiseller çekimser dönerse (None) ağırlıklı ortalamadan çıkarılır --
  böylece mobil dokunma "mouse izi yok" diye cezalanmaz. `compute()` skor +
  kalem-kalem döküm veriyor. Varsayılan set: webdriver-yok / tıklama-öncesi
  hareket / tam-ortada-değil (offset<2px = bot) / dil / saat-dilimi /
  etkileşim-süresi. Tamamen tunable (ağırlık/sezgisel değiştir, kendini ekle).

**Dürüstlük duruşu (yine kritik)**: skorlama tamamen client-submitted
sinyal üzerinde -- istemci uydurabilir. Docstring'de ve docs'ta açıkça
"bu bot dedektörü/ML DEĞİL, şeffaf sezgisel skor; kuralları bilen bot
insan-gibi puan alabilir; her zaman PoW (maliyet) + hesap-bağlama (kimlik)
ile birlikte" dedim. reCAPTCHA v3/Turnstile'ın kavramsal olarak yaptığını
yapıyor ama "ML sihri" gibi sunmuyorum -- şeffaf ve dürüst. Sahte bir
kesinlik iddia etmektense gerçek sınırı yazdım.

Elle runtime doğrulaması: human sinyalleri 1.00 geçer, bot sinyalleri 0.00
kalır, mobil-touch mouse-izi çekimseriyle geçer, boş sinyaller 0.35 kalır.
Sonra kalıcı testlere döküldü. path-trace + PoW korundu (kullanıcı sadece
flash-tap'i kaldır dedi; path-trace opsiyonel sürtünme olarak duruyor).

## captcha: yeni modeller -- PoW + etkileşimli (bu oturumda)

Kullanıcı Cloudflare-Turnstile tarzı görünmez katman (arka planda PoW +
tarayıcı instrumentation, kullanıcı hiçbir şey hissetmez, düşük maliyet;
sıkıntı olursa görünür captcha'ya düş) + görsel captcha'ların "AI kolay
çözüyor" zayıflığına karşı daha zor etkileşimli modeller (ekranda çizgi
çıkar mouse/parmakla takip; karanlık ekranda yanıp sönen noktalara tıkla)
istedi.

**Dürüstlük duruşu (önemli)**: bu istekte overclaim tuzağı büyük. Ne
yaptım:
- **PoW** gerçek ve tam backend-doğrulanabilir -- hashcash: istemci nonce
  arar (2^difficulty hash), sunucu tek hash'le sha256 leading-zero-bits
  kontrol eder. "Minimum sunucu maliyeti" isteğini birebir karşılıyor
  (maliyet asimetriktir, sunucu tarafı sabit 1 hash). Bunu headline yaptım.
- **Instrumentation** özünde client-side; backend sadece client'ın
  gönderdiği sinyali şeffaf kuralla değerlendirir. Sahte bir "bot
  dedektörü" YAZMADIM -- `signals.py`'de şeffaf, kolay-atlatılır
  `PredicateCheck` yardımcıları verdim ve docstring'lerde açıkça "bu bir
  hız engeli, dedektör değil, kimse client sinyalden güvenilir insan/bot
  ayrımı yapamaz" dedim.
- **Etkileşimli captcha'lar (path-trace, flash-tap)**: üretim + doğrulama
  gerçekten backend'de ve test edilebilir (gerçek geometri). AMA dürüst
  sınır: challenge verisi (çizgi noktaları / nokta düzeni) çizilebilmek
  için istemciye gidiyor, yani kararlı bir script onu okuyup mükemmel
  cevap üretebilir -- bu yüzden bunları "AI çözemez" diye SUNMADIM,
  OCR'dan daha zor *sürtünme* katmanı olarak sundum, asıl sertliğin PoW +
  hesap-bağlamadan geldiğini vurguladım. Kullanıcının "AI'yı en çok
  zorlayacak" beklentisini karşılamaya çalışırken yalan söylemektense bu
  gerçek sınırı net yazdım.

**Mimari**: hepsi mevcut `CaptchaProvider` Protocol'üne oturuyor (issue/
verify) -- bu yüzden API/gate/checks hiç değişmeden çalışıyor, sadece yeni
`kind`'ler. `CaptchaChallenge`'a `params: dict` eklendi (image_data_uri/
site_key gibi ama parametreli sağlayıcılar için: PoW prefix/difficulty,
path noktaları, flash düzeni; kendi provider'ın için de genişletme
noktası). Ortak verify lifecycle'ı (expiry/attempts/one-time-use)
`_shared.check_pending_challenge(store, id, *, max_attempts, verifier)`'a
çıkarıldı -- provider'a özel karşılaştırma verifier callable'ında (PoW hash,
geometri, sekans eşleşmesi), string-eşitliği `verify_pending_challenge`
bunun üstünde ince bir sarmalayıcı olarak duruyor (math/text testleri hiç
değişmedi). SQL `answer` sütunu `String(256)` → `Text` (path/flash JSON
cevapları daha büyük).

**Bağımlılık**: yeni sağlayıcıların hiçbiri Pillow gerektirmiyor (sadece
stdlib hashlib/math/json) -- görsel captcha'ların aksine
`discord-webapi[captcha]` olmadan çalışıyorlar.

**Doğrulama**: her provider'ı önce elle gerçek mantığa karşı test ettim
(PoW için gerçek nonce araması; path-trace için mükemmel/yanlış/yarım/
bozuk trace; flash-tap için doğru sıra/yanlış sıra/yakın-jitter/uzak/
yanlış-sayı), sonra kalıcı testlere döktüm. 40 yeni test, 619 yeşil (1
ortam-bağımlı Postgres hariç), ruff+mypy temiz.

## captcha genişletme: hesap-bağlama + kompoz edilebilir doğrulama katmanları (bu oturumda)

Kullanıcı captcha teslim edildikten sonra önemli bir eksiği işaret etti
(kek/krema analojisiyle): captcha "insan mı" der ama "hangi hesap" demez --
forwardlanmış bir link başkası tarafından çözülebilir, bu yüzden gerçek
güvenilirlik için doğrulama gerçek Discord hesabına (OAuth) bağlanmalı. Ve
bunun iki-seçenekli sabit bir menü değil, kompoz edilebilir katmanlar
olmasını istedi: bizim captcha katımız, bizim hesap katımız, tüketicinin
kendi katları; hepsi kullanılır/karıştırılır/hiç kullanılmaz.

**Tasarım -- `VerificationCheck` Protocol (kek katları)**: `captcha/
checks.py`'de her doğrulama gereksinimi bağımsız bir check
(`async run(ctx) -> CheckOutcome`). Gate bir liste tutuyor, hepsinin
geçmesini şart koşuyor (AND). Yerleşikler: `AccountMatchCheck` (asıl güven
çıpası -- `ctx.authenticated_user_id == request.user_id`), `CaptchaCheck`
(provider'a devreder), `PredicateCheck` (tüketicinin kendi async
fonksiyonu -- fingerprint/davranış/üyelik-yaşı/anti-fraud kancası; kasıtlı
olarak biz ML/bot-tespiti YAZMIYORUZ, sadece kancayı veriyoruz).

**`CaptchaGate` genelleştirildi ama geriye uyumlu**: `provider` hâlâ 3.
pozisyonel arg ama artık opsiyonel (`None`). Yeni flag'ler:
`require_captcha` (varsayılan True), `require_account` (varsayılan False),
`extra_checks`. Modlar bunlardan çıkıyor -- captcha-only (varsayılan,
mevcut davranış), account-only, ikisi (safety), click-only (boş check
listesi -- linke sahip olmak tek kanıt), veya bunlara kendi katmanını
ekleme. `create_verification` captcha challenge'ı sadece `require_captcha`
ise üretiyor (aksi halde `challenge=None`, o yüzden model + SQL sütunu
nullable yapıldı).

**Bulunan gerçek tasarım sorunu -- consuming check sırası**: ilk
implementasyonda check'ler kayıt sırasında çalışıyordu (captcha ilk). Ama
`CaptchaCheck` doğru cevabı tüketiyor (tek-kullanımlık); eğer captcha
doğru ama SONRAKİ bir check (hesap, custom) patlarsa, captcha zaten
harcanmış oluyor ve kullanıcı doğru çözdüğü captcha'yı kaybediyordu. Test
yazarken yakalandı (safety-mod ve extra-check testleri patladı). Çözüm:
consuming olan captcha check'i HER ZAMAN en sona koy -- ucuz/yan-etkisiz
check'ler (hesap, custom) önce çalışıp patlarsa captcha hiç tüketilmiyor.
AND-semantiği olduğu için sıra sonucu değiştirmiyor, sadece bir
başarısızlığın captcha'yı boşa harcamasını önlüyor. `checks_passed`/
`.passed` listesinin sırası da buna göre (["account", "captcha"]).

**`verify()` dönüşü**: artık `bool` değil `CheckResult` (`.verified`,
`.failed_check`, `.passed`, `.detail`) -- frontend "önce Discord ile giriş
yap" gibi yönlendirebilsin diye. `__bool__` tanımlı, yani
`if await gate.verify(...):` hâlâ okunaklı çalışıyor. `CaptchaVerified`
event'ine `checks_passed` eklendi.

**API tarafı**: gate GET artık `GateInfo` (challenge + requires_captcha/
requires_account); gate verify gövdesi `{captcha_response?, signals?}`;
giriş yapmış kullanıcı OAuth session'ından çözülüyor. Bunun için
`auth/dependencies.py`'ye `get_current_user_optional` eklendi (401 yerine
None -- captcha-only gate'te giriş zorunlu değil ama hesap check'i için
lazım). Hesap-bağlamanın gerçek OAuth giriş akışıyla uçtan uca çalıştığı
`respx`-mock'lu bir entegrasyon testiyle doğrulandı (mock login id=1;
id=1 için link giriş sonrası geçiyor, başka kullanıcı için geçmiyor).

Yeni testler: `test_captcha_checks.py` (check edge case'leri),
`test_captcha_gate.py`'ye account-only/safety/click-only/extra-check/
provider-eksik testleri, `test_captcha_api.py`'ye account-binding HTTP
akışı + GateInfo/yeni gövde, `test_captcha_stores.py`'ye None-challenge
SQL round-trip. 598 test yeşil (1 ortam-bağımlı Postgres testi hariç),
ruff+mypy temiz. `docs/OZELLIKLER.md` captcha bölümü kompoz-edilebilir
katman örnekleriyle genişletildi.

## `discord_webapi.captcha`: sıfırdan captcha sistemi (bu oturumda)

Kullanıcının isteği (Türkçe, yorumlanmış): web tabanlı robot doğrulama
(captcha) -- kendi sistemimizden 1-2 farklı tür (biri matematiksel,
"yapay zeka tanıyamasın diye farklı renkler kullanarak", biri görsel
bazlı), reCAPTCHA/hCaptcha gibi üçüncü-taraf servisleri de (ya da başka
captcha kütüphanelerini) bağlayabilme, ve iki kullanım şekli: sitede
direkt (istedikleri noktalarda) ve bot komutu için bir "eşik" olarak.
Somut örnek senaryo (kullanıcının kendi tabiriyle "sadece senaryoydu, 1
tane basit senaryo"): bir çekiliş botunun butonuna tıklanınca bot
kullanıcıya (DM mi, sadece ona görünen bir mesaj mı -- botun kendi
tercihi) bir link yolluyor, kullanıcı linke gidip captcha'yı doğrulayınca
bot "çekilişe katılman başarılı" diyor.

**Kritik erken tasarım kararı -- SVG değil, gerçek PNG**: ilk aklıma
gelen "SVG üret, Pillow'a gerek kalmasın" fikri temelden güvensiz --
SVG'deki metin dosyanın içinde gerçek bir `<text>` node'u olarak durur,
yani biri (ya da bir script/yapay zeka) sadece XML'i parse edip cevabı
doğrudan okuyabilir, captcha'yı tamamen anlamsız kılar. Bunun yerine
gerçek raster PNG (Pillow, yeni opsiyonel `discord-webapi[captcha]`
extra'sı) -- metin sadece piksel verisi olarak var, hiçbir yapılandırılmış
metin düğümü yok. Pillow'un kendi gömülü fontu kullanıldı
(`ImageFont.load_default(size=...)`, Pillow>=10.1) -- sisteme kurulu bir
TTF font dosyasına (ör. DejaVuSans) bel bağlamak taşınabilir değil (minimal
Docker image'larında font olmayabilir), Pillow'un kendi içine gömdüğü font
her platformda çalışıyor.

**Render kalitesi elle görsel olarak doğrulandı, ilk denemede iki gerçek
bug bulundu**: (1) sabit 220px genişlik uzun matematik ifadelerinde
("20 * 15 = ?", 11 karakter) harfleri üst üste bindiriyordu -- genişlik
artık metne göre otomatik hesaplanıyor (`len(text) * _CHAR_ADVANCE + 20`).
(2) gürültü çizgileri köşeden köşeye çiziliyordu, bazı harflerin (özellikle
"=") üstünden tam geçip okunmaz hale getiriyordu -- artık kısa yerel
"çiziklere" (başlangıç noktasından ±40px/±20px) indirildi. Düzeltmeden
önce/sonra render'lar gerçekten PNG'ye decode edilip görsel olarak
incelendi (Read tool ile), sadece kod okuyarak değil.

**Mimari** (kütüphanenin geri kalanıyla aynı desen -- Protocol + Memory/SQL
+ Transport event):
- `CaptchaProvider` Protocol (`issue()` + `verify()`) hem kendi
  sağlayıcılarımızı hem üçüncü-taraf sarmalayıcıları hem de kullanıcının
  yazacağı herhangi bir şeyi aynı arayüzde topluyor -- kendi sağlayıcılar
  `CaptchaStore`'da (challenge_id -> doğru cevap) durum tutuyor, üçüncü-
  taraf sağlayıcılar (reCAPTCHA/hCaptcha) hiç yerel durum tutmuyor, tüm
  durum Google/hCaptcha'da.
- `CaptchaGate`: bot-tarafı eşikleme katmanı. `create_verification()` bir
  challenge üretip tek kullanımlık bir token'a sarıyor,
  `get_challenge(token)`/`verify(token, response)` web tarafının
  kullandığı API, `verify()` başarılı olunca `captcha_verified` Transport
  event'i yayınlıyor (`GuildRateLimiter`/`EscalationEngine`/`AppRoleCache`
  ile aynı cross-process canlı bildirim deseni), `on_verified(handler)`
  bot tarafının `transport.subscribe`'ı elle çağırmasına gerek kalmadan
  abone olmasını sağlıyor.
- Kaba kuvvet koruması `captcha/_shared.py`'de tek bir
  `verify_pending_challenge()` helper'ında toplandı (Math/Text
  provider'ların `verify()`'ı birer satıra iniyor) -- süre doldu mu, deneme
  hakkı bitti mi, cevap doğru mu kontrolü ve her durumda tek-kullanımlık
  silme mantığı iki yerde ayrı ayrı yazılıp birbirinden sapma riski
  taşımasın diye.
- Dashboard API'si (`build_captcha_router()`) iki bağımsız endpoint grubu
  sunuyor: düz `/api/captcha/challenge`+`/verify` (guild/kullanıcı kavramı
  yok, herkese açık bir form vb. korumak için) ve `/api/captcha/gate/
  {token}` (+ `/verify`) -- `CaptchaGate`'in web yarısı. `DiscordWebAPI`'ye
  otomatik bağlanmıyor (ratelimiter/escalation'ın aksine) -- hangi
  sağlayıcıyı/anahtarları kullanacağının sağlıklı bir varsayılanı yok, bu
  yüzden `app.state.discord_webapi_captcha_providers`/`_captcha_gate`
  elle set edilip router elle `include_router` edilecek şekilde tasarlandı.

**Test kapsamı**: store CRUD (Memory+SQL), render'ın gerçekten PNG
üretmesi + metin uzunluğuna göre boyutlanması + her çağrıda piksel-farklı
olması (aynı cevap için hep aynı görsel scraper'ın ezberlemesine izin
verirdi), sağlayıcıların issue/verify akışı (doğru/yanlış cevap, tek-
kullanımlık, deneme limiti, süre dolması), üçüncü-taraf sağlayıcıların
`respx`-mock'lanmış gerçek HTTP çağrıları (auth akışlarındaki mevcut
desenle aynı), `CaptchaGate`'in tam çekiliş-senaryosu akışı (Transport
event'i dahil -- `InProcessTransport`'un fire-and-forget dispatch'i
yüzünden `asyncio.sleep(0.05)` gerekti, bu oturumun daha önceki
bölümlerinde `GuildRateLimiter`/`EscalationEngine` testlerinde görülen
aynı zamanlama deseni), ve dashboard API'sinin uçtan uca `TestClient`
testleri. 55 yeni test, 583 test yeşil (1 ortam-bağımlı Postgres testi
hariç), ruff+mypy temiz.

`pyproject.toml`'a `captcha = ["Pillow>=10.1"]` extra'sı eklendi (`all`
extra'sına da dahil edildi). `docs/OZELLIKLER.md`'ye kod örnekli bir
bölüm eklendi (hem düz web kullanımı hem çekiliş-botu senaryosu).

## Kapsamlı güvenlik/sağlamlık taraması: 4 paralel denetim ajanı (bu oturumda)

Kullanıcının backup/healthcheck teslim edildikten sonraki isteği:
"fiziksel testler aksadı, biraz daha aksatalım, sağlam bir tarama yap,
bugları fixle, 'bu varken bu neden yok' dedirtecek yerleri ve kolaya
kaçılan yerleri sağlamlaştırıp genişletelim." Yani: gerçek hata avı +
paralel implementasyonlar arası asimetri avı (Memory vs SQL store'lar,
sibling moderasyon komutları arasında feature parity) + sertleştirme.

**Yöntem**: 4 general-purpose ajan paralel olarak (Explore değil -- bu
görev "cross-file consistency check" gerektiriyordu, Explore'un kapsamı
dışında) 4 kümeyi taradı: (1) storage/audit/consent/ratelimits/escalation,
(2) transport/jobs, (3) extras (moderasyon komutları), (4) commands/
authz/dashboard API. Her biri file:line + somut başarısızlık senaryosu
istendi, spekülasyon değil doğrulanmış bulgu. Toplam 19 bulgu geldi,
neredeyse tamamı gerçek ve düzeltildi.

### Düzeltilenler (özet -- detaylar CHANGELOG.md'de)

1. **`SessionStore.update()` yarışı**: Memory sessizce silinen session'ı
   diriltirken SQL yakalanmayan `ValueError` fırlatıyordu -- ikisi de artık
   `SessionExpiredError` (zaten `get_current_user`'ın yakaladığı tip).
2. **`escalation/sql.py`**: eksik `IntegrityError`-toleranslı upsert
   (storage/sql.py'deki `_commit_upsert` deseninin kendi küçük kopyası).
3. **`GuildRateLimiter`**: `per_seconds=0` → `ZeroDivisionError` DoS'u
   (artık `set_rule`'da reddediliyor); `sub_key` bucket'ları artık
   periyodik süpürülüyor (önceden süresiz bellek sızıntısı).
4. **`EscalationEngine._apply_action`**: rol-hiyerarşisi kontrolü + 
   `Forbidden`/`NotFound` yakalama eklendi (önceden `automod`'un
   `on_message`'ından fırlayan yakalanmamış hataydı); audit kaydı artık
   `action_applied: bool` tutuyor (rung tetiklendi ama aksiyon
   uygulanamadıysa bunu dürüstçe kaydediyor).
5. **`extras/ban.py`/`kick.py`/`timeout.py`/`role_assign.py`**: hepsine
   `Forbidden`/`NotFound` yakalama, opsiyonel `audit_logger`, ortak
   `build_audit_reason()` (Discord'un 512 karakter audit-reason limitine
   göre kırpıyor) eklendi. `timeout.py`'ye `dm_before_timeout`, `warn.py`'ye
   `require_reason`/`dm_before_warn` eklendi (asimetri giderme).
6. **`AppRoleCache`**: artık `GuildRateLimiter`/`EscalationEngine`/
   `GuildMemberCache` ile aynı Transport-event cross-process invalidation
   desenini kullanıyor (`app_role_changed`) -- önceden SADECE bu cache
   bu deseni kullanmıyordu, `for_bot_process`/`for_web_process`
   kurulumunda bir replica'daki rol iptali diğerlerinde 30sn'ye kadar hâlâ
   geçerli görünüyordu. `AppRoleCache(store)` → `AppRoleCache(transport,
   store)` imza değişikliği, tüm çağıran yerler güncellendi.
7. **Audit kapsam boşluğu**: `ratelimits/api.py`, `escalation/api.py`
   (kural CRUD), `jobs/api.py` audit hiç yazmıyordu -- artık
   `commands/api.py`/`authz/api.py` ile aynı desende yazıyor.
8. **`consent/api.py`**: `POST /api/consent` artık diğer tüm
   state-changing endpoint'lerle aynı dashboard rate-limit'ine sahip.
9. **`RedisTransport`**: request/reply kanal önekleri artık birbirinin
   öneki değil (`rpc-cmd:`/`rpc-reply:` -- `reply:` ile başlayan bir komut
   adının yanlış sınıflandırılmasını by-construction imkansız kıldı).
   Her fire-and-forget task artık `_create_tracked_task` ile
   istisna-loglayan bir done-callback'e sahip. RPC reply publish kendi
   try/except'inde (publish başarısız olursa loglanıyor, sessizce kaybolmuyor).
10. **`RedisJobQueue`**: çıplak `assert`'ler → `_require_redis()` (açık
    `RuntimeError`). Yeni **`reclaim_stale_jobs(max_age_seconds=...)`**:
    worker çökmesi/kill edilmesi durumunda sonsuza kadar "running" kalan
    job'ları bulup "failed" yapıyor -- bilinçli olarak otomatik yeniden
    kuyruğa almıyor (toplu DM/ban gibi bazı job'lar güvenli şekilde
    otomatik tekrar çalıştırılamaz, karar operatöre bırakıldı).
11. **`discord_webapi/tools/`**: `confirm()` artık `EOFError`'da (interaktif
    olmayan stdin) çökmüyor, "hayır" kabul ediyor; Türkçe tek harf "e" de
    kabul ediliyor. `migrate run`'a `backup create` ile parite için
    `--tables` eklendi. Eksik/bozuk dosyalar artık `DumpFileError` ile
    temiz hata veriyor (ham traceback yerine).

### Kontrol edilip bulunmayan (gerçek doğrulamayla, spekülasyonla değil)

- **`RedisTransport.request()`'in paylaşılan `PubSub`'ı**: ajan bunu
  teorik bir yarış durumu olarak işaretlemişti (subscribe/publish/
  unsubscribe, arka plan `listen()` döngüsüyle eşzamanlı). Gerçek bir
  Redis'e karşı 8 tur × 20 eşzamanlı RPC (160 toplam) hiçbir cevap
  karışması olmadan doğru sonuçlandı -- kalıcı regresyon testi olarak
  eklendi (`test_many_concurrent_requests_never_cross_wires`). Bu
  deneyde ayrı bir gerçek bulgu ortaya çıktı: redis-py'nin varsayılan
  connection pool'u 100 bağlantıyla sınırlı, çok yüksek eşzamanlı RPC
  hacminde `MaxConnectionsError` verebiliyor -- zaten `**redis_kwargs`
  üzerinden `max_connections=` ile ayarlanabiliyordu, sadece
  docstring'e not düşüldü.
- `commands/registry.py`'nin çift-invocation koruması kurulu discord.py
  sürümüne karşı doğrulandı, doğru.

### Bilinçli olarak düzeltilmeyen

- `warn.py`'nin `auto_timeout_after` sayacı ile `EscalationEngine`'in
  ihlal sayaçları birbirinden habersiz -- ikisi birden "uyarı" kavramı
  için kullanılırsa paylaşılan bir sayaç yok. Birleştirmek `warn.py`'yi
  `EscalationEngine`'in üzerine yeniden yazmak demek -- daha büyük bir
  mimari değişiklik, davranış değiştirme riski taşıyor, bu turun kapsamı
  dışında bırakıldı. `warn.py`'nin docstring'inde bu net şekilde uyarı
  olarak yazılı.

Tüm düzeltmeler gerçek testlerle doğrulandı (gerçek SQLite/Redis'e karşı,
mock değil) -- storage/ratelimits/escalation/extras/transport/jobs'a
yeni regresyon testleri eklendi. 528 test yeşil (1 ortam-bağımlı Postgres
testi hariç), ruff+mypy temiz.

## `discord_webapi.tools.healthcheck`: bağlantı sağlığı CLI'si (bu oturumda)

`backup` bittikten sonra kullanıcının "diğerleri boş olursa direkt başla"
onayıyla eklenen ikinci parça (aynı orijinal istekteki "health check
eklenebilir" kısmı). Kapsam kullanıcıyla ayrıca teyit edilmedi, en makul
tasarımla ilerlendi: DB bağlantı kontrolü (`SELECT 1`), opsiyonel Redis
`PING`, opsiyonel HTTP endpoint kontrolü, cron/monitoring için 0/1 exit
code.

**Tasarım**: üç kontrol de tamamen bağımsız ve opsiyonel — hangi
URL'leri verirsen sadece onlar çalışır. `check_database`/`check_redis`/
`check_http` ayrı ayrı `CheckResult` (`name`, `ok`, `detail`,
`elapsed_ms`) döndürüyor, `run_checks` sadece verilenleri topluyor.
Redis import'u fonksiyon içinde (lazy) — `redis` extra'sı kurulu
değilse ve `--redis-url` hiç verilmezse hiç sorun olmuyor, tıpkı
`transport/redis.py`'nin aksine burada modül importu shared değil.

**Uçtan uca gerçek bağlantılarla doğrulandı** (mock yok): gerçek bir
SQLite dosyasına karşı (`create_all` sonrası) başarı, var olmayan bir
dizine karşı `OperationalError` ile başarısızlık; gerçek bir loopback
`http.server` sunucusuna karşı `HTTP 200`, kapalı bir porta karşı
bağlantı hatası; sandbox'ta gerçek bir `redis-server` başlatılıp `PING`
başarısı, kapalı bir porta karşı `ConnectionError` başarısızlığı —
hepsi elle (CLI çalıştırılarak) denendikten sonra otomatik testlere
döküldü.

Testler: `tests/unit/test_tools_healthcheck.py` (11 test). Redis testi,
`tests/transport/conftest.py`'deki mevcut desenle birebir aynı şekilde
(`DWA_TEST_REDIS_URL`, `RedisError` yakalanırsa `pytest.skip`) yazıldı —
CI'da Redis service container'ı zaten var, yoksa sessizce atlanıyor.
488 test yeşil (1 ortam-bağımlı Postgres testi hariç), ruff+mypy temiz.

`pyproject.toml`'a `discord-webapi-healthcheck` console script eklendi
(Redis extra'sı zaten mevcuttu, yeni bir extra gerekmedi — `httpx` zaten
çekirdek bağımlılık). `discord_webapi/tools/__init__.py` docstring'i,
`docs/DAGITIM.md`'ye "6. Health check", `TESTING.md`'ye "25. Health
check CLI'si" bölümleri eklendi.

Bununla kullanıcının "Yedek alma komutu ekleyebiliriz tam yedek belli
bir yere kadar yedek tarihe belli yerlerin yedeği health check
eklenebilir" isteğinin tamamı (backup + health check) teslim edildi.

## `discord_webapi.tools.backup`: yedek alma CLI'si (bu oturumda)

`migrate` bittikten sonra kullanıcının istediği takip: "Yedek alma komutu
ekleyebiliriz tam yedek belli bir yere kadar yedek tarihe belli yerlerin
yedeği health check eklenebilir" — yani tam yedek + guild-scoped +
tarih-scoped yedek (health check ayrı bir sonraki iş).

**Refactor önce**: `migrate.py`'nin reflection/okuma/yazma/(de)serileştirme
kodu (`_reflect`, `_read_rows`, `_write_rows`, `_delete_rows`,
`_json_default`/`_json_object_hook`, `_redact`, onay istemi) `backup.py`
ile birebir aynı ihtiyaç olduğu için `discord_webapi/tools/_sql_dump.py`'ye
taşındı, `migrate.py` da bunları import edecek şekilde güncellendi. İkisi
arasında kod tekrarı yok.

**Üç kapsam, SQL seviyesinde filtrelenip birleştirilebiliyor** (Python'da
değil — `sqlalchemy.and_` ile `where` clause'una gömülüyor):
- Guild: `table.c.guild_id == guild_id`, sadece `guild_id` sütunu olan
  tablolara uygulanıyor.
- Tarih: her tablonun `created_at`/`updated_at`/`given_at`/`expires_at`
  sütunlarından hangisi varsa (bu sırayla kontrol edilip) ona göre
  `>=`/`<=`.
- İkisi aynı anda verilirse `and_(*conditions)` ile birleşiyor.

**Bilinçli sınır (dokümante edildi)**: bir yedek JSON dosyası sadece
satır verisi tutuyor, `migrate.py`'nin aksine canlı bir kaynak engine'i
yok ki oradan şema/sütun tipi reflect edilsin. Bu yüzden `restore_backup`,
hedefte olmayan bir tabloyu OLUŞTURAMIYOR — `migrate restore` ile aynı
davranışla sadece atlayıp mesaj basıyor. Restore için hedefin en az bir
kez `create_all()`/`quickstart()` görmüş olması gerekiyor.

**Uçtan uca elle doğrulandı** (sandbox'ta gerçek SQLite dosyalarıyla): 2
guild/2 tarihe yayılan 3 satır seed edildi; tam yedek 3, `--guild-id 111`
2, `--since <1 gün önce>` 2 (10 günlük satır hariç) satır verdi —
hepsi hem komutun kendi çıktısından hem `discord-webapi-backup list`'ten
doğrulandı. Boş bir hedefe `create_all` sonrası tam restore yapıldı,
`SQLCommandConfigStore.get_all_overrides()` ile guild 111'in
`{ping, warn}`, guild 222'nin `{ping}` override'larına sahip olduğu
doğrulandı (seed edilenle birebir eşleşti).

Testler: `tests/unit/test_tools_backup.py` (11 test — tam/guild/tarih/
birleşik kapsam, tablo filtresi, restore/var-olan-tabloya-yazma,
restore/eksik-tabloyu-atlama, `list_backup` çıktısı, CLI argüman
doğrulama, `_parse_iso`'nun naive datetime'ı UTC varsayması). 449 test
yeşil (1 ortam-bağımlı Postgres testi hariç), ruff+mypy temiz.

`pyproject.toml`'a `discord-webapi-backup` console script eklendi,
`discord_webapi/tools/__init__.py`'nin docstring'i güncellendi.
`docs/DAGITIM.md`'ye "5. Yedek alma" ve `TESTING.md`'ye "24. Yedek alma
CLI'si" bölümleri eklendi.

Sırada: health check aracı (kullanıcının aynı istekte belirttiği ikinci
parça, henüz başlanmadı — kapsam tam netleşmedi: DB bağlantı kontrolü,
opsiyonel Redis `PING`, opsiyonel HTTP endpoint kontrolü, cron/monitoring
için 0/1 exit code fikri var ama kullanıcıyla teyit edilmedi).

## `discord_webapi.tools.migrate`: veritabanı taşıma CLI'si (bu oturumda)

Fiziksel test turunda kullanıcının sorduğu "SQLite'tan MariaDB'ye geçebilir
miyim" sorusundan doğdu. Kullanıcının netleştirdiği gereksinimler: tam
config edilebilir bir komut, onay istemeli, uyarı vermeli ("yedek alın"),
**checkpoint (geri dönüş) varsayılan açık olmalı**, komut normal
kullanımda checkpoint'i kapatabilmeli. Ayrıca kullanıcı "terminal bazlı
araçlar ayrı bir klasörde olsun mu" diye sordu — evet dedim ve
`discord_webapi/tools/` diye yeni bir alt paket açtım (bot davranışı olan
`extras`'tan, çekirdek altyapıdan ayrı — farklı kullanım şekli: CLI
komutu, `setup(bot,...)` değil).

**Tasarım kararı — şema-agnostik, hardcode yok**: `discord_webapi/tools/
migrate.py` hiçbir ORM sınıfını (`storage.sql.SessionRow` vb.) import
etmiyor. Bunun yerine SQLAlchemy'nin kendi `MetaData().reflect()`'ini
kullanarak kaynak veritabanında GERÇEKTEN ne varsa onu buluyor, hedefte
karşılığını `Table.create(checkfirst=True)` ile oluşturuyor, satırları
`select`/`insert` ile kopyalıyor. Bu sayede çekirdek store'lar +
`escalation` + `extras.warn`'ın `SQLWarnStore`'u + gelecekteki HERHANGİ
bir üçüncü-taraf extension'ın kendi tablosu otomatik olarak destekleniyor,
hiçbir liste güncellenmesi gerekmiyor.

**Checkpoint/restore mekanizması**: `run` komutu, yazmadan ÖNCE hedefin o
anki durumunu (kaynaktaki tablolarla eşleşen, hedefte varsa) bir JSON
dosyasına dump ediyor (`_write_checkpoint`). `restore` komutu bu dosyayı
okuyup hedefteki ilgili tabloların içeriğini SİLİP checkpoint'tekiyle
DEĞİŞTİRİYOR (`_delete_rows` + `_write_rows`) — yani "migration öncesi
duruma dön" tam olarak bunu yapıyor. `--no-checkpoint` bu adımı atlıyor
(hedefin boş/önemsiz olduğunu bildiğin tekrar çalıştırmalar için).

**Bulunan gerçek bug (kendi round-trip testimde)**: `datetime` değerleri
checkpoint JSON'ına `.isoformat()` string'i olarak yazılıyordu ama
`restore` sırasında geri okunurken hâlâ düz string kalıyordu — SQLite
sürücüsü `INSERT`'e düz string yerine gerçek bir `datetime` nesnesi
bekliyor, `TypeError` fırlatıyordu. Fix: `_json_default`/`_json_object_hook`
hem `bytes` hem `datetime` için ayrı bir etiketli-dict formatı kullanıyor
artık (`{"__bytes_hex__": ...}` / `{"__datetime_iso__": ...}`), restore
her ikisini de doğru tipe geri çeviriyor.

**Uçtan uca doğrulandı** (sandbox'ta, gerçek SQLite dosyalarıyla): bir
kaynak DB'ye gerçek bir `SessionRow` yazıldı → `migrate run` çağrıldı →
hedefte satırın (bytes/JSON alanları dahil) doğru geldiği `SQLSessionStore`
üzerinden okunarak doğrulandı → hedefe "kötü" bir satır elle eklendi →
`migrate restore` çağrıldı → hem migrate edilen satırın hem "kötü"
satırın gittiği, checkpoint'in doğru şekilde "önceden hiçbir şey yoktu"
durumunu geri getirdiği doğrulandı.

Testler: `tests/unit/test_tools_migrate.py` (10 test — kopyalama,
checkpoint dosyası oluşturma, `--no-checkpoint`, restore/boş-durum
senaryosu, restore/önceden-veri-vardı senaryosu, boş kaynak no-op,
şifre gizleme, CLI argüman doğrulama). 438 test yeşil, ruff+mypy temiz.

`pyproject.toml`: `discord-webapi-migrate` console script + `tools/`
paketi zaten `discord_webapi`'nin bir parçası olduğu için ayrıca extra
gerekmedi (mevcut `[sql-*]` extra'ları DBAPI sürücüsünü sağlıyor).
`docs/DAGITIM.md`'ye "4. Veritabanı taşıma" bölümü eklendi.

## `examples/test_console`: tıklanabilir fiziksel test aracı (bu oturumda)

Kullanıcı 7 sunucuda gerçek botunu çalıştıracak, 2-3'ünü kendi test
sunucusunda deneyecek. curl yerine "butonlara tıklayarak" test etmek
istedi; şu komutları istedi: uyarı (warn), ping, automod/küfür engelleme
(`badword1`/`badword2`/`badword3` örneği), uyarı listeleme, etiketlenen
kullanıcı üzerinde işlem.

Karar: kütüphanenin kendisine UI EKLEMEDİM (backend-odak kararı hâlâ
geçerli) — bunun yerine `examples/test_console/` adında ayrı bir örnek
proje: gerçek bir bot (`main.py`) + tek sayfalık, self-contained (CDN'siz)
bir test arayüzü (`console.html`, `GET /console`'da `FileResponse` ile
sunuluyor). Bu, "biz UI sağlamıyoruz" ilkesini bozmuyor çünkü örnek/test
aracı, kütüphanenin şevkle sunduğu bir ürün parçası değil.

**Bot** (`main.py`): `/ping` (skeleton `rate_limited`, key `"ping"`,
quickstart sonrası imperatif kayıt — `weather` örneğindeki desenin aynısı,
çünkü gerçek limiter ancak `quickstart()` dönünce var oluyor), `/warn`
(`extras.warn`, `audit_logger=` ile audit'li), `/warnings @member` (yeni,
kütüphanede yok — `warn_store.list_for_user` kullanan basit bir komut,
kasıtlı olarak örnek koduna yazıldı çünkü `extras.warn` sadece store+komut
sağlıyor, dashboard API'si sağlamıyor), automod (`banned_words_list=[
"badword1","badword2","badword3"]`, `block_invites=True`,
`on_violation`→hem `warn_store.add` hem `escalation.record_violation(...,
"automod", ...)`, `audit_logger=` ile audit'li). `warn_store` tek bir
`MemoryWarnStore` — hem `/warn` hem automod hem `/warnings` hem konsolun
kendi `/api/guilds/{id}/warnings/{user_id}` endpoint'i (yeni, örneğe özel
custom endpoint, `require_guild_permission("manage_guild")` ile korunuyor)
AYNI sayıyı görüyor.

**Konsol** (`console.html`): vanilla JS, framework/CDN yok, tek dosya.
Bölümler: Ayarlar (guild id + session token, localStorage'da kalıcı),
Komutlar (listele/aç-kapat/cooldown/`required_app_role` — hepsi tek
tablodan), Rate Limit (get/set/sil), Escalation (kural kaydet/listele/sil),
Uyarılar (kullanıcı ID'siyle sorgula), Audit Log (hepsi tek feed'de), Son
Yanıt (debug — her `api()` çağrısının ham JSON'u). Tema `prefers-color-
scheme` ile otomatik light/dark.

**Tek-tıkla giriş**: `mobile_redirect_uri=f"{_base_url}/console"` —
Discord login sonrası doğrudan `/console?session_id=...&expires_at=...`'a
dönüyor, sayfa kendi JS'i ile bunu URL'den okuyup localStorage'a kaydediyor
ve `history.replaceState` ile URL'i temizliyor. Elle token kopyalama yok
(full_featured_bot'un `/mobile-login-done`'ından farkı: o sadece gösteriyor,
bu otomatik kaydediyor VE konsolun kendisi olduğu için hemen kullanılabilir
hale geliyor).

**Uçtan uca doğrulandı** (sandbox'ta, gerçek Discord token'ı olmadan):
- `TestClient` ile `GET /console` → 200, HTML içeriği doğru.
- Kimliksiz `GET /api/guilds/1/warnings/2` → 401 (auth zorunlu çalışıyor).
- `create_all_tables()` + `escalation.rule_store.create_all()` çağrılıp
  (gerçek lifespan bir Discord token'ı gerektirdiği için tam lifespan
  yerine tabloları elle kurduk) `/warn` komutu gerçekten çağrıldı → SQL
  audit tablosuna `action="warn"` kaydı gerçekten yazıldığını doğrudan SQL
  sorgusuyla doğruladık.
- Bir escalation kuralı (`kick` @ threshold 1) tanımlanıp
  `record_violation()` çağrıldı → **gerçekten `guild.kick()` çağrıldığını**
  (`AsyncMock.assert_awaited_once()`) VE bunun audit tablosuna
  `action="escalation.kick"` olarak yazıldığını doğrudan doğruladık.

`TESTING.md`'ye 22. bölüm eklendi (test_console'un kendi kontrol listesi)
+ giriş metni güncellendi ("önerilen ana test aracı" olarak işaretlendi).

Kod tarafında (kütüphanenin kendisinde) hiçbir değişiklik yok — sadece yeni
örnek + doküman. 427 test yeşil, ruff+mypy temiz.

## P1.4: audit log bot-tarafı moderasyonu kapsıyor (opt-in)

Audit şimdiye dek sadece web-tarafı (dashboard PATCH/PUT/DELETE)
aksiyonlarını `app.state.discord_webapi_audit_logger` üzerinden
kaydediyordu. Bot-tarafı (warn/escalation/automod) için tasarım kararı:
her birine opsiyonel `audit_logger` parametresi — verilmezse no-op (tam
opt-in, gizli bağımlılık yok).
- `EscalationEngine.__init__(..., audit_logger=None)` + `_audit_trigger`:
  rung tetiklenince `escalation.<action>`, `actor_user_id=0` (otomatik).
  Facade: `install(enable_audit_log=True)` `self.audit_logger`'ı yaratıp
  hem app.state'e koyuyor hem `escalation_engine.audit_logger`'a atıyor
  (aynı store → `GET /audit-log` ikisini de gösterir). `self.audit_logger`
  `__init__`'te `None`, install'da set ediliyor.
- `extras.warn.setup(..., audit_logger=)`: `warn` kaydı, actor=moderatör.
- `extras.automod.setup(..., audit_logger=)`: `automod.violation`, actor=0.
- Timing notu: warn/automod `setup()` genelde modül yüklenirken (api'den
  ÖNCE) çağrıldığı için quickstart'ta `api.audit_logger`'ı geçmek zor;
  composable API kullananlar ya da kendi `AuditLogger(store)`'unu kuranlar
  bağlar. Escalation audit'i facade'ın kendi motoru olduğu için
  quickstart'ta bile `enable_audit_log` ile çalışıyor.
8 yeni test (`test_audit_bot_side.py` 7 + facade wiring 1). 427 test yeşil.

## P1 DX turu tamamlandı (extras export, hata rehberliği, 2 örnek)

ROADMAP P1.1-P1.3 yapıldı:
- **P1.1**: `extras/__init__.py`'ye lazy `__getattr__`/`__all__`/`__dir__` —
  `discord_webapi.extras.ban` attribute erişimi + tab-completion, eager
  import olmadan (`_SUBMODULES` frozenset'i, `_shared` bilerek dışında).
- **P1.2**: `CommandRegistry._check_app_role` fail-closed dalına `WARNING`
  log'u eklendi (`logging.getLogger("discord_webapi.commands")`). Grok'un
  değindiği `enable_jobs`/`job_queue` mesajı zaten yeterince net'ti,
  dokunulmadı.
- **P1.3**: `examples/skeleton_custom_command/` (skeleton + custom rate
  limit key) ve `examples/hybrid_moderation/` (automod on_violation → warn
  + escalation, paylaşılan WarnStore). İkisi de fake env ile import edilip
  app/komut/listener kuruluşu doğrulandı. Not: skeleton örneği komutu
  app kurulduktan SONRA imperatif kaydediyor (`bot.hybrid_command(...)(
  rate_limited(...)(fn))`) çünkü quickstart limiter'ı app kurulunca
  yaratıyor; composable API kullansan decorator'ı inline stack'lerdin.

## v0.7: `discord_webapi.extensions` — üçüncü-taraf paket ekosistemi (bu oturumda tamamlandı)

Kullanıcının vizyonu: insanlar bizim `extras`'ta yaptığımız gibi tam
kapasite bot altyapıları yazıp paylaşsın, başkaları `pip` ile kurup
projesine taksın. **Kritik kısıt (kullanıcı):** "pluginler core'a etki
etmesin, ağır sistem istemem" — yani plugin VM/sandbox DEĞİL.

**Tasarım kararının temeli** (bunu bir daha tartışma): bizim `extras`'ımız
zaten SADECE public API kullanıyor. Dolayısıyla üçüncü-taraf bir paket,
birinci-taraf bir paketten mimari olarak AYIRT EDİLEMEZ — aynı yüzey, aynı
yetki, aynı sınır. Bu yüzden özel bir runtime'a gerek yok; extension =
dokümante edilmiş konvansiyonu izleyen sıradan bir pip paketi. Güvenlik
modeli = pip'in kendi güven modeli (extension kurmak = herhangi bir
bağımlılık kurmak). discord-webapi, kullanıcının açıkça kurup açıkça
çağırmadığı hiçbir kodu çalıştırmaz.

**Mimari** (`discord_webapi/extensions/`):
1. `manifest.py::ExtensionManifest` — metadata (name/version/author/
   `discord_webapi_requires`/`provides`), sıfır ayrıcalık.
2. `base.py::Extension` — `manifest + setup` container'ı (frozen dataclass),
   paketin entry point'ine koyduğu şey.
3. `registry.py::ExtensionRegistry.discover()` — `discord_webapi.extensions`
   entry-point grubunu okur (`importlib.metadata.entry_points`), her
   extension'ın modülünü import eder (manifest'i okumak için — "import yan
   etkisiz" konvansiyonu bunu güvenli kılıyor), `discord_webapi_requires`'ı
   `packaging.SpecifierSet` ile kurulu `__version__`'a karşı kontrol eder
   (packaging yoksa best-effort atlar). **`setup`'ı ASLA çağırmaz.**
   Kırık/uyumsuz/duplicate'leri `ExtensionLoadError` olarak toplar (biri
   diğerini gizlemez). `get`/`list`/`names`/`errors`.
4. `sdk.py` — bir extension'ın karşı yazacağı KARARLI re-export yüzeyi.
   Stabilite sözü: burada re-export edilen her isim public/garantili;
   edilmeyen her şey sürümler arası değişebilir. Bu, "plugin runtime
   gereksiz" argümanının somut karşılığı — extension'lar da bizim
   `extras`'ımız da tam olarak bu yüzeyi kullanır.
5. `scaffold.py` + `__main__` — `discord-webapi-scaffold new <isim>` CLI'si.
   Templating `.format` DEĞİL token-replacement (`__PKG__`/`__NAME__`/
   `__DIST__`) çünkü üretilen kod f-string süslü parantezleri içeriyor.
   Üretilen paket: örnek `/roll` (SDK'daki `rate_limited` ile), manifest,
   entry point, `[tool.pytest.ini_options] asyncio_mode="auto"`, geçen test.

`discord_webapi.__version__ = "0.6.0"` eklendi (uyumluluk kontrolü için;
`pyproject`'teki `version` hâlâ `0.1.0` — bu, PyPI publish'le birlikte ayrı
ele alınacak versiyon disiplini maddesi, bkz. ROADMAP P2.3).

**Uçtan uca doğrulandı** (sandbox'ta): scaffold → `pip install -e . --no-deps`
→ `ExtensionRegistry.discover()` → keşfedildi, uyumlu raporlandı, `setup`
çalıştı, üretilen paketin kendi testi geçti. Sonra funbot uninstall edildi
(ana suite temiz kalsın diye). 24 yeni test (`test_extensions_registry.py`
14, `test_extensions_scaffold.py` 10). 419 test yeşil, ruff+mypy temiz.

`pyproject`: `[extensions]` extra'sı (`packaging`), `[project.scripts]`
scaffold komutu. Doküman: `docs/PAKET_YAZMA.md`.

## Kapsamlı inceleme + uzun yol haritası: `docs/ROADMAP.md` (bu oturumda)

Kullanıcının isteğiyle tam kapsamlı bir mimari/kod incelemesi yapıldı ve
Grok'un önerileri değerlendirilip (doğru olanlar alındı, kullanıcının
kısıtlarına aykırı olanlar reddedildi) önceliklendirilmiş uzun bir yol
haritası **`docs/ROADMAP.md`** olarak repoya yazıldı. Bundan sonra güncel
öncelik sırası için önce oraya bakılır.

**Grok önerilerinden ALINANLAR**: extras ergonomik export'ları, daha net
hata rehberliği, iki eksik örnek (skeleton-custom + automod/warn/escalation
hibrit), audit log kapsamının genişletilmesi (opt-in), opsiyonel
observability (metrics/tracing, `[metrics]` extra'sı), `__init__`/
`quickstart` refactor'u, Redis-izolasyon + MySQL-upsert dokümantasyon
vurguları, versiyon disiplini.

**Grok önerilerinden REDDEDİLEN/ERTELENEN (kullanıcı kararıyla)**: gömülü
dashboard UI (backend odak, UI ekstra yük), İngilizce docs (adoption yok,
erken), tam plugin/manifest VM (güvenlik+karmaşıklık yüksek — kullanıcı
"pluginler core'a etki etmesin, ağır sistem istemeyiz" dedi). Ayrıca
Grok'un "magic string'leri Enum yap" önerisi zaten büyük ölçüde çözülmüş
(RPC komutları sabit, `EscalationAction` zaten `StrEnum`) — ek iş yok.

**Üçüncü-taraf vizyonu netleşti (v0.7)**: plugin VM değil, "discord-webapi
uyumlu paket konvansiyonu". Kritik içgörü: bizim `extras`'ımız zaten
yalnızca public API kullanıyor, dolayısıyla üçüncü-taraf bir paket
birinci-taraftan mimari olarak ayırt edilemez — özel bir runtime/izolasyon
gerekmiyor. Kapsam: konvansiyonu belgelemek + scaffold CLI + opsiyonel
hafif manifest (discovery için, kod çalıştırma için değil). Detay:
`docs/ROADMAP.md` §3.

## İki bilinen boşluk düzeltildi: `required_app_role` + ratelimit isim çakışması (bu oturumda)

Önceki oturumun sonunda dış bir gözden geçirmenin işaret ettiği iki somut
madde ele alındı:

1. **`CommandOverride.required_app_role`**: modelde tanımlı+persist
   ediliyordu ama hiçbir zaman set edilemiyordu (PATCH endpoint'i kabul
   etmiyordu) ve hiçbir zaman enforce edilmiyordu (`CommandRegistry`
   hiçbir yerde okumuyordu) — tamamen ölü bir alan. Karar: silmek yerine
   bitirmek, çünkü mimari olarak zaten iyi oturuyordu (mevcut `AppRole`/
   `AppRoleCache` sistemiyle bire bir uyumlu, sadece registry'ye
   bağlanmamıştı). `CommandRegistry` artık opsiyonel bir `app_role_cache`
   parametresi alıyor, `_check_app_role()` hem `global_check`
   (prefix/hybrid) hem `_wrap_interaction_check` (slash) yolunda
   çağrılıyor — `is_enabled`/cooldown kontrolünün hemen ardından, ikisinin
   de önce çalıştığı bir sırada (disabled/cooldown/app-role hepsi kısa
   devre yapabilir). Diğer enforcement kontrollerinin aksine bu saf O(1)
   in-memory değil — `AppRoleCache`'in kendi kısa-TTL cache'inden geçiyor,
   çünkü bir `AppRole`'ün üyeliği `CommandOverride`'dan bağımsız
   değişebilir. **Fail-closed** tasarım kararı: `required_app_role`
   ayarlı ama `app_role_cache=None` ise (yanlış yapılandırma), sessizce
   izin vermek yerine reddediyor. `DiscordWebAPI.__init__` kendi
   `self.app_role_cache`'ini `CommandRegistry`'ye otomatik geçiyor.
2. **`ratelimit.py`/`ratelimits/` isim çakışması**: `discord_webapi/ratelimit.py`
   (TokenBucketLimiter — dashboard PATCH/PUT/DELETE endpoint'lerini
   abuse'tan koruyan iç mekanizma) ile `discord_webapi/ratelimits/`
   (GuildRateLimiter — botunuzun kendi komutları/mantığı için genel amaçlı
   rate limit sistemi) sadece tekil/çoğul farkıyla ayrılıyordu, kafa
   karıştırıcıydı. `discord_webapi/dashboard_ratelimit.py` (bağımsız
   `TokenBucketLimiter`) + `discord_webapi/dashboard_ratelimit_dependency.py`
   (auth'a bağımlı `rate_limit_dependency`, circular import'u önlemek için
   ayrı dosyada — `commands/ratelimit.py`'nin eskiden yaptığı ayrımın
   aynısı, sadece "commands" isim alanından çıkarılıp üst seviyeye taşındı
   çünkü zaten `commands`'a özel değildi, `ratelimits`/`escalation`/`jobs`/
   `authz` API'lerinin hepsi kullanıyordu) olarak yeniden adlandırıldı.

391 test yeşil (1 ortam-bağımlı Postgres testi hariç), ruff+mypy temiz.

**Kod denetimi sonucu (tamamlandı)**: auth/authz/jobs/audit/consent/
transport/storage/extras/bridge.py kapsayan arka-plan denetimi 4 gerçek
bug buldu, hepsi `extras`'ta (diğer her alan — jobs kuyruğu, Redis
reconnect/RPC temizliği, auth refresh race, authz cache — temiz çıktı):
1. `warn.py`'de `auto_timeout_after` eşiği geçtikten sonra HER warn'da
   yeniden tetikleniyordu (`>=` yerine `==` olmalıydı) — düzeltildi.
2. `warn.py`'de bot'un `moderate_members` izni yoksa `member.timeout()`
   yakalanmamış `Forbidden` fırlatıyordu, warn kaydı zaten yazıldıktan
   sonra — `try/except` ile sarıldı (blanket
   `bot_has_permissions` decorator'ı KULLANILMADI, çünkü bu
   `auto_timeout_after` kullanmayanları da gereksiz yere kısıtlardı).
3. `welcome.py`'de kanal gönderimi `dm_instead`'in aksine best-effort
   değildi, izin yoksa listener'ı çökertiyordu — aynı `try/except` ile
   sarıldı.
4. `welcome.py`'de bilinmeyen bir template placeholder'ı (`{user}` gibi)
   yakalanmamış `KeyError` fırlatıyordu — best-effort olarak yakalanıyor.

4 yeni test eklendi. 395 test yeşil (1 ortam-bağımlı Postgres testi
hariç), ruff+mypy temiz.

## `builtins` + `skeletons` → tek `discord_webapi.extras` paketi (bu oturumda yapıldı)

Dış bir gözden geçirme (ChatGPT'ye sorulup kullanıcının paylaştığı geri
bildirim) şunu vurguladı: kütüphane "discord.py'nin FastAPI'si" (dar,
keskin bir bot↔dashboard köprüsü) hedefinden, `builtins`/`automod`/`jobs`/
`audit`/`consent` gibi giderek genişleyen bir "hazır moderasyon botu"
katmanına doğru kayıyor olabilir. Kullanıcı bunu tam olarak "amaçtan
sapma" olarak görmedi (bu builtin'lerin çoğu kendi isteğiyle eklendi) ama
paket sınırının bulanıklaştığını kabul etti: `builtins` ve `skeletons`
aslında aynı şeyin ("çekirdek değil, opsiyonel") iki farklı derinliği
olmasına rağmen, iki ayrı üst-seviye paket olarak duruyorlardı, isimleri
de bu ilişkiyi yansıtmıyordu.

Karar (kullanıcıyla netleştirildi, `AskUserQuestion` ile): tek bir
`discord_webapi.extras` paketi açıldı, `builtins`'in tüm içeriği (ban,
kick, timeout, warn, welcome, role_assign, automod/) doğrudan `extras/`
altına, `skeletons`'ın tüm içeriği `extras/skeletons/` alt paketine
taşındı — SADECE dosya taşıma + import path güncellemesi, hiçbir kod
mantığı/davranış değişmedi. Kapsam bilinçli olarak dar tutuldu (kullanıcı
"sadece klasör taşıma + import güncelleme" seçeneğini seçti) — README'lerin
birleştirilmesi ve `pyproject.toml`'a ayrı bir `[extras]` extra'sı
eklenmesi ayrı seçenekler olarak sunuldu ama seçilmedi (extras paketinin
şu an kendine özgü bir bağımlılığı yok, eklemenin şu an katacağı değer
yok).

`builtins/README.md` + `skeletons/README.md` yine de tek bir
`extras/README.md`'de birleştirildi (üst seviye "tam komutlar vs
iskeletler" ayrımını açıklayan bir üst-yazı ile), `skeletons/README.md`
kendi 10-senaryolu derinlemesine bölümüyle `extras/skeletons/README.md`
olarak aynen korundu.

Test dosyaları da aynı yapıyı yansıtacak şekilde taşındı:
`tests/unit/test_builtins_*.py` → `tests/unit/extras/test_*.py`,
`tests/unit/test_automod_*.py` → `tests/unit/extras/automod/test_*.py`,
`tests/unit/test_skeletons_ping.py` → `tests/unit/extras/skeletons/test_ping.py`,
`tests/integration/test_skeletons_deep_dive.py` →
`tests/integration/extras/test_skeletons_deep_dive.py`. 381 test yeşil
(1 ortam-bağımlı Postgres testi hariç), ruff+mypy temiz — taşıma
sırasında hiçbir test bozulmadı.

**Henüz yapılmayan, gözden geçirmenin işaret ettiği diğer maddeler**
(kullanıcıyla konuşulacak, bu oturumda ele alınmadı): `ratelimit.py`
(eski `TokenBucketLimiter`, `commands/`'ın cooldown rate-limit'i) ile
`ratelimits/` (yeni `GuildRateLimiter` paketi) arasındaki isim çakışması
kafa karıştırıcı bulundu; `CommandOverride.required_app_role` modelde
tanımlı+persist ediliyor ama hiçbir zaman PATCH edilemiyor/enforce
edilmiyor (ölü alan); `pyproject.toml` hâlâ `0.1.0` diyor ama CHANGELOG
"v0.6" vizyonundan bahsediyor. İngilizce dokümantasyon (README/docs/
dashboard HTML hâlâ tamamen Türkçe) kullanıcı tarafından bilinçli olarak
şimdilik ertelendi ("adoption henüz yok, projeyi gerçekten dışarı
açacağım gün yaparım").

## Strateji netleşmesi: `discord_webapi.skeletons` — "demir/rebar", tam komut değil (bu oturumda eklendi)

Kullanıcının yönlendirdiği strateji: bundan sonra öncelik, Discord'da
kullanılan sistemlere/algoritmalara (rate limit, eskalasyon, permission,
...) daha kapsamlı odaklanmak — `builtins`'in yaptığı gibi her komutu
uçtan uca "tam ürün" olarak çoğaltmak yerine. Somut istek: bir komut
ismimiz varsa (`ping` gibi), kullanıcı onu import edip sadece "demiri"
(komut kaydı + dashboard'dan ayarlanabilir rate-limit kontrolü) alsın,
gövdeyi (ne cevap vereceğini) kendisi yazsın — "ping binasının demirini
koyarız, çeliği/iç mekanı siz yaparsınız" benzetmesi. Tamamen opsiyonel;
hiç kullanmadan da düz discord.py yazılabilir.

`discord_webapi/skeletons/` bu yüzden `builtins`'ten AYRI bir paket
olarak açıldı — ama ilk tasarımdan sonra kullanıcı netleştirdi:
kendi `setup(bot, **kwargs)` fonksiyonumuzu çağırıp komutu BİZİM
kaydetmemiz yerine, kullanıcı komutu discord.py'nin kendi
`@bot.command(...)`/`@bot.tree.command(...)`/`@bot.hybrid_command(...)`
decorator'ıyla NORMAL şekilde yazsın, biz sadece onun ALTINA istiflenen
ince bir decorator verelim — hem klasik prefix komut hem slash komut aynı
decorator'la çalışsın (discord.py'ye "@bot.command" ya da
"@bot.tree.command" ile kaydedilen fonksiyona ilk argüman olarak ya
`commands.Context` ya da `discord.Interaction` geliyor, decorator ikisini
de otomatik ayırt ediyor):

1. `skeletons/_shared.py::rate_limited(key, *, rate_limiter=None,
   rate_limited_message=...)`: genel "demir" decorator'ı — sarmaladığı
   fonksiyonun ilk argümanı `Interaction` mı `Context` mi diye bakıp
   guild_id/user_id çıkarır, `rate_limiter` verilmişse `GuildRateLimiter`'ı
   her kullanıcı için `sub_key=str(user_id)` ile kontrol eder, DM'lerde
   (guild yok) kontrolü tamamen atlar, `rate_limiter=None` ise hiç kontrol
   yapmadan direkt fonksiyonu çağırır. Rate-limited olursa `Context` için
   `ctx.reply(...)`, `Interaction` için `interaction.response.send_message(
   ..., ephemeral=True)` (ya da interaction zaten yanıtlanmışsa
   `interaction.followup.send(...)`) ile cevap verir.
2. `skeletons/ping.py::ping(*, rate_limiter=None, rate_limit_key="ping",
   ...)`: ilk somut iskelet, yukarıdaki decorator'ın ping'e özel
   varsayılanlarla ince bir sarmalayıcısı.

Kullanım:
```python
@bot.command(name="ping")
@ping(rate_limiter=api.rate_limiter)
async def ping_cmd(ctx): await ctx.reply("pong")

@bot.tree.command(name="ping")
@ping(rate_limiter=api.rate_limiter)
async def ping_slash(interaction): await interaction.response.send_message("pong")
```

Gelecekteki her yeni iskelet aynı şekli takip edecek: paylaşılan bir
"rebar" decorator fabrikasının ince, isimli bir sarmalayıcısı, asla tam
bir komut ya da bizim kendi kayıt fonksiyonumuz. Testler:
`tests/unit/test_skeletons_ping.py` (10 test — hem `Context` hem
`Interaction` üzerinden handler çağrımı, rate-limit engelleme, interaction
zaten yanıtlanmışsa followup'a düşme, kullanıcı bazlı bağımsız bucket,
DM'de atlanma, varsayılan/özel `rate_limit_key`). 371 test yeşil (1
ortam-bağımlı Postgres testi hariç), ruff+mypy temiz.

## v0.6: `discord_webapi.escalation` — genel, tamamen kullanıcı-tanımlı eskalasyon motoru (bu oturumda tamamlandı)

Kullanıcının `ratelimits`'ten sonraki net talebi: "ban kick timeout vesaire
tüm olaylarda kullanılabilir hazır bir eşik algoritması olsun, ama
eşikleri/aksiyonları kendileri yazıp ayarlasınlar, biz dayatmayalım."
Yani `warn.py`'nin kendi `auto_timeout_after`'ı gibi tek bir builtin'e
gömülü değil, `ratelimits` gibi her yerden kullanılabilen, ama HİÇBİR
varsayılan eşik/aksiyon içermeyen genel bir sistem.

Mimari, `ratelimits` ile birebir aynı desende ama **kendi bağımsız SQL
şeması** (`builtins.warn.SQLWarnStore` gibi — core `storage/sql.py`'nin
paylaşılan `Base`'ine değil, çünkü `EscalationRule`/`ViolationRecord`
`CommandOverride`/`RateLimitRule` gibi "core" bir kavram değil, opsiyonel
bir builtin-üstü katman):

1. `discord_webapi/escalation/models.py`: `EscalationRule` (guild_id, key,
   threshold, action: `none|timeout|kick|ban`, action_minutes, reason),
   `ViolationRecord` (guild_id, user_id, key, source, reason, created_at),
   `EscalationOutcome` (count, triggered_rule).
2. `discord_webapi/escalation/base.py`+`memory.py`+`sql.py`:
   `EscalationRuleStore`+`ViolationStore` Protocol'leri, Memory + SQL
   implementasyonları (SQL'in kendi `create_all()`'ı, kendi `dwa_escalation_rules`/
   `dwa_escalation_violations` tabloları).
3. `discord_webapi/escalation/events.py`: `EVENT_TYPE_ESCALATION_RULES_CHANGED`.
4. `discord_webapi/escalation/engine.py::EscalationEngine`:
   `record_violation(member, key, source=, reason=)` — bir `ViolationRecord`
   ekler, `(guild_id, user_id, key)` için sayar, sayı TAM OLARAK bir
   `threshold`'a denk geliyorsa o kuralın aksiyonunu uygular
   (`member.timeout()`/`guild.kick()`/`guild.ban()`). Rule cache,
   `GuildRateLimiter`/`CommandRegistry` ile aynı Transport-event-invalidation
   desenini kullanıyor.
5. `discord_webapi/escalation/api.py::build_escalation_router()`:
   `GET /api/guilds/{id}/escalation-rules` (tüm kurallar),
   `GET/PUT/DELETE /api/guilds/{id}/escalation-rules/{key}[/{threshold}]`.
6. `DiscordWebAPI.__init__`'te `self.escalation_engine` HER ZAMAN kuruluyor
   (`rate_limiter` ile aynı gerekçe — opt-in olan sadece dashboard
   endpoint'i, `enable_escalation_api=True`).

**Kasıtlı olarak YOK**: hiçbir varsayılan eşik, hiçbir varsayılan aksiyon,
`ban`/`kick`/`timeout`/`warn`/`automod` builtin'lerinin hiçbirine gömülü
bir eskalasyon mantığı. Boş bir merdiven sadece sayar, hiçbir şey yapmaz.

**Somut hibrit kullanım kanıtı**: `examples/full_featured_bot/main.py`'de
`builtins.automod`'un `on_violation` callback'i artık
`app.state.discord_webapi_escalation_engine.record_violation(member, "automod", ...)`
çağırıyor — `automod`'un kendisi hâlâ hiçbir eskalasyon bilmiyor, sadece
"bir ihlal oldu" diye haber veriyor; asıl "3 ihlalde timeout, 5 ihlalde
kick" gibi merdiven tamamen dashboard'dan (`PUT
/api/guilds/{id}/escalation-rules/automod/3`) yapılandırılıyor.

Testler: `tests/unit/test_escalation_store.py` (Memory+SQL, 18 test),
`tests/unit/test_escalation_engine.py` (engine davranışı, canlı güncelleme
dahil, 11 test), `tests/integration/test_escalation_api.py` (dashboard
API, 7 test), `tests/integration/test_facade.py`'ye eklenen 2 test.

361 test yeşil (1 ortam-bağımlı Postgres testi hariç), ruff+mypy temiz.

## v0.6: `discord_webapi.ratelimits` — sunucu bazlı, koda bağımsız rate limit sistemi

Kullanıcının netleştirdiği büyük vizyon (plan dosyasındaki "v0.6 Vizyonu"
bölümüne bakın): discord.py komut yazmayı nasıl kolaylaştırıyorsa, biz de
rate limit/permission/eşik/ceza gibi altyapıları SAĞLAYALIM — insanlar
hem tek satırla (hazır) hem 50 satırla (kendi kodlarıyla config edip
harmanlayarak) kullanabilsinler, rate limit sadece komuta değil başka
yerlere de bağlanabilsin. Uzun vadeli ikinci hayal (şimdilik sadece
vizyon, aktif plan değil): üçüncü-taraf paylaşım ekosistemi — insanlar
kendi builtin-tarzı dosyalarını paylaşıp başkaları "discord-webapi uyumlu"
şekilde kullanabilsin (plan dosyasının en başından beri ertelenen
"üçüncü-taraf paket/manifest sistemi" fikrinin aynısı, hâlâ aktif
inşa edilmiyor ama artık net bir hedef).

**Bu oturumda yapılan somut ilk adım**: `discord_webapi/ratelimits/` —
`CommandRegistry`'nin `cooldown_seconds`/`cooldown_uses`'ıyla BİREBİR
AYNI mimari desende (`RateLimitStore` Protocol + Memory/SQL + Transport
event ile restart'sız canlı güncelleme, in-memory token-bucket cache hot
path'te asla DB'ye gitmiyor), ama **discord.py `Command` nesnesine hiç
ihtiyaç duymadan**, keyfi bir string `key`'e bağlanabiliyor.

Mimari:
1. `discord_webapi/ratelimits/models.py`: `RateLimitRule`, `RateLimitRulePatch`.
2. `discord_webapi/storage/base.py`/`memory.py`/`sql.py`: `RateLimitStore`
   Protocol + `MemoryRateLimitStore` + `SQLRateLimitStore` — CommandConfigStore
   ile aynı yerlerde, aynı desende (CORE bir özellik, builtins'in kendi
   izole tablosu değil, çünkü `CommandOverride` da core'da).
3. `discord_webapi/ratelimits/events.py`: `EVENT_TYPE_RATELIMIT_CONFIG_CHANGED`.
4. `discord_webapi/ratelimits/limiter.py::GuildRateLimiter`:
   `check(guild_id, key, sub_key="_")` — `sub_key`, TEK bir dashboard'dan
   ayarlanabilir eşiği (`(guild_id, key)`) paylaşırken her alt-anahtara
   (ör. `str(user_id)`) kendi bağımsız bucket'ını veriyor — "5 mesaj/10sn,
   kullanıcı başına" tam olarak bunu istiyor: bir dashboard-düzenlenebilir
   kural, çok sayıda bucket.
5. `discord_webapi/ratelimits/api.py::build_ratelimits_router()`:
   `GET/PUT/DELETE /api/guilds/{id}/ratelimits/{key}`.
6. `DiscordWebAPI.__init__`'te `self.rate_limiter` HER ZAMAN kuruluyor
   (job_queue/registry'nin aksine, opt-in gate yok) — çünkü bu, bot
   sürecindeki elle yazılmış koddan (ör. bir automod check'i) da
   kullanılabilmesi gereken bir sistem, sadece dashboard'daki
   `enable_ratelimits_api=True` bayrağı düzenleme endpoint'ini açıyor.
   `app.state.discord_webapi_ratelimiter` da her zaman set ediliyor
   (aynı gerekçe) — `enable_ratelimits_api` sadece router'ı mount ediyor.

**Somut hibrit kullanım kanıtı**: `examples/full_featured_bot/main.py`'daki
elle yazılmış `/ping` komutu artık `app.state.discord_webapi_ratelimiter.check(...)`
çağırıyor — ne bir `builtins` komutu ne `CommandRegistry`'nin cooldown'ı,
kullanıcının tarif ettiği "ping komutunun dondurulmasını bizim
altyapımızla, sunucu bazlı ayarlanabilir şekilde" senaryosunun birebir
karşılığı.

Testler: `tests/unit/test_ratelimit_store.py` (Memory+SQL, 13 test),
`tests/unit/test_guild_ratelimiter.py` (limiter davranışı, canlı güncelleme
dahil, 11 test), `tests/integration/test_ratelimits_api.py` (dashboard API,
6 test), `tests/integration/test_facade.py`'ye eklenen 2 test.

351 test yeşil (1 ortam-bağımlı Postgres testi hariç), ruff+mypy temiz.

**Sırada (v0.6 devamı, kullanıcı isterse)**: ceza-eşikleme/escalation
motorunun genelleştirilmesi (`warn.py`'nin `auto_timeout_after`'ının
genel bir "ihlal sayısı → aksiyon" sistemine dönüştürülmesi, `automod`'un
da kullanabileceği şekilde), builtin'lerin kendi istatistik/veri toplama
katmanı (`invocation_count`'un genelleştirilmiş hali).

## Automod'u tek dosyadan modüler alt pakete genişletme (bir önceki tur)

Kullanıcı ilk automod.py'yi (tek dosya, yasaklı kelime + basit spam) "çok
basit" buldu, açıkça istedi: "automod ekleyeceksek automod klasörü
içinde herşey ayrı klasör... o kadar kapsamlı olsun ki insanlar ya ping
komutu 5-6 satırlık kod nasıl bu kadar kapsamlı yapabilirsiniz desin."

Eski `discord_webapi/builtins/automod.py` silinip yerine
`discord_webapi/builtins/automod/` alt paketi kondu:
- `base.py` — `AutomodCheck` tipi (`Callable[[discord.Message], str | None]`).
- `banned_words.py`, `spam.py`, `mention_spam.py`, `invite_filter.py`,
  `link_filter.py`, `caps_spam.py`, `emoji_spam.py` — her biri
  `make_check(**kwargs) -> AutomodCheck | None` şeklinde, `None` dönmesi
  o kontrolün devre dışı olduğu anlamına geliyor (config'e göre otomatik
  disable, ekstra `if enabled:` dallanması gerekmiyor `setup()`'ta).
- `exemptions.py` — `is_exempt()`, moderatörleri (`manage_messages`) ve
  yapılandırılmış rol/kanal muafiyetlerini kontrol ediyor, tüm
  kontrollerden ÖNCE bir kere çalışıyor.
- `__init__.py::setup()` — koordinatör: 7 kontrolü sırayla çalıştırıp ilk
  ihlalde duruyor (`checks` listesi, `None` dönenler zaten filtrelenmiş),
  sonra aksiyon: sil / kanal bildirimi / log-kanalı / `on_violation`
  callback (async, mesaj+reason alıyor — `warn.py`'ye import bağımlılığı
  olmadan consumer kendi entegrasyonunu yapabilsin diye).

**Tasarım kararı — neden her check ayrı, saf, senkron bir fonksiyon**:
Her kontrol hiç `await`/I/O içermiyor, sadece `discord.Message`'ın zaten
Gateway cache'inde olan verisine bakıyor (aynı "ekstra fetch yok" ilkesi
`authz/cache.py`/`commands/bridge.py`'de de var). Bu, her kontrolün düz
bir sahte mesaj nesnesiyle (event loop bile gerekmeden) tek başına test
edilebilmesini sağlıyor — `tests/unit/test_automod_*.py` altında 7 ayrı
dosya, her biri kendi kontrolünü izole test ediyor, artı
`test_automod_exemptions.py` ve koordinatörü uçtan uca test eden
`test_automod_setup.py`.

53 yeni automod testi (toplamda 294 test yeşil, 1 ortam-bağımlı Postgres
testi hariç), ruff+mypy temiz. `examples/full_featured_bot/main.py`'a
`setup_automod(bot, banned_words_list=[], block_invites=True)` olarak
eklendi (parametre adı `banned_words` → `banned_words_list` oldu, tek
dosyalık ilk sürümden farklı — `README.md`/`docs/OZELLIKLER.md` buna göre
güncellendi).

## İki yeni builtin: rol atama, otomatik moderasyon (bir önceki tur)

Daha önce NOTES'ta "daha fazla builtin fikri: on_message otomatik
moderasyon, rol-atama komutu — zamanı değil" diye not edilmişti; kullanıcı
bu oturumda "builtins genişlet" isteyince sırası geldi.

- **`role_assign.py`**: `/role-add`/`/role-remove`. Önemli tasarım detayı:
  `check_role_hierarchy` (ban/kick/timeout'un kullandığı) hedef ÜYENİN
  sırasını kontrol ediyor, ama rol atama için asıl önemli olan verilen/
  alınan ROLÜN kendi sırası — bu yüzden `_shared.py`'ye ayrı bir
  `check_role_assignable(ctx, role)` eklendi.
- **`automod.py`**: `on_message` tabanlı, iki bağımsız kontrol (yasaklı
  kelime + basit spam). Bilerek bellek-içi, kalıcı state yok (warn.py'nin
  aksine) — TokenBucketLimiter'la aynı "zararsız eviction" mantığı.

Her ikisi de mevcut convention'a (`setup(bot, **kwargs)`, tek dosya, hiçbir
şey hardcoded değil) uyuyor. Testler: `tests/unit/test_builtins_role_assign.py`
(8 test), `tests/unit/test_builtins_automod.py` (9 test),
`test_builtins_shared.py`'ye `check_role_assignable` testleri eklendi.
`examples/full_featured_bot/main.py`'a da eklendi.

278 test yeşil (1 ortam-bağımlı Postgres testi hariç), ruff+mypy temiz.

## Test coverage artırma (tamamlandı)

Kullanıcı fiziksel testleri akşama erteledi, bu arada "test coverage artır"
ve "builtins genişlet" istedi (PyPI/repo taşıma işine hiç dokunmadık,
o kullanıcının kendi işi). `pytest-cov` ile ölçüldü: %91 → %95.

En değerli bulgu: **`require_role` fonksiyonu (public API, `discord_webapi`
top-level'dan export ediliyor) hiç test edilmiyormuş** — sıfır coverage.
Diğer önemli boşluklar: `bot/extension.py`'nin bot-tarafı wiring
fonksiyonlarının hiçbiri (`install_member_lookup` vb.) doğrudan test
edilmiyordu (sadece `DiscordWebAPI.__init__` üzerinden dolaylı), `single_process_lifespan`'ın
bot-başlatma-hatası yolu hiç tetiklenmemişti, `CommandRegistry.command_meta`
decorator'ı ve gerçek slash-command `interaction_check` gövdesi (sadece
prefix/hybrid'in `global_check`'i test ediliyordu) hiç çağrılmamıştı.

Eklenen test dosyaları: `tests/unit/test_bot_extension.py`,
`tests/unit/test_bridge_not_found_paths.py`, `tests/unit/test_registry_misc.py`,
`tests/integration/test_require_role.py`, ayrıca `test_storage.py`'ye
lazy `__getattr__` testi eklendi.

257 test yeşil (1 ortam-bağımlı Postgres testi hariç), ruff+mypy temiz.
Kalan düşük-coverage alanlar (`discord_webapi/__init__.py` %82,
`storage/sql.py` %87) çoğunlukla migration/hata-yolu kenar durumları —
düşük öncelik, bilerek derinleştirilmedi.

## Harici inceleme geri bildirimi (tamamlandı)

Kullanıcı önceki iki denetim raporunu (auth/authz + jobs/çoklu-sunucu)
harici birine incelettirmiş, üç nokta gelmiş:

1. `RedisTransport`/`RedisJobQueue` imzasız/kimlik doğrulamasız — çoklu-
   tenant paylaşımlı Redis'te risk. **Yanıt**: bilinçli tasarım kararı
   olduğu zaten dokümante edilmişti, ama gerçek bir iyileştirme yapılabilir
   gördüm: `namespace=` parametresi ekledim (`DEFAULT_NAMESPACE =
   "discord_webapi"`, geriye dönük uyumlu) — kanal/kuyruk isimleri artık
   `{namespace}:events`, `{namespace}:jobs:queue:...` şeklinde. Bu
   authentication değil ama farklı tenant'ların (ayrı `namespace` ile)
   aynı Redis'te yanlışlıkla birbirinin event/RPC/job trafiğini
   görmesini engelliyor. Gerçek mutually-untrusted izolasyon için hâlâ
   ayrı Redis DB/ACL gerekiyor, dokümante edildi.
2. `TokenBucketLimiter._buckets` sınırsız büyüyor — **düzeltildi**:
   `max_tracked_keys` (varsayılan 10.000) ile `OrderedDict` tabanlı
   LRU eviction eklendi.
3. `RedisTransport`'un "bir komuta tek handler" kısıtlaması — **bilinçli
   olarak değiştirilmedi**, dağıtık kilit/lease mekanizması eklemek
   library'nin basitlik hedefine (plain pub/sub, Streams/consumer-group
   yok) aykırı olurdu; operasyonel dokümantasyonla ele alınmaya devam
   ediyor (`docs/DAGITIM.md`'deki "tam olarak bir bot_process.py" notu).

**Refactor detayı**: `RedisTransport`/`RedisJobQueue`'daki modül-seviyesi
sabitler (`EVENTS_CHANNEL`, `_RPC_REQUEST_PREFIX` vb., `_QUEUE_PREFIX`,
`_STATUS_PREFIX`) instance-seviyesine taşındı (`self._events_channel`,
`self._queue_key()` vb.) çünkü artık `namespace`'e bağlı olarak her
instance farklı bir prefix kullanabiliyor — modül sabitleri olarak
kalamazlardı.

226 test yeşil (gerçek Redis'e karşı çalıştırıldı — ortamda
`redis-server` başlatılıp doğrulandı), ruff+mypy temiz. Yeni testler:
`tests/unit/test_ratelimit.py` (LRU eviction), `tests/unit/
test_redis_transport_namespace.py`, `tests/unit/test_redis_job_queue.py`'ye
eklenen namespace-isolation testi.

## Kuyruk sistemi taraması (tamamlandı)

Kullanıcının "genel bir tarama daha yap, buglar/kırılma yerleri" talebiyle
bir subagent'a kuyruk sistemi + çoklu sunucu refactoring'i + facade
değişikliklerini kapsayan geniş bir denetim yaptırıldı (önceki auth/authz
denetimi tekrar edilmedi, o kısım zaten temizdi). İki gerçek bug bulundu,
ikisi de `discord_webapi/jobs/redis.py`'de:

1. **TTL, pending/running durumundaki job'lara da uygulanıyordu** — worker
   backlog'u/kapalı kalması `result_ttl_seconds`'tan uzun sürerse, job
   kuyrukta beklerken status'u sessizce silinip job kayboluyordu. Fix:
   TTL artık sadece terminal state'e (succeeded/failed) uygulanıyor.
2. **`register_worker()`, `start()`'tan sonra çağrılırsa sessizce
   hiçbir şey yapmıyordu** (BLPOP key listesi `start()` anında
   sabitleniyor). `InProcessJobQueue`'nun geç register'ı sessizce kabul
   etmesiyle tutarsız — dev'de çalışan kod prod'da (Redis) sessizce
   bozulabilirdi. Fix: artık `RuntimeError` fırlatıyor.

Ayrıca iki küçük düzeltme: `_with_job_queue`'da `start()` başarısız
olursa `stop()` çağrılmıyor (kaynak-durumu hatası önlendi);
`for_bot_process()`'e `job_queue=...` eklendi (bot/Gateway erişimi
gereken job handler'ları için, önceden sadece `for_web_process`'te vardı).

**Not**: Bu oturumda ortamda gerçek bir Redis sunucusu (`redis-server`)
başlatılıp testler ona karşı gerçekten çalıştırıldı (önceki oturumlarda
Redis'e bağımlı testler hep skip ediliyordu, lokal ortamda Redis yoktu)
— 220 test yeşil, hepsi gerçek geçti, sadece 1 ortam-bağımlı Postgres
testi (Postgres kurulu değil) skip/fail.

## Kuyruk sistemi / background jobs (tamamlandı)

Kullanıcının "sırada kuyruk sistemi var" talebiyle eklendi (çoklu sunucu
işinden hemen sonra, çoklu bot hâlâ ertelenmiş durumda).

**Mimari**: `Transport`'un aynı deseni tekrarlandı — `discord_webapi/jobs/`
paketi, `JobQueue` Protocol'ü (`base.py`) + `InProcessJobQueue` (varsayılan,
asyncio.Queue + N worker task, zaten competing-consumer semantiği veriyor
tek process içinde) + `RedisJobQueue` (`redis.py`, `RPUSH`/`BLPOP` ile).

**Önemli tasarım farkı — `RedisTransport`'tan bilinçli olarak farklı**:
`RedisTransport`'un RPC'si "bir komuta tam olarak bir handler" kısıtlaması
taşıyordu (plain pub/sub — iki process aynı komutu register ederse
undefined davranış). Redis list'ler (`RPUSH`/`BLPOP`) bunun tam tersini,
GERÇEK competing-consumer semantiğini bedavaya veriyor — kaç tane worker
process aynı `job_type`'ı register edip `start()` çağırırsa çağırsın,
Redis aynı job_id'yi iki worker'a birden vermemeyi garanti ediyor. Bu
yüzden job queue, transport'tan farklı olarak GERÇEK yatay ölçekleme
için tasarlandı (birden fazla worker process, ayrı makinelerde).

**Yapılanlar**:
1. `discord_webapi/jobs/base.py`: `JobStatus` (pydantic model) + `JobQueue`
   Protocol (`start`/`stop`/`register_worker`/`enqueue`/`get_status`).
2. `discord_webapi/jobs/memory.py`: `InProcessJobQueue`.
3. `discord_webapi/jobs/redis.py`: `RedisJobQueue` — `discord_webapi:jobs:
   queue:{job_type}` (RPUSH/BLPOP) + `discord_webapi:jobs:job:{job_id}`
   (JSON status, TTL'li — varsayılan 24 saat, `result_ttl_seconds`).
4. `discord_webapi/jobs/api.py`: `build_jobs_router()` —
   `POST /api/guilds/{id}/jobs/{job_type}` (enqueue, rate-limited,
   manage_guild gerektiriyor, 202+job_id döner) ve
   `GET /api/guilds/{id}/jobs/{job_id}` (status poll — başka guild'in
   job'ı 404, cross-guild leak yok).
5. `discord_webapi/jobs/worker.py::run_worker(queue)` — FastAPI'siz
   bağımsız worker process girişi (`run_bot_process` ile aynı desen).
6. `DiscordWebAPI(job_queue=..., ...)` + `install(enable_jobs=True)` —
   opt-in, `job_queue` verilmeden `enable_jobs=True` denenirse açık
   RuntimeError. `for_web_process`'e de `job_queue` parametresi eklendi.
7. `DiscordWebAPI.lifespan()`/`web_lifespan()` artık `job_queue`'yu da
   otomatik start/stop ediyor (`_with_job_queue` helper) — tek-process
   kurulumda consumer'ın elle `queue.start()/.stop()` çağırmasına gerek yok.
8. `examples/split_deployment/worker_process.py` — üçüncü opsiyonel
   process tipi, `web_process.py`'ye `enable_jobs=True` + `RedisJobQueue`
   eklendi.
9. Contract test suite `tests/jobs/` (Transport'un `tests/transport/`
   deseniyle birebir aynı — her iki implementasyon da aynı testlerden
   geçiyor) + `tests/integration/test_jobs_api.py` (dashboard API) +
   `tests/integration/test_facade.py`'ye `enable_jobs` wiring testi.

193 test yeşil (1 ortam-bağımlı Postgres testi hariç), ruff+mypy temiz.

**Not**: `tests/jobs/test_contract.py` ismi `test_transport`'un
`test_contract.py`'siyle çakışıp pytest module-name collision hatası
veriyordu (her iki `tests/*/` dizininde de `__init__.py` yok) —
`tests/jobs/test_jobs_contract.py` olarak yeniden adlandırılarak çözüldü.

**Sırada (kullanıcı isterse)**: çoklu bot hâlâ ertelenmiş durumda
(guild_id→hangi bot routing'i gerektirir, disnake/pycord'u ertelerken
kullanılan mantıkla aynı kategoride).

## Çoklu sunucu/makine deployment (bot ve web ayrı process, tamamlandı)

Kullanıcı "5-6 büyük sunucuda çalışan botlar için sağlam bir sistem"
istedi — netleştirince asıl istenen: bot'un Discord Gateway bağlantısı bir
process'te, FastAPI dashboard'ı ayrı process'te/makinede, web tarafı N
replica olarak yatay ölçeklenebilsin (load balancer arkasında). Çoklu
bot (birden fazla farklı bot/token) ve job queue şimdilik ertelendi
(kullanıcı: "kuyruk sistemi ve çoklu botu şuanlık boşverelim").

**Kritik keşif**: `RedisTransport` zaten multi-process/multi-machine için
tasarlanmıştı (v0.1'den beri), ve authz/members/guilds gibi her alt sistem
zaten SADECE `Transport` üzerinden konuşuyordu — bot objesine hiç direkt
erişmiyorlardı. Tek istisna: `commands/api.py` (dashboard'un command
listeleme/override endpoint'leri), `app.state.discord_webapi_commands`
üzerinden CANLI bir `CommandRegistry` nesnesine DOĞRUDAN erişiyordu — bu,
web ve bot'un aynı process'te olmasını zorunlu kılan TEK parçaydı.

**Yapılanlar**:
1. `commands/registry.py::install_command_registry_bridge(registry, transport)`
   eklendi — `list_command_status`/`set_command_override` RPC'lerini
   registry'nin yaşadığı process'te cevaplıyor.
2. `commands/api.py` artık `app.state.discord_webapi_commands`'a hiç
   bakmıyor, sadece `transport.request(...)` çağırıyor — tek-process modda
   (`InProcessTransport`) davranış birebir aynı kalıyor (sadece bir RPC
   round-trip'e dönüşüyor, aynı process içinde).
3. `DiscordWebAPI.__init__`'te `bot`/`auth` artık opsiyonel (`None`
   olabilir) — `self.registry` de `CommandRegistry | None` oldu, sadece
   `bot is not None` olduğunda kuruluyor (RedisTransport'un "bir command'a
   sadece bir handler" kuralı gereği — web-only process asla bu RPC'leri
   register etmemeli).
4. İki yeni classmethod: `DiscordWebAPI.for_bot_process(bot=..., transport=...)`
   (FastAPI yok, sadece bot-side wiring) ve
   `DiscordWebAPI.for_web_process(transport=..., auth=...)` (bot yok,
   sadece web-side wiring). Mevcut `DiscordWebAPI(bot=..., auth=...)` /
   `quickstart()` API'si hiç değişmeden çalışmaya devam ediyor.
5. `bot/extension.py`'ye `run_bot_process(bot, transport, token)`
   (FastAPI'siz, sonsuza kadar bekleyen bot-only entry point) ve
   `web_only_lifespan(transport)` (bot'suz FastAPI lifespan) eklendi.
6. `examples/split_deployment/` (`bot_process.py` + `web_process.py` +
   README) — gerçek Redis+Postgres ile nasıl çalıştırılacağını gösteriyor.
7. Yeni test: `tests/integration/test_split_deployment.py` — iki ayrı
   `DiscordWebAPI` nesnesi (birbirine hiç referans vermeden, sadece
   paylaşılan `InProcessTransport` — gerçek `RedisTransport`'un makineler
   arası paylaşımının yerine geçiyor) ile GET/PATCH commands API'sinin
   gerçekten sadece Transport üzerinden çalıştığını doğruluyor.

Mevcut testlerden ikisi (`test_commands_api.py`, `test_audit_log.py`)
`app.state.discord_webapi_commands` yerine `install_command_registry_bridge`
+ `app.state.discord_webapi_transport` kullanacak şekilde güncellendi.

182 test yeşil (1 ortam-bağımlı Postgres testi hariç), ruff+mypy temiz.

**Sırada (kullanıcı isterse)**: çoklu bot (farklı bot/token'ları tek
dashboard'dan yönetme — guild_id→hangi bot routing'i gerektirir, bilinçli
olarak ayrı/opt-in bir katman olarak ele alınmalı) ve job queue (Celery/arq
tarzı, `Transport` gibi opt-in bir modül olarak) hâlâ ertelenmiş durumda.

## Kapsamlı güvenlik denetimi (v0.5 sonrası, tamamlandı)

Genişleme bittikten sonra planlanmış olan tam kapsamlı güvenlik denetimi
bir subagent ile yapıldı (diff değil, tüm paket okunarak). Sonuç: mimari
zaten sağlam çıktı (OAuth2 state/CSRF `secrets.compare_digest` ile doğru,
session cookie flag'leri doğru, SQL tamamen ORM üzerinden/injection riski
yok, authz guild/channel'a fail-closed, `GET /api/guilds` client input'una
güvenmiyor, token'lar hiçbir yerde loglanmıyor). İki gerçek bug bulundu ve
düzeltildi:

1. Session-management endpoint'lerinde (`logout`, `sessions` GET/DELETE)
   rate limit yoktu — eklendi (`DiscordAuth(session_management_rate_limiter=...)`).
   Bunu yaparken `TokenBucketLimiter` sınıfı `discord_webapi/ratelimit.py`'ye
   (bağımsız, auth'a hiç import etmeyen bir modül) taşındı çünkü
   `commands.ratelimit`'i doğrudan auth/oauth.py'den import etmek circular
   import'a yol açıyordu (`auth.oauth → commands.ratelimit →
   auth.dependencies → auth.oauth`). `commands/ratelimit.py` artık sadece
   re-export + `rate_limit_dependency` (FastAPI `Depends` sarmalayıcısı,
   hâlâ auth'a bağımlı, ama artık `TokenBucketLimiter`'ın kendisi değil).
2. `DiscordAuth._refresh_locks` dict'i asla küçülmüyordu — token refresh
   gereken her session için kalıcı bir lock birikirdi. `finally` bloğunda
   evict edilecek şekilde düzeltildi.

Düşük öncelikli, düzeltilmeyen bulgular: `commands/ratelimit.py`'nin
`_buckets` dict'i de aynı şekilde sınırsız büyüyor (sadece bellek, auth
bypass değil) — ileride bakılabilir. RedisTransport'un pub/sub kanalları
imzasız (Redis'in kendisi güvenilir altyapı olmalı varsayımı, docstring'de
zaten belirtiliyor ama daha net bir uyarı eklenebilir).

## v0.5 — genişleme: `GET /api/guilds`, oturum yönetimi (tamamlandı)

Hardening turu bittikten sonra kullanıcının "ikisini de yap" dediği iki
genişleme özelliği:

1. **`GET /api/guilds`** (`discord_webapi/guilds/`): kullanıcının kendi
   Discord `guild_ids` listesindeki hangi sunucuların hem bu bot'un içinde
   olduğunu HEM DE kullanıcının orada "Manage Server" yetkisi olduğunu
   döndürür — "sunucu seç" ekranı için, tüketicinin tek tek her guild'i
   deneyip 403/404 almasına gerek kalmadan. Bot tarafı
   (`commands/bridge.py::list_manageable_guilds` + `bot/extension.py::
   install_guild_listing`) botun warm Gateway cache'inden cevaplıyor, web
   tarafı (`guilds/api.py`) `has_permission(..., "manage_guild")` ile
   filtreliyor (izin kontrolü kasıtlı olarak transport cevabından SONRA,
   web tarafında yapılıyor).
2. **Oturum yönetimi / "her yerden çıkış yap"**: `SessionStore` protokolüne
   `list_by_user(user_id)` eklendi (Memory + SQL), `DiscordAuth`'a
   `GET /auth/discord/sessions` (kendi aktif oturumlarını listele,
   `is_current` bayrağıyla, şifreli token alanları asla dönmez —
   `SessionSummary` modeli bilerek dar) ve
   `DELETE /auth/discord/sessions/{session_id}` (sadece kendi oturumunu
   iptal edebilir — başka bir `user_id`'ye ait session_id 404 döner, 403
   değil — session'ın var olup olmadığını sızdırmamak için).

Her ikisi de mevcut modül-başına-endpoint deseniyle (authz/consent/audit
gibi) uyumlu; yeni testler: `tests/integration/test_guilds_api.py`,
`tests/integration/test_auth_flow.py`'ye eklenen 4 test, `tests/unit/
test_storage.py` ve `test_sql_storage.py`'ye eklenen `list_by_user` testi.
177 test yeşil (Postgres-bağlantısı gerektiren 1 test yerelde ortam
yüzünden skip/fail oluyor, kod tarafıyla ilgisiz), ruff+mypy temiz.


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

## Çekirdek dayanıklılık (hardening) turu — kullanıcı isteğiyle başlatıldı

Kullanıcı builtins'i yine erteledi, "önce core sistemleri/algoritmaları/
bağlantıları en sağlam kapsamlı şekilde tamamlayalım, küçük kalırsa hafta
sonu projesine dönme korkum var" dedi. `code-review` skill'i diff-bazlı
çalıştığı için (bu branch'te commit'lenmemiş diff yoktu) elle,
dosya dosya bir inceleme yaptım — **iki gerçek, ciddi bug** bulundu:

1. **`discord_webapi/transport/redis.py`**: `_read_loop`'un Redis bağlantı
   kopmasına karşı hiçbir dayanıklılığı yoktu — `RedisError` fırlayınca
   reader task'ı sessizce ölüyor, bir daha asla toparlanmıyordu. Fix:
   `_read_loop` artık `_read_loop_once()`'u bir dış retry döngüsüyle
   sarmalıyor, `RedisError` yakalanınca 1 saniye bekleyip
   `_resubscribe_all()` ile tüm kanallara (events + tüm registered RPC
   komutları + bekleyen reply kanalları) yeniden abone oluyor. Regresyon
   testi: `test_reader_loop_reconnects_after_a_dropped_connection`
   (gerçek Redis gerektirmiyor, fake pubsub ile deterministik).
2. **`discord_webapi/web/websocket.py`**: `commands_stream`, istemci
   bağlantıyı kapattığında bunu **hiç fark etmiyordu** — sadece kuyruktan
   okuyup gönderiyordu, websocket'ten hiç okuma yapmıyordu. O guild'de
   yeni bir event gelene kadar (belki hiç gelmeyebilir) subscriber+task
   sonsuza kadar askıda kalıyordu — uzun süreli bir deployment'ta gerçek
   bir kaynak sızıntısı. Fix: `_relay_until_disconnect()` artık iki paralel
   task çalıştırıyor (`_forward_events` + `_watch_for_disconnect`,
   `asyncio.wait(FIRST_COMPLETED)` ile), istemci kapanınca ikisi de düzgün
   iptal ediliyor. **Yan keşif**: Starlette'in ham `websocket.receive()`'i
   disconnect'te exception FIRLATMIYOR (sadece `receive_text`/`receive_json`
   gibi üst seviye metodlar fırlatıyor) — mesaj tipini elle kontrol edip
   `WebSocketDisconnect`'i kendimiz fırlatmamız gerekti, aksi halde ikinci
   `receive()` çağrısı `RuntimeError` fırlatıyordu (test bunu hemen yakaladı).

190 test yeşil (18 yeni: Redis reconnect testi + gerçek Redis'e karşı
çalışan entegrasyon testleri artık local Redis çalıştığı için skip
olmuyor), ruff+mypy temiz.

3. **`discord_webapi/storage/sql.py`**: `set_override`/`set_app_role`/
   consent'in `set()`'i "oku, yoksa oluştur" deseninde — aynı satırı ilk
   kez yazmaya çalışan iki eşzamanlı istek, ikisi de "yok" görüp ikisi de
   INSERT deniyordu, kaybeden yakalanmamış bir `IntegrityError` (500)
   alıyordu. Fix: paylaşılan `_commit_upsert()` yardımcı fonksiyonu —
   `IntegrityError` yakalanırsa rollback edip satırı tekrar okuyup update
   olarak uyguluyor. Regresyon testi gerçek Postgres'e karşı yazıldı
   (`tests/unit/test_sql_storage_multidb.py`) — SQLite'ta StaticPool'un
   tek fiziksel bağlantıyı paylaşması yüzünden bu yarış hiç
   tetiklenemiyor, gerçek izole bağlantılar (Postgres/MySQL) gerekiyor.

191 test yeşil, ruff+mypy temiz (bkz. commit `fc0f94a` sonrası).

**Kullanıcı kararı**: genişleme (yeni sistemler/özellikler) bittikten
sonra **tek seferde** kapsamlı bir güvenlik denetimi yapılacak — şimdi
değil, çünkü genişleme sonrası zaten tekrar gerekecekti. Henüz
incelenmedi: `commands/bridge.py`'nin daha derin introspection edge
case'leri (ayrı, daha küçük bir hardening maddesi olarak kalabilir).

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
