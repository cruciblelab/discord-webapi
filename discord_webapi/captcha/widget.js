/*
 * discord-webapi bundled captcha widget.
 *
 * Drop-in usage:
 *   <div class="dwa-captcha-widget" data-token="{gate_token}"></div>
 *   <script src="/static/discord-webapi-captcha-widget.js" data-callback="onVerified"></script>
 *   <script>function onVerified(result) { ... result.verified, result.failed_check ... }</script>
 *
 * Every internal step (approach, click, animation, raw signals sent,
 * per-check pass/fail, final verdict) also fires a
 * `dwa-captcha-widget-log` CustomEvent on `document` with
 * `{ token, message, ok, detail }` -- listen for it if your page wants
 * its own visible timeline (this is how examples/captcha_playground
 * shows every step without duplicating this widget's logic).
 */
(function () {
  'use strict';

  var SCRIPT_TAG = document.currentScript;
  var CALLBACK_NAME = SCRIPT_TAG ? SCRIPT_TAG.getAttribute('data-callback') : null;
  var MAX_TRAJECTORY = 500;

  function emit(token, message, ok, detail) {
    document.dispatchEvent(new CustomEvent('dwa-captcha-widget-log', {
      detail: { token: token, message: message, ok: ok === undefined ? null : ok, detail: detail || null },
    }));
  }

  function fireCallback(token, result) {
    if (CALLBACK_NAME && typeof window[CALLBACK_NAME] === 'function') {
      window[CALLBACK_NAME](Object.assign({ token: token }, result));
    }
  }

  function injectStyles() {
    if (document.getElementById('dwa-captcha-widget-styles')) return;
    var style = document.createElement('style');
    style.id = 'dwa-captcha-widget-styles';
    style.textContent = [
      '.dwa-captcha-widget{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;',
      'max-width:300px;color:#1a1a1a;}',
      '.dwa-cw-box{display:flex;align-items:center;gap:12px;padding:14px 16px;',
      'border:1px solid #e3e3e8;border-radius:12px;background:#fff;cursor:pointer;',
      'user-select:none;box-shadow:0 1px 3px rgba(0,0,0,.06);transition:box-shadow .15s ease,border-color .15s ease;}',
      '.dwa-cw-box:hover{box-shadow:0 2px 8px rgba(0,0,0,.09);border-color:#d0d0d8;}',
      '.dwa-cw-box.dwa-cw-done{cursor:default;}',
      '.dwa-cw-checkbox{flex:0 0 auto;width:24px;height:24px;border-radius:7px;',
      'border:2px solid #b7b7c2;background:#fff;display:flex;align-items:center;justify-content:center;',
      'transition:all .18s ease;}',
      '.dwa-cw-checkbox svg{width:15px;height:15px;opacity:0;transform:scale(.5);transition:all .18s ease;}',
      '.dwa-cw-checkbox.dwa-cw-ok{background:#1fa564;border-color:#1fa564;}',
      '.dwa-cw-checkbox.dwa-cw-ok svg{opacity:1;transform:scale(1);}',
      '.dwa-cw-checkbox.dwa-cw-fail{background:#e5484d;border-color:#e5484d;}',
      '.dwa-cw-checkbox.dwa-cw-fail svg{opacity:1;transform:scale(1);}',
      '.dwa-cw-spinner{width:18px;height:18px;border-radius:50%;',
      'background:conic-gradient(from 0deg,#2b6fff,transparent 70%);',
      '-webkit-mask:radial-gradient(farthest-side,transparent calc(100% - 3px),#000 calc(100% - 3px));',
      'mask:radial-gradient(farthest-side,transparent calc(100% - 3px),#000 calc(100% - 3px));',
      'animation:dwa-cw-spin .8s linear infinite;display:none;}',
      '@keyframes dwa-cw-spin{to{transform:rotate(360deg);}}',
      '.dwa-cw-label{font-size:.92rem;color:#3a3a42;}',
      '.dwa-cw-expand{margin-top:12px;padding-top:12px;border-top:1px solid #ececf0;',
      'display:none;font-size:.85rem;}',
      '.dwa-cw-expand.dwa-cw-shown{display:block;}',
      '.dwa-cw-expand img{max-width:100%;border-radius:6px;display:block;margin-bottom:8px;}',
      '.dwa-cw-expand input[type=text]{padding:6px 8px;width:60%;border:1px solid #ccc;border-radius:6px;}',
      '.dwa-cw-expand button{padding:6px 12px;border:1px solid #ccc;border-radius:6px;background:#f4f4f7;',
      'cursor:pointer;margin-left:6px;}',
      '.dwa-cw-canvas{touch-action:none;cursor:crosshair;border:1px solid #ddd;border-radius:6px;}',
      '@media (prefers-color-scheme: dark){',
      '.dwa-captcha-widget{color:#e6e6ea;}',
      '.dwa-cw-box{background:#1e1e24;border-color:#33333c;}',
      '.dwa-cw-box:hover{border-color:#45454f;}',
      '.dwa-cw-checkbox{background:#1e1e24;border-color:#55555f;}',
      '.dwa-cw-label{color:#c7c7d1;}',
      '.dwa-cw-expand{border-top-color:#33333c;}',
      '.dwa-cw-expand button{background:#2a2a32;border-color:#45454f;color:#e6e6ea;}',
      '}',
    ].join('');
    document.head.appendChild(style);
  }

  var CHECK_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3" ' +
    'stroke-linecap="round" stroke-linejoin="round"><path d="M4 12l5 5L20 6"/></svg>';
  var CROSS_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3" ' +
    'stroke-linecap="round" stroke-linejoin="round"><path d="M5 5l14 14M19 5L5 19"/></svg>';

  // -- path-trace geometry, mirrors discord_webapi/captcha/providers/path_trace.py --
  function distPointToSegment(p, a, b) {
    var dx = b[0] - a[0], dy = b[1] - a[1];
    if (dx === 0 && dy === 0) return Math.hypot(p[0] - a[0], p[1] - a[1]);
    var t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy);
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
  }
  function distPointToPolyline(p, poly) {
    var best = Infinity;
    for (var i = 0; i < poly.length - 1; i++) best = Math.min(best, distPointToSegment(p, poly[i], poly[i + 1]));
    return best;
  }

  async function sha256LeadingZeroBits(text) {
    var buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
    var bytes = new Uint8Array(buf);
    var bits = 0;
    for (var i = 0; i < bytes.length; i++) {
      if (bytes[i] === 0) { bits += 8; continue; }
      var leading = 0;
      for (var b = 7; b >= 0; b--) { if ((bytes[i] >> b) & 1) break; leading++; }
      bits += leading;
      break;
    }
    return bits;
  }

  function CaptchaWidget(el) {
    this.el = el;
    this.token = el.getAttribute('data-token');
    this.pageLoadedAt = performance.now();
    this.trajectory = [];
    this.lastPointerType = 'mouse';
    this.clickOffset = null;
    this.captchaResponse = null;
    this.needsExplicitAnswer = false;
    this.busy = false;
    this.approached = false;
    this.build();
    this.trackMovement();
    this.loadInfo();
  }

  CaptchaWidget.prototype.since = function (t) { return Math.round(t - this.pageLoadedAt); };

  CaptchaWidget.prototype.build = function () {
    this.el.innerHTML =
      '<div class="dwa-cw-box"><div class="dwa-cw-checkbox">' + CHECK_SVG.replace('<svg', '<svg style="display:none"') + '</div>' +
      '<div class="dwa-cw-spinner"></div><span class="dwa-cw-label">İnsan olduğumu doğrula</span></div>' +
      '<div class="dwa-cw-expand"></div>';
    this.boxEl = this.el.querySelector('.dwa-cw-box');
    this.checkboxEl = this.el.querySelector('.dwa-cw-checkbox');
    this.spinnerEl = this.el.querySelector('.dwa-cw-spinner');
    this.labelEl = this.el.querySelector('.dwa-cw-label');
    this.expandEl = this.el.querySelector('.dwa-cw-expand');
    this.checkboxEl.innerHTML = '';

    var self = this;
    this.boxEl.addEventListener('pointerenter', function (e) {
      self.lastSeenPointerType = e.pointerType;
      if (self.approached) return;
      self.approached = true;
      emit(self.token, 'widget: yaklaşıldı', null, self.since(performance.now()) + 'ms, pointer_type=' + e.pointerType);
    });
    this.boxEl.addEventListener('pointerleave', function (e) {
      if (self.approached && !self.busy && e.pointerType !== 'touch' && e.pointerType !== 'pen') {
        emit(self.token, 'widget: uzaklaşıldı (henüz tıklanmadı)', null, self.since(performance.now()) + 'ms');
      }
    });
    this.boxEl.addEventListener('click', function (e) { self.onBoxClick(e); });
  };

  CaptchaWidget.prototype.trackMovement = function () {
    var self = this;
    function push(e) {
      self.lastPointerType = e.pointerType;
      self.trajectory.push([e.clientX, e.clientY, performance.now()]);
      if (self.trajectory.length > MAX_TRAJECTORY) self.trajectory.shift();
    }
    window.addEventListener('pointermove', push);
    window.addEventListener('pointerdown', push);
  };

  CaptchaWidget.prototype.currentSignals = function () {
    return {
      webdriver: navigator.webdriver === true,
      language: navigator.language,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      pointer_type: this.lastPointerType,
      pointer_moves: this.trajectory.length,
      mouse_trajectory: this.trajectory.slice(),
      click_offset: this.clickOffset,
      interaction_ms: performance.now() - this.pageLoadedAt,
    };
  };

  CaptchaWidget.prototype.loadInfo = async function () {
    try {
      var resp = await fetch('/api/captcha/gate/' + this.token);
      if (!resp.ok) { this.showFatalError('Doğrulama linki geçersiz veya süresi dolmuş.'); return; }
      this.info = await resp.json();
    } catch (e) {
      this.showFatalError('Sunucuya ulaşılamadı.');
      return;
    }
    if (this.info.requires_captcha && this.info.challenge) {
      this.renderChallenge(this.info.challenge);
    }
  };

  CaptchaWidget.prototype.showFatalError = function (msg) {
    this.labelEl.textContent = msg;
    this.boxEl.style.cursor = 'default';
    this.boxEl.removeEventListener('click', this.onBoxClick);
    emit(this.token, 'widget: hata', false, msg);
  };

  CaptchaWidget.prototype.showExpand = function (html) {
    this.expandEl.innerHTML = html;
    this.expandEl.classList.add('dwa-cw-shown');
  };

  CaptchaWidget.prototype.renderChallenge = function (challenge) {
    if (challenge.kind === 'math' || challenge.kind === 'text') this.renderImageChallenge(challenge);
    else if (challenge.kind === 'pow') this.renderPowChallenge(challenge);
    else if (challenge.kind === 'path-trace') this.renderPathTraceChallenge(challenge);
    else if (challenge.kind === 'recaptcha') this.renderThirdParty(challenge, 'recaptcha', 'https://www.google.com/recaptcha/api.js', 'g-recaptcha');
    else if (challenge.kind === 'hcaptcha') this.renderThirdParty(challenge, 'hcaptcha', 'https://js.hcaptcha.com/1/api.js', 'h-captcha');
  };

  // -- math / text: image + text input + its own submit button --
  CaptchaWidget.prototype.renderImageChallenge = function (challenge) {
    this.needsExplicitAnswer = true;
    this.labelEl.textContent = 'Aşağıdaki soruyu çözün';
    this.showExpand(
      '<img src="' + challenge.image_data_uri + '" alt="captcha" />' +
      '<input type="text" class="dwa-cw-answer" placeholder="cevabınız" />' +
      '<button type="button" class="dwa-cw-submit">Doğrula</button>'
    );
    var self = this;
    this.expandEl.querySelector('.dwa-cw-submit').addEventListener('click', function (e) {
      e.stopPropagation();
      self.captchaResponse = self.expandEl.querySelector('.dwa-cw-answer').value;
      emit(self.token, 'widget: cevap gönderiliyor', null, 'girilen cevap: "' + self.captchaResponse + '"');
      self.runVerification(e);
    });
    emit(this.token, 'widget: görsel captcha yüklendi', null, challenge.prompt);
  };

  // -- proof-of-work: fully automatic, no UI, runs before the click even matters --
  CaptchaWidget.prototype.renderPowChallenge = function (challenge) {
    var self = this;
    this.labelEl.textContent = 'Hazırlanıyor...';
    this.boxEl.style.pointerEvents = 'none';
    var prefix = challenge.params.prefix, difficulty = challenge.params.difficulty;
    emit(this.token, 'widget: proof-of-work aranıyor', null, 'zorluk ' + difficulty + ' bit');
    (async function () {
      var start = performance.now();
      var nonce = 0;
      while (true) {
        var bits = await sha256LeadingZeroBits(prefix + nonce);
        if (bits >= difficulty) break;
        nonce++;
        if (nonce % 500 === 0) await new Promise(function (r) { setTimeout(r, 0); });
      }
      self.captchaResponse = String(nonce);
      self.labelEl.textContent = 'İnsan olduğumu doğrula';
      self.boxEl.style.pointerEvents = '';
      emit(self.token, 'widget: proof-of-work tamamlandı', null,
        nonce + ' deneme, ' + Math.round(performance.now() - start) + 'ms');
    })();
  };

  // -- path-trace: inline canvas, its own submit button --
  CaptchaWidget.prototype.renderPathTraceChallenge = function (challenge) {
    this.needsExplicitAnswer = true;
    this.labelEl.textContent = 'Çizgiyi takip edin';
    var p = challenge.params;
    this.showExpand(
      '<canvas class="dwa-cw-canvas" width="' + p.width + '" height="' + p.height + '"></canvas><br/>' +
      '<button type="button" class="dwa-cw-submit">Doğrula</button>'
    );
    var canvas = this.expandEl.querySelector('canvas');
    var ctx = canvas.getContext('2d');
    var tracePoints = [];
    var tracing = false;
    function redraw() {
      ctx.clearRect(0, 0, p.width, p.height);
      ctx.strokeStyle = '#c9c9d2'; ctx.lineWidth = p.tolerance * 2;
      ctx.lineCap = 'round'; ctx.lineJoin = 'round';
      ctx.beginPath();
      p.path.forEach(function (pt, i) { i === 0 ? ctx.moveTo(pt[0], pt[1]) : ctx.lineTo(pt[0], pt[1]); });
      ctx.stroke();
      ctx.strokeStyle = '#2b6fff'; ctx.lineWidth = 2;
      ctx.beginPath();
      tracePoints.forEach(function (pt, i) { i === 0 ? ctx.moveTo(pt[0], pt[1]) : ctx.lineTo(pt[0], pt[1]); });
      ctx.stroke();
    }
    redraw();
    canvas.addEventListener('pointerdown', function (e) {
      tracing = true; tracePoints = [];
      var r = canvas.getBoundingClientRect();
      tracePoints.push([e.clientX - r.left, e.clientY - r.top]);
      redraw();
    });
    canvas.addEventListener('pointermove', function (e) {
      if (!tracing) return;
      var r = canvas.getBoundingClientRect();
      tracePoints.push([e.clientX - r.left, e.clientY - r.top]);
      redraw();
    });
    window.addEventListener('pointerup', function () { tracing = false; });

    var self = this;
    this.expandEl.querySelector('.dwa-cw-submit').addEventListener('click', function (e) {
      e.stopPropagation();
      if (tracePoints.length === 0) {
        emit(self.token, 'widget: çizgi gönderilemedi', false, 'hiç nokta çizilmedi');
        return;
      }
      var maxDev = Math.max.apply(null, tracePoints.map(function (pt) { return distPointToPolyline(pt, p.path); }));
      var uncovered = p.path.filter(function (v) {
        return Math.min.apply(null, tracePoints.map(function (pt) { return Math.hypot(pt[0] - v[0], pt[1] - v[1]); })) > p.tolerance;
      }).length;
      emit(self.token, 'widget: çizgi gönderiliyor', null,
        tracePoints.length + ' nokta, en uzak sapma ' + maxDev.toFixed(1) + 'px (tolerans ' + p.tolerance + 'px), kapsanmayan köşe ' + uncovered + '/' + p.path.length);
      self.captchaResponse = JSON.stringify(tracePoints);
      self.runVerification(e);
    });
    emit(this.token, 'widget: çizgi-takip yüklendi', null, p.path.length + ' nokta, tolerans ' + p.tolerance + 'px');
  };

  // -- reCAPTCHA / hCaptcha: embed the real widget, our own submit button reads its token --
  CaptchaWidget.prototype.renderThirdParty = function (challenge, kind, scriptUrl, cssClass) {
    this.needsExplicitAnswer = true;
    this.labelEl.textContent = 'Aşağıdaki doğrulamayı tamamlayın';
    this.showExpand('<div class="' + cssClass + '" data-sitekey="' + challenge.site_key + '"></div>' +
      '<button type="button" class="dwa-cw-submit">Doğrula</button>');
    if (!document.querySelector('script[data-dwa-' + kind + ']')) {
      var s = document.createElement('script');
      s.src = scriptUrl; s.async = true; s.defer = true; s.setAttribute('data-dwa-' + kind, '1');
      document.body.appendChild(s);
    }
    var self = this;
    this.expandEl.querySelector('.dwa-cw-submit').addEventListener('click', function (e) {
      e.stopPropagation();
      if (kind === 'recaptcha') {
        self.captchaResponse = window.grecaptcha ? window.grecaptcha.getResponse() : '';
      } else {
        var el = document.querySelector('[name="h-captcha-response"]');
        self.captchaResponse = el ? el.value : '';
      }
      emit(self.token, 'widget: ' + kind + ' cevabı gönderiliyor', null);
      self.runVerification(e);
    });
    emit(this.token, 'widget: ' + kind + ' yüklendi', null);
  };

  CaptchaWidget.prototype.onBoxClick = function (e) {
    if (this.busy) return;
    if (this.needsExplicitAnswer) {
      // Image/canvas/3rd-party challenges are solved and submitted from
      // their own button in the expanded panel below -- clicking the
      // checkbox itself does nothing but isn't an error either.
      return;
    }
    this.runVerification(e);
  };

  CaptchaWidget.prototype.runVerification = async function (e) {
    if (this.busy) return;
    this.busy = true;
    var rect = this.boxEl.getBoundingClientRect();
    var cx = rect.left + rect.width / 2, cy = rect.top + rect.height / 2;
    this.clickOffset = Math.hypot(e.clientX - cx, e.clientY - cy);
    var touchNote = (this.lastSeenPointerType === 'touch' || this.lastSeenPointerType === 'pen')
      ? ' [dokunmatik: yaklaşma+tıklama aynı dokunuşun parçası, bu normaldir]' : '';
    emit(this.token, 'widget: doğrulama tetiklendi', null,
      'merkezden sapma=' + this.clickOffset.toFixed(1) + 'px, ' + this.since(performance.now()) + 'ms' + touchNote);

    this.spinnerEl.style.display = 'inline-block';
    this.labelEl.textContent = 'Kontrol ediliyor...';
    var frozenSignals = this.currentSignals();
    await new Promise(function (r) { setTimeout(r, 600); });

    emit(this.token, 'widget: sunucuya gönderiliyor', null,
      'pointer_type=' + frozenSignals.pointer_type + ', pointer_moves=' + frozenSignals.pointer_moves +
      ', interaction_ms=' + frozenSignals.interaction_ms.toFixed(0));

    var resp = await fetch('/api/captcha/gate/' + this.token + '/verify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ captcha_response: this.captchaResponse, signals: frozenSignals }),
    });
    var result = await resp.json();
    this.spinnerEl.style.display = 'none';
    this.boxEl.classList.add('dwa-cw-done');

    if (result.verified) {
      this.checkboxEl.classList.add('dwa-cw-ok');
      this.checkboxEl.innerHTML = CHECK_SVG;
      this.labelEl.textContent = 'Doğrulandı';
      emit(this.token, 'widget: doğrulama sonucu', true);
    } else {
      this.checkboxEl.classList.add('dwa-cw-fail');
      this.checkboxEl.innerHTML = CROSS_SVG;
      this.labelEl.textContent = result.detail || 'Doğrulanamadı';
      emit(this.token, 'widget: doğrulama sonucu', false, result.failed_check || result.detail);
    }
    fireCallback(this.token, result);

    var self = this;
    setTimeout(function () {
      self.busy = false;
      self.boxEl.classList.remove('dwa-cw-done');
      self.checkboxEl.className = 'dwa-cw-checkbox';
      self.checkboxEl.innerHTML = '';
      self.labelEl.textContent = self.needsExplicitAnswer ? 'Tekrar deneyin' : 'İnsan olduğumu doğrula';
    }, 2500);
  };

  function init() {
    var nodes = document.querySelectorAll('.dwa-captcha-widget:not([data-dwa-initialized])');
    if (nodes.length === 0) return;
    injectStyles();
    nodes.forEach(function (el) {
      el.setAttribute('data-dwa-initialized', 'true');
      new CaptchaWidget(el);
    });
  }

  // Exposed so a page that injects `.dwa-captcha-widget` divs dynamically
  // (a fresh token after the initial page load, an SPA route change, ...)
  // can (re)scan for new ones without a full page reload.
  window.dwaCaptchaWidgetInit = init;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
