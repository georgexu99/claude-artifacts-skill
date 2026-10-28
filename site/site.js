// Renders the sidebar (every shell page and the gallery) and the gallery itself from
// manifest.json at load time, so publishing one artifact never rewrites the others.
// Manifest entry: {slug, title, emoji, project, group, state, next, nav, summary, claude_url, created, updated}
//   group: topic the page belongs to, "🧪 Build experiments" (emoji first, optional)
//   state: Open | Waiting | Done | Dropped (default Open)
//   next:  one line, what happens next (shown on Open/Waiting cards)
//   nav:   "monitoring" | "prs" puts the page in that sidebar section instead of a group
(function () {
  'use strict';
  var script = document.currentScript || document.querySelector('script[src$="site.js"]');
  var ROOT = script ? script.src.replace(/site\.js(\?.*)?$/, '') : './';
  var esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };
  var PALETTE = ['#d9488a', '#e8912d', '#3fa45b', '#2f80ed', '#8e5be8', '#e0533f', '#1aa5a5', '#c2410c', '#8a6fd4', '#2aa9d4'];
  var STATES = { Open: '#2563eb', Waiting: '#c2410c', Done: '#15803d', Dropped: '#6b7280' };
  var STATE_ORDER = ['Open', 'Waiting', 'Done', 'Dropped'];
  var NAV_ACCENT = '#5b6ee1';
  var STALE_DAYS = 30;

  function splitGroup(group) {
    var g = (group || '').trim();
    if (!g) return { emoji: '📄', name: 'Other' };
    var m = /^(\S+)\s+(.+)$/.exec(g);
    if (m && !/^[\w.-]+$/.test(m[1])) return { emoji: m[1], name: m[2] };
    return { emoji: '📄', name: g };
  }
  function colorOf(name) {
    var h = 0;
    for (var i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
    return PALETTE[h % PALETTE.length];
  }
  function stateOf(it) { return STATES[it.state] ? it.state : 'Open'; }
  function isDoc(it) { return !it.nav; }
  function byUpdated(a, b) { return (b.updated || '').localeCompare(a.updated || ''); }
  function daysSince(iso) { return iso ? Math.floor((Date.now() - new Date(iso).getTime()) / 864e5) : 0; }
  function ago(iso) {
    var d = daysSince(iso);
    return d <= 0 ? 'today' : d === 1 ? 'yesterday' : d + 'd ago';
  }
  function dateOf(iso) {
    return iso ? new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '';
  }
  function href(it) { return ROOT + it.slug + '/'; }
  function pill(st) { return '<span class="state-pill" style="--state:' + STATES[st] + '">' + st + '</span>'; }
  function dot(st) { return '<span class="state-dot" style="--state:' + STATES[st] + '" title="' + st + '"></span>'; }
  function stalePill(it) {
    var st = stateOf(it);
    return (st === 'Open' || st === 'Waiting') && daysSince(it.updated) >= STALE_DAYS
      ? '<span class="stale-pill" title="Not updated in ' + STALE_DAYS + '+ days">stale</span>' : '';
  }

  // Groups ordered by their newest entry; entries newest first within a group.
  function groups(items) {
    var byName = {}, order = [];
    items.filter(isDoc).sort(byUpdated).forEach(function (it) {
      var g = splitGroup(it.group);
      if (!byName[g.name]) { byName[g.name] = { name: g.name, emoji: g.emoji, color: colorOf(g.name), items: [] }; order.push(byName[g.name]); }
      byName[g.name].items.push(it);
    });
    return order;
  }

  function currentSlug() {
    var rel = location.pathname.replace(new URL(ROOT).pathname, '');
    return rel.split('/')[0] || '';
  }

  function navSection(title, list, slug) {
    if (!list.length) return '';
    return '<div class="nav-section"><div class="nav-title">' + esc(title) + '</div>' + list.map(function (it) {
      return '<a class="doc' + (it.slug === slug ? ' active' : '') + '" style="--doc-accent:' + NAV_ACCENT + '" href="' + esc(href(it)) + '">' +
        (it.emoji ? esc(it.emoji) + ' ' : '') + esc(it.title || it.slug) + '</a>';
    }).join('') + '</div>';
  }

  function renderNav(items, slug) {
    var links = document.querySelector('.nav-links');
    if (!links) return;
    if (!items.length) { links.innerHTML = '<div class="nav-empty">Nothing published yet.</div>'; return; }
    var monitoring = items.filter(function (it) { return it.nav === 'monitoring'; });
    var prs = items.filter(function (it) { return it.nav === 'prs'; });
    var docs = '<div class="nav-section"><div class="nav-title">Research &amp; Docs</div>' + groups(items).map(function (g) {
      var mine = g.items.some(function (it) { return it.slug === slug; });
      return '<details class="cat-group"' + (mine ? ' open' : '') + '><summary class="cat" style="--cat-accent:' + g.color + '">' +
        esc(g.emoji) + ' ' + esc(g.name) + '<span class="cat-count">' + g.items.length + '</span><span class="chevron">▶</span></summary>' +
        g.items.map(function (it) {
          return '<a class="doc' + (it.slug === slug ? ' active' : '') + '" style="--doc-accent:' + g.color + '" href="' + esc(href(it)) + '">' +
            esc(it.title || it.slug) + dot(stateOf(it)) + '</a>';
        }).join('') + '</details>';
    }).join('') + '</div>';
    links.innerHTML = navSection('Monitoring', monitoring, slug) + navSection('Pull requests', prs, slug) + docs;
    var legend = document.querySelector('.nav-legend');
    if (legend) legend.innerHTML = STATE_ORDER.map(function (st) { return '<span>' + dot(st) + st + '</span>'; }).join('');
  }

  function renderFoot(item) {
    var foot = document.querySelector('.nav-foot');
    if (!foot) return;
    var page = document.querySelector('.content iframe');
    var rows = [];
    if (page) rows.push('<a href="' + esc(page.getAttribute('src').split('#')[0]) + '" target="_top">Open page without sidebar ↗</a>');
    if (item && item.claude_url) rows.push('<a href="' + esc(item.claude_url) + '" target="_blank" rel="noopener">Open in claude.ai ↗</a>');
    if (page) rows.push('<a href="#" class="print">Print page</a>');
    rows.push('<a href="' + esc(ROOT) + '#instructions">Make your own site like this ↗</a>');
    foot.innerHTML = rows.join('');
    var pr = foot.querySelector('.print');
    if (pr) pr.addEventListener('click', function (e) { e.preventDefault(); printPage(); });
  }

  function comebackRows(items) {
    var open = items.filter(isDoc).filter(function (it) { var s = stateOf(it); return s === 'Open' || s === 'Waiting'; })
      .sort(function (a, b) { return (a.updated || '').localeCompare(b.updated || ''); });
    if (!open.length) return '';
    return '<section><h2 class="cat-heading"><span class="badge">📌</span>Come back to<span class="count">' + open.length + '</span></h2><div class="comeback-list">' +
      open.map(function (it) {
        var g = splitGroup(it.group);
        return '<a class="comeback-row" style="--card-accent:' + colorOf(g.name) + '" href="' + esc(href(it)) + '">' + pill(stateOf(it)) +
          '<span class="comeback-main"><span class="comeback-title">' + esc(it.title || it.slug) + '</span>' +
          (it.next ? '<span class="comeback-next">Next: ' + esc(it.next) + '</span>' : '') + '</span>' +
          '<span class="comeback-meta">' + stalePill(it) + '<span class="recent-time">' + ago(it.updated) + '</span></span></a>';
      }).join('') + '</div></section>';
  }

  function recentRows(items) {
    var recent = items.slice().sort(byUpdated).slice(0, 8);
    return '<section><h2 class="cat-heading"><span class="badge">🕒</span>Recently updated<span class="count">' + recent.length + '</span></h2><div class="recent-list">' +
      recent.map(function (it) {
        var g = splitGroup(it.group);
        var chip = it.nav ? '' : '<span class="card-cat">' + esc(g.emoji) + ' ' + esc(g.name) + '</span>';
        return '<a class="recent-row" style="--card-accent:' + (it.nav ? NAV_ACCENT : colorOf(g.name)) + '" href="' + esc(href(it)) + '"><span class="recent-title">' +
          (isDoc(it) ? dot(stateOf(it)) : '') + esc(it.title || it.slug) + '</span><span class="recent-meta">' + chip +
          '<span class="recent-time">' + dateOf(it.updated) + '</span></span></a>';
      }).join('') + '</div></section>';
  }

  function renderGallery(items) {
    var el = document.getElementById('gallery');
    if (!el) return;
    if (!items.length) { el.innerHTML = '<p>Nothing published yet.</p>'; return; }
    var docs = items.filter(isDoc);
    var count = function (st) { return docs.filter(function (it) { return stateOf(it) === st; }).length; };
    var week = items.filter(function (it) { return daysSince(it.updated) < 7; }).length;
    var cfg = document.body.dataset;
    var html = '<header class="hero"><div><h1 class="hero-title">' + esc(cfg.siteTitle || 'Claude Artifacts') + '</h1><p class="hero-sub">' + esc(cfg.siteSubtitle || 'Pages from my Claude Code sessions') + '</p></div>' +
      '<div class="search-wrap"><input class="search-input" type="search" placeholder="Search…" aria-label="Search docs" autocomplete="off" spellcheck="false"><div class="search-results"></div></div>' +
      '<div class="hero-stats"><div class="hero-stat"><b>' + docs.length + '</b><span>docs</span></div><div class="hero-stat"><b>' + count('Open') + '</b><span>open</span></div>' +
      '<div class="hero-stat"><b>' + count('Waiting') + '</b><span>waiting</span></div><div class="hero-stat"><b>' + week + '</b><span>this week</span></div></div></header>';
    html += '<div class="top-rails">' + comebackRows(items) + recentRows(items) + '</div>';
    html += '<div class="state-filter" role="group" aria-label="Filter docs by state"><button type="button" class="filter-btn" data-filter="All" aria-pressed="true">All <span>' + docs.length + '</span></button>' +
      STATE_ORDER.map(function (st) {
        return '<button type="button" class="filter-btn" data-filter="' + st + '" aria-pressed="false" style="--state:' + STATES[st] + '">' + st + ' <span>' + count(st) + '</span></button>';
      }).join('') + '</div>';
    html += groups(items).map(function (g) {
      return '<section class="cat-section"><h2 class="cat-heading"><span class="badge">' + esc(g.emoji) + '</span>' + esc(g.name) + '<span class="count">' + g.items.length + '</span></h2><div class="card-grid">' +
        g.items.map(function (it) {
          var st = stateOf(it);
          var body = it.next && (st === 'Open' || st === 'Waiting') ? '<div class="card-next">Next: ' + esc(it.next) + '</div>'
            : it.summary ? '<div class="card-summary">' + esc(it.summary) + '</div>' : '';
          return '<a class="card" data-state="' + st + '" style="--card-accent:' + g.color + '" href="' + esc(href(it)) + '"><div class="card-title">' +
            (it.emoji ? esc(it.emoji) + ' ' : '') + esc(it.title || it.slug) + '</div>' + body +
            '<div class="card-meta">' + pill(st) + '<span>updated ' + dateOf(it.updated) + '</span></div></a>';
        }).join('') + '</div></section>';
    }).join('');
    el.innerHTML = html;
    wireFilter(el);
    wireSearch(el.querySelector('.search-wrap'), items);
  }

  function wireFilter(root) {
    var buttons = root.querySelectorAll('.filter-btn');
    buttons.forEach(function (b) {
      b.addEventListener('click', function () {
        var f = b.getAttribute('data-filter');
        buttons.forEach(function (o) { o.setAttribute('aria-pressed', String(o === b)); });
        root.querySelectorAll('.cat-section').forEach(function (sec) {
          var shown = 0;
          sec.querySelectorAll('.card').forEach(function (c) {
            var hit = f === 'All' || c.getAttribute('data-state') === f;
            c.hidden = !hit;
            if (hit) shown++;
          });
          sec.hidden = shown === 0;
        });
      });
    });
  }

  // Client-side search over titles, summaries, groups and "next" lines.
  function wireSearch(wrap, items) {
    if (!wrap) return;
    var input = wrap.querySelector('.search-input'), box = wrap.querySelector('.search-results'), focused = -1;
    function close() { box.classList.remove('open'); box.innerHTML = ''; focused = -1; }
    function render(q) {
      var needle = q.trim().toLowerCase();
      if (!needle) { close(); return; }
      var hits = items.filter(function (it) {
        return [it.title, it.summary, it.group, it.next, it.slug].join(' ').toLowerCase().indexOf(needle) !== -1;
      }).slice(0, 8);
      box.innerHTML = hits.length ? hits.map(function (it) {
        var text = it.summary || it.next || splitGroup(it.group).name;
        var i = text.toLowerCase().indexOf(needle);
        var snippet = i === -1 ? esc(text.slice(0, 90))
          : esc(text.slice(Math.max(0, i - 30), i)) + '<mark>' + esc(text.substr(i, needle.length)) + '</mark>' + esc(text.slice(i + needle.length, i + 60));
        return '<a class="search-result" href="' + esc(href(it)) + '"><span class="sr-title">' + (it.emoji ? esc(it.emoji) + ' ' : '') + esc(it.title || it.slug) + '</span><div class="sr-snippet">' + snippet + '</div></a>';
      }).join('') : '<div class="search-no-results">No matches</div>';
      box.classList.add('open'); focused = -1;
    }
    input.addEventListener('input', function () { render(input.value); });
    input.addEventListener('focus', function () { if (input.value) render(input.value); });
    input.addEventListener('keydown', function (e) {
      var results = box.querySelectorAll('.search-result');
      if (e.key === 'Escape') { close(); input.blur(); }
      else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        if (!results.length) return;
        e.preventDefault();
        focused = (focused + (e.key === 'ArrowDown' ? 1 : -1) + results.length) % results.length;
        results.forEach(function (r, i) { r.classList.toggle('focused', i === focused); });
      } else if (e.key === 'Enter') {
        var target = results[focused >= 0 ? focused : 0];
        if (target) location.href = target.getAttribute('href');
      }
    });
    document.addEventListener('click', function (e) { if (!wrap.contains(e.target)) close(); });
  }

  // Shell only: the artifact lives in the iframe; keep the outer URL's hash in sync
  // so deep links into the page still work when shared.
  function wireFrame() {
    var frame = document.querySelector('.content iframe');
    if (!frame) return;
    var base = frame.getAttribute('src');
    if (location.hash) frame.src = base + location.hash;
    frame.addEventListener('load', function () {
      try {
        // A redirect or link to another artifact must not nest a second sidebar.
        var here = frame.contentWindow.location;
        if (here.origin === location.origin && !/\/page\.html$/.test(here.pathname)) { location.replace(here.href); return; }
        frame.contentWindow.focus();
        frame.contentWindow.addEventListener('hashchange', function () {
          history.replaceState(null, '', location.pathname + location.search + frame.contentWindow.location.hash);
        });
        frame.contentWindow.addEventListener('keydown', onPrintKey);
        // GitHub (and most sites) send X-Frame-Options: deny, so off-site links must leave the frame.
        frame.contentDocument.addEventListener('click', function (e) {
          var a = e.target.closest && e.target.closest('a[href]');
          if (!a || (a.target && a.target !== '_self')) return;
          var url = new URL(a.getAttribute('href'), frame.contentWindow.location.href);
          if (url.origin === location.origin || !/^https?:$/.test(url.protocol)) return;
          e.preventDefault();
          window.open(url.href, '_blank', 'noopener');
        }, true);
      } catch (e) { /* cross-origin (e.g. session redirect); nothing to sync */ }
    });
    window.addEventListener('hashchange', function () {
      try { frame.contentWindow.location.hash = location.hash; } catch (e) { /* cross-origin */ }
    });
    window.addEventListener('keydown', onPrintKey);
  }

  function printPage() {
    var frame = document.querySelector('.content iframe');
    try { frame.contentWindow.focus(); frame.contentWindow.print(); } catch (e) { window.print(); }
  }
  function onPrintKey(e) {
    if ((e.metaKey || e.ctrlKey) && e.key === 'p') { e.preventDefault(); printPage(); }
  }

  function wireTheme() {
    var root = document.documentElement, toggle = document.querySelector('.theme-toggle');
    if (!toggle) return;
    var isDark = function () { return root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches; };
    toggle.setAttribute('aria-pressed', String(isDark()));
    toggle.addEventListener('click', function () {
      root.dataset.theme = isDark() ? 'light' : 'dark';
      toggle.setAttribute('aria-pressed', String(isDark()));
      try { localStorage.setItem('claude-artifacts-theme', root.dataset.theme); } catch (e) { /* private window */ }
    });
  }

  function wireInstructions() {
    var copy = document.querySelector('.copy-prompt'), raw = document.getElementById('prompt-raw');
    if (copy && raw) copy.addEventListener('click', function () {
      var done = function (msg) { copy.textContent = msg; setTimeout(function () { copy.textContent = 'Copy prompt'; }, 1600); };
      if (navigator.clipboard) navigator.clipboard.writeText(raw.value).then(function () { done('Copied'); }, function () { done('Copy failed'); });
      else done('Copy failed');
    });
    var det = document.getElementById('instructions');
    if (det && location.hash === '#instructions') det.open = true;
  }

  var toggle = document.querySelector('.nav-toggle');
  if (toggle) toggle.addEventListener('click', function () { document.querySelector('.sidebar').classList.toggle('open'); });
  wireFrame();
  wireTheme();
  wireInstructions();

  fetch(ROOT + 'manifest.json', { cache: 'no-store', credentials: 'same-origin' })
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(function (items) {
      if (!Array.isArray(items)) items = [];
      var slug = currentSlug();
      var me = items.filter(function (it) { return it.slug === slug; })[0];
      if (me && me.title) document.title = me.title;
      renderNav(items, slug);
      renderFoot(me);
      renderGallery(items);
      wireSearch(document.querySelector('.sidebar .search-wrap'), items);
    })
    .catch(function (err) {
      var links = document.querySelector('.nav-links');
      if (links) links.innerHTML = '<div class="nav-empty">Could not load the index (' + esc(err.message) + '). <a href="' + esc(ROOT) + '" style="color:#fff">Reload</a></div>';
    });
})();
