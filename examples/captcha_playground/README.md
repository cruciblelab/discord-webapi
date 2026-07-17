# captcha_playground

Discord bot yok, OAuth yok -- sadece `discord_webapi.captcha` alt
sisteminin **tamamını** tıklayarak test edebileceğiniz tek bir sayfa.
Her captcha modeli ve görünmez davranış katmanı gerçekten çalışır (mock
değil); sonuç ekrandaki log paneline PASS/FAIL olarak yazılır.

## Ne test edilebiliyor

0. **Doğrulama widget'ı** -- gerçek bir Cloudflare Turnstile / "ben robot
   değilim" kutusu gibi. Sayfaya girdiğiniz andan itibaren her adım ayrı
   ayrı loglanıyor: ilk hareket/dokunuş, mouse'un kutuya yaklaşması, tam
   tıklanan piksel + merkezden sapma (tam ortaya tıklarsanız bunu açıkça
   "şüpheli" diye işaretliyor), kontrol animasyonu, sunucunun verdiği
   sonuç. Widget her tıklamadan ~2.5sn sonra kendini sıfırlayıp tekrar
   denemenize izin veriyor -- fiziksel testin ana noktası burası.
1. **Görünmez davranış katmanı** -- `reject_webdriver`,
   `require_min_interaction_ms`, `SignalScoreCheck` (mouse-kinematiği ve
   homing-correction dahil tüm varsayılan sezgiseller),
   `RepeatedMovementCheck`. "Aynı hareketi tekrar gönder" butonu, replay
   tespitinin ikinci gönderimde gerçekten FAIL'e döndüğünü canlı gösterir.
2. **Math / Text** görsel captcha'lar (Pillow render, gerçek PNG).
3. **Proof-of-Work** -- gerçek hashcash araması tarayıcının kendi
   `crypto.subtle.digest`'ıyla yapılır, sunucu tek hash ile doğrular.
4. **Path-trace** -- çizgiyi canvas'ta gerçekten fare/parmakla takip edip
   gönderiyorsunuz.
5. **reCAPTCHA / hCaptcha** -- yalnızca gerçek site key'ler env'de
   ayarlıysa görünür; ayarlı değilse sayfa bunu açıkça söyler.

## Çalıştırma

```bash
pip install -e ".[captcha]"   # repo kökünden -- Pillow, Math/Text için

# İsterseniz (opsiyonel) gerçek 3. taraf key'lerinizi de ekleyin:
export RECAPTCHA_SITE_KEY=...  RECAPTCHA_SECRET_KEY=...
export HCAPTCHA_SITE_KEY=...   HCAPTCHA_SECRET_KEY=...

uvicorn main:app --reload --app-dir examples/captcha_playground
```

Sonra tarayıcıda: <http://localhost:8000/playground>

## Notlar

- Her şey `MemoryCaptchaStore`/`MemoryTrajectoryFingerprintStore` ile bellek
  içi tutuluyor -- sunucuyu yeniden başlatmak her şeyi sıfırlar.
- `RepeatedMovementCheck` bilerek **global**: aynı tarayıcı sekmesinden
  "replay testi" butonuna basmak bile onu tetikler (gerçek dünyada farklı
  hesap/cihaz/IP'den gelen bir replay'i yakalaması gereken mantığın aynısı).
- Bu bir örnek/test aracı -- pytest suite'inin bir parçası değil, elle
  çalıştırıp gözlemlemek için.
