/* Impulse: Revenue Recovery Platform. Pillar screens, vanilla JS, inline-SVG charts, no build step. */
(function () {
'use strict';

const API = '/api/impulse';
const $ = (s, r = document) => r.querySelector(s);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const inr = (n) => '₹' + Math.round(Number(n) || 0).toLocaleString('en-IN');
const pct = (n, d = 0) => ((Number(n) || 0) * 100).toFixed(d) + '%';
const label = (s) => String(s || '').replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
const LEAKS = { failed: { name: 'Failed', mod: 'Payment Recovery', c: 'var(--s1)', href: '#payments' },
  clawed_back: { name: 'Clawed back', mod: 'Clawback Defense', c: 'var(--s2)', href: '#clawback' },
  stopped: { name: 'Stopped', mod: 'Retention Rescue', c: 'var(--s3)', href: '#retention' },
  missed: { name: 'Missed', mod: 'Billing & Collections', c: 'var(--s4)', href: '#billing' } };
const POLICY_COLORS = { baseline: 'var(--s-gray)', rules: 'var(--s2)', frozen: 'var(--s3)', impulse: 'var(--s1)' };
const POLICY_NAMES = { baseline: 'Merchant baseline', rules: 'Static playbook', frozen: 'Impulse, priors only', impulse: 'Impulse (learning)' };

async function api(path, opts = {}) {
  const init = { method: opts.method || 'GET', headers: {} };
  if (opts.json !== undefined) { init.body = JSON.stringify(opts.json); init.headers['content-type'] = 'application/json'; }
  if (opts.form) init.body = opts.form;
  const r = await fetch(API + path, init);
  const ct = r.headers.get('content-type') || '';
  const body = ct.includes('json') ? await r.json() : await r.text();
  if (!r.ok) throw new Error((body && body.detail) || r.statusText);
  return body;
}
function toast(msg) { const t = document.createElement('div'); t.className = 'pf-toast'; t.textContent = msg; document.body.appendChild(t); setTimeout(() => t.remove(), 2600); }
const pill = (text, kind = '') => `<span class="pill ${kind}">${esc(text)}</span>`;
const inrC = (n) => UI.num(n, 'inr');
const pctC = (n, d = 0) => UI.num(n, d ? 'pct1' : 'pct');
const tt = (text) => `<span class="tt" tabindex="0" data-tip="${esc(text)}">${UI.icon('info', 14)}</span>`;
const kpi = (l, v, sub = '') => `<div class="card kpi spot"><div class="v">${typeof v === 'number' ? UI.num(v, 'int') : v}</div><div class="l">${esc(l)}</div>${sub ? `<div class="muted" style="font-size:12px">${sub}</div>` : ''}</div>`;
const skeleton = () => `<div class="pf-head"><div class="sk sk-tag"></div><div class="sk sk-h1"></div><div class="sk sk-line"></div></div><div class="grid g4">${'<div class="card"><div class="sk sk-num"></div><div class="sk sk-line short"></div></div>'.repeat(4)}</div><div class="card"><div class="sk sk-block"></div></div>`;
function table(cols, rows, opts = {}) {
  if (!rows.length) return `<div class="empty">${esc(opts.empty || 'Nothing here yet.')}</div>`;
  const limit = opts.limit === undefined ? 12 : opts.limit;
  const go = opts.click && opts.go !== false;
  const body = rows.map((r, i) => `<tr class="${opts.click ? 'click' : ''}${limit && i >= limit ? ' extra' : ''}" ${opts.click ? `data-id="${esc(opts.click(r))}"` : ''}>${cols.map((c) => `<td class="${c.num ? 'num' : ''}">${c.f(r)}</td>`).join('')}${go ? `<td class="go-cell"><span class="row-go">${opts.goLabel || 'Open'} ${UI.icon('arrow', 13)}</span></td>` : ''}</tr>`).join('');
  const more = limit && rows.length > limit ? `<div class="more-wrap"><button class="show-more" type="button">Show all ${rows.length} rows</button></div>` : '';
  return `<div class="tbl"><div class="scroll"><table><thead><tr>${cols.map((c) => `<th class="${c.num ? 'num' : ''}">${esc(c.h)}</th>`).join('')}${go ? '<th></th>' : ''}</tr></thead><tbody>${body}</tbody></table></div>${more}</div>`;
}
function bindRows(root, fn) { root.querySelectorAll('tr.click').forEach((tr) => tr.addEventListener('click', () => fn(tr.dataset.id))); }
const modeKind = { auto: 'good', approve: 'warn', recommend: 'brand', skip: '' };
const statusKind = { active: 'brand', pending_approval: 'warn', resolved: 'good', holdout: '', no_action: '', recommended: 'brand', rejected: 'bad', superseded: '' };

/* ── charts ─────────────────────────────────────────────────────────────── */
function tipFor(host) { let t = host.querySelector('.tip'); if (!t) { t = document.createElement('div'); t.className = 'tip'; t.hidden = true; host.appendChild(t); } return t; }
function lineChart(host, series, { xs, fmt = pct, height = 240, yMin = null, area = false } = {}) {
  const W = Math.max(360, Math.round(host.clientWidth || 760)), H = height, m = { l: 52, r: 16, t: 12, b: 26 };
  const all = series.flatMap((s) => s.data);
  let lo = yMin !== null ? yMin : Math.min(...all), hi = Math.max(...all);
  if (hi === lo) hi = lo + 1; const pad = (hi - lo) * 0.08; lo = yMin !== null ? yMin : lo - pad; hi += pad;
  const x = (i) => m.l + (i * (W - m.l - m.r)) / Math.max(xs.length - 1, 1), y = (v) => m.t + (1 - (v - lo) / (hi - lo)) * (H - m.t - m.b);
  const ticks = [0, 1, 2, 3].map((i) => lo + ((hi - lo) * i) / 3);
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="line chart">`;
  ticks.forEach((t) => { svg += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(t)}" y2="${y(t)}" stroke="var(--line)"/><text x="${m.l - 8}" y="${y(t) + 4}" text-anchor="end" font-size="11" fill="var(--ink-3)">${esc(fmt(t))}</text>`; });
  xs.forEach((l, i) => { if (i % Math.ceil(xs.length / 8) === 0) svg += `<text x="${x(i)}" y="${H - 6}" text-anchor="middle" font-size="11" fill="var(--ink-3)">${esc(l)}</text>`; });
  series.forEach((s) => {
    const pts = s.data.map((v, i) => `${x(i)},${y(v)}`).join(' ');
    if (area) svg += `<polygon points="${m.l},${y(lo)} ${pts} ${x(s.data.length - 1)},${y(lo)}" fill="${s.color}" opacity=".08"/>`;
    svg += `<polyline class="${s.dash ? 'ln-fade' : 'ln'}" ${s.dash ? '' : 'pathLength="1"'} points="${pts}" fill="none" stroke="${s.color}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round" ${s.dash ? 'stroke-dasharray="5 4"' : ''}/>`;
    const last = s.data.length - 1; svg += `<circle class="ln-dot" cx="${x(last)}" cy="${y(s.data[last])}" r="4.5" fill="${s.color}" stroke="#fff" stroke-width="2"/>`;
  });
  svg += `<line class="xh" y1="${m.t}" y2="${H - m.b}" stroke="var(--ink-3)" stroke-dasharray="3 3" visibility="hidden"/><rect class="hit" x="${m.l}" y="${m.t}" width="${W - m.l - m.r}" height="${H - m.t - m.b}" fill="transparent"/></svg>`;
  host.classList.add('chart');
  host.innerHTML = `<div class="legend">${series.map((s) => `<span style="--c:${s.color}">${esc(s.name)}</span>`).join('')}</div>${svg}`;
  const tip = tipFor(host), svgEl = host.querySelector('svg'), xh = host.querySelector('.xh');
  host.querySelector('.hit').addEventListener('mousemove', (ev) => {
    const r = svgEl.getBoundingClientRect(), px = ((ev.clientX - r.left) / r.width) * W;
    const i = Math.max(0, Math.min(xs.length - 1, Math.round(((px - m.l) / (W - m.l - m.r)) * (xs.length - 1))));
    xh.setAttribute('x1', x(i)); xh.setAttribute('x2', x(i)); xh.setAttribute('visibility', 'visible');
    tip.hidden = false; tip.innerHTML = `<b>${esc(xs[i])}</b>` + series.map((s) => `<div><span class="leak-dot" style="background:${s.color}"></span>${esc(s.name)}: ${esc(fmt(s.data[i]))}</div>`).join('');
    tip.style.left = Math.min(ev.clientX - host.getBoundingClientRect().left + 14, host.clientWidth - 200) + 'px'; tip.style.top = '30px';
  });
  host.querySelector('.hit').addEventListener('mouseleave', () => { tip.hidden = true; xh.setAttribute('visibility', 'hidden'); });
}
function stackBar(parts) { const t = parts.reduce((a, p) => a + p.v, 0) || 1; return `<div class="bar" title="${esc(parts.map((p) => p.name + ' ' + inr(p.v)).join(' · '))}">${parts.map((p) => `<i style="width:${(p.v / t) * 100}%;background:${p.c}"></i>`).join('')}</div>`; }
function hbars(rows, color = 'var(--s1)', fmt = inr) { const mx = Math.max(...rows.map((r) => r.v), 1); return rows.map((r) => `<div style="margin:7px 0"><div class="row between"><span>${esc(r.name)}</span><span class="muted">${esc(fmt(r.v))}${r.note ? ' · ' + esc(r.note) : ''}</span></div><div class="meter"><i style="width:${(r.v / mx) * 100}%;background:${r.c || color}"></i></div></div>`).join(''); }
function heat(matrix, cols, rowsKeys) {
  const vals = rowsKeys.flatMap((r) => cols.map((c) => matrix[r][c])), lo = Math.min(...vals), hi = Math.max(...vals);
  const cs = ['#cde2fb', '#86b6ef', '#3987e5', '#1c5cab', '#0d366b'];
  const cell = (v) => { const k = Math.min(4, Math.floor(((v - lo) / (hi - lo || 1)) * 4.999)); return `<div style="background:${cs[k]};color:${k > 1 ? '#fff' : '#0d366b'}" title="${pct(v, 1)}">${pct(v)}</div>`; };
  return `<div class="heat" style="grid-template-columns:70px repeat(${cols.length},1fr)"><div class="h"></div>${cols.map((c) => `<div class="h">${esc(c)}</div>`).join('')}${rowsKeys.map((r) => `<div class="h" style="text-align:left">${esc(r)}</div>${cols.map((c) => cell(matrix[r][c])).join('')}`).join('')}</div>`;
}

/* ── case drawer ─────────────────────────────────────────────────────────── */

/* plain-language helpers: the UI speaks in everyday words; technical detail lives behind "details" */
const KIND = { failed_payment: 'Failed payment', recovery_follow_up: 'Follow-up on a failed payment', chargeback: 'Chargeback', pre_dispute: 'Early dispute warning', refund_request: 'Refund request', rto_risk: 'COD order check', save: 'Customer at risk of leaving', win_back: 'Win-back', compound: 'Several issues with one customer' };
const kindLabel = (k) => KIND[k] || label(k);
const STATUS = { active: ['In progress', 'brand'], pending_approval: ['Needs your approval', 'warn'], resolved: ['Done', 'good'], holdout: ['Left as is', ''], no_action: ['No action needed', ''], recommended: ['Suggested', 'brand'], rejected: ['Rejected', 'bad'], superseded: ['Merged into another case', ''] };
const statusPill = (st) => { const [t, k] = STATUS[st] || [label(st), '']; return pill(t, k); };
const plain = (reason) => String(reason || '').replace(/;?\s*EV\s*₹[-\d,]+\s*\([^)]*\)/g, '').replace(/\s*\(least-cost option[^)]*\)/, '').replace(/\.;/g, '.').replace(/_/g, ' ').trim();
const riskWord = (x) => (x >= 0.6 ? ['High', 'bad'] : x >= 0.35 ? ['Medium', 'warn'] : ['Low', 'good']);
const riskPill = (x) => { const [t, k] = riskWord(x); return pill(t, k); };
const chanceWord = (p) => (p == null ? 'Unknown' : p >= 0.6 ? 'High' : p >= 0.4 ? 'Medium' : 'Low');
const DECLINE = { soft: 'Temporary (for example low balance)', hard: 'Permanent (for example expired card)', bank: 'Bank unavailable', auth: 'Needs customer authentication' };
const cut = (t, n) => (t.length <= n ? t : t.slice(0, n).replace(/\s+\S*$/, '') + '…');
const MODNAME = { rto: 'COD returns', clawback: 'Clawback', refunds: 'Refunds', payments: 'Payments', retention: 'Retention', billing: 'Billing' };
const shortAction = (s) => String(s || '').replace(/\s*\(.*\)/, '');


