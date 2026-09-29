/* Getting-started guide (B2B onboarding), the data-in-use panel, and the Ask Impulse assistant. */
(function () {
  'use strict';
  const { api, esc, screens, toast } = window.IMP;
  const { icon } = window.UI;
  const $ = (s, r) => (r || document).querySelector(s);

  /* ── data in use: shown next to every place a business can add data ── */
  const state = { health: null };
  api('/health').then((h) => { state.health = h; document.querySelectorAll('[data-fill="counts"]').forEach((n) => { n.textContent = `${h.customers} customers · ${h.cases} cases`; }); }).catch(() => {});
  function dataStatus() {
    const h = state.health;
    return `<div class="data-status"><div class="ds-main"><span class="ds-dot"></span><div><b>Data in use: sample workspace <em>synthetic</em></b><span>Made-up customers, payments and disputes, generated to show how Impulse behaves. <span data-fill="counts">${h ? `${h.customers} customers · ${h.cases} cases` : ''}</span></span></div></div>
      <div class="ds-side"><div><b>Your files</b><span>Files added in the Leak Audit are analysed in memory to build your report. They are not stored and do not replace the sample workspace.</span></div>
      <div><b>Real data</b><span>Real customers appear only after a gateway is connected (Connections) or events are sent to the API.</span></div></div></div>`;
  }

  /* ── content ── */
  const PHASES = [
    { n: 'Phase 0', ic: 'search', t: 'Run the free Leak Audit', who: 'Finance or ops, no engineering', d: 'Export 90 days of payments (and, if you have them, disputes, refunds, subscriptions and invoices). Upload them to the Leak Audit. Columns are matched automatically and you can correct them.', out: 'A report showing where you leak money and an estimate of what is recoverable.', go: 'audit', cta: 'Open the Leak Audit' },
    { n: 'Phase 1', ic: 'plug', t: 'Connect your gateway', who: 'One engineer', d: 'Add the Impulse webhook URL for Razorpay and/or Stripe in your gateway dashboard and set a shared secret. Send a test event and confirm it appears. Events that cannot be mapped land in a dead-letter queue you can fix and replay.', out: 'Payments, disputes and refunds flow in through one schema, and one customer stays one profile across gateways.', go: 'connections', cta: 'Open Connections' },
    { n: 'Phase 2', ic: 'inbox', t: 'Learn in recommend-only mode', who: 'Finance or ops lead', d: 'Leave every module on recommend-only. Impulse suggests an action and explains why, but changes nothing. Review suggestions in the Approval Inbox and compare them with what your team would have done.', out: 'Confidence in the reasoning before anything is automated.', go: 'approvals', cta: 'Open the Approval Inbox' },
    { n: 'Phase 3', ic: 'settings', t: 'Set your rules', who: 'Finance or ops lead', d: 'Choose how much Impulse may do per module: recommend only, ask first, or act. Set the auto-approve limit, the monthly budget for offers, how often a customer may be contacted, and which guardrails apply.', out: 'A policy that matches your risk appetite. Anything above your limit always waits for a person.', go: 'settings', cta: 'Open Settings' },
    { n: 'Phase 4', ic: 'check', t: 'Automate low-risk actions and measure', who: 'Finance and ops together', d: 'Turn on automatic actions for the lowest-risk cases first, such as retry scheduling. A small control group stays on your current approach so results are measured fairly. The Results page lists every action and outcome.', out: 'Measured recovery beyond your baseline, and an audit trail for finance.', go: 'ledger', cta: 'Open Results' },
    { n: 'Phase 5', ic: 'spark', t: 'Expand to the other pillars', who: 'Whoever owns each area', d: 'Add Clawback Defense for disputes and refunds, Retention Rescue for customers at risk, and Billing & Collections for missing invoices. They all use the same customer profile, so each one benefits from the others.', out: 'One view of every place revenue leaks.', go: 'dashboard', cta: 'Open the Dashboard' },
  ];
  const ROLES = [
    ['Finance or ops lead', 'Runs the audit, reviews recommendations, approves larger actions, sets budgets and limits.', 'Audit, Approval Inbox, Results, Settings'],
    ['Engineer', 'Connects the gateway webhooks, sets the secret, fixes any events in the dead-letter queue.', 'Connections'],
    ['Support or customer success', 'Handles personal outreach calls and refund requests that need a human.', 'Retention Rescue, Refund requests'],
    ['Leadership', 'Reviews the results and the fee against the measured baseline.', 'Dashboard, Results'],
  ];
  const DATA = [
    ['Payments: status, amount, decline reason, date', 'Finding failed payments and choosing how to retry', 'Gateway export or webhook', 'Payment Recovery'],
    ['Customer email or phone', 'Recognising the same customer across gateways', 'Gateway or billing tool', 'All pillars'],
    ['Disputes: amount, reason, outcome, respond-by date', 'Deciding whether to fight, refund early or accept', 'Gateway dispute export', 'Clawback Defense'],
    ['Refund requests: amount and reason', 'Spotting unfair claims and choosing a response', 'Gateway or order system', 'Clawback Defense'],
    ['Orders and delivery: proof of delivery, COD status', 'Building the evidence pack and checking risky COD orders', 'Order or shipping system', 'Clawback Defense'],
    ['Subscriptions: plan, status, last payment result', 'Telling card problems from lost interest', 'Billing tool', 'Retention Rescue'],
    ['Usage and support activity (optional)', 'Early warning signs of a customer leaving', 'Your product, via the API', 'Retention Rescue'],
    ['Contracts, invoices, seats (optional)', 'Finding billing mistakes and ranking overdue invoices', 'Billing or finance system', 'Billing & Collections'],
  ];
  const FAQ = [
    ['Do I need an engineer to start?', 'No. The Leak Audit works from spreadsheet exports. An engineer is needed only when you connect a gateway for live events.'],
    ['Will Impulse change anything in my systems on day one?', 'No. Every module starts in recommend-only mode. Nothing is sent or changed until you allow it.'],
    ['What stops it from doing something risky?', 'Guardrails: it never retries a permanent decline, limits how often a customer is contacted, ties discounts to customer value, and always asks a person above your auto-approve limit.'],
    ['How do you know Impulse is helping?', 'A small control group stays on your current approach, so results are compared against what you would have recovered anyway. You are charged only on the difference.'],
    ['What about card data?', 'Card numbers are never stored. Impulse works with the tokens and fingerprints your gateway provides.'],
    ['Which gateways are supported?', 'Razorpay and Stripe today, plus CSV/Excel upload and a REST API for custom events. Other gateways and billing tools are on the roadmap.'],
    ['Is the demo real data?', 'No. The demo workspace is synthetic. It shows how Impulse behaves, and its outcomes are simulated.'],
  ];
  const LEVELS = [['recommend', 'Recommend only', 'Impulse suggests, you do the work. Start here.', 'brand'], ['approve', 'Ask first', 'Impulse prepares the action and waits for your approval.', 'warn'], ['auto', 'Act on its own', 'Low-risk actions run automatically inside your guardrails.', 'good']];

  /* ── the guide page ── */
  screens.guide = async (el) => {
    let done = {};
    try { done = JSON.parse(localStorage.getItem('impulse-checklist') || '{}'); } catch (e) { done = {}; }
    const CHECK = ['Exported 90 days of payments', 'Ran the Leak Audit and reviewed the report', 'Chose who approves actions', 'Connected a gateway webhook and sent a test event', 'Reviewed recommendations in recommend-only mode', 'Set the auto-approve limit and budgets', 'Turned on automation for low-risk actions', 'Reviewed the first Results report'];
    el.innerHTML = `<section class="gd-hero rv"><span class="pf-tag"><i style="background:var(--brand-indigo)"></i>Getting started</span><h1>From your first spreadsheet to automated recovery</h1>
      <p>A step-by-step path for finance and operations teams. You start read-only, stay in control at every stage, and only move on when you are comfortable.</p>
      <div class="gd-facts"><span>${icon('check', 15)} No engineering needed to start</span><span>${icon('check', 15)} Nothing changes until you allow it</span><span>${icon('check', 15)} Fees only on measured results</span></div></section>
    <section class="gd-sec rv"><div class="gd-h"><h2>Your onboarding path</h2><p>Six phases. You can stop after any of them and still keep the value.</p></div>
      <ol class="gd-time">${PHASES.map((p, i) => `<li class="gd-step rv" style="--d:${i * 40}ms"><div class="gd-rail"><span class="gd-ico">${icon(p.ic, 18)}</span></div><div class="gd-card"><div class="gd-top"><span class="gd-n">${p.n}</span><span class="gd-who">${icon('user', 13)} ${p.who}</span></div><h3>${p.t}</h3><p>${p.d}</p><div class="gd-out"><b>You get</b>${p.out}</div><a class="gd-go" href="#${p.go}">${p.cta} ${icon('arrow', 14)}</a></div></li>`).join('')}</ol></section>
    <section class="gd-sec rv"><div class="gd-h"><h2>You stay in control</h2><p>Each module has three levels. Move up only when the recommendations have earned your trust.</p></div>
      <div class="gd-levels">${LEVELS.map(([k, t, d, kind], i) => `<div class="gd-level"><span class="gd-lv-n">${i + 1}</span><b>${t}</b><p>${d}</p></div>`).join('')}</div></section>
    <section class="gd-sec rv"><div class="gd-h"><h2>Who does what</h2></div><div class="gd-table"><table><thead><tr><th>Role</th><th>What they do</th><th>Where in the product</th></tr></thead><tbody>${ROLES.map((r) => `<tr><td><b>${r[0]}</b></td><td>${r[1]}</td><td>${r[2]}</td></tr>`).join('')}</tbody></table></div></section>
    <section class="gd-sec rv"><div class="gd-h"><h2>What data you will need</h2><p>Start with payments only. Add the rest when you are ready for that pillar.</p></div><div class="gd-table"><table><thead><tr><th>Data</th><th>Used for</th><th>Where it comes from</th><th>Pillar</th></tr></thead><tbody>${DATA.map((r) => `<tr><td><b>${r[0]}</b></td><td>${r[1]}</td><td>${r[2]}</td><td>${r[3]}</td></tr>`).join('')}</tbody></table></div>
      <div class="gd-data">${dataStatus()}</div></section>
    <section class="gd-sec gd-two rv"><div><div class="gd-h"><h2>Go-live checklist</h2><p>Your progress is saved in this browser.</p></div><ul class="gd-check" id="gd-check">${CHECK.map((c, i) => `<li><label><input type="checkbox" data-i="${i}" ${done[i] ? 'checked' : ''}><span>${c}</span></label></li>`).join('')}</ul><div class="gd-prog"><div class="meter"><i id="gd-bar" style="width:0%"></i></div><span id="gd-pct">0 of ${CHECK.length} done</span></div></div>
      <div><div class="gd-h"><h2>Common questions</h2></div><div class="gd-faq">${FAQ.map(([q, a]) => `<details><summary>${q}</summary><p>${a}</p></details>`).join('')}</div></div></section>
    <section class="gd-cta rv"><div><h2>Ready to begin?</h2><p>Start with the free Leak Audit. It takes a spreadsheet and no integration.</p></div><div class="lp-cta"><button class="btn-hero-primary shine" data-go="audit">Run the Leak Audit ${icon('arrow', 16)}</button><button class="btn-hero-secondary" data-go="connections">Connect a gateway</button></div></section>`;
    const upd = () => { const boxes = [...el.querySelectorAll('#gd-check input')], n = boxes.filter((b) => b.checked).length; $('#gd-bar', el).style.width = (n / boxes.length) * 100 + '%'; $('#gd-pct', el).textContent = `${n} of ${boxes.length} done`; };
    el.querySelectorAll('#gd-check input').forEach((b) => (b.onchange = () => { done[b.dataset.i] = b.checked; try { localStorage.setItem('impulse-checklist', JSON.stringify(done)); } catch (e) { /* private mode */ } upd(); }));
    upd();
  };

  /* ── Ask Impulse assistant ── */
  const CHIPS = ['How do I get started?', 'What data is being used?', 'How do I connect Razorpay?', 'What needs my approval?', 'How does pricing work?'];
  function mountChat() {
    if ($('#chat-fab')) return;
    const root = document.createElement('div'); root.id = 'chat-root';
    root.innerHTML = `<button id="chat-fab" aria-label="Ask Impulse" aria-expanded="false">${icon('spark', 22)}<span>Ask Impulse</span></button>
      <div id="chat-panel" role="dialog" aria-label="Ask Impulse" hidden><div class="ch-head"><div><b>Ask Impulse</b><span>Answers about the product, your data and your results</span></div><button id="chat-x" aria-label="Close">×</button></div>
      <div class="ch-body" id="chat-body"><div class="ch-msg bot">Hi. I can explain how to get started, what data the demo is using, how to connect a gateway, or summarise results.</div><div class="ch-chips">${CHIPS.map((c) => `<button type="button">${c}</button>`).join('')}</div></div>
      <form class="ch-in" id="chat-form"><input id="chat-q" placeholder="Ask a question" autocomplete="off" maxlength="300"><button type="submit" aria-label="Send">${icon('arrow', 16)}</button></form></div>`;
    document.body.appendChild(root);
    const panel = $('#chat-panel'), fab = $('#chat-fab'), body = $('#chat-body');
    const open = (v) => { panel.hidden = !v; fab.setAttribute('aria-expanded', v); fab.classList.toggle('on', v); if (v) setTimeout(() => $('#chat-q').focus(), 60); };
    fab.onclick = () => open(panel.hidden); $('#chat-x').onclick = () => open(false);
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !panel.hidden) open(false); });
    const add = (t, who) => { const d = document.createElement('div'); d.className = 'ch-msg ' + who; d.textContent = t; body.appendChild(d); body.scrollTop = body.scrollHeight; return d; };
    const ask = async (q) => { if (!q.trim()) return; body.querySelector('.ch-chips')?.remove(); add(q, 'me'); const w = add('…', 'bot'); try { const a = await api('/ask', { method: 'POST', json: { question: q } }); w.textContent = a.answer; } catch (e) { w.textContent = 'Sorry, I could not reach the server.'; } body.scrollTop = body.scrollHeight; };
    $('#chat-form').onsubmit = (e) => { e.preventDefault(); const i = $('#chat-q'); const q = i.value; i.value = ''; ask(q); };
    body.addEventListener('click', (e) => { const b = e.target.closest('.ch-chips button'); if (b) ask(b.textContent); });
  }
  mountChat();

  window.IMP.dataStatus = dataStatus;
})();
