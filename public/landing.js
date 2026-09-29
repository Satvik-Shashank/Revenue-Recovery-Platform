/* Home: the landing page. Explains what Impulse does in plain language and links into the workspace.
   It makes no performance claims: anything shown from the demo workspace is labelled as sample data. */
(function () {
  'use strict';
  const { api, esc, inr, label, screens } = window.IMP;
  const { icon } = window.UI;
  const $ = (s, r) => (r || document).querySelector(s);

  const PILLARS = [
    { href: '#payments', icon: 'card', c: 'var(--s1)', name: 'Failed', title: 'Payment Recovery', what: 'A payment did not go through.', how: 'Impulse works out why it failed and picks the best next step: retry at a smarter time, or send the customer a link to fix their payment method.' },
    { href: '#clawback', icon: 'shield', c: 'var(--s2)', name: 'Clawed back', title: 'Clawback Defense', what: 'Money is taken back after the sale.', how: 'For each chargeback, refund request or risky COD order, Impulse weighs the options and recommends one: fight, concede, refund early or verify.' },
    { href: '#retention', icon: 'users', c: 'var(--s3)', name: 'Stopped', title: 'Retention Rescue', what: 'Customers quietly stop paying.', how: 'Impulse tells card problems from lost interest, and suggests the gentlest fix that is likely to keep the customer.' },
    { href: '#billing', icon: 'file', c: 'var(--s4)', name: 'Missed', title: 'Billing & Collections', what: 'Money was never billed or collected.', how: 'Contracts, usage and invoices are checked against each other, and overdue invoices are ranked so you chase the right ones first.' },
  ];
  const STEPS = [
    ['plug', 'Connect', 'Bring your payment data in.', ['Razorpay and Stripe events', 'CSV or Excel uploads', 'A REST API for custom events'], 'Start with a spreadsheet'],
    ['users', 'Understand', 'One clear picture of every customer.', ['The same person on two gateways becomes one profile', 'Customer value, trust and risk of leaving', 'History of every payment, refund and dispute'], 'No duplicate customers'],
    ['spark', 'Decide', 'Impulse recommends the best action.', ['Every option compared in rupees', 'The reason explained in plain words', 'Your guardrails always respected'], 'Nothing is a black box'],
    ['check', 'Act and check', 'You stay in control of the outcome.', ['Low-risk actions run on their own', 'Bigger ones wait for your approval', 'Every result is recorded'], 'Full audit trail'],
  ];
  const TRUST = [
    ['inbox', 'You stay in control', 'Choose what Impulse does on its own and what needs your approval.'],
    ['shield', 'Safe by default', 'It never retries a permanent decline, and never over-contacts a customer.'],
    ['ledger', 'Every result recorded', 'Each action and its outcome is listed, so nothing is a black box.'],
    ['lock', 'Light on data', 'Card numbers are never stored, only the tokens your gateway provides.'],
  ];
  const MEASURE = [
    ['users', 'A control group', 'A small share of cases stays on your current approach, so we can compare like with like.'],
    ['ledger', 'A record of every action', 'You can see each decision, the reason, and what happened next.'],
    ['check', 'Fees on real results only', 'You pay a share of what Impulse recovers beyond your own baseline.'],
  ];
  const DEMOS = [['moat_case', 'Keeps failing', 'trend'], ['serial_refunder', 'Frequent refunder', 'shield'], ['refund_vs_fight', 'Small dispute', 'card'], ['auto_dispute', 'Strong evidence', 'check']];
  const WORDS = ['failed payments', 'chargebacks', 'silent churn', 'missed invoices'];
  const KIND = { failed_payment: 'A failed payment', recovery_follow_up: 'A failed payment', chargeback: 'A chargeback', pre_dispute: 'An early dispute warning', refund_request: 'A refund request', rto_risk: 'A COD order', save: 'A customer at risk', compound: 'Several issues with one customer' };
  const plain = (r) => String(r || '').replace(/;?\s*EV\s*₹[-\d,]+\s*\([^)]*\)/g, '').replace(/\.;/g, '.').trim();
  const short = (s) => String(s || '').replace(/\s*\(.*\)/, '');

  screens.landing = async (el) => {
    const ribbon = window.__ribbonHTML || '';
    el.innerHTML = `
    <section class="lp-hero">${ribbon}<div class="lp-blobs"><i></i><i></i><i></i></div>
      <div class="lp-copy">
        <span class="hero-tag lp-fade" style="--d:0ms">${icon('bolt', 13)} Revenue Recovery Platform</span>
        <h1 class="lp-h1 lp-fade" style="--d:80ms">Stop losing money to <span class="rw-wrap" id="rw"><span class="rw on">${WORDS[0]}</span></span></h1>
        <p class="lp-sub lp-fade" style="--d:160ms">Impulse finds the places your business quietly loses revenue, recommends the best fix for each one, and explains why. You pay only when it recovers money.</p>
        <div class="lp-cta lp-fade" style="--d:240ms"><button class="btn-hero-primary shine" data-go="guide">How to get started ${icon('arrow', 16)}</button><button class="btn-hero-secondary" data-go="audit">Get a free Leak Audit</button></div>
        <div class="lp-trust lp-fade" style="--d:320ms"><span>${icon('check', 14)} Pay only on results</span><span>${icon('check', 14)} Every decision explained</span><span>${icon('check', 14)} You approve what matters</span></div>
      </div>
      <div class="lp-visual lp-fade" style="--d:200ms"><div class="lp-glass" id="lpv"><div class="lpg-bar"><i></i><i></i><i></i><span>Impulse · Sample workspace</span></div>
        <div class="lpg-body"><div class="lpg-title">Needs your attention</div><div class="lpg-list" id="lp-list"><div class="sk sk-line"></div><div class="sk sk-line"></div><div class="sk sk-line"></div></div>
          <div class="lpg-leaks">${['Failed', 'Clawed back', 'Stopped', 'Missed'].map((n, i) => `<span style="--c:${['var(--s1)', 'var(--s2)', 'var(--s3)', 'var(--s4)'][i]}"><i></i>${n}</span>`).join('')}</div></div>
        <div class="lp-chip c1"><span class="ci" style="--c:var(--s1)">${icon('refresh', 15)}</span><div><b>Retry when salaries land</b><small>Temporary decline</small></div></div>
        <div class="lp-chip c2"><span class="ci" style="--c:var(--s2)">${icon('shield', 15)}</span><div><b>Refund early</b><small>Cheaper than fighting</small></div></div>
        <div class="lp-chip c3"><span class="ci" style="--c:var(--s3)">${icon('pause', 15)}</span><div><b>Offer a pause</b><small>After repeated failures</small></div></div></div></div>
    </section>

    <div class="lp-marquee rv" aria-label="Sources"><div class="lp-track">${['Razorpay', 'Stripe', 'CSV & Excel upload', 'REST API', 'Razorpay', 'Stripe', 'CSV & Excel upload', 'REST API', 'Razorpay', 'Stripe', 'CSV & Excel upload', 'REST API'].map((n) => `<span>${n}</span>`).join('')}</div></div>
    <p class="lp-note rv">Connects to Razorpay and Stripe today. Other gateways and billing tools are next.</p>

    <section class="lp-sec" id="lp-start"><div class="lp-head rv"><span class="pf-tag"><i style="background:var(--brand-indigo)"></i>Getting started</span><h2>How to use Impulse</h2><p>A guided path for finance and operations teams. You start read-only, stay in control, and only move on when you are ready.</p></div>
      <div class="st-grid">${[['Run the free audit', 'Upload a spreadsheet export. No engineer needed.', 'search'], ['Connect a gateway', 'Add a Razorpay or Stripe webhook and send a test event.', 'plug'], ['Review recommendations', 'Impulse suggests, you compare with what your team would do.', 'inbox'], ['Automate and measure', 'Turn on low-risk actions. A control group measures the real gain.', 'check']].map(([t, d, ic], i) => `<div class="st-card rv" style="--d:${i * 50}ms"><span class="st-n">${i + 1}</span><span class="h-ico" style="--c:var(--brand-indigo)">${icon(ic, 20)}</span><h3>${t}</h3><p>${d}</p></div>`).join('')}</div>
      <div class="st-foot rv"><span>${icon('lock', 15)} Nothing changes in your systems until you allow it.</span><button class="primary" data-go="guide">Read the full guide ${icon('arrow', 14)}</button></div></section>

    <section class="lp-sec band" id="lp-problem"><div class="lp-head rv"><span class="pf-tag"><i style="background:var(--brand-rose)"></i>The problem</span><h2>Revenue leaks in four places</h2><p>Each one sits in a different tool and a different team, so nobody sees the whole picture. Impulse looks across all of them.</p></div>
      <div class="grid g4 lp-pillars">${PILLARS.map((p, i) => `<a class="lp-pillar spot rv" href="${p.href}" style="--c:${p.c};--d:${i * 70}ms"><span class="h-ico" style="--c:${p.c}">${icon(p.icon, 22)}</span><div class="lpp-name">${p.name}</div><h3>${p.title}</h3><p class="lpp-what">${p.what}</p><p>${p.how}</p><span class="lpp-go">Explore ${icon('arrow', 15)}</span></a>`).join('')}</div></section>

    <section class="lp-sec" id="lp-how"><div class="lp-head rv"><span class="pf-tag"><i style="background:var(--brand-indigo)"></i>How it works</span><h2>Four simple steps</h2></div>
      <div class="lp-steps"><div class="lp-line"><i></i></div>${STEPS.map(([ic, t, d, pts, foot], i) => `<div class="lp-step rv" style="--d:${i * 60}ms"><div class="lps-top"><span class="h-ico" style="--c:var(--brand-indigo)">${icon(ic, 22)}</span><span class="lps-n">0${i + 1}</span></div><h3>${t}</h3><p class="lps-d">${d}</p><ul class="lps-list">${pts.map((x) => `<li>${x}</li>`).join('')}</ul><div class="lps-foot">${foot}</div></div>`).join('')}</div></section>

    <section class="lp-sec" id="lp-demo"><div class="lp-head rv flank"><div class="flank-l" aria-hidden="true"><span class="fk fk1">${icon('check', 15)} Fight with evidence</span><span class="fk fk2">${icon('refresh', 15)} Retry on the 1st</span></div><div class="flank-r" aria-hidden="true"><span class="fk fk3">${icon('pause', 15)} Offer a pause</span><span class="fk fk4">${icon('shield', 15)} Refund early</span></div><span class="pf-tag"><i style="background:var(--s3)"></i>See a decision</span><h2>Every recommendation<br>comes with its reason</h2><p>Sample decisions from the demo workspace. Impulse compares the options and tells you which it would choose, and why.</p></div>
      <div class="card lp-demo rv"><div class="lpd-tabs">${DEMOS.map(([k, l, ic], i) => `<button class="${i === 0 ? 'on' : ''}" data-d="${k}">${icon(ic, 16)}${l}</button>`).join('')}</div><div id="lpd-body" class="lpd-body"><div class="sk sk-block"></div></div></div></section>

    <section class="lp-sec" id="lp-measure"><div class="lp-head rv"><span class="pf-tag"><i style="background:var(--s1)"></i>Measured honestly</span><h2>Results you can check</h2><p>Impulse is judged on what it adds beyond what you would have recovered anyway.</p></div>
      <div class="lp-measure"><div class="receipt rv" id="lp-receipt"><div class="rc-bar"><span>Outcome Ledger</span><span class="rc-live">Sample entry</span></div><div class="rc-body"><div class="sk sk-line"></div><div class="sk sk-line"></div><div class="sk sk-line short"></div></div></div>
      <div class="lp-mpoints">${MEASURE.map(([ic, t, d], i) => `<div class="lp-mp rv" style="--d:${i * 90}ms"><span class="lp-mp-n">0${i + 1}</span><div><h3>${t}</h3><p>${d}</p></div></div>`).join('')}</div></div></section>

    <section class="lp-sec band" id="lp-trust"><div class="lp-head rv"><span class="pf-tag"><i style="background:var(--s4)"></i>Built for finance and ops</span><h2>Automation you stay in charge of</h2></div>
      <div class="grid g4 lp-trustg">${TRUST.map(([ic, t, d], i) => `<div class="card lp-t spot rv" style="--d:${i * 60}ms"><span class="h-ico" style="--c:var(--brand-indigo)">${icon(ic, 20)}</span><h3>${t}</h3><p>${d}</p></div>`).join('')}</div></section>

    <section class="lp-cta-band rv"><div class="cta-copy"><h2>See what you might be leaking, free.</h2><p>Upload your exports and get a shareable report. No integration needed.</p><div class="lp-cta"><button class="btn-hero-primary shine" data-go="audit">Run the Leak Audit ${icon('arrow', 16)}</button><button class="btn-hero-secondary" data-go="dashboard">Open the demo</button></div></div>
      <div class="cta-card" id="cta-card"><div class="rc-bar"><span>Leak Audit report</span><span class="rc-live">Sample</span></div><div class="cta-body"><div class="sk sk-line"></div><div class="sk sk-line"></div><div class="sk sk-line short"></div></div></div></section>`;

    window.UI.tilt($('#lpv', el), 5);
    const stopWords = window.UI.rotateWords($('#rw', el), WORDS);
    const obs = new MutationObserver(() => { if (!document.body.contains(el.querySelector('#rw'))) { stopWords(); obs.disconnect(); } });
    obs.observe(document.body, { childList: true, subtree: true });
    el.querySelectorAll('.lp-fade').forEach((n) => requestAnimationFrame(() => n.classList.add('go')));
    el.querySelectorAll('.lp-line').forEach((n) => n.classList.add('rv'));

    // hero preview: a few real (sample) pending decisions, no performance numbers
    api('/overview').then((o) => {
      const rows = o.top_actions.slice(0, 3);
      $('#lp-list', el).innerHTML = rows.map((a, i) => `<div class="lpg-item" style="--i:${i}"><span class="pill brand">${esc(label(a.module))}</span><b>${esc(short(a.action))}</b><span class="muted">${inr(a.amount)}</span></div>`).join('') || '<div class="muted">Nothing needs attention.</div>';
      $('#lp-list', el).classList.add('go');
    }).catch(() => { $('#lp-list', el).innerHTML = '<div class="muted">Sample workspace unavailable.</div>'; });

    // CTA: a real report generated from the sample export files
    api('/audit/sample').then((j) => {
      const r = j.report, box = $('#cta-card .cta-body', el); if (!box) return;
      const names = { failed: 'Failed payments', clawed_back: 'Clawed back', stopped: 'Customers stopping', missed: 'Missed billing' };
      const cols = { failed: 'var(--s1)', clawed_back: 'var(--s2)', stopped: 'var(--s3)', missed: 'var(--s4)' };
      const mx = Math.max(...Object.values(r.by_cause).map((v) => v.leaked), 1);
      box.innerHTML = `<div class="cta-total"><span>Leaked in 90 days (sample data)</span><b>${inr(r.total_leak)}</b></div>` + Object.entries(r.by_cause).map(([k, v]) => `<div class="cta-row"><span>${names[k]}</span><div class="meter"><i style="width:${Math.max(4, (v.leaked / mx) * 100)}%;background:${cols[k]}"></i></div><em>${inr(v.leaked)}</em></div>`).join('') + '<div class="cta-foot">Estimated from made-up export files</div>';
    }).catch(() => {});

    // receipt: a real entry from the sample ledger
    api('/ledger?limit=40').then((l) => {
      const e = l.entries.find((x) => x.arm === 'treatment' && x.recovered > 0 && x.module !== 'rto') || l.entries[0];
      const box = $('#lp-receipt .rc-body', el); if (!e || !box) return;
      const act = { recovery_journey: 'Payment recovery', submit_evidence: 'Dispute fought with evidence', refund_early: 'Refunded before a dispute', offer_pause: 'Pause offered', payment_update_link: 'Payment-update link sent', decline_refund: 'Refund declined', request_proof: 'Proof requested' }[e.action] || label(e.action);
      box.innerHTML = `<dl><div><dt>Action</dt><dd>${esc(act)}</dd></div><div><dt>Area</dt><dd>${esc(label(e.module))}</dd></div><div><dt>At stake</dt><dd>${inr(e.amount_at_stake)}</dd></div><div><dt>Recovered</dt><dd class="g">${inr(e.recovered)}</dd></div></dl>
        <div class="rc-why"><dt>Why</dt><dd>${esc(plain(e.receipt.reason || '')).slice(0, 170)}</dd></div>
        <div class="rc-hash"><span>Entry #${e.seq}</span><code>${esc(e.hash.slice(0, 24))}…</code>${l.chain.valid ? '<em>Chain verified</em>' : ''}</div>`;
    }).catch(() => {});

    // decision explainer
    let scen = null; const cache = {};
    const show = async (key) => {
      const body = $('#lpd-body', el); body.classList.add('swap');
      try {
        scen = scen || (await api('/scenarios')).scenarios;
        cache[key] = cache[key] || (await api('/cases/' + encodeURIComponent(scen[key])));
        const c = cache[key], d = c.decision, cands = c.candidates.filter((x) => x.action !== 'do_nothing').sort((a, b) => b.ev - a.ev).slice(0, 4), mx = Math.max(...cands.map((x) => Math.max(x.ev, 0)), 1);
        setTimeout(() => {
          body.innerHTML = `<div class="lpd-grid"><div><div class="lpd-k">The situation</div><h3>${esc(KIND[c.kind] || label(c.kind))} · ${inr(c.amount)} at stake</h3>
            <div class="lpd-k" style="margin-top:14px">Impulse recommends</div><div class="lpd-choice">${icon('check', 18)}${esc(d.chosen ? short(d.chosen.label) : 'No action')}</div><div class="reason">${esc(plain(d.reason))}</div></div>
            <div><div class="lpd-k">Options it compared</div>${cands.map((x, i) => `<div class="lpd-opt ${d.chosen && x.action === d.chosen.action ? 'win' : ''}" style="--i:${i}"><div class="row between"><span>${esc(short(x.label))}</span>${d.chosen && x.action === d.chosen.action ? '<span class="pill good">Chosen</span>' : ''}</div><div class="meter"><i style="width:${Math.max(6, (Math.max(x.ev, 0) / mx) * 100)}%"></i></div></div>`).join('')}</div></div>`;
          body.classList.remove('swap');
        }, 180);
      } catch (e) { body.classList.remove('swap'); body.innerHTML = '<div class="empty">Sample decision unavailable.</div>'; }
    };
    el.querySelectorAll('.lpd-tabs button').forEach((b) => (b.onclick = () => { el.querySelectorAll('.lpd-tabs button').forEach((x) => x.classList.toggle('on', x === b)); show(b.dataset.d); }));
    show(DEMOS[0][0]);
  };
})();