const chipBar = (id, items) => `<div class="chips" id="${id}">${items.map(([k, l, n], i) => `<button type="button" class="chipf ${i === 0 ? 'on' : ''}" data-f="${k}">${l}${n != null ? `<em>${n}</em>` : ''}</button>`).join('')}</div>`;
function bindChips(root, id, cb) { root.querySelectorAll('#' + id + ' .chipf').forEach((b) => (b.onclick = () => { root.querySelectorAll('#' + id + ' .chipf').forEach((x) => x.classList.toggle('on', x === b)); cb(b.dataset.f); })); }
/** Render a table into `host` and wire row clicks + "show all". */
function liveTable(host, cols, rows, opts, onOpen) {
  host.innerHTML = table(cols, rows, opts);
  bindRows(host, onOpen);
  host.querySelectorAll('.show-more').forEach((b) => (b.onclick = () => { b.closest('.tbl').classList.add('expanded'); b.parentElement.remove(); }));
}
const ACTION = { schedule_retry: 'Scheduled a retry', payment_update_link: 'Sent a payment-update link', upi_fallback: 'Offered UPI as another way to pay', offer_pause: 'Offered a pause', offer_downgrade: 'Offered a lighter plan', discount: 'Offered a discount', personal_outreach: 'Planned a personal call', submit_evidence: 'Submitted evidence', refund_early: 'Refunded early', accept_liability: 'Accepted the dispute', otp_verify: 'Asked for OTP confirmation', prepaid_nudge: 'Suggested paying online', decline_refund: 'Declined the refund', request_proof: 'Asked for proof', approve_refund: 'Approved the refund', partial_refund: 'Offered a partial refund', offer_replacement_credit: 'Offered a replacement or credit', win_back_offer: 'Sent a win-back offer', hold_order: 'Held the order', block_order: 'Blocked the order', call_verify: 'Called to verify the order', ship_as_is: 'Shipped as normal' };
const initials = (n) => String(n || '?').split(/[\s@.]+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('');
const humanize = (t) => String(t || '').replace(/_/g, ' ');

async function showCase(id) {
  const c = await api('/cases/' + encodeURIComponent(id)); const d = c.decision;
  const cands = (c.candidates || []).filter((x) => x.action !== 'do_nothing').slice().sort((a, b) => b.ev - a.ev);
  const top = cands.slice(0, 4), maxEv = Math.max(...top.map((x) => Math.abs(x.ev)), 1);
  const ev = c.evidence_pack, dl = c.deadline_status, an = c.analysis;
  let extra = '';
  if (c.journey) extra += `<div class="card"><h2>What happens next</h2><ol class="steps">${c.journey.filter((s) => s.action !== 'pre_debit_notice').slice(0, 4).map((s) => `<li><b>${esc(label(s.action))}</b> <span class="muted">by ${esc(s.channel)}, ${esc((s.at || '').slice(0, 10))}</span></li>`).join('')}</ol></div>`;
  if (dl) extra += `<div class="card"><h2>Deadline</h2>${pill(dl.urgency === 'normal' ? 'On track' : label(dl.urgency), dl.urgency === 'critical' || dl.urgency === 'overdue' ? 'bad' : dl.urgency === 'high' ? 'warn' : 'good')} ${esc(dl.alert)}</div>`;
  if (an && an.win_probability != null) extra += `<div class="card"><h2>Chance of winning</h2><b>${chanceWord(an.win_probability)}</b> <span class="muted">based on the evidence available</span></div>`;
  if (ev) extra += `<div class="card"><h2>Evidence</h2>${table([{ h: 'Item', f: (r) => esc(r.label) }, { h: 'Status', f: (r) => r.present ? pill('Attached', 'good') : (r.role === 'not_required' ? pill('Not needed') : pill('Missing', 'bad')) }], ev.items.filter((r) => r.role !== 'not_required'), { limit: 0 })}<div class="row" style="margin-top:8px"><button id="narr">Draft the response</button></div><div id="narr-out" class="msg" hidden></div></div>`;
  if (c.meta && c.meta.factors && c.meta.factors.length) extra += `<div class="card"><h2>What we looked at</h2><ul>${c.meta.factors.map((f) => `<li>${esc(f.factor)}</li>`).join('')}</ul></div>`;
  if (c.action && c.action.message) extra += `<div class="card"><h2>Message to the customer <span class="muted" style="font-weight:500">(preview, not sent)</span></h2><div class="msg"><b>${esc(c.action.message.subject)}</b><br>${esc(c.action.message.body)}</div></div>`;
  if (c.outcome) extra += `<div class="card"><h2>Result</h2>${c.outcome.success ? pill('Recovered', 'good') : pill('Not recovered')} ${c.outcome.simulated ? pill('sample outcome', 'warn') : pill('confirmed', 'good')}</div>`;
  const tech = `<details class="adv"><summary>Technical details</summary>
    <div class="muted" style="margin:8px 0">Case <span class="mono">${esc(c.case_id)}</span> · mode ${esc(d.mode)}${c.arm === 'holdout' ? ' · control group' : ''}</div>
    ${top.map((x) => `<div class="row between" style="font-size:12.5px"><span>${esc(shortAction(x.label))}</span><span>expected gain ${inr(x.ev)} · success chance ${pct(x.p)}</span></div>`).join('')}
    ${d.guardrails_triggered && d.guardrails_triggered.length ? `<h3 style="margin-top:10px">Guardrails that applied</h3><ul>${d.guardrails_triggered.map((g) => `<li>${esc(g.message)}</li>`).join('')}</ul>` : ''}
    <a href="${API}/cases/${encodeURIComponent(c.case_id)}" target="_blank">Raw JSON</a></details>`;
  const ov = $('#overlay'); ov.innerHTML = `<div class="drawer-bg"><div class="drawer"><div class="row between"><h1>${esc(kindLabel(c.kind))}</h1><button id="x">Close</button></div>
    <div class="row">${pill(label(c.module), 'brand')} ${statusPill(c.status)}</div>
    <p class="muted" style="margin-top:6px">Customer <a href="#customers/${encodeURIComponent(c.customer_id)}" id="cl">${esc(c.customer_id)}</a> · ${inr(c.amount)} at stake</p>
    <div class="card rec"><div class="rec-k">Recommended</div><div class="rec-t">${UI.icon('check', 20)}${esc(d.chosen ? shortAction(d.chosen.label) : 'No action needed')}</div><p>${esc(plain(d.reason))}</p></div>
    ${top.length > 1 ? `<div class="card"><h2>Other options considered</h2>${top.map((x, i) => `<div class="opt ${d.chosen && x.action === d.chosen.action ? 'win' : ''}"><div class="row between"><span>${esc(shortAction(x.label))}</span><span>${d.chosen && x.action === d.chosen.action ? pill('Chosen', 'good') : i < 2 ? pill('Close second') : pill('Less suitable')}</span></div><div class="meter"><i style="width:${Math.max(6, (Math.max(x.ev, 0) / maxEv) * 100)}%"></i></div></div>`).join('')}</div>` : ''}
    ${extra}${tech}
    <div class="row" style="margin-top:14px">${c.status === 'active' || c.status === 'holdout' ? '<button class="primary" id="sim">Simulate the outcome</button>' : ''}${c.status === 'pending_approval' ? '<a class="btn" href="#approvals" id="toapr">Go to Approval Inbox</a>' : ''}${c.action && c.action.reversible && c.action.status === 'executed' ? '<button id="undo">Undo action</button>' : ''}</div></div></div>`;
  const close = () => { ov.innerHTML = ''; }; $('#x', ov).onclick = close; $('.drawer-bg', ov).onclick = (e) => { if (e.target.classList.contains('drawer-bg')) close(); };
  $('#cl', ov).onclick = close; if ($('#toapr', ov)) $('#toapr', ov).onclick = close;
  if ($('#sim', ov)) $('#sim', ov).onclick = async () => { await api(`/cases/${id}/resolve`, { method: 'POST', json: { simulate: true } }); toast('Sample outcome recorded'); close(); route(); };
  if ($('#undo', ov)) $('#undo', ov).onclick = async () => { await api(`/actions/${c.action.id}/undo`, { method: 'POST' }); toast('Action reversed'); close(); route(); };
  if ($('#narr', ov)) $('#narr', ov).onclick = async () => { const n = await api(`/cases/${id}/narrative`); const o = $('#narr-out', ov); o.hidden = false; o.textContent = n.text; };
}

const PILLAR_META = {
  payments: { icon: 'card', tag: 'Pillar 1 · Failed money', c: 'var(--s1)', title: 'Payment Recovery', sub: 'A payment attempt did not go through. Impulse finds out why, and picks the retry time, link or fallback most likely to win the money back.',
    steps: [['Detect', 'Every failed attempt from Razorpay or Stripe lands here with its decline reason.'], ['Decide', 'Hard declines are never retried. Soft ones get the window with the best chance of success.'], ['Act and prove', 'The action runs, the outcome is logged, and the ledger shows what you would have got anyway.']] },
  clawback: { icon: 'shield', tag: 'Pillar 2 · Clawed-back money', c: 'var(--s2)', title: 'Clawback Defense', sub: 'Money taken back after the sale: chargebacks, refund requests and COD returns. Impulse compares every option in rupees. Fighting is not always the right call.',
    steps: [['Detect', 'Disputes, refund requests and risky COD orders arrive with the customer history attached.'], ['Decide', 'Win odds, evidence strength and cost are weighed: fight, concede, refund early or verify.'], ['Act and prove', 'Evidence packs are assembled, deadlines tracked, and every decision is explained.']] },
  retention: { icon: 'users', tag: 'Pillar 3 · Stopped money', c: 'var(--s3)', title: 'Retention Rescue', sub: 'Customers quietly stop paying. Impulse separates card problems from lost interest and tries the cheapest effective save first.',
    steps: [['Detect', 'Payment failures, falling usage, tickets and downgrades feed one churn score.'], ['Decide', 'A payment fix, a pause, a lighter plan or a call, and a discount only when lifetime value justifies it.'], ['Act and prove', 'Offers respect budgets, and customers who abuse them are excluded.']] },
  billing: { icon: 'file', tag: 'Pillar 4 · Missed money', c: 'var(--s4)', title: 'Billing Assurance & Collections', sub: 'Revenue that was never billed or never collected. Roadmap module, shown on planted-error demo data.',
    steps: [['Detect', 'Contracts, invoices, usage and seats are reconciled to find gaps.'], ['Decide', 'Overdue invoices are ranked by rupees at stake times likelihood of payment.'], ['Act and prove', 'Reminders follow a soft-to-firm sequence, and promises to pay are tracked.']] },
};

/* ── pitch heroes: the problem, the fix, and how it works in plain words ── */
const PITCH = {
  payments: { problem: 'Every day customers try to pay you and the payment fails. Sometimes the balance is low for a few days, sometimes the card has expired, sometimes the bank is down. Most businesses retry blindly or give up, and the customer quietly disappears.',
    fix: 'Impulse reads why each payment failed and picks the smartest next move: wait for salary day and retry, send a link to update the card, or offer UPI. A permanent failure is never retried.',
    steps: [['search', 'We find out why it failed', 'Low balance, expired card, bank down, or a missing verification code.'], ['spark', 'We choose the best next step', 'Retry at the right time, or ask the customer to fix it in one tap.'], ['shield', 'We keep the customer happy', 'After repeated failures we offer a pause instead of another annoying retry.']] },
  clawback: { problem: 'After a sale, money can be taken back: a customer disputes the charge with their bank, asks for a refund, or a cash-on-delivery parcel comes back. Fighting every case wastes effort. Giving in to every case loses money.',
    fix: 'Impulse checks the evidence you hold, estimates your chance of winning, and recommends the cheapest good outcome: fight, refund early, accept, or verify a risky order first.',
    steps: [['file', 'We gather what you have', 'Delivery proof, login location, past orders and messages.'], ['spark', 'We weigh the options', 'The chance of winning against the cost of fighting.'], ['check', 'We prepare the response', 'An evidence pack and a draft reply, with the deadline tracked.']] },
  retention: { problem: 'Customers rarely announce they are leaving. Cards fail quietly, usage fades, support tickets pile up, and one day the subscription simply ends. By then it is too late to ask why.',
    fix: 'Impulse watches for the early warning signs, tells a card problem from lost interest, and suggests the gentlest fix that is likely to work: a payment link, a pause, a lighter plan, or a personal call.',
    steps: [['search', 'We spot the warning signs', 'Failed payments, falling usage, tickets and downgrades.'], ['users', 'We pick the gentlest fix', 'A discount is the last resort, not the first.'], ['shield', 'We protect you from abuse', 'People who only ask for refunds never get discounts.']] },
  billing: { problem: 'Some revenue is never lost by a customer. It is simply never billed, or never chased: a renewal nobody invoiced, extra seats in use, an expired discount still applied, invoices sitting overdue.',
    fix: 'Impulse compares your contracts, usage and invoices to find billing mistakes, then ranks overdue invoices so your team chases the ones most likely to pay first.',
    steps: [['file', 'We compare the records', 'Contract, usage and invoice side by side.'], ['search', 'We flag the mistakes', 'Missing invoices, extra seats, expired discounts.'], ['trend', 'We rank who to chase', 'Biggest amount and best chance of payment first.']] },
};
const pillarHead = (k) => { const m = PILLAR_META[k], P = PITCH[k]; return `<section class="pitch rv" style="--c:${m.c}"><div class="pitch-copy"><span class="pf-tag"><i style="background:${m.c}"></i>${m.tag}</span><h1>${m.title}</h1>
  <div class="pitch-k">The problem</div><p class="pitch-p">${P.problem}</p><div class="pitch-k">How Impulse fixes it</div><p class="pitch-p">${P.fix}</p>
  <ol class="pitch-steps">${P.steps.map(([ic, t, d], i) => `<li style="--i:${i}"><span class="ps-ico">${UI.icon(ic, 18)}</span><div><b>${t}</b><span>${d}</span></div></li>`).join('')}</ol></div><div class="pitch-art">${ART[k]}</div></section>`; };

/* ── playgrounds: try each pillar with sample data ── */
const playShell = (id, title, lead, form) => `<section class="play card rv" id="${id}"><div class="play-head"><span class="play-badge">${UI.icon('spark', 14)} Try it yourself</span><h2>${title}</h2><p>${lead}</p></div>
  <div class="play-grid"><div class="play-form">${form}</div><div class="play-out"><div class="play-empty">${UI.icon('arrow', 22)}<b>Your result appears here</b><span>Fill in the form and press the button. It all runs on made-up sample data.</span></div></div></div></section>`;
const playOut = (root, html) => { const o = $('.play-out', root); o.innerHTML = html; o.classList.remove('pop'); void o.offsetWidth; o.classList.add('pop'); };
const resultCard = (title, why, extra = '') => `<div class="res"><div class="res-k">Impulse recommends</div><div class="res-t">${UI.icon('check', 22)}<span>${esc(title)}</span></div><p class="res-why">${esc(why)}</p>${extra}</div>`;
const working = (btn, text) => { const o = btn.innerHTML; btn.disabled = true; btn.textContent = text; return () => { btn.disabled = false; btn.innerHTML = o; }; };
const fmtDate = (iso) => { const d = new Date(iso); return isNaN(d) ? '' : d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' }); };
const JOURNEY = { pre_debit_notice: 'Warn the customer 24 hours before the retry', retry: 'Retry the payment', failure_notice: 'Tell the customer it did not go through', payment_update_link: 'Send a link to update the payment method', upi_fallback: 'Offer UPI as another way to pay', final_notice: 'Send a final reminder', authentication_link: 'Send a link to complete the verification', reminder: 'Send a reminder' };
const optionsList = (c) => { const top = (c.candidates || []).filter((x) => x.action !== 'do_nothing').sort((a, b) => b.ev - a.ev).slice(0, 4); return top.length > 1 ? `<details class="adv res-more"><summary>Other options it considered</summary><ul>${top.map((x) => `<li>${esc(shortAction(x.label))}${c.decision.chosen && x.action === c.decision.chosen.action ? ' ' + pill('chosen', 'good') : ''}</li>`).join('')}</ul></details>` : ''; };
const fullCaseBtn = (c) => `<button class="btn full-case" data-case="${esc(c.case_id)}">See the full case ${UI.icon('arrow', 14)}</button>`;
const bindFull = (root) => root.querySelectorAll('.full-case').forEach((b) => (b.onclick = () => showCase(b.dataset.case)));

// Payments
const layPay = (c) => { const ch = c.decision.chosen || {}, a = ch.action;
  if (a === 'schedule_retry') return `The bank says this is a temporary problem, so trying again can work. Impulse picked "${(ch.params && ch.params.arm_label) || 'the best time'}" because that is when a retry is most likely to succeed.`;
  if (a === 'payment_update_link' || a === 'authentication_link') return 'Retrying would not help here, because the card or the verification is the problem. Impulse asks the customer to fix it themselves in one tap.';
  if (a === 'upi_fallback') return 'The card is not working, so Impulse offers UPI as another way to pay.';
  if (a === 'offer_pause') return 'This customer has already failed several times. Another retry would only annoy them, so Impulse offers a pause and keeps the relationship.';
  return plain(c.decision.reason); };
const playPay = () => playShell('play-pay', 'Make a payment fail and see what Impulse does', 'Choose what went wrong. Impulse decides the next step and explains why.',
  `<label>What went wrong?<select id="pp-reason"><option value="insufficient_funds">Not enough balance</option><option value="card_expired">The card has expired</option><option value="bank_unavailable">The bank was down</option><option value="authentication_failed">Customer did not enter the code</option><option value="do_not_honor">The bank declined it</option></select></label>
   <label>Amount ₹<input id="pp-amt" type="number" min="1" value="1299"></label>
   <label>Has this customer failed before?<select id="pp-prior"><option value="0">No, first time</option><option value="2">Yes, twice already</option><option value="3">Yes, three times already</option></select></label>
   <label class="chk"><input type="checkbox" id="pp-rec" checked> It is a monthly subscription payment</label><button class="primary big" id="pp-go">${UI.icon('bolt', 16)} Run it</button>`);
function wirePay(el) { const b = $('#pp-go', el); if (!b) return; b.onclick = async () => { const done = working(b, 'Thinking…');
  try { const c = await api('/try/payment', { method: 'POST', json: { reason: $('#pp-reason', el).value, amount: +$('#pp-amt', el).value || 1299, recurring: $('#pp-rec', el).checked, prior_failures: +$('#pp-prior', el).value } });
    const steps = (c.journey || []).filter((x) => JOURNEY[x.action]).slice(0, 4);
    playOut($('#play-pay', el), resultCard(c.decision.chosen ? shortAction(c.decision.chosen.label) : 'Leave it alone', layPay(c), `<div class="res-k">What happens next</div><ol class="steps">${steps.map((x) => `<li>${esc(JOURNEY[x.action])} <span class="muted">${esc(fmtDate(x.at))}</span></li>`).join('')}</ol>${optionsList(c)}${fullCaseBtn(c)}`)); bindFull(el);
  } catch (e) { toast(e.message); } finally { done(); } }; }

// Disputes
const layDispute = (c) => { const a = (c.decision.chosen || {}).action;
  if (a === 'submit_evidence') return 'You hold solid evidence, so fighting is likely to win the money back for less than it costs.';
  if (a === 'accept_liability') return 'The evidence is thin and the odds are low. Fighting would cost more than it could win back, so conceding limits the loss.';
  if (a === 'refund_early') return 'Refunding now costs less than fighting later, and it avoids the dispute fee and the damage to your chargeback record.';
  return plain(c.decision.reason); };
const playDispute = () => playShell('play-disp', 'Check a dispute', 'Describe the evidence you have. Impulse tells you whether to fight, refund early or accept.',
  `<div class="row" style="gap:8px"><button type="button" class="chipf" data-pre="strong">Strong evidence</button><button type="button" class="chipf" data-pre="weak">Weak evidence, small amount</button></div>
   <label>Amount ₹<input id="d-amt" type="number" min="1" value="12499"></label><label>Was it delivered?<select id="d-del"><option value="1">Yes</option><option value="0">No</option></select></label>
   <label>Do you have proof of delivery?<select id="d-pod"><option value="1">Yes</option><option value="0">No</option></select></label><label>Did the customer pass 3-D Secure?<select id="d-3ds"><option value="1">Yes</option><option value="0">No</option></select></label>
   <label>Did address and CVV match?<select id="d-avs"><option value="both_match">Both matched</option><option value="avs_only">Address only</option><option value="neither">Neither</option></select></label>
   <label>Is it an early warning?<select id="d-pre"><option value="0">No, a dispute was filed</option><option value="1">Yes, the bank warned us first</option></select></label><button class="primary big" id="d-go">${UI.icon('bolt', 16)} Get a recommendation</button>`);
function wireDispute(el) { const root = $('#play-disp', el); if (!root) return;
  const set = (v) => { Object.entries(v).forEach(([k, x]) => { $('#' + k, root).value = x; }); };
  root.querySelectorAll('[data-pre]').forEach((b) => (b.onclick = () => set(b.dataset.pre === 'strong' ? { 'd-amt': 12499, 'd-del': '1', 'd-pod': '1', 'd-3ds': '1', 'd-avs': 'both_match', 'd-pre': '0' } : { 'd-amt': 900, 'd-del': '0', 'd-pod': '0', 'd-3ds': '0', 'd-avs': 'neither', 'd-pre': '1' })));
  const b = $('#d-go', root); b.onclick = async () => { const done = working(b, 'Thinking…'); const g = (i) => $('#' + i, root).value;
    try { const c = await api('/clawback/disputes', { method: 'POST', json: { dispute_id: 'TRY-' + Date.now().toString().slice(-6), card_network: 'Visa', dispute_amount: +g('d-amt') || 1000, delivery_confirmed: g('d-del') === '1', has_delivery_proof: g('d-pod') === '1', has_3ds_authentication: g('d-3ds') === '1', avs_cvv_match: g('d-avs'), ip_geolocation_match: g('d-pod') === '1', customer_prior_orders: 3, customer_account_age_days: 120, pre_dispute: g('d-pre') === '1' } });
      const wp = c.analysis && c.analysis.win_probability, ev = c.evidence_pack, dl = c.deadline_status;
      const extra = `<div class="res-row">${wp != null ? `<div><span>Chance of winning</span>${pill(chanceWord(wp), wp >= 0.6 ? 'good' : wp >= 0.4 ? 'warn' : 'bad')}</div>` : ''}${dl && dl.hours_left != null ? `<div><span>Reply within</span><b>${Math.max(1, Math.round(dl.hours_left / 24))} days</b></div>` : ''}</div>${ev ? `<div class="res-k">Your evidence</div><ul class="ticks">${ev.items.filter((x) => x.role !== 'not_required').map((x) => `<li class="${x.present ? 'y' : 'n'}">${esc(x.label)}</li>`).join('')}</ul>` : ''}${optionsList(c)}${fullCaseBtn(c)}`;
      playOut(root, resultCard(c.decision.chosen ? shortAction(c.decision.chosen.label) : 'No action', layDispute(c), extra)); bindFull(root);
    } catch (e) { toast(e.message); } finally { done(); } }; }

// Customers for refund / COD playgrounds
async function fillCustomers(sel) { const d = await api('/customers?limit=120'); const rows = d.customers.slice().sort((a, b) => (b.serial_abuser ? 1 : 0) - (a.serial_abuser ? 1 : 0)).slice(0, 24);
  sel.innerHTML = rows.map((r) => `<option value="${esc(r.customer_id)}">${esc(r.name)}${r.serial_abuser ? ' (asks for refunds often)' : ''}</option>`).join(''); }
const layRefund = (c) => ({ approve_refund: 'This customer has a good history, so approving keeps them happy at little risk.', decline_refund: 'The claim looks doubtful and the evidence favours you, so declining protects your money.', request_proof: 'Asking for proof first filters out unfair claims without upsetting honest customers.', partial_refund: 'A partial refund splits the loss and keeps the customer.', offer_replacement_credit: 'Store credit costs you less than cash and keeps the customer buying.' }[(c.decision.chosen || {}).action] || plain(c.decision.reason));
const playRefund = () => playShell('play-ref', 'Check a refund request', 'Pick a customer and what they are asking for. Impulse looks at their history before deciding.',
  `<label>Customer<select id="r-c"><option>Loading…</option></select></label><label>Refund amount ₹<input id="r-a" type="number" min="1" value="2999"></label>
   <label>Their reason<select id="r-r"><option value="not received">Says it never arrived</option><option value="not as described">Says it was not as described</option><option value="changed mind">Changed their mind</option><option value="defective">Says it was faulty</option></select></label><button class="primary big" id="r-go">${UI.icon('bolt', 16)} Get a recommendation</button>`);
async function wireRefund(el) { const root = $('#play-ref', el); if (!root) return; fillCustomers($('#r-c', root)); const b = $('#r-go', root);
  b.onclick = async () => { const done = working(b, 'Thinking…'); try { const c = await api('/clawback/refunds', { method: 'POST', json: { customer_id: $('#r-c', root).value, amount: +$('#r-a', root).value || 1000, reason: $('#r-r', root).value } });
    const ab = c.meta && c.meta.abuse_probability; playOut(root, resultCard(c.decision.chosen ? shortAction(c.decision.chosen.label) : 'No action', layRefund(c), `<div class="res-row">${ab != null ? `<div><span>Risk of an unfair claim</span>${riskPill(ab)}</div>` : ''}</div>${c.meta && c.meta.factors && c.meta.factors.length ? `<div class="res-k">What it looked at</div><ul class="ticks">${c.meta.factors.map((f) => `<li class="y">${esc(f.factor)}</li>`).join('')}</ul>` : ''}${optionsList(c)}${fullCaseBtn(c)}`)); bindFull(root);
  } catch (e) { toast(e.message); } finally { done(); } }; }

// COD
const layCod = (c) => ({ ship_as_is: 'This order looks safe, so it ships as normal with no extra steps.', otp_verify: 'A quick OTP confirmation is cheap and catches fake or careless orders before they ship.', call_verify: 'This one is risky enough to justify a call to confirm the address and intent.', prepaid_nudge: 'Nudging the buyer to pay online removes the return risk at a small discount.', hold_order: 'Holding the order gives your team time to review it before it ships.', block_order: 'The chance of a return is so high that not shipping is the cheaper choice.' }[(c.decision.chosen || {}).action] || plain(c.decision.reason));
const playCod = () => playShell('play-cod', 'Check a cash-on-delivery order', 'Some COD parcels come back, and you pay shipping both ways. Impulse spots the risky ones before they ship.',
  `<label>Customer<select id="o-c"><option>Loading…</option></select></label><label>Order value ₹<input id="o-a" type="number" min="1" value="6499"></label>
   <label>Delivery area<select id="o-p"><option value="781001">Guwahati (higher returns)</option><option value="560001">Bengaluru centre (low returns)</option></select></label>
   <label>Address quality<select id="o-ad"><option value="Room 5">Short address: "Room 5"</option><option value="12, MG Road, near City Mall, Sector 4">Full address with landmark</option></select></label><button class="primary big" id="o-go">${UI.icon('bolt', 16)} Check this order</button>`);
async function wireCod(el) { const root = $('#play-cod', el); if (!root) return; fillCustomers($('#o-c', root)); const b = $('#o-go', root);
  b.onclick = async () => { const done = working(b, 'Thinking…'); try { const c = await api('/clawback/orders', { method: 'POST', json: { customer_id: $('#o-c', root).value, amount: +$('#o-a', root).value || 1000, payment_mode: 'COD', pincode: $('#o-p', root).value, address: $('#o-ad', root).value } });
    const rk = c.meta && c.meta.rto_probability; playOut(root, resultCard(c.decision.chosen ? shortAction(c.decision.chosen.label) : 'Ship as normal', layCod(c), `<div class="res-row">${rk != null ? `<div><span>Chance it comes back</span>${riskPill(rk)}</div>` : ''}</div>${c.meta && c.meta.factors && c.meta.factors.length ? `<div class="res-k">What it looked at</div><ul class="ticks">${c.meta.factors.map((f) => `<li class="n">${esc(f.factor)}</li>`).join('')}</ul>` : ''}${optionsList(c)}`));
  } catch (e) { toast(e.message); } finally { done(); } }; }

// Retention
const layRet = (c) => { const a = (c.decision.chosen || {}).action; return ({ payment_update_link: 'The card is the problem, not the customer. Make it easy to update and they will most likely stay.', offer_pause: 'A pause keeps the relationship alive at almost no cost, and often brings people back.', offer_downgrade: 'A lighter plan keeps some revenue instead of losing all of it.', discount: 'A discount is the last rung of the ladder, used only because this customer is worth it.', personal_outreach: 'Several things are going wrong at once. A person should reach out instead of sending more automatic messages.', win_back_offer: 'The customer has already left, so a gentle win-back offer is worth a try.' }[a]) || plain(c.decision.reason); };
const playRet = (all) => playShell('play-ret', 'Check a customer', 'Pick someone at risk of leaving. Impulse works out why and suggests the gentlest fix.',
  `<label>Customer<select id="t-c">${all.slice(0, 25).map((x) => `<option value="${esc(x.customer_id)}">${esc(x.name)} · ${riskWord(x.churn_risk)[0].toLowerCase()} risk</option>`).join('')}</select></label><button class="primary big" id="t-go">${UI.icon('bolt', 16)} Check this customer</button>`);
function wireRet(el) { const root = $('#play-ret', el); if (!root) return; const b = $('#t-go', root);
  b.onclick = async () => { const done = working(b, 'Thinking…'); try { const r = await api('/customers/' + encodeURIComponent($('#t-c', root).value) + '/evaluate', { method: 'POST' }); const c = await api('/cases/' + encodeURIComponent(r.case_id));
    const rs = (c.meta && c.meta.reasons) || []; playOut(root, resultCard(c.decision.chosen ? shortAction(c.decision.chosen.label) : 'Keep watching', layRet(c), `<div class="res-row">${c.meta && c.meta.churn_risk != null ? `<div><span>Risk of leaving</span>${riskPill(c.meta.churn_risk)}</div>` : ''}<div><span>Type</span><b>${c.meta && c.meta.churn_type === 'involuntary' ? 'Card problem' : c.meta && c.meta.churn_type === 'voluntary' ? 'Losing interest' : 'Mixed'}</b></div></div>${rs.length ? `<div class="res-k">Warning signs</div><ul class="ticks">${rs.map((x) => `<li class="n">${esc(label(x))}</li>`).join('')}</ul>` : ''}${optionsList(c)}${fullCaseBtn(c)}`)); bindFull(root);
  } catch (e) { toast(e.message); } finally { done(); } }; }

// Billing
const playBill = () => playShell('play-bill', 'Check a contract for billing mistakes', 'Enter what the contract says and what you actually billed. Impulse finds what is missing.',
  `<button type="button" class="chipf" id="b-ex">Load an example with mistakes</button>
   <label>Contract price ₹<input id="b-cp" type="number" min="0" value="50000"></label><label>Amount you billed ₹<input id="b-bl" type="number" min="0" value="50000"></label>
   <label>Seats in use<input id="b-as" type="number" min="0" value="10"></label><label>Seats you billed for<input id="b-bs" type="number" min="0" value="10"></label>
   <label>Price per seat ₹<input id="b-sp" type="number" min="0" value="1000"></label><label>Extra units used<input id="b-uu" type="number" min="0" value="0"></label>
   <label>Units included in the plan<input id="b-iu" type="number" min="0" value="0"></label><label>Price per extra unit ₹<input id="b-ur" type="number" min="0" value="0"></label><button class="primary big" id="b-go">${UI.icon('bolt', 16)} Check for mistakes</button>`);
function wireBill(el) { const root = $('#play-bill', el); if (!root) return; const num = (i) => +$('#' + i, root).value || 0;
  $('#b-ex', root).onclick = () => { ({ 'b-cp': 60000, 'b-bl': 50000, 'b-as': 14, 'b-bs': 10, 'b-sp': 1200, 'b-uu': 1500, 'b-iu': 1000, 'b-ur': 40 } && Object.entries({ 'b-cp': 60000, 'b-bl': 50000, 'b-as': 14, 'b-bs': 10, 'b-sp': 1200, 'b-uu': 1500, 'b-iu': 1000, 'b-ur': 40 }).forEach(([k, v]) => { $('#' + k, root).value = v; })); };
  const b = $('#b-go', root); b.onclick = async () => { const done = working(b, 'Checking…'); try {
    const r = await api('/billing/check', { method: 'POST', json: { contract_price: num('b-cp'), billed: num('b-bl'), active_seats: num('b-as'), billed_seats: num('b-bs'), seat_price: num('b-sp'), used_units: num('b-uu'), included_units: num('b-iu'), unit_rate: num('b-ur') } });
    const NAMES = { contract_vs_invoice: 'Billed less than the contract', seat_mismatch: 'More seats in use than billed', usage_vs_billing: 'Extra usage never billed' };
    playOut(root, r.findings.length ? `<div class="res"><div class="res-k">Impulse found</div><div class="res-t warnc">${UI.icon('search', 22)}<span>${inr(r.total)} that was never billed</span></div><p class="res-why">Each line below is money you are entitled to but have not charged.</p><ul class="found">${r.findings.map((f) => `<li><div><b>${esc(NAMES[f.check] || label(f.check))}</b><span>${esc(f.detail)}</span></div><em>${inr(f.amount)}</em></li>`).join('')}</ul></div>` : resultCard('No mistakes found', 'Everything adds up: what you billed matches the contract, the seats in use and the usage.'));
  } catch (e) { toast(e.message); } finally { done(); } }; }

/* ── screens ─────────────────────────────────────────────────────────────── */
const screens = {};

screens.dashboard = async (el) => {
  const [o, apr, ob, ret] = await Promise.all([api('/overview'), api('/approvals'), api('/outbox?limit=40'), api('/retention').catch(() => null)]);
  const LK = { failed: { href: '#payments', mods: ['payments'], line: 'Payments that did not go through' }, clawed_back: { href: '#clawback', mods: ['clawback', 'refunds', 'rto'], line: 'Money taken back after the sale' }, stopped: { href: '#retention', mods: ['retention'], line: 'Customers quietly stopping' }, missed: { href: '#billing', mods: ['billing'], line: 'Revenue never billed or collected' } };
  const MODCOL = { payments: 'var(--s1)', clawback: 'var(--s2)', refunds: 'var(--s2)', rto: 'var(--s2)', retention: 'var(--s3)', billing: 'var(--s4)' };
  const entries = Object.entries(o.by_leak), total = entries.reduce((a, [, v]) => a + v.at_stake, 0) || 1, sc = o.status_counts || {};
  const openCases = (sc.active || 0) + (sc.pending_approval || 0) + (sc.recommended || 0);
  const rel = (t) => { const d = Math.max(0, Date.now() / 1000 - t); return d < 90 ? 'just now' : d < 5400 ? Math.round(d / 60) + ' min ago' : d < 129600 ? Math.round(d / 3600) + ' h ago' : Math.round(d / 86400) + ' days ago'; };
  const feed = ob.items.filter((x) => x.event === 'decision.created' && x.payload.action).slice(0, 6);
  const pend = apr.items.slice(0, 4);
  const today = new Date().toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' });
  el.innerHTML = `<section class="dz-intro"><div class="dz-eyebrow">${esc(today)}</div>
    <h1 class="dz-title">Dashboard</h1>
    <p class="dz-lead">${o.pending_approvals ? `<b>${UI.num(o.pending_approvals, 'int')} ${o.pending_approvals === 1 ? 'decision needs' : 'decisions need'}</b> your approval.` : 'Nothing needs your approval right now.'} <b>${UI.num(openCases, 'int')} cases</b> are open, with <b>${UI.num(total, 'lakh')}</b> at stake.</p>
    <p class="dz-sub">Impulse is watching ${o.customers} customers${ret ? `. ${ret.totals.customers_at_risk} of them show signs of leaving` : ''}.</p></section>

  <section class="dz-river"><div class="dz-river-head"><span>Where the money is at stake</span><a href="#customers">All customers →</a></div>
    <div class="river">${entries.map(([k, v]) => { const m = LEAKS[k], I = LK[k], latest = o.top_actions.find((a) => I.mods.includes(a.module)); return `<a href="${I.href}" class="seg" style="--w:${(v.at_stake / total).toFixed(3)};--c:${m.c}"><span class="seg-name">${m.name}</span><span class="seg-line">${I.line}</span><b class="seg-num">${UI.num(v.at_stake, 'lakh')}</b><span class="seg-meta">${v.open ? `${v.open} open case${v.open > 1 ? 's' : ''}` : 'No open cases'}${latest ? ` · next: ${esc(shortAction(latest.action))}` : ''}</span><span class="seg-go">${m.mod} ${UI.icon('arrow', 14)}</span></a>`; }).join('')}</div></section>

  <div class="dz-cols">
    <section class="dz-list"><div class="dz-list-head"><h2>Waiting for you</h2><a href="#approvals">Open the inbox →</a></div>
      ${pend.length ? pend.map((x) => `<div class="dz-row" data-id="${esc(x.id)}" style="--c:${MODCOL[x.module] || 'var(--brand-indigo)'}"><div class="dz-row-main"><div class="dz-row-t"><b>${esc(shortAction(x.label))}</b><span class="muted">${esc(MODNAME[x.module] || label(x.module))}</span></div><p>${esc(cut(plain(x.reason).replace(/\s*Routed for approval.*$/, ''), 120))}</p></div><div class="dz-row-amt">${inr(x.amount)}</div><div class="dz-row-btns"><button class="ok" data-v="approve" title="Approve">${UI.icon('check', 16)}<span>Approve</span></button><button class="no" data-v="reject" title="Reject">${UI.icon('undo', 15)}<span>Reject</span></button></div></div>`).join('') : `<div class="empty-cta"><b>You are all caught up.</b><span>Approve or reject a few, then add more samples to keep exploring.</span><button class="primary" id="refill">Add sample decisions</button></div>`}</section>
    <section class="dz-list"><div class="dz-list-head"><h2>What Impulse just did</h2></div>
      ${feed.length ? `<ul class="dz-tl">${feed.map((x) => `<li style="--c:${MODCOL[x.payload.module] || 'var(--brand-indigo)'}"><div><b>${esc(ACTION[x.payload.action] || label(x.payload.action))}</b><span class="muted">${esc(MODNAME[x.payload.module] || label(x.payload.module))}</span></div><em>${rel(x.at)}</em></li>`).join('')}</ul>` : '<div class="empty">No decisions yet.</div>'}</section>
  </div>

  <section class="dz-bill"><div class="dz-bill-copy"><h2>You only pay for the extra</h2><p>Impulse's fee applies to money it recovers <b>beyond what you would have recovered on your own</b>. A control group on your current approach sets that baseline, and every rupee is listed on the <a href="#ledger">Results</a> page.</p></div>
    <div class="dz-eq" aria-label="Illustrative example"><div class="eq-bar"><i class="eq-base"></i><i class="eq-add"></i></div><div class="eq-cap"><div><b>₹100</b><span>you would recover anyway</span></div><div><b>+ ₹30</b><span>extra from Impulse</span></div></div><p class="eq-note">Illustrative example. The fee is charged on the extra ₹30 only.</p></div></section>`;
  const rf = $('#refill', el); if (rf) rf.onclick = async () => { rf.disabled = true; rf.textContent = 'Adding…'; try { const r = await api('/samples/refill', { method: 'POST' }); toast(r.added + ' sample decisions added'); route(); } catch (e) { toast(e.message); rf.disabled = false; } };
  el.querySelectorAll('.dz-row').forEach((row) => {
    row.onclick = (e) => { if (!e.target.closest('button')) showCase(row.dataset.id.replace('apr_', '')); };
    row.querySelectorAll('button[data-v]').forEach((b) => (b.onclick = async () => { try { await api('/approvals/' + row.dataset.id, { method: 'POST', json: { verdict: b.dataset.v } }); toast(b.dataset.v === 'approve' ? 'Approved' : 'Rejected'); route(); } catch (err) { toast(err.message); } }));
  });
};

screens.payments = async (el) => {
  const p = await api('/payments'); const f = p.funnel;
  const heatCodes = Object.keys(p.heatmap); const arms = Object.keys(p.heatmap[heatCodes[0]].start);
  const cats = Object.entries(p.decline_breakdown).sort((a, b) => b[1].count - a[1].count);
  el.innerHTML = `${pillarHead('payments')}${playPay()}
  <div class="grid g3">${kpi('Failed payments', f.failed, 'in this sample')}${kpi('Being handled', f.actioned)}${kpi('Recovered', f.recovered)}</div>
  <div class="grid g2"><div class="card"><h2>Why payments fail</h2>${hbars(cats.map(([k, v]) => ({ name: DECLINE[k] || label(k), v: v.count, note: '' })), 'var(--s1)', (n) => n + ' payments')}</div>
    <div class="card"><h2>What Impulse does about it</h2><ul class="plain-list"><li><b>Temporary failures</b> are retried at the time most likely to work, for example when salaries land.</li><li><b>Permanent failures</b> are never retried. The customer gets a link to update their payment method.</li><li><b>Repeated failures</b> switch to a friendlier offer instead of another retry.</li></ul></div></div>
  <div class="card"><div class="row between"><h2 style="margin:0">Recovery queue</h2></div>${chipBar('qf', [['all', 'All', p.queue.length], ['progress', 'In progress', p.queue.filter((r) => r.status === 'active').length], ['approval', 'Needs approval', p.queue.filter((r) => r.status === 'pending_approval').length], ['done', 'Done', p.queue.filter((r) => r.status === 'resolved').length]])}<div id="qt"></div></div>
  <details class="card adv"><summary>Advanced insights <span class="muted">(retry timing, cards expiring, routing)</span></summary>
    <div class="row between" style="margin-top:12px"><h2 style="margin:0">Best retry time ${tt('How likely each retry window is to succeed, by decline type and the day of the month the payment failed. Starts from sensible rules and updates as real outcomes arrive.')}</h2><select id="hc">${heatCodes.map((c) => `<option value="${c}">${label(c)}</option>`).join('')}</select></div><div id="hm" style="margin-top:8px"></div>
    <div class="grid g2" style="margin-top:16px"><div><h3>Cards expiring soon</h3>${table([{ h: 'Customer', f: (r) => `<a href="#customers/${encodeURIComponent(r.customer_id)}">${esc(r.customer_id)}</a>` }, { h: 'Expires', f: (r) => esc(r.expiry) }, { h: 'Days left', num: 1, f: (r) => r.days_left }], p.predunning.slice(0, 6), { empty: 'No cards expiring in the next 30 days.', limit: 0 })}</div>
      <div><h3>Which gateway to use at checkout</h3>${p.routing.advice.length ? table([{ h: 'Bank and method', f: (r) => esc(r.bank + ' · ' + r.method) }, { h: 'Best gateway', f: (r) => esc(r.route_to) }], p.routing.advice.slice(0, 6), { limit: 0 }) : '<div class="empty">Not enough volume yet.</div>'}<div class="muted" style="font-size:12px">${esc(p.routing.caveat)}</div></div></div></details>`;
  const m = () => { const code = $('#hc', el).value, mtx = p.heatmap[code], rows = ['start', 'mid', 'end'], mm = {}; rows.forEach((r) => { mm[r] = {}; arms.forEach((a) => { mm[r][label(a)] = mtx[r][a]; }); }); $('#hm', el).innerHTML = heat(mm, arms.map(label), rows); };
  $('#hc', el).onchange = m; m();
  const qcols = [{ h: 'Customer', f: (r) => `<b>${esc(r.features.customer_name && r.features.customer_name !== 'there' ? r.features.customer_name : 'Customer')}</b>` }, { h: 'Why it failed', f: (r) => esc(label(r.features.decline_code)) }, { h: 'Amount', num: 1, f: (r) => inr(r.amount) }, { h: 'What Impulse will do', f: (r) => esc(r.decision.chosen ? shortAction(r.decision.chosen.label) : 'Nothing') }, { h: 'Status', f: (r) => statusPill(r.status) }];
  const qmap = { all: () => true, progress: (r) => r.status === 'active', approval: (r) => r.status === 'pending_approval', done: (r) => r.status === 'resolved' };
  const drawQ = (f = 'all') => liveTable($('#qt', el), qcols, p.queue.filter(qmap[f]), { click: (r) => r.case_id, limit: 8, empty: 'Nothing in this view.' }, showCase);
  bindChips(el, 'qf', drawQ); drawQ(); wirePay(el);
};

screens.clawback = async (el, arg) => {
  const c = await api('/clawback'); const tab = arg || 'disputes';
  el.innerHTML = `${pillarHead('clawback')}<div id="tabbody"></div>`;
  const pre = tab === 'disputes' ? playDispute() : tab === 'refunds' ? playRefund() : tab === 'rto' ? playCod() : '';
  const body = $('#tabbody', el);
  const chance = (r) => (r.analysis && r.analysis.win_probability != null ? chanceWord(r.analysis.win_probability) : 'Unknown');
  if (tab === 'disputes') {
    const due = (r) => r.deadline_status && r.deadline_status.hours_left != null && r.deadline_status.hours_left < 72 && r.status !== 'resolved';
    body.innerHTML = `<div class="card"><h2>Disputes</h2>${chipBar('df', [['all', 'All', c.disputes.length], ['approval', 'Needs approval', c.disputes.filter((r) => r.status === 'pending_approval').length], ['due', 'Due within 3 days', c.disputes.filter(due).length], ['done', 'Done', c.disputes.filter((r) => r.status === 'resolved').length]])}<div id="dt"></div></div>`;
    const cols = [{ h: 'Dispute', f: (r) => `<span class="mono">${esc(r.features.dispute_id)}</span>${r.kind === 'pre_dispute' ? ' ' + pill('early warning', 'brand') : ''}` }, { h: 'Amount', num: 1, f: (r) => inr(r.amount) }, { h: 'Respond within', f: (r) => { const d = r.deadline_status; return d && d.hours_left != null ? pill(d.hours_left < 0 ? 'Overdue' : Math.max(1, Math.round(d.hours_left / 24)) + ' days', d.urgency === 'critical' || d.urgency === 'overdue' ? 'bad' : d.urgency === 'high' ? 'warn' : 'good') : ''; } }, { h: 'Chance of winning', f: (r) => chance(r) }, { h: 'Recommendation', f: (r) => esc(r.decision.chosen ? shortAction(r.decision.chosen.label) : '') }, { h: 'Status', f: (r) => statusPill(r.status) }];
    const fm = { all: () => true, approval: (r) => r.status === 'pending_approval', due, done: (r) => r.status === 'resolved' };
    const draw = (f = 'all') => liveTable($('#dt', el), cols, c.disputes.filter(fm[f]), { click: (r) => r.case_id, limit: 8, goLabel: 'Review', empty: 'Nothing in this view.' }, showCase);
    bindChips(el, 'df', draw); draw();
  }
  if (tab === 'refunds') {
    body.innerHTML = `<div class="card"><h2>Refund requests</h2>${chipBar('rf', [['all', 'All', c.refunds.length], ['approval', 'Needs approval', c.refunds.filter((r) => r.status === 'pending_approval').length], ['risky', 'Higher abuse risk', c.refunds.filter((r) => r.meta.abuse_probability >= 0.35).length], ['done', 'Done', c.refunds.filter((r) => r.status === 'resolved').length]])}<div id="rt"></div></div>`;
    const cols = [{ h: 'Customer', f: (r) => `<b>${esc((r.features.customer_name && r.features.customer_name !== 'there') ? r.features.customer_name : r.customer_id)}</b>` }, { h: 'Reason', f: (r) => esc(label(r.features.reason)) }, { h: 'Amount', num: 1, f: (r) => inr(r.amount) }, { h: 'Risk of abuse', f: (r) => riskPill(r.meta.abuse_probability) }, { h: 'Recommendation', f: (r) => esc(r.decision.chosen ? shortAction(r.decision.chosen.label) : '') }, { h: 'Status', f: (r) => statusPill(r.status) }];
    const fm = { all: () => true, approval: (r) => r.status === 'pending_approval', risky: (r) => r.meta.abuse_probability >= 0.35, done: (r) => r.status === 'resolved' };
    const draw = (f = 'all') => liveTable($('#rt', el), cols, c.refunds.filter(fm[f]), { click: (r) => r.case_id, limit: 8, goLabel: 'Review', empty: 'Nothing in this view.' }, showCase);
    bindChips(el, 'rf', draw); draw();
  }
  if (tab === 'rto') {
    const rows = c.rto.filter((r) => r.decision.chosen && r.decision.chosen.action !== 'ship_as_is');
    body.innerHTML = `<div class="card"><h2>COD orders that need a check</h2><p class="muted">Cash-on-delivery orders with a higher chance of being returned. Safe orders ship as normal and are not listed.</p>${table([{ h: 'Order', f: (r) => `<span class="mono">${esc(r.features.order_id)}</span>` }, { h: 'Amount', num: 1, f: (r) => inr(r.amount) }, { h: 'Return risk', f: (r) => riskPill(r.meta.rto_probability) }, { h: 'Recommended check', f: (r) => esc(r.decision.chosen ? shortAction(r.decision.chosen.label) : '') }, { h: 'Status', f: (r) => statusPill(r.status) }], rows, { click: (r) => r.case_id, limit: 8, empty: 'No risky orders right now.' })}</div>`;
  }
  if (pre) { body.insertAdjacentHTML('afterbegin', pre); if (tab === 'disputes') wireDispute(body); if (tab === 'refunds') wireRefund(body); if (tab === 'rto') wireCod(body); }
  bindRows(el, showCase);
};

screens.retention = async (el) => {
  const r = await api('/retention');
  const all = r.at_risk.filter((x) => x.churn_risk >= 0.3);
  const card = (x, i) => { const [rw, rk] = riskWord(x.churn_risk); return `<div class="rc-card spot" style="--i:${i % 9}"><div class="rc-top"><span class="avatar ${rk}">${esc(initials(x.name))}</span><div><a class="rc-name" href="#customers/${encodeURIComponent(x.customer_id)}">${esc(x.name)}</a><div class="muted" style="font-size:12px">${x.fusion ? 'Several issues at once' : x.churn_type === 'involuntary' ? 'Card problem' : x.churn_type === 'voluntary' ? 'Losing interest' : 'Mixed signals'}</div></div>${pill(rw + ' risk', rk)}</div>
    <div class="rc-why"><span>Why</span>${esc(x.reasons.length ? x.reasons.slice(0, 2).map(label).join(', ') : 'Early warning signs')}</div>
    <div class="rc-do"><span>Suggested</span><b>${esc(x.action ? shortAction(x.action) : 'Keep watching')}</b></div>
    <div class="rc-btns">${x.case_id ? `<button class="primary" data-case="${esc(x.case_id)}">Review action</button>` : `<button class="primary" data-eval="${esc(x.customer_id)}">Get recommendation</button>`}<a class="btn" href="#customers/${encodeURIComponent(x.customer_id)}">View profile</a></div></div>`; };
  el.innerHTML = `${pillarHead('retention')}${playRet(all)}
  ${chipBar('rtf', [['all', 'All at risk', all.length], ['card', 'Card problems', all.filter((x) => x.churn_type === 'involuntary').length], ['interest', 'Losing interest', all.filter((x) => x.churn_type === 'voluntary' || x.churn_type === 'mixed').length], ['multi', 'Several issues', all.filter((x) => x.fusion).length], ['action', 'Has a suggested action', all.filter((x) => x.case_id).length]])}
  <div id="rgrid" class="rc-grid"></div><div id="rmore" class="more-wrap" style="border:0"></div>`;
  const fm = { all: () => true, card: (x) => x.churn_type === 'involuntary', interest: (x) => x.churn_type === 'voluntary' || x.churn_type === 'mixed', multi: (x) => x.fusion, action: (x) => x.case_id };
  const draw = (f = 'all') => {
    const rows = all.filter(fm[f]), first = rows.slice(0, 9);
    $('#rgrid', el).innerHTML = first.length ? first.map(card).join('') : '<div class="empty" style="grid-column:1/-1">Nobody in this view.</div>';
    $('#rmore', el).innerHTML = rows.length > 9 ? `<button class="show-more" type="button">Show all ${rows.length}</button>` : '';
    const more = $('#rmore .show-more', el); if (more) more.onclick = () => { $('#rgrid', el).innerHTML = rows.map(card).join(''); $('#rmore', el).innerHTML = ''; wire(); };
    wire();
  };
  const wire = () => { el.querySelectorAll('.rc-card button[data-case]').forEach((b) => (b.onclick = () => showCase(b.dataset.case)));
    el.querySelectorAll('.rc-card button[data-eval]').forEach((b) => (b.onclick = async () => { b.disabled = true; b.textContent = 'Thinking…'; try { const r = await api('/customers/' + encodeURIComponent(b.dataset.eval) + '/evaluate', { method: 'POST' }); showCase(r.case_id); } catch (e) { toast(e.message); } finally { b.disabled = false; b.textContent = 'Get recommendation'; } })); };
  bindChips(el, 'rtf', draw); draw(); wireRet(el);
};

screens.billing = async (el) => {
  const b = await api('/billing');
  el.innerHTML = `${pillarHead('billing')}${playBill()}<div class="banner">This pillar is on the roadmap. It runs on sample invoices with mistakes planted on purpose, to show the idea.</div>
  <div class="grid g3">${kpi('Billing mistakes found', b.findings.length)}${kpi('Overdue invoices', b.worklist.length)}${kpi('Promises to pay tracked', b.promises.length)}</div>
  <div class="card"><h2>Billing mistakes found</h2>${table([{ h: 'Customer', f: (r) => esc(r.customer || '') }, { h: 'What is wrong', f: (r) => esc(r.detail) }, { h: 'Amount', num: 1, f: (r) => inr(r.amount) }, { h: 'Fix', f: (r) => esc(r.fix) }], b.findings, { limit: 6 })}</div>
  <div class="card"><h2>Who to chase first</h2>${table([{ h: 'Invoice', f: (r) => `<b>${esc(r.customer)}</b><div class="muted mono">${esc(r.invoice)}</div>` }, { h: 'Overdue', num: 1, f: (r) => r.days_overdue + ' days' }, { h: 'Amount', num: 1, f: (r) => inr(r.amount) }, { h: 'Next step', f: (r) => esc(r.next_action) }, { h: '', f: (r) => `<button data-p='${esc(JSON.stringify({ invoice: r.invoice, customer: r.customer, amount: r.amount }))}'>Log a promise</button>` }], b.worklist, { limit: 6 })}</div>
  ${b.promises.length ? `<div class="card"><h2>Promises to pay</h2>${table([{ h: 'Invoice', f: (r) => esc(r.invoice) }, { h: 'Customer', f: (r) => esc(r.customer) }, { h: 'Promised', f: (r) => esc(r.promised_date) }, { h: 'Status', f: (r) => pill(r.status, r.status === 'kept' ? 'good' : r.status === 'broken' ? 'bad' : '') }, { h: '', f: (r) => r.status === 'open' ? `<button data-k="${r.id}:kept">Kept</button> <button class="danger" data-k="${r.id}:broken">Broken</button>` : '' }], b.promises)}</div>` : ''}`;
  el.querySelectorAll('button[data-p]').forEach((btn) => (btn.onclick = async () => { const p = JSON.parse(btn.dataset.p); p.promised_date = new Date(Date.now() + 5 * 864e5).toISOString().slice(0, 10); await api('/billing/promises', { method: 'POST', json: p }); toast('Promise logged'); route(); }));
  el.querySelectorAll('button[data-k]').forEach((btn) => (btn.onclick = async () => { const [id, o] = btn.dataset.k.split(':'); await api(`/billing/promises/${id}/${o}`, { method: 'POST' }); route(); }));
  wireBill(el);
};

screens.customers = async (el, arg) => {
  if (arg) return customer360(el, decodeURIComponent(arg));
  const d = await api('/customers?limit=200'); const all = d.customers;
  el.innerHTML = `<div class="pf-head"><h1>Customers</h1><p class="sub">One profile per customer, even when they pay through different gateways. Select someone to see their story.</p></div>
  <div class="row" style="margin-bottom:12px;gap:14px">${chipBar('cf', [['all', 'Everyone', all.length], ['risk', 'At risk of leaving', all.filter((r) => r.churn_risk >= 0.6).length], ['refunds', 'Frequent refunds', all.filter((r) => r.serial_abuser).length], ['multi', 'Several issues', all.filter((r) => r.fusion).length]])}<input id="f" placeholder="Search by name or email" style="min-width:260px;margin-left:auto"></div><div id="cgrid" class="rc-grid"></div><div id="cmore" class="more-wrap" style="border:0"></div>`;
  const fm = { all: () => true, risk: (r) => r.churn_risk >= 0.6, refunds: (r) => r.serial_abuser, multi: (r) => r.fusion };
  let f = 'all';
  const card = (r) => { const [rw, rk] = riskWord(r.churn_risk); return `<a class="rc-card spot cust-card" href="#customers/${encodeURIComponent(r.customer_id)}"><div class="rc-top"><span class="avatar ${rk}">${esc(initials(r.name))}</span><div><div class="rc-name">${esc(r.name)}</div><div class="muted" style="font-size:12px;overflow:hidden;text-overflow:ellipsis;max-width:190px">${esc(r.email || r.customer_id)}</div></div></div>
    <div class="cc-stats"><div><span>Customer value</span><b>${inr(r.value_score)}</b></div><div><span>Risk of leaving</span>${pill(rw, rk)}</div></div>
    <div class="cc-tags">${r.serial_abuser ? pill('frequent refunds', 'bad') : ''}${r.fusion ? pill('several issues', 'warn') : ''}${r.sources.length > 1 ? pill(r.sources.length + ' gateways', 'brand') : ''}</div><span class="cc-go">View profile ${UI.icon('arrow', 14)}</span></a>`; };
  const draw = (showAll) => {
    const q = $('#f', el).value.toLowerCase(), rows = all.filter(fm[f]).filter((r) => (r.name + r.email + r.customer_id).toLowerCase().includes(q));
    $('#cgrid', el).innerHTML = rows.length ? (showAll ? rows : rows.slice(0, 12)).map(card).join('') : '<div class="empty" style="grid-column:1/-1">No customers match.</div>';
    $('#cmore', el).innerHTML = !showAll && rows.length > 12 ? `<button class="show-more" type="button">Show all ${rows.length}</button>` : '';
    const m = $('#cmore .show-more', el); if (m) m.onclick = () => draw(true);
  };
  bindChips(el, 'cf', (k) => { f = k; draw(); }); $('#f', el).oninput = () => draw(); draw();
};
async function customer360(el, id) {
  const v = await api('/customers/' + encodeURIComponent(id)); const p = v.passport, ch = p.clawback_history;
  const trust = p.trust_score >= 80 ? ['High', 'good'] : p.trust_score >= 55 ? ['Medium', 'warn'] : ['Low', 'bad'];
  const [rw, rk] = riskWord(p.churn_risk);
  const openCase = v.cases.find((c) => ['active', 'pending_approval', 'recommended'].includes(c.status));
  const story = p.timeline.slice(0, 10).map((t) => {
    if (t.type === 'impulse_action') { const m = /^(\w+) \((\w+)\)$/.exec(t.detail || ''); return { ic: 'spark', text: 'Impulse: ' + (m ? (ACTION[m[1]] || label(m[1])) : humanize(t.detail)), tag: m ? (m[2] === 'completed' ? 'done' : m[2] === 'pending_approval' ? 'waiting for approval' : 'in progress') : '', t: t.t }; }
    const names = { payment_failed: 'Payment failed', payment_succeeded: 'Payment succeeded', refund: 'Asked for a refund', dispute: 'Opened a dispute', ticket: 'Contacted support', downgrade: 'Downgraded their plan', seat_reduction: 'Reduced seats', offer_taken: 'Accepted an offer' };
    return { ic: t.type.startsWith('payment') ? 'card' : t.type === 'dispute' ? 'shield' : 'user', text: (names[t.type] || label(t.type)) + (t.detail ? ' · ' + humanize(t.detail) : ''), tag: '', t: t.t };
  });
  el.innerHTML = `<p><a href="#customers">← All customers</a></p>
  <div class="cust-head"><span class="avatar big ${rk}">${esc(initials(p.profile.name || p.profile.email))}</span><div><h1 style="margin:0">${esc(p.profile.name || p.profile.email || id)}</h1><div class="muted">${esc(p.profile.email || '')} ${esc(p.profile.phone || '')}${v.identity.linked_ids.length > 1 ? ` · seen on ${v.identity.linked_ids.length} gateways, merged into one profile` : ''}</div></div>
    <div class="cust-actions">${openCase ? `<button class="primary" id="oc">Review open case ${UI.icon('arrow', 14)}</button>` : ''}<a class="btn" href="#approvals">Approval Inbox</a></div></div>
  ${p.fusion ? `<div class="card" style="border-color:var(--brand-rose)"><b>${pill('Needs a personal touch', 'bad')} ${esc(p.fusion.explanation)}</b></div>` : ''}
  <div class="grid g3">${kpi('Customer value', inrC(p.value_score), 'estimated lifetime revenue')}<div class="card kpi"><div class="v">${pill(trust[0], trust[1])}</div><div class="l">Trust</div><div class="muted" style="font-size:12px">${ch.refund_count} refunds, ${ch.disputes} disputes</div></div><div class="card kpi"><div class="v">${pill(rw, rk)}</div><div class="l">Risk of leaving</div><div class="muted" style="font-size:12px">${esc(p.churn_reasons.map(label).join(', ') || 'No warning signs')}</div></div></div>
  <div class="grid g2"><div class="card"><h2>Their story</h2>${story.length ? `<ol class="story">${story.map((x) => `<li><span class="st-ico">${UI.icon(x.ic, 15)}</span><div><b>${esc(x.text)}</b>${x.tag ? ' ' + pill(x.tag, x.tag === 'done' ? 'good' : 'brand') : ''}<div class="muted" style="font-size:12px">${new Date(x.t * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })}</div></div></li>`).join('')}</ol>` : '<div class="empty">No activity yet.</div>'}</div>
    <div class="card"><h2>What Impulse is doing</h2>${v.cases.length ? v.cases.slice(0, 6).map((c) => `<a class="attn-row" data-case="${esc(c.case_id)}"><span class="pill brand">${esc(kindLabel(c.kind))}</span><span class="attn-t">${esc(c.decision.chosen ? shortAction(c.decision.chosen.label) : 'No action needed')}</span>${statusPill(c.status)}${UI.icon('arrow', 14)}</a>`).join('') : '<div class="empty">Nothing open for this customer.</div>'}</div></div>`;
  el.querySelectorAll('.attn-row').forEach((r) => (r.onclick = () => showCase(r.dataset.case)));
  if ($('#oc', el)) $('#oc', el).onclick = () => showCase(openCase.case_id);
}

screens.approvals = async (el) => {
  const a = await api('/approvals');
  el.innerHTML = `<h1>Approval Inbox</h1><p class="sub">Decisions Impulse will not make without you. Approve, choose a different option, or reject.</p>${a.items.length ? a.items.map((x) => `<div class="card" data-id="${esc(x.id)}"><div class="row between"><div><b>${esc(shortAction(x.label))}</b> ${pill(label(x.module), 'brand')} <span class="muted">${inr(x.amount)} at stake</span></div><a href="#customers/${encodeURIComponent(x.customer_id)}">${esc(x.customer_id)}</a></div>
    <div class="reason">${esc(plain(x.reason))}</div>
    <div class="row" style="margin-top:10px"><button class="primary" data-v="approve">Approve</button><select class="alt">${x.alternatives.filter((y) => y.action !== x.action).map((y) => `<option value="${esc(y.action)}">${esc(shortAction(y.label))}</option>`).join('')}</select><button data-v="edit">Use this instead</button><button class="danger" data-v="reject">Reject</button><button data-v="open">Open case</button></div></div>`).join('') : `<div class="card"><div class="empty-cta"><b>Inbox zero.</b><span>Nothing needs you right now. Add more sample decisions to keep exploring.</span><button class="primary" id="refill">Add sample decisions</button></div></div>`}`;
  const rf2 = $('#refill', el); if (rf2) rf2.onclick = async () => { rf2.disabled = true; try { const r = await api('/samples/refill', { method: 'POST' }); toast(r.added + ' sample decisions added'); route(); } catch (e) { toast(e.message); rf2.disabled = false; } };
  el.querySelectorAll('.card[data-id]').forEach((card) => card.querySelectorAll('button[data-v]').forEach((b) => (b.onclick = async () => {
    const id = card.dataset.id, v = b.dataset.v; if (v === 'open') return showCase(id.replace('apr_', ''));
    try { await api('/approvals/' + id, { method: 'POST', json: { verdict: v, edit_action: v === 'edit' ? $('.alt', card).value : null } }); toast('Decision recorded'); route(); } catch (e) { toast(e.message); } })));
};

screens.ledger = async (el) => {
  const l = await api('/ledger'); const s = l.summary;
  el.innerHTML = `<h1>Results</h1><p class="sub">Every recovered rupee, listed and auditable. Only revenue beyond what you would have recovered on your own counts towards the fee.</p>
  <div class="banner">This is a sample ledger. The outcomes are simulated, so treat the amounts as an illustration of the format, not as real results.</div>
  <div class="grid g3">${kpi('Recovered', inrC(s.gross_recovered))}${kpi('Beyond your baseline', inrC(s.net_incremental), 'after the cost of acting')}${kpi('Impulse fee (' + s.fee_pct + '%)', inrC(s.impulse_fee), 'on the amount beyond baseline')}</div>
  <div class="card"><div class="row between"><h2 style="margin:0">By area ${tt('Your baseline is what would have been recovered without Impulse. It is measured from a control group left on your original logic, or assumed until the control group is large enough.')}</h2><div>${l.chain.valid ? pill('Audit trail verified', 'good') : pill('Audit trail broken', 'bad')} <a href="${API}/ledger/export.csv">Download CSV</a></div></div>
  ${table([{ h: 'Area', f: (r) => label(r[0]) }, { h: 'Cases', num: 1, f: (r) => r[1].cases }, { h: 'Recovered', num: 1, f: (r) => inr(r[1].gross_recovered) }, { h: 'Beyond baseline', num: 1, f: (r) => '<b>' + inr(r[1].net) + '</b>' }], Object.entries(s.by_module), { limit: 0 })}</div>
  <details class="card adv"><summary>Detailed entries <span class="muted">(latest ${Math.min(l.entries.length, 15)})</span></summary>${table([{ h: '#', num: 1, f: (r) => r.seq }, { h: 'What', f: (r) => label(r.module) + ' · ' + label(r.action) + (r.arm === 'holdout' ? ' ' + pill('control group') : '') }, { h: 'Recovered', num: 1, f: (r) => inr(r.recovered) }, { h: 'Why', f: (r) => `<span class="muted">${esc(plain(r.receipt.reason || '')).slice(0, 110)}</span>` }], l.entries.slice(0, 15), { limit: 0 })}</details>`;
};

screens.replay = async (el) => drawReplay(el, await api('/replay-lab'));
function drawReplay(el, r) {
  const P = r.policies, order = ['baseline', 'rules', 'frozen', 'impulse'], lf = r.lift, ac = r.attribution_check;
  el.innerHTML = `<h1>Replay Lab</h1><div class="banner">${esc(r.disclosure)}</div><p class="sub">Four policies replay the same failed payments in a simulated world whose true retry behaviour is hidden from every policy. ${r.config.worlds} worlds × ${r.config.cases_per_world} failures, ${r.config.holdout_pct}% holdout.</p>
  <div class="grid g4">${kpi('Impulse vs merchant baseline', '+' + lf.recovery_rate_pts.mean + ' pts', '95% CI ' + lf.recovery_rate_pts.lo + ' to ' + lf.recovery_rate_pts.hi)}${kpi('extra ₹ recovered per world', inrC(lf.extra_recovered_inr))}${kpi('churn loss avoided', inrC(lf.churn_loss_avoided_inr))}${kpi('what learning added', (lf.learning_gain_pts >= 0 ? '+' : '') + lf.learning_gain_pts + ' pts', 'vs Impulse frozen at rule priors')}</div>
  <div class="card"><h2>Cumulative recovery rate by failure week</h2><div id="curve"></div><div class="muted">Impulse starts near the static playbook and adjusts as the bandit sees real outcomes.</div></div>
  <div class="grid g2"><div class="card"><h2>Recovery rate with 95% interval</h2>${order.map((k) => { const v = P[k].recovery_rate; return `<div style="margin:9px 0"><div class="row between"><span><span class="leak-dot" style="background:${POLICY_COLORS[k]}"></span>${esc(POLICY_NAMES[k])}</span><b>${pct(v.mean, 1)}</b></div><div class="meter" style="position:relative"><i style="width:${v.mean * 100}%;background:${POLICY_COLORS[k]}"></i></div><div class="muted" style="font-size:11px">${pct(v.lo, 1)} to ${pct(v.hi, 1)} · involuntary churn ${pct(P[k].involuntary_churn_rate.mean, 1)} · ${P[k].retries_per_recovery} retries per recovery</div></div>`; }).join('')}</div>
  <div class="card"><h2>Is the ledger's attribution honest?</h2><div class="grid g2"><div class="kpi"><div class="v">${inrC(ac.ledger_estimated_incremental_inr)}</div><div class="l">estimated from the holdout arm</div></div><div class="kpi"><div class="v">${inrC(ac.true_incremental_inr)}</div><div class="l">true, from the simulated counterfactual</div></div></div><p class="muted">${esc(ac.note)}</p>
  <div class="reason">Honest reading: against a well-built static playbook, Impulse's recovery rate is roughly level. Its edge is measured against the merchant's original logic, plus lower churn and fewer retries. Learning adds recovery but can cost some churn; the numbers above show both.</div></div></div>
  <div class="card"><h2>Run a fresh simulation</h2><div class="row"><label>Failures per world<input id="n" type="number" value="400" min="100" max="1500"></label><label>Worlds<input id="w" type="number" value="3" min="1" max="6"></label><label>Holdout %<input id="h" type="number" value="10" min="0" max="40"></label><button class="primary" id="run">Run</button><span id="st" class="muted"></span></div></div>`;
  lineChart($('#curve', el), order.map((k) => ({ name: POLICY_NAMES[k], data: P[k].weekly_cumulative_rate, color: POLICY_COLORS[k], dash: k === 'frozen' })), { xs: P.impulse.weekly_cumulative_rate.map((_, i) => 'wk ' + (i + 1)), fmt: (v) => pct(v), yMin: 0.3, height: 260 });
  $('#run', el).onclick = async () => { $('#st', el).textContent = 'Running…'; try { const res = await api(`/replay-lab/run?cases=${$('#n', el).value}&worlds=${$('#w', el).value}&holdout_pct=${$('#h', el).value}`, { method: 'POST' }); toast('Done: showing fresh results'); drawReplay(el, res); } catch (e) { $('#st', el).textContent = e.message; } };
}

screens.audit = async (el) => {
  const KINDS = [['payments', 'card', 'Payments', 'Every attempt with status and decline reason', true], ['disputes', 'shield', 'Disputes', 'Chargebacks with outcome and amount'], ['refunds', 'refresh', 'Refunds', 'Refund requests and reasons'],
    ['subscriptions', 'users', 'Subscriptions', 'Plans, status and last payment result'], ['invoices', 'file', 'Invoices', 'Due dates and payment dates']];
  el.innerHTML = `<div class="pf-head"><span class="pf-tag"><i style="background:var(--brand-indigo)"></i>Free · no integration needed</span><h1>Leak Audit</h1>
    <p class="sub">Upload up to 90 days of exports. Impulse maps your columns automatically and shows what leaked and what it would have recovered.</p>
    <div class="pf-steps"><div class="pf-step"><b>1</b><div><strong>Upload</strong><span>Drop CSV or Excel exports. Payments is enough to start.</span></div></div><div class="pf-step"><b>2</b><div><strong>Auto-map</strong><span>Column names are matched for you, and you can review them.</span></div></div><div class="pf-step"><b>3</b><div><strong>Get the report</strong><span>Leak by cause, top findings and a printable PDF.</span></div></div></div></div>
  ${(window.IMP && window.IMP.dataStatus ? window.IMP.dataStatus() : '')}
  <div class="card audit-card"><div class="dz-grid">${KINDS.map(([k, ic, t, d, req]) => `<label class="dz" data-k="${k}"><input type="file" data-k="${k}" accept=".csv,.xlsx,.xls" hidden>
      <span class="dz-ico">${UI.icon(ic, 22)}</span><span class="dz-t">${t}${req ? '<em>start here</em>' : ''}</span><span class="dz-d">${d}</span>
      <span class="dz-drop">${UI.icon('arrow', 14)} Drop file or <u>browse</u></span><span class="dz-file"><span class="dz-name"></span><button type="button" class="dz-x" aria-label="Remove file">×</button></span></label>`).join('')}</div>
    <div class="audit-actions"><button class="primary big" id="up" disabled>${UI.icon('search', 16)} Run audit</button><button class="big" id="sample">${UI.icon('spark', 16)} Try with sample data</button><span class="muted" id="hint">Add at least one file to begin. Files are analysed in memory and never stored.</span></div></div><div id="res"></div>`;
  const refresh = () => { const n = el.querySelectorAll('.dz.has').length; $('#up', el).disabled = !n; $('#hint', el).textContent = n ? `${n} file${n > 1 ? 's' : ''} ready.` : 'Add at least one file to begin. Files are analysed in memory and never stored.'; };
  el.querySelectorAll('.dz').forEach((z) => {
    const input = $('input', z), setFile = (f) => { if (!f) return; const dt = new DataTransfer(); dt.items.add(f); input.files = dt.files; $('.dz-name', z).textContent = f.name + ' · ' + (f.size / 1024).toFixed(0) + ' KB'; z.classList.add('has'); refresh(); };
    input.onchange = () => setFile(input.files[0]);
    ['dragenter', 'dragover'].forEach((ev) => z.addEventListener(ev, (e) => { e.preventDefault(); z.classList.add('over'); }));
    ['dragleave', 'drop'].forEach((ev) => z.addEventListener(ev, (e) => { e.preventDefault(); z.classList.remove('over'); }));
    z.addEventListener('drop', (e) => setFile(e.dataTransfer.files[0]));
    $('.dz-x', z).onclick = (e) => { e.preventDefault(); e.stopPropagation(); input.value = ''; z.classList.remove('has'); refresh(); };
  });
  const show = (j) => { const r = j.report; $('#res', el).innerHTML = `<div class="card hero"><div class="big">${esc(r.headline)}</div><div class="muted">${esc(r.disclosure)}</div><div class="row" style="margin-top:10px"><a class="btn" href="${API}/audit/${j.session}/report" target="_blank">Open printable report (save as PDF)</a></div></div>
    <div class="grid g2"><div class="card"><h2>Leak by cause</h2>${Object.entries(LEAKS).map(([k, m]) => `<div style="margin:9px 0"><div class="row between"><span><span class="leak-dot" style="background:${m.c}"></span>${m.name}</span><span>leaked <b>${inr(r.by_cause[k].leaked)}</b> · recoverable ${inr(r.by_cause[k].recoverable)}</span></div>${stackBar([{ name: 'Recoverable', v: r.by_cause[k].recoverable, c: m.c }, { name: 'Unrecoverable', v: Math.max(r.by_cause[k].leaked - r.by_cause[k].recoverable, 0), c: 'var(--line-strong)' }])}</div>`).join('')}</div>
    <div class="card"><h2>Top findings</h2><ul>${r.top_findings.map((f) => `<li>${esc(f.text)}</li>`).join('')}</ul></div></div>
    <div class="card"><h2>Customers with the most exposure</h2>${table([{ h: 'Customer', f: (c) => esc(c.customer) }, { h: 'Exposure', num: 1, f: (c) => inr(c.exposure) }, { h: 'Causes', f: (c) => c.causes.map((x) => pill(label(x))).join(' ') }], r.sample_customers)}</div>
    <div class="card"><h2>How your columns were mapped</h2>${Object.entries(r.mapping).map(([k, m]) => `<h3>${label(k)} (${r.rows_analysed[k]} rows)</h3><div class="row">${Object.entries(m).map(([f, c]) => c ? pill(f + ' ← ' + c, 'good') : pill(f + ' unmapped')).join(' ')}</div>`).join('')}${r.problems.length ? `<div class="banner" style="margin-top:10px">${r.problems.map(esc).join('<br>')}</div>` : ''}<details style="margin-top:10px"><summary>Assumptions behind the estimates</summary><pre class="mono">${esc(JSON.stringify(r.assumptions, null, 1))}</pre></details></div>`; };
  $('#sample', el).onclick = async () => { $('#sample', el).disabled = true; try { show(await api('/audit/sample')); } finally { $('#sample', el).disabled = false; } $('#res', el).scrollIntoView({ behavior: 'smooth', block: 'start' }); };
  $('#up', el).onclick = async () => { const fd = new FormData(); let n = 0; el.querySelectorAll('input[type=file]').forEach((i) => { if (i.files[0]) { fd.append(i.dataset.k, i.files[0]); n++; } }); if (!n) return toast('Choose at least one file'); const b = $('#up', el); b.disabled = true; b.textContent = 'Analysing…'; try { show(await api('/audit/upload', { method: 'POST', form: fd })); $('#res', el).scrollIntoView({ behavior: 'smooth', block: 'start' }); } catch (e) { toast(e.message); } finally { b.innerHTML = UI.icon('search', 16) + ' Run audit'; refresh(); } };
};

screens.connections = async (el) => {
  const [c, dl, idn, ob, al, smp] = await Promise.all([api('/connections'), api('/dead-letters'), api('/identity'), api('/outbox?limit=8'), api('/audit-log?limit=12'), api('/webhooks/samples')]);
  el.innerHTML = `<h1>Connections</h1><p class="sub">Razorpay, Stripe and custom sources land in one canonical schema. Duplicate deliveries never double-count.</p>
  ${(window.IMP && window.IMP.dataStatus ? window.IMP.dataStatus() : '')}<div class="grid g3">${c.connections.map((x) => `<div class="card"><b>${label(x.source)}</b> ${pill(x.status, x.status === 'healthy' ? 'good' : '')}<div class="muted">Endpoint <span class="mono">${esc(c.endpoints[x.source])}</span></div><div class="muted">Signature verification: ${x.signature_verification ? 'on' : 'off (demo)'}</div><div class="row" style="margin-top:6px"><input placeholder="webhook secret" data-s="${x.source}" style="width:140px"><button data-set="${x.source}">Save</button></div></div>`).join('')}</div>
  <div class="card"><h2>Live webhook simulator</h2><div class="muted">Send a recorded payload through the real ingestion path. Try the Razorpay soft decline, then the Stripe one: same person, two gateways, one identity.</div><div class="row" style="margin:10px 0">${Object.entries(smp).map(([k, v]) => `<button data-sim="${k}">${esc(v.label)}</button>`).join('')}</div><div id="simout"></div></div>
  <div class="grid g2"><div class="card"><h2>Dead-letter queue (${dl.items.length})</h2>${dl.items.length ? dl.items.map((d) => `<div style="margin-bottom:12px"><div>${pill(d.source)} <b>${esc(d.error)}</b> <span class="mono muted">${esc(d.id)}</span></div><textarea rows="5" data-t="${d.id}">${esc(JSON.stringify(d.event || d.raw, null, 1))}</textarea><button data-r="${d.id}">Fix payload and replay</button></div>`).join('') : '<div class="empty">Nothing failed to map.</div>'}</div>
  <div class="card"><h2>Identity resolution</h2><h3>Recent merges</h3>${table([{ h: 'Kept', f: (m) => `<span class="mono">${esc(m.keep)}</span>` }, { h: 'Absorbed', f: (m) => `<span class="mono">${esc(m.absorbed)}</span>` }, { h: 'Why', f: (m) => esc(m.reason || m.action) }, { h: '', f: (m) => m.action === 'merge' ? `<button data-un="${m.id}">Unmerge</button>` : '' }], idn.merges.slice(-6), { empty: 'No merges yet.' })}<h3 style="margin-top:10px">Suggested merges (human decides)</h3>${table([{ h: 'A', f: (s) => esc(s.a) }, { h: 'B', f: (s) => esc(s.b) }, { h: 'Match', f: (s) => esc(s.reason) }, { h: '', f: (s) => `<button data-m="${esc(s.a)}|${esc(s.b)}">Merge</button>` }], idn.suggestions.slice(0, 4), { empty: 'No suggestions.' })}</div></div>
  <details class="card adv"><summary>Advanced: outbound webhooks and audit log</summary><div class="grid g2" style="margin-top:12px"><div class="card"><h2>Outbound webhooks</h2><div class="row"><input id="wu" placeholder="https://your-system.example/hooks/impulse" style="flex:1"><button id="wa">Add</button></div><div class="muted">${c.webhook_urls.map(esc).join(', ') || 'None registered. Events queue in the outbox.'}</div>${table([{ h: 'Event', f: (o) => esc(o.event) }, { h: 'Delivery', f: (o) => pill(o.delivery) }], ob.items, { empty: 'No events yet.' })}</div>
  <div class="card"><h2>Audit log</h2>${table([{ h: 'Who', f: (a) => esc(a.actor) }, { h: 'What', f: (a) => esc(a.event) }, { h: 'When', f: (a) => new Date(a.at * 1000).toLocaleString() }], al.items)}</div></div></details>`;
  el.querySelectorAll('[data-set]').forEach((b) => (b.onclick = async () => { const s = b.dataset.set, v = $(`[data-s="${s}"]`, el).value; await api('/connections/secret', { method: 'PUT', json: { source: s, secret: v || null } }); toast(v ? 'Signature verification on' : 'Signature verification off'); route(); }));
  el.querySelectorAll('[data-sim]').forEach((b) => (b.onclick = async () => { const r = await api('/webhooks/simulate', { method: 'POST', json: { name: b.dataset.sim } }); const x = r.result; $('#simout', el).innerHTML = `<div class="reason"><b>${esc(r.sent)}</b><br>Result: ${pill(x.status, x.status === 'processed' ? 'good' : 'warn')} ${x.entities ? 'entities: ' + esc(x.entities.join(', ')) : esc(x.error || '')}${r.customer ? `<br>Resolved customer <b>${esc(r.customer.identity.id)}</b> linked to ${r.customer.identity.linked_ids.map(esc).join(' + ')}` : ''}</div>${r.cases.map((cs) => `<div class="msg" style="margin-top:6px">${esc(cs.explain)}</div>`).join('')}<details><summary>Payload</summary><pre class="mono">${esc(JSON.stringify(r.payload, null, 1))}</pre></details>`; refreshNav(); }));
  el.querySelectorAll('[data-r]').forEach((b) => (b.onclick = async () => { try { const ev = JSON.parse($(`[data-t="${b.dataset.r}"]`, el).value); const r = await api(`/dead-letters/${b.dataset.r}/replay`, { method: 'POST', json: { patched_event: ev } }); toast('Replay: ' + r.status); route(); } catch (e) { toast(e.message); } }));
  el.querySelectorAll('[data-un]').forEach((b) => (b.onclick = async () => { await api('/identity/unmerge/' + b.dataset.un, { method: 'POST' }); toast('Unmerged'); route(); }));
  el.querySelectorAll('[data-m]').forEach((b) => (b.onclick = async () => { const [a, bb] = b.dataset.m.split('|'); await api('/identity/merge', { method: 'POST', json: { a, b: bb } }); toast('Merged'); route(); }));
  $('#wa', el).onclick = async () => { await api('/outbound-webhooks', { method: 'POST', json: { url: $('#wu', el).value } }); route(); };
};

screens.settings = async (el) => {
  const p = await api('/policy'); const mods = Object.keys(p.autonomy), lv = ['auto', 'approve', 'recommend'];
  el.innerHTML = `<h1>Settings</h1><p class="sub">Autonomy, budgets, guardrails and economics in one policy (version ${p.version}). Every change is written to the audit log.</p>
  <div class="grid g2"><div class="card"><h2>Autonomy per module</h2><div class="form">${mods.map((m) => `<label>${label(m)}<select data-a="${m}">${lv.map((l) => `<option ${p.autonomy[m] === l ? 'selected' : ''}>${l}</option>`).join('')}</select></label>`).join('')}</div><div class="muted" style="margin-top:8px">Per-action overrides: ${Object.entries(p.action_overrides).map(([k, v]) => k + '=' + v).join(', ')}</div></div>
  <div class="card"><h2>Guardrails</h2>${Object.entries(p.guardrails).map(([k, v]) => `<label style="flex-direction:row;align-items:center;gap:8px;margin:5px 0"><input type="checkbox" data-g="${k}" ${v ? 'checked' : ''}> ${label(k)}</label>`).join('')}</div></div>
  <div class="card"><details class="adv"><summary><b>Limits, budgets and economics</b> <span class="muted">(advanced)</span></summary><div class="form" style="margin-top:12px">${[['approval_threshold_inr', 'Auto-approve limit ₹'], ['contact_cap_per_7d', 'Messages per customer / 7d'], ['max_retries_per_payment', 'Max retries'], ['discount_ceiling_pct_of_ltv', 'Discount ceiling (share of LTV)'], ['holdout_pct', 'Holdout %'], ['fee_pct', 'Performance fee %'], ['dispute_fee_inr', 'Dispute fee ₹'], ['ratio_penalty_inr', 'Chargeback-ratio damage ₹'], ['evidence_cost_inr', 'Cost to fight ₹']].map(([k, l]) => `<label>${l}<input type="number" step="any" data-n="${k}" value="${p[k]}"></label>`).join('')}${Object.entries(p.budgets_inr_per_month).map(([k, v]) => `<label>Budget: ${label(k)} ₹/mo<input type="number" data-b="${k}" value="${v}"></label>`).join('')}</div></details>
  <div class="row" style="margin-top:12px"><button class="primary" id="save">Save policy</button><button id="reset">Reset demo data</button></div></div>`;
  $('#save', el).onclick = async () => { const patch = { autonomy: {}, guardrails: {}, budgets_inr_per_month: {} }; el.querySelectorAll('[data-a]').forEach((s) => (patch.autonomy[s.dataset.a] = s.value)); el.querySelectorAll('[data-g]').forEach((c) => (patch.guardrails[c.dataset.g] = c.checked)); el.querySelectorAll('[data-b]').forEach((i) => (patch.budgets_inr_per_month[i.dataset.b] = +i.value)); el.querySelectorAll('[data-n]').forEach((i) => (patch[i.dataset.n] = +i.value)); try { await api('/policy', { method: 'PUT', json: patch }); toast('Policy saved'); route(); } catch (e) { toast(e.message); } };
  $('#reset', el).onclick = async () => { if (confirm('Rebuild the demo workspace?')) { await api('/reset', { method: 'POST' }); toast('Demo workspace rebuilt'); route(); } };
};

/* ── shell: navigation shared with the original chargeback screens ─────────────────── */
const SUBS = {
  clawback: [['disputes', 'Disputes'], ['refunds', 'Refund requests'], ['rto', 'COD returns'], ['analyzer', 'Dispute Analyzer']],
  platform: [['guide', 'Getting started'], ['customers', 'Customers'], ['approvals', 'Approval Inbox'], ['ledger', 'Results'], ['audit', 'Leak Audit'], ['connections', 'Connections'], ['settings', 'Settings'], ['replay', 'Simulator']],
};
const TECH = [];
const PLATFORM_MENU = [['guide', 'Getting started', 'flask', 'Onboarding, step by step'], ['approvals', 'Approval Inbox', 'inbox', 'Decisions waiting for you'], ['customers', 'Customers', 'user', 'One profile per customer'], ['ledger', 'Results', 'ledger', 'What was recovered, audited'],
  ['audit', 'Leak Audit', 'search', 'Upload exports, see what you leak'], ['connections', 'Connections', 'plug', 'Gateways and data sources'], ['settings', 'Settings', 'settings', 'How much Impulse can do on its own']];
const TOP = [['home', 'Home'], ['dashboard', 'Dashboard'], ['payments', 'Payment Recovery'], ['clawback', 'Clawback Defense'], ['retention', 'Retention Rescue'], ['billing', 'Billing & Collections']];
const LEGACY = { analyzer: 'home' };
const PLATFORM_SUBS = new Set(SUBS.platform.map((x) => x[0]));
let pending = 0, current = { pillar: 'home', sub: '' }, subFor = '';

function parseHash() {
  const [name, ...rest] = (location.hash.slice(1) || 'home').split('/');
  if (PLATFORM_SUBS.has(name)) return { pillar: 'platform', sub: name, arg: rest.join('/') };
  if (name === 'platform') return { pillar: 'platform', sub: rest[0] || 'customers', arg: rest.slice(1).join('/') };
  if (name === 'cockpit') return { pillar: 'dashboard', sub: '', arg: '' };
  if (name === 'clawback') return { pillar: 'clawback', sub: ['disputes', 'refunds', 'rto', 'analyzer'].includes(rest[0]) ? rest[0] : 'disputes', arg: rest.slice(1).join('/') };
  return { pillar: TOP.some((p) => p[0] === name) ? name : 'home', sub: '', arg: rest.join('/') };
}
function buildNav() {
  const nav = $('#mainnav');
  nav.innerHTML = TOP.map(([k, l]) => `<button class="tab-btn" data-k="${k}">${l}</button>`).join('') +
    `<div class="nav-dd"><button class="tab-btn dd-btn" data-k="platform" aria-haspopup="true" aria-expanded="false">Platform ${UI.icon('arrow', 12, 'chev')}</button>
      <div class="dd-panel" role="menu">${PLATFORM_MENU.map(([k, l, ic, d], i) => `<a href="#${k}" role="menuitem" style="--i:${i}"><span class="dd-ico">${UI.icon(ic, 18)}</span><span><b>${l}</b><small>${d}</small></span></a>`).join('')}</div></div><span class="nav-ind"></span>`;
  nav.querySelectorAll('.tab-btn:not(.dd-btn)').forEach((b) => (b.onclick = () => { location.hash = '#' + b.dataset.k; closeDD(); }));
  const dd = nav.querySelector('.nav-dd'), btn = dd.querySelector('.dd-btn'); let t;
  const open = () => { clearTimeout(t); dd.classList.add('open'); btn.setAttribute('aria-expanded', 'true'); };
  window.closeDD = () => { dd.classList.remove('open'); btn.setAttribute('aria-expanded', 'false'); };
  btn.onclick = (e) => { e.stopPropagation(); dd.classList.contains('open') ? closeDD() : open(); };
  dd.addEventListener('mouseenter', open); dd.addEventListener('mouseleave', () => { t = setTimeout(closeDD, 220); });
  dd.querySelectorAll('.dd-panel a').forEach((a) => a.addEventListener('click', closeDD));
  document.addEventListener('click', closeDD); document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDD(); });
  addEventListener('resize', placeIndicator);
}
function placeIndicator() {
  const nav = $('#mainnav'), on = nav.querySelector('.tab-btn.active'), ind = nav.querySelector('.nav-ind'); if (!on || !ind) return;
  const nb = nav.getBoundingClientRect(), ob = on.getBoundingClientRect(); ind.style.width = ob.width + 'px'; ind.style.transform = `translateX(${ob.left - nb.left - nav.clientLeft}px)`; ind.style.opacity = 1;
}
async function refreshNav() { try { pending = (await api('/approvals')).pending; } catch (e) { /* offline */ } drawNav(); }
function drawNav() {
  const { pillar, sub } = current;
  $('#mainnav').querySelectorAll('.tab-btn').forEach((b) => {
    b.classList.toggle('active', b.dataset.k === pillar);
    b.querySelector('.badge')?.remove();
    if (b.dataset.k === 'platform' && pending) b.insertAdjacentHTML('beforeend', `<span class="badge">${pending}</span>`);
  });
  requestAnimationFrame(placeIndicator);
  const items = SUBS[pillar], box = $('#subnav'); const box2 = $('#subnav2'); if (box2) { const tech = pillar === 'clawback' && TECH.some((t) => t[0] === sub); box2.innerHTML = tech ? '<span>Model details</span>' + TECH.map(([k, l]) => `<a href="#clawback/${k}" class="${k === sub ? 'on' : ''}">${l}</a>`).join('') : ''; }
  if (!items) { box.innerHTML = ''; subFor = ''; return; }
  if (subFor !== pillar) { box.innerHTML = items.map(([k, l], i) => `<a href="#${pillar === 'platform' ? k : pillar + '/' + k}" data-k="${k}" style="--i:${i}">${l}</a>`).join(''); subFor = pillar; }
  box.querySelectorAll('a').forEach((a) => { a.classList.toggle('on', a.dataset.k === sub || (a.dataset.k === 'performance' && TECH.some((t) => t[0] === sub))); a.querySelector('.badge')?.remove(); if (a.dataset.k === 'approvals' && pending) a.insertAdjacentHTML('beforeend', `<span class="badge">${pending}</span>`); });
}
function showPanel(id) { document.querySelectorAll('.tab-panel').forEach((p) => p.classList.toggle('active', p.id === id)); }
const ICON_FOR = { guide: 'flask', customers: 'user', approvals: 'inbox', ledger: 'ledger', replay: 'flask', audit: 'search', connections: 'plug', settings: 'settings' };
async function route() {
  const r = parseHash(); current = r; drawNav(); document.body.dataset.route = r.pillar;
  document.title = 'Impulse: Revenue Recovery Platform';
  UI.progress('start');
  if (r.pillar === 'clawback' && LEGACY[r.sub]) {                       // the original chargeback screens live inside this pillar
    showPanel('tab-' + LEGACY[r.sub]);
    const t = LEGACY[r.sub];
    if (t === 'performance' && window.renderPerformanceCharts) setTimeout(window.renderPerformanceCharts, 50);
    else if (t === 'monitoring' && window.fetchMonitoringDrift) setTimeout(window.fetchMonitoringDrift, 50);
    else if (t === 'cases' && window.renderCaseExplorer) setTimeout(window.renderCaseExplorer, 50);
    window.scrollTo({ top: 0 }); UI.progress('done'); refreshNav(); return;
  }
  showPanel('tab-platform');
  const el = $('#platform-root'); if (r.pillar !== 'home') el.innerHTML = skeleton();
  const fn = r.pillar === 'home' ? screens.landing : r.pillar === 'dashboard' ? screens.dashboard : r.pillar === 'platform' ? screens[r.sub] : screens[r.pillar];
  try { await fn(el, r.pillar === 'clawback' ? r.sub : r.arg); } catch (e) { el.innerHTML = `<div class="card"><b>Could not load this screen.</b><div class="muted">${esc(e.message)}</div></div>`; }
  el.querySelectorAll('[data-go]').forEach((b) => (b.onclick = () => { location.hash = '#' + b.dataset.go; }));
  el.querySelectorAll('.show-more').forEach((b) => (b.onclick = () => { b.closest('.tbl').classList.add('expanded'); b.parentElement.remove(); }));
  const h1 = el.querySelector('h1'); if (r.pillar === 'platform' && h1 && !h1.querySelector('.h-ico') && ICON_FOR[r.sub]) h1.insertAdjacentHTML('afterbegin', `<span class="h-ico" style="--c:var(--brand-indigo)">${UI.icon(ICON_FOR[r.sub], 22)}</span>`);
  el.classList.remove('pf-enter'); void el.offsetWidth; el.classList.add('pf-enter');
  UI.reveal(el); UI.spotlight(el);
  window.scrollTo({ top: 0 }); UI.progress('done'); refreshNav();
}
// legacy chargeback code calls switchTab(...): route it into the Clawback pillar
window.switchTab = () => { location.hash = '#clawback/analyzer'; };   // old chargeback pages now all lead to the analyzer
const rib = document.querySelector('.stripe-pulsing-ribbon'); if (rib) window.__ribbonHTML = rib.outerHTML;
window.IMP = { api, esc, inr, inrC, pct, pctC, label, pill, table, kpi, hbars, stackBar, lineChart, showCase, toast, screens, tt, go: (h) => { location.hash = '#' + h; }, LEAKS };
buildNav();
addEventListener('hashchange', route);
document.addEventListener('DOMContentLoaded', route);
if (document.readyState !== 'loading') setTimeout(route, 0);

})();
