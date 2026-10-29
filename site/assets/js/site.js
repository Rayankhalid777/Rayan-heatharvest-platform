/* HeatHarvest site script: estimator, accordion, inquiry form and motion. No build step. */
(function () {
  'use strict';
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------------- Estimator ----------------
     Screening rules (indicative; see README):
     - Cement: 0.5–1.0 kWe per tonne/day of clinker capacity.
     - Gas turbine: exhaust heat = P × (1/η − 1) × 0.9 with η = 0.33; cooled to 150 °C from ambient 35 °C reference.
     - Any exhaust: Q = ṁ × 1.1 kJ/kg·K × (T − 150 °C).
     - ORC net efficiency on recovered heat: 14–19 % (Saudi ambient, air-cooled).
     - CO2: 0.46 t/MWh (37,000 t / 80 GWh, Riyadh Cement published figures). */
  var MODES = {
    kiln: { label: 'Drawing of a cement kiln with its preheater tower and stack', fact: 'Kiln preheater gas leaves at about 300–380 °C, and clinker cooler air at about 250–400 °C.', hours: 7500 },
    turbine: { label: 'Drawing of a gas turbine with its exhaust stack', fact: 'Simple-cycle gas turbine exhaust usually leaves at 450–550 °C, hot enough for ORC at almost any size.', hours: 8000 },
    exhaust: { label: 'Drawing of an exhaust stack with heat rising from it', fact: 'Large streams can work down to about 150 °C. Small ones need about 300 °C or more to pay back.', hours: 8000 }
  };
  var ETA = [0.14, 0.19];
  var CO2 = 0.46;
  var mode = 'kiln';
  var last = null;

  var fmt = function (n, d) { return n.toLocaleString('en-US', { maximumFractionDigits: d || 0, minimumFractionDigits: d || 0 }); };
  var sig = function (n) { // two significant figures for big numbers
    if (n >= 100) { var p = Math.pow(10, Math.floor(Math.log10(n)) - 1); return Math.round(n / p) * p; }
    return n;
  };
  var range = function (a, b, d, unit) {
    return fmt(a, d) + '–' + fmt(b, d) + (unit ? ' ' + unit : '');
  };
  var dp = function (x) { return x < 10 ? 1 : 0; };
  var power = function (lo, hi) {
    if (hi < 1) { var k = function (x) { return Math.round(x * 100) * 10; }; return range(k(lo), k(hi)) + ' kWe'; }
    return range(lo, hi, dp(lo)) + ' MWe';
  };

  function val(id) { var el = document.getElementById(id); return el ? parseFloat(el.value) : 0; }

  function compute() {
    var lo, hi, heat = null, T = null;
    if (mode === 'kiln') {
      var c = val('in-clinker');
      lo = c * 0.5 / 1000; hi = c * 1.0 / 1000;
    } else if (mode === 'turbine') {
      var P = val('in-gt'); T = val('in-gtT');
      var exh = P * (1 / 0.33 - 1) * 0.9;
      heat = exh * Math.max(0, (T - 150)) / (T - 35);
      lo = heat * ETA[0]; hi = heat * ETA[1];
    } else {
      var m = val('in-flow'); T = val('in-T');
      heat = m * 1.1 * Math.max(0, T - 150) / 1000;
      lo = heat * ETA[0]; hi = heat * ETA[1];
    }
    var h = val('in-hours');
    var price = Math.max(0, val('in-price') || 0);
    var gwhLo = lo * h / 1000, gwhHi = hi * h / 1000;
    return { lo: lo, hi: hi, heat: heat, T: T, h: h, price: price,
      gwhLo: gwhLo, gwhHi: gwhHi,
      co2Lo: gwhLo * 1000 * CO2, co2Hi: gwhHi * 1000 * CO2,
      sarLo: gwhLo * 1e6 * price, sarHi: gwhHi * 1e6 * price };
  }

  function render() {
    var r = compute(); last = r;
    var out = function (id, txt) { var el = document.getElementById(id); if (el) el.textContent = txt; };
    out('out-clinker', fmt(val('in-clinker')) + ' t/day');
    out('out-gt', fmt(val('in-gt')) + ' MW');
    out('out-gtT', fmt(val('in-gtT')) + ' °C');
    out('out-flow', fmt(val('in-flow')) + ' kg/s');
    out('out-T', fmt(val('in-T')) + ' °C');
    out('out-hours', fmt(val('in-hours')) + ' h');

    if (r.hi < 0.05) {
      out('r-mwe', 'Too little heat');
      ['r-gwh', 'r-co2', 'r-sar'].forEach(function (id) { out(id, '–'); });
    } else {
      out('r-mwe', power(r.lo, r.hi));
      out('r-gwh', range(r.gwhLo, r.gwhHi, dp(r.gwhLo)) + ' GWh');
      out('r-co2', range(sig(r.co2Lo), sig(r.co2Hi)) + ' t');
      var m = function (x) { return x / 1e6; };
      out('r-sar', 'SAR ' + range(m(r.sarLo), m(r.sarHi), m(r.sarLo) < 10 ? 1 : 0) + ' million');
    }
    out('r-heat', r.heat === null ? 'Based on kiln size' : fmt(r.heat, r.heat < 10 ? 1 : 0) + ' MW of heat');

    var v = $('#verdict');
    var tone = 'ok', msg;
    if (r.hi < 0.5) { tone = 'low'; msg = 'Below the smallest commercial ORC units, about 0.5 MWe. A heat pump or direct use of the heat may fit better. We can check.'; }
    else if (r.lo < 5 && r.T !== null && r.T < 300) { tone = 'low'; msg = 'At this size, heat below about 300 °C is rarely economic for ORC. Worth checking other uses of the heat.'; }
    else if (r.lo < 0.5) { msg = 'Borderline. The result depends on your site data, so a closer look is worthwhile.'; }
    else { msg = 'Worth a closer look. A site of this size can usually support an ORC unit.'; }
    v.textContent = msg; v.setAttribute('data-tone', tone);
    var link = $('#send-est'); if (link) link.setAttribute('href', studyLink());
    askServer();
  }

  var serverTimer = null, serverSeq = 0;
  function askServer() {
    clearTimeout(serverTimer);
    serverTimer = setTimeout(function () {
      var seq = ++serverSeq;
      var body = { mode: mode, clinker_tpd: val('in-clinker'), gt_mw: val('in-gt'), gt_exhaust_c: val('in-gtT'),
        flow_kg_s: val('in-flow'), gas_c: val('in-T'), hours: val('in-hours'), price_sar_kwh: Math.max(0, val('in-price') || 0) };
      fetch('/api/quick-estimate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
        .then(function (r) { if (!r.ok) throw 0; return r.json(); })
        .then(function (s) {
          if (seq !== serverSeq) return;
          var out = function (id, txt) { var el = document.getElementById(id); if (el) el.textContent = txt; };
          if (s.mwe[1] < 0.05) return;
          out('r-mwe', power(s.mwe[0], s.mwe[1]));
          out('r-gwh', range(s.gwh[0], s.gwh[1], dp(s.gwh[0])) + ' GWh');
          out('r-co2', range(sig(s.co2_t[0]), sig(s.co2_t[1])) + ' t');
          var m = function (x) { return x / 1e6; };
          out('r-sar', 'SAR ' + range(m(s.sar[0]), m(s.sar[1]), m(s.sar[0]) < 10 ? 1 : 0) + ' million');
          var v = $('#verdict'); v.textContent = s.verdict; v.setAttribute('data-tone', s.tone);
        })
        .catch(function () { /* keep the in-page estimate */ });
    }, 160);
  }

  function setMode(next) {
    mode = next;
    $$('.mode-btn').forEach(function (b) { b.setAttribute('aria-pressed', String(b.dataset.mode === next)); });
    $$('.field[data-for]').forEach(function (f) { f.hidden = f.dataset.for !== next; });
    var disc = $('#disc');
    disc.dataset.mode = next;
    disc.setAttribute('aria-label', MODES[next].label);
    $$('.obj', disc).forEach(function (o) { o.classList.toggle('is-on', o.dataset.obj === next); });
    $('#fact').textContent = MODES[next].fact;
    var hours = $('#in-hours'); if (hours) hours.value = MODES[next].hours;
    render();
  }

  $$('.mode-btn').forEach(function (b) { b.addEventListener('click', function () { setMode(b.dataset.mode); }); });
  $$('#est-form input').forEach(function (i) { i.addEventListener('input', render); });
  var estForm = $('#est-form'); if (estForm) estForm.addEventListener('submit', function (e) { e.preventDefault(); });

  function studyLink() {
    var p = new URLSearchParams({ mode: mode, hours: val('in-hours'), price: val('in-price') });
    if (mode === 'kiln') p.set('clinker', val('in-clinker'));
    if (mode === 'turbine') { p.set('gt', val('in-gt')); p.set('gtT', val('in-gtT')); }
    if (mode === 'exhaust') { p.set('flow', val('in-flow')); p.set('T', val('in-T')); }
    return 'study.html?' + p.toString();
  }

  if ($('#disc')) render();

  /* ---------------- Accordion ---------------- */
  var items = $$('.acc__item');
  items.forEach(function (it) {
    var btn = $('.acc__btn', it);
    btn.addEventListener('click', function () {
      items.forEach(function (o) {
        var open = o === it;
        o.classList.toggle('is-open', open);
        $('.acc__btn', o).setAttribute('aria-expanded', String(open));
      });
      var body = $('.acc__body', it); var h = body && $('h3', body);
      if (h) { h.setAttribute('tabindex', '-1'); h.focus({ preventScroll: true }); }
    });
  });

  /* ---------------- Inquiry form ----------------
     Posts to the HeatHarvest server (/api/inquiries), which stores it and notifies the team.
     If the server cannot be reached, the visitor is offered a ready-written email instead. */
  var form = $('#inquiry');
  if (form) form.addEventListener('submit', function (e) {
    e.preventDefault();
    var status = $('#form-status');
    var name = $('#f-name'), email = $('#f-email');
    if (!name.value.trim()) { status.dataset.state = 'error'; status.textContent = 'Add your name so we know who to reply to.'; name.focus(); return; }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.value.trim())) { status.dataset.state = 'error'; status.textContent = 'Add an email address we can reply to, like name@company.com.'; email.focus(); return; }
    var data = new FormData(form);
    var btn = $('.submit', form);
    btn.disabled = true; btn.textContent = 'Sending…'; status.dataset.state = ''; status.textContent = '';
    var endpoint = form.dataset.endpoint || '/api/inquiries';
    var payload = {}; data.forEach(function (v, k) { payload[k] = v; });
    var body = JSON.stringify(payload);
    var headers = { 'Content-Type': 'application/json', 'Accept': 'application/json' };
    fetch(endpoint, { method: 'POST', headers: headers, body: body })
      .then(function (res) { if (!res.ok) throw new Error(res.status); })
      .then(function () {
        form.reset();
        btn.textContent = 'Sent';
        status.textContent = 'Thank you. We have your request and will reply by email within a few days.';
      })
      .catch(function () {
        btn.disabled = false; btn.textContent = 'Send inquiry';
        var subject = encodeURIComponent('Site inquiry from ' + data.get('name'));
        var lines = ['Name: ' + data.get('name'), 'Email: ' + data.get('email'), 'Company and site: ' + (data.get('company') || ''), 'Role: ' + (data.get('role') || ''), '', data.get('message') || ''];
        if (data.get('estimate')) lines.push('', 'Estimate: ' + data.get('estimate'));
        status.dataset.state = 'error';
        status.innerHTML = 'The form could not send from here. <a class="link" style="color:#fff;text-decoration-color:#fff" href="mailto:awad.alquaity@kfupm.edu.sa?subject=' + subject + '&body=' + encodeURIComponent(lines.join('\n')) + '">Send it by email instead</a>.';
      });
  });

  /* ---------------- Motion (GSAP) ---------------- */
  function motion() {
    if (!window.gsap || !window.ScrollTrigger) { $$('.shutter').forEach(function (s) { s.classList.add('is-in'); }); return; }
    gsap.registerPlugin(ScrollTrigger);
    var mm = gsap.matchMedia();

    mm.add('(prefers-reduced-motion: no-preference)', function () {
      // Signature: the two discs arrive, then drift apart as the page scrolls.
      gsap.from('[data-disc="heat"]', { scale: 0.72, duration: 1.4, ease: 'expo.out' });
      gsap.from('[data-disc="harvest"]', { scale: 0.4, autoAlpha: 0, duration: 1.2, delay: 0.25, ease: 'expo.out' });
      gsap.to('[data-disc="heat"]', { yPercent: 14, xPercent: 6, ease: 'none', scrollTrigger: { trigger: '.hero', start: 'top top', end: 'bottom top', scrub: 0.6 } });
      gsap.to('[data-disc="harvest"]', { yPercent: -22, xPercent: -10, ease: 'none', scrollTrigger: { trigger: '.hero', start: 'top top', end: 'bottom top', scrub: 0.6 } });

      // Section entrances: parts arrive in order, once.
      $$('main > section:not(.hero)').forEach(function (sec) {
        var parts = $$('[data-reveal]', sec);
        if (!parts.length) return;
        gsap.from(parts, { y: 26, autoAlpha: 0, duration: 0.8, ease: 'expo.out', stagger: 0.08,
          scrollTrigger: { trigger: sec, start: 'top 78%', once: true } });
      });

      // Shutter on the estimator picture.
      ScrollTrigger.create({ trigger: '#disc', start: 'top 80%', once: true, onEnter: function () { $('#disc').classList.add('is-in'); } });

      // Rolling figures.
      $$('[data-count]').forEach(function (el) {
        var end = parseFloat(el.dataset.count); var o = { v: 0 };
        gsap.to(o, { v: end, duration: 1.4, ease: 'power3.out', scrollTrigger: { trigger: el, start: 'top 85%', once: true },
          onUpdate: function () { el.textContent = Math.round(o.v).toLocaleString('en-US'); } });
      });

      // Map: priority sites pulse in after the tile arrives.
      gsap.from('.map-dot', { scale: 0, transformOrigin: '50% 50%', duration: 0.5, ease: 'back.out(2)', stagger: { each: 0.025, from: 'random' },
        scrollTrigger: { trigger: '.tile--map', start: 'top 75%', once: true } });

      // Footer mark: blocks rise from the baseline.
      gsap.from('.blockmark span', { scaleY: 0, transformOrigin: '50% 100%', duration: 0.9, ease: 'expo.out', stagger: 0.04,
        scrollTrigger: { trigger: '.blockmark', start: 'top 85%', once: true } });
    });

    mm.add('(prefers-reduced-motion: reduce)', function () {
      $$('.shutter').forEach(function (s) { s.classList.add('is-in'); });
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', motion); else motion();
})();
