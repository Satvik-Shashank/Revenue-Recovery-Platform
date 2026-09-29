/* Shared UI toolkit: icons, count-up numbers, scroll reveal, spotlight/tilt effects, route progress bar.
   Every effect respects prefers-reduced-motion. */
(function () {
  'use strict';
  const reduce = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const ease = (t) => (t === 1 ? 1 : 1 - Math.pow(2, -10 * t));                 // easeOutExpo

  const ICONS = {
    card: '<rect x="2" y="5" width="20" height="14" rx="2.5"/><path d="M2 10h20M6 15h4"/>',
    shield: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
    users: '<circle cx="9" cy="8" r="3.2"/><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6"/><circle cx="17.5" cy="9" r="2.5"/><path d="M16.5 14.2c2.6.2 4.5 2.2 4.5 4.8"/>',
    file: '<path d="M6 3h8l5 5v13H6z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>',
    plug: '<path d="M9 2v5M15 2v5M6 7h12v3a6 6 0 0 1-12 0zM12 16v6"/>',
    spark: '<path d="M12 3l1.9 5.6L19.5 10.5l-5.6 1.9L12 18l-1.9-5.6L4.5 10.5l5.6-1.9z"/><path d="M19 3v3M20.5 4.5h-3"/>',
    bolt: '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
    check: '<path d="M5 12.5l4.5 4.5L19 7"/>',
    lock: '<rect x="5" y="11" width="14" height="10" rx="2.5"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    chart: '<path d="M4 20V4M4 20h16"/><path d="M8 15l4-5 3 3 5-7"/>',
    arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    inbox: '<path d="M4 13l2-8h12l2 8v6H4z"/><path d="M4 13h5l1 2h4l1-2h5"/>',
    flask: '<path d="M9 3h6M10 3v6L4.5 19a2 2 0 0 0 1.8 3h11.4a2 2 0 0 0 1.8-3L14 9V3"/><path d="M8 15h8"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2.1 2.1M16.9 16.9L19 19M19 5l-2.1 2.1M7.1 16.9L5 19"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.5-4.5"/>',
    ledger: '<path d="M5 4h14v16H5zM9 4v16M12 9h4M12 13h4"/>',
    user: '<circle cx="12" cy="8" r="3.5"/><path d="M5 21c0-4 3.1-7 7-7s7 3 7 7"/>',
    link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3A4 4 0 0 0 11 18.7l1-1"/>',
    refresh: '<path d="M20 11a8 8 0 0 0-14.5-3.5M4 4v4h4M4 13a8 8 0 0 0 14.5 3.5M20 20v-4h-4"/>',
    undo: '<path d="M9 14L4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/>',
    pause: '<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>',
    trend: '<path d="M3 17l6-6 4 4 8-9"/><path d="M15 6h6v6"/>',
    globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
  };
  const icon = (name, size = 20, cls = '') =>
    `<svg class="ico ${cls}" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ''}</svg>`;

  const FMT = {
    inr: (n) => '₹' + Math.round(n).toLocaleString('en-IN'),
    lakh: (n) => (Math.abs(n) >= 1e7 ? '₹' + (n / 1e7).toFixed(2) + ' Cr' : Math.abs(n) >= 1e5 ? '₹' + (n / 1e5).toFixed(2) + ' L' : '₹' + Math.round(n).toLocaleString('en-IN')),
    pct: (n) => (n * 100).toFixed(0) + '%', pct1: (n) => (n * 100).toFixed(1) + '%',
    int: (n) => Math.round(n).toLocaleString('en-IN'), pts: (n) => (n >= 0 ? '+' : '') + n.toFixed(1) + ' pts',
  };
  /** <span class="cu" data-v=".." data-f="inr">final text</span>; text is final for no-JS/reduced motion, animated on view. */
  const num = (v, f = 'inr') => `<span class="cu" data-v="${Number(v) || 0}" data-f="${f}">${(FMT[f] || FMT.int)(Number(v) || 0)}</span>`;

  function countUp(el, dur = 1300) {
    const to = Number(el.dataset.v), fmt = FMT[el.dataset.f] || FMT.int;
    if (reduce() || !isFinite(to)) { el.textContent = fmt(to); return; }
    const t0 = performance.now();
    const step = (t) => { const p = Math.min(1, (t - t0) / dur); el.textContent = fmt(to * ease(p)); if (p < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  }

  let io = null;
  function observer() {
    if (io) return io;
    io = new IntersectionObserver((entries) => {
      entries.forEach((en) => {
        if (!en.isIntersecting) return;
        const el = en.target; io.unobserve(el);
        el.classList.add('in');
        el.querySelectorAll('.cu').forEach((c) => countUp(c));
        if (el.classList.contains('cu')) countUp(el);
      });
    }, { threshold: 0.04, rootMargin: '0px 0px 12% 0px' });
    return io;
  }
  /** Stagger-reveal children of `root` matching `sel` as they scroll into view. */
  function reveal(root, sel = '.card, .pf-head, .pf-steps, .kpi, .rv', base = 0) {
    const o = observer();
    root.querySelectorAll(sel).forEach((el, i) => {
      if (el.closest('.reveal')) return;
      el.classList.add('reveal'); el.style.setProperty('--d', Math.min(i, 5) * 35 + base + 'ms');
      if (reduce()) { el.classList.add('in'); el.querySelectorAll('.cu').forEach((c) => countUp(c, 1)); } else o.observe(el);
    });
    root.querySelectorAll('.cu').forEach((c) => { if (!c.closest('.reveal')) o.observe(c); });
  }

  /** Cursor-following spotlight on cards (sets --mx/--my for a radial highlight). */
  function spotlight(root) {
    root.querySelectorAll('.spot').forEach((el) => {
      if (el._spot) return; el._spot = true;
      el.addEventListener('pointermove', (e) => { const r = el.getBoundingClientRect(); el.style.setProperty('--mx', e.clientX - r.left + 'px'); el.style.setProperty('--my', e.clientY - r.top + 'px'); });
    });
  }
  /** Gentle 3D tilt + parallax layers for the hero visual. */
  function tilt(el, strength = 6) {
    if (!el || reduce()) return;
    const move = (e) => {
      const r = el.getBoundingClientRect(), x = (e.clientX - r.left) / r.width - 0.5, y = (e.clientY - r.top) / r.height - 0.5;
      el.style.transform = `perspective(1100px) rotateY(${x * strength}deg) rotateX(${-y * strength}deg)`;
      el.style.setProperty('--px', x.toFixed(3)); el.style.setProperty('--py', y.toFixed(3));
    };
    const leave = () => { el.style.transform = ''; el.style.setProperty('--px', 0); el.style.setProperty('--py', 0); };
    el.addEventListener('pointermove', move); el.addEventListener('pointerleave', leave);
  }

  /** Thin route-progress bar at the very top of the viewport. */
  let bar = null, timer = null;
  function progress(state) {
    if (!bar) { bar = document.createElement('div'); bar.className = 'route-progress'; document.body.appendChild(bar); }
    clearTimeout(timer);
    if (state === 'start') { bar.style.transition = 'none'; bar.style.opacity = 1; bar.style.transform = 'scaleX(0)'; requestAnimationFrame(() => { bar.style.transition = 'transform 900ms cubic-bezier(.1,.7,.2,1)'; bar.style.transform = 'scaleX(.82)'; }); }
    else { bar.style.transition = 'transform 220ms ease-out, opacity 400ms ease 200ms'; bar.style.transform = 'scaleX(1)'; timer = setTimeout(() => { bar.style.opacity = 0; }, 260); }
  }


  /** Typewriter headline: types each word, holds, deletes, moves on. Returns a stop function. */
  function typeWords(el, words, { type = 55, erase = 28, hold = 1900 } = {}) {
    const tw = el.querySelector('.tw'); if (!tw || reduce()) return () => {};
    let i = 0, n = words[0].length, dir = -1, stopped = false, t;
    const tick = () => {
      if (stopped) return;
      const w = words[i];
      tw.textContent = w.slice(0, n);
      if (dir === 1) { if (n < w.length) { n++; t = setTimeout(tick, type); } else { dir = -1; t = setTimeout(tick, hold); } }
      else { if (n > 0) { n--; t = setTimeout(tick, erase); } else { dir = 1; i = (i + 1) % words.length; t = setTimeout(tick, 260); } }
    };
    t = setTimeout(tick, hold);
    return () => { stopped = true; clearTimeout(t); };
  }

  /** Rotating headline word. */
  function rotateWords(el, words, every = 2600) {
    if (!el || reduce()) return () => {};
    let i = 0; el.innerHTML = words.map((w, k) => `<span class="rw ${k === 0 ? 'on' : ''}">${w}</span>`).join('');
    const nodes = [...el.children];
    const w = Math.max(...nodes.map((n) => n.getBoundingClientRect().width)); if (w) el.style.minWidth = w + 'px';
    const id = setInterval(() => { nodes[i].classList.remove('on'); nodes[i].classList.add('out'); const p = nodes[i]; setTimeout(() => p.classList.remove('out'), 700); i = (i + 1) % nodes.length; nodes[i].classList.add('on'); }, every);
    return () => clearInterval(id);
  }

  window.UI = { icon, num, countUp, reveal, spotlight, tilt, progress, rotateWords, typeWords, FMT, reduce };
})();
