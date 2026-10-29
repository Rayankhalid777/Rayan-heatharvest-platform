/* HeatHarvest detailed study form: builds the site data and sends it to the server. */
(function () {
  'use strict';
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var form = $('#study-form');
  var list = $('#sources');
  var tpl = $('#source-tpl');
  var MAX = 12;

  var FALLBACK = {
    cities: ['Riyadh', 'Al-Kharj', 'Dammam', 'Jubail', 'Ras Al-Khair', 'Hofuf', 'Jeddah', 'Makkah', 'Rabigh', 'Yanbu', 'Taif', 'Madinah', 'Buraydah', 'Hail', 'Tabuk', 'Turaif', 'Bisha', 'Jazan', 'Najran', 'Abu Dhabi (UAE)', 'Doha (Qatar)', 'Kuwait City (Kuwait)', 'Manama (Bahrain)', 'Muscat (Oman)'],
    sectors: { cement: 'Cement', glass: 'Glass', steel: 'Steel', gas_compression: 'Gas compression or pipeline pumping', power: 'Power generation', chemicals: 'Chemicals, aluminium or other process industry', other: 'Other' }
  };

  function fillSelects(meta) {
    var city = $('#f-city'), sector = $('#f-sector');
    city.innerHTML = meta.cities.map(function (c) { return '<option>' + c + '</option>'; }).join('');
    sector.innerHTML = Object.keys(meta.sectors).map(function (k) { return '<option value="' + k + '">' + meta.sectors[k] + '</option>'; }).join('');
    prefill();
  }

  function renumber() {
    $$('.source', list).forEach(function (li, i) {
      $('.n', li).textContent = i + 1;
      $('.source__remove', li).hidden = list.children.length === 1;
    });
    $('#add-source').hidden = list.children.length >= MAX;
  }

  function addSource(values) {
    var node = tpl.content.firstElementChild.cloneNode(true);
    var idx = list.children.length + 1;
    $$('[data-k]', node).forEach(function (el) {
      el.id = 's' + idx + '-' + el.dataset.k + '-' + Date.now();
      if (values && values[el.dataset.k] != null) el.value = values[el.dataset.k];
    });
    $('.source__remove', node).addEventListener('click', function () { node.remove(); renumber(); });
    list.appendChild(node);
    renumber();
    return node;
  }

  function prefill() {
    var p = new URLSearchParams(location.search);
    var mode = p.get('mode');
    if (mode === 'kiln') {
      $('#f-sector').value = 'cement';
      addSource({ name: 'Preheater exhaust', temp_in_c: 330, dust: 'high' });
      addSource({ name: 'Clinker cooler vent air', temp_in_c: 280, dust: 'medium' });
      if (p.get('clinker')) form.notes.value = 'Clinker capacity about ' + p.get('clinker') + ' t/day.';
    } else if (mode === 'turbine') {
      $('#f-sector').value = 'gas_compression';
      addSource({ name: 'Gas turbine exhaust', temp_in_c: p.get('gtT') || 500, dust: 'low' });
      if (p.get('gt')) form.notes.value = 'Gas turbine rating about ' + p.get('gt') + ' MW.';
    } else if (mode === 'exhaust') {
      addSource({ name: 'Exhaust stack', flow: p.get('flow') || '', temp_in_c: p.get('T') || '' });
    } else {
      addSource();
    }
    if (p.get('hours')) form.operating_hours.value = p.get('hours');
    if (p.get('price')) form.electricity_value_sar_kwh.value = p.get('price');
  }

  fetch('/api/meta').then(function (r) { if (!r.ok) throw 0; return r.json(); }).then(fillSelects).catch(function () { fillSelects(FALLBACK); });
  $('#add-source').addEventListener('click', function () { var n = addSource(); $('input', n).focus(); });

  $$('input[name="value_basis"]').forEach(function (r) {
    r.addEventListener('change', function () {
      var basis = $('input[name="value_basis"]:checked').value;
      $$('[data-basis]').forEach(function (el) { el.hidden = el.dataset.basis !== basis; });
    });
  });

  function num(v) { var n = parseFloat(v); return isFinite(n) ? n : null; }

  function collect() {
    var f = form;
    var sources = $$('.source', list).map(function (li) {
      var g = function (k) { return $('[data-k="' + k + '"]', li).value.trim(); };
      var s = { name: g('name'), temp_in_c: num(g('temp_in_c')), dust: g('dust'), hours_share: Math.min(1, Math.max(0.01, (num(g('hours_pct')) || 100) / 100)) };
      var flow = num(g('flow'));
      if (g('flow_unit') === 'nm3_h') s.volume_flow_nm3_h = flow; else s.mass_flow_kg_s = flow;
      var mo = num(g('min_outlet_c')); if (mo !== null) s.min_outlet_c = mo;
      return s;
    });
    var basis = $('input[name="value_basis"]:checked').value;
    var site = {
      company: f.company.value.trim(), site_name: f.site_name.value.trim(), city: f.city.value, sector: f.sector.value,
      heat_sources: sources, operating_hours: num(f.operating_hours.value) || 8000, value_basis: basis,
      electricity_value_sar_kwh: num(f.electricity_value_sar_kwh.value) || 0,
      gas_price_usd_mmbtu: num(f.gas_price_usd_mmbtu.value) || 0,
      gas_generation_efficiency: (num(f.gas_generation_efficiency.value) || 33) / 100,
      notes: f.notes.value.trim() || null
    };
    var area = num(f.available_area_m2.value); if (area) site.available_area_m2 = area;
    return {
      contact: { name: f.c_name.value.trim(), email: f.c_email.value.trim(), phone: f.c_phone.value.trim(), role: f.c_role.value.trim() },
      site: site, consent: f.consent.checked, website: f.website.value
    };
  }

  function firstInvalid() {
    var bad = $$('input[required]:not([type="checkbox"]), select[required]', form).filter(function (el) { return !el.checkValidity(); });
    return bad[0] || null;
  }

  var FRIENDLY = {
    'contact › email': 'Check your email address.',
    'site › company': 'Add your company name.',
    'site › site_name': 'Add the site or plant name.'
  };

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var status = $('#sf-status');
    status.className = 'sf__status';
    var bad = firstInvalid();
    if (bad) {
      status.classList.add('is-error');
      var label = bad.closest('label');
      var name = label ? Array.prototype.filter.call(label.childNodes, function (n) { return n.nodeType === 3; }).map(function (n) { return n.textContent; }).join(' ').trim() : '';
      var src = bad.closest('.source');
      status.textContent = 'Fill in ' + (src ? 'stream ' + $('.n', src).textContent + ': ' : '') + (name ? name.toLowerCase() : 'the highlighted field') + ' before sending.';
      bad.focus();
      return;
    }
    if (!form.consent.checked) {
      status.classList.add('is-error');
      status.textContent = 'Tick the box to let us use this data for your study.';
      form.consent.focus();
      return;
    }
    var btn = $('#sf-submit');
    btn.disabled = true; btn.textContent = 'Sending…';
    var payload = collect();
    fetch('/api/study-requests', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j, code: r.status }; }, function () { return { ok: false, j: {}, code: r.status }; }); })
      .then(function (res) {
        if (res.ok && res.j.ok) {
          form.hidden = true;
          $('#done-id').textContent = '#' + res.j.id;
          $('#done-email').textContent = payload.contact.email;
          var done = $('#sf-done'); done.hidden = false; done.focus();
          window.scrollTo({ top: 0, behavior: 'smooth' });
          return;
        }
        btn.disabled = false; btn.textContent = 'Send my site data';
        status.classList.add('is-error');
        if (res.code === 429) { status.textContent = 'Too many requests from this connection. Try again in an hour, or email us.'; return; }
        var errs = (res.j.errors || []).map(function (m) {
          var key = Object.keys(FRIENDLY).find(function (k) { return m.indexOf(k) === 0; });
          return key ? FRIENDLY[key] : m.replace(/^site › heat_sources › (\d+) › /, function (_, n) { return 'Stream ' + (parseInt(n, 10) + 1) + ': '; }).replace(/^site › /, '').replace(/^contact › /, '');
        });
        status.innerHTML = errs.length ? 'Please fix this and send again:<ul>' + errs.map(function (x) { return '<li>' + x.replace(/</g, '&lt;') + '</li>'; }).join('') + '</ul>' : 'The data could not be sent. Try again, or email us.';
      })
      .catch(function () {
        btn.disabled = false; btn.textContent = 'Send my site data';
        status.classList.add('is-error');
        status.textContent = 'The data could not be sent from here. Check your connection and try again, or email awad.alquaity@kfupm.edu.sa.';
      });
  });
})();
