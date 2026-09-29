/* Inline SVG illustrations (animated with CSS/SMIL). Each explains one idea in a single glance. */
(function () {
  'use strict';
  const T = (x, y, t, c = '#475569', w = 600, s = 12) => `<text x="${x}" y="${y}" text-anchor="middle" font-family="Inter,sans-serif" font-size="${s}" font-weight="${w}" fill="${c}">${t}</text>`;

  const payments = `<svg viewBox="0 0 400 280" class="art" role="img" aria-label="A failed payment is retried at the best time and succeeds">
    <defs><linearGradient id="ga" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#94A3B8"/><stop offset="1" stop-color="#64748B"/></linearGradient><linearGradient id="gb" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#3B82F6"/><stop offset="1" stop-color="#6366F1"/></linearGradient></defs>
    <g class="art-float"><rect x="26" y="98" width="118" height="76" rx="13" fill="url(#ga)"/><rect x="26" y="118" width="118" height="13" fill="rgba(255,255,255,.35)"/><rect x="40" y="148" width="38" height="8" rx="4" fill="rgba(255,255,255,.75)"/></g>
    <g class="art-pop" style="transform-origin:136px 98px"><circle cx="136" cy="98" r="15" fill="#EF4444"/><path d="M129 91l14 14M143 91l-14 14" stroke="#fff" stroke-width="3" stroke-linecap="round"/></g>
    <path d="M150 122 C 190 28, 254 28, 266 120" fill="none" stroke="#C7D2FE" stroke-width="3" stroke-dasharray="6 8" class="art-dash"/>
    <circle r="6.5" fill="#6366F1"><animateMotion dur="3.4s" repeatCount="indefinite" path="M150 122 C 190 28, 254 28, 266 120"/></circle>
    <g transform="translate(208 44)"><circle r="21" fill="#fff" stroke="#A5B4FC" stroke-width="3"/><path d="M0 -11V0l9 5" stroke="#6366F1" stroke-width="3" fill="none" stroke-linecap="round"><animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="6s" repeatCount="indefinite"/></path></g>
    <g class="art-float2"><rect x="256" y="98" width="118" height="76" rx="13" fill="url(#gb)"/><rect x="256" y="118" width="118" height="13" fill="rgba(255,255,255,.3)"/><rect x="270" y="148" width="38" height="8" rx="4" fill="rgba(255,255,255,.8)"/></g>
    <g class="art-pop2" style="transform-origin:366px 98px"><circle cx="366" cy="98" r="15" fill="#10B981"/><path d="M359 98l5 5 9-10" stroke="#fff" stroke-width="3.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/></g>
    ${T(85, 206, 'Payment fails')}${T(208, 84, 'Best time', '#4F46E5')}${T(315, 206, 'Money recovered', '#047857')}
    <rect x="70" y="228" width="260" height="30" rx="15" fill="#EEF2FF"/>${T(200, 248, 'Retry when the customer can pay', '#4338CA', 700, 12.5)}</svg>`;

  const clawback = `<svg viewBox="0 0 400 280" class="art" role="img" aria-label="Weighing whether to fight, refund or accept a dispute">
    <path d="M200 30 L296 62 V132 C296 190 252 226 200 246 C148 226 104 190 104 132 V62 Z" fill="#FFF1E8" stroke="#FDBA74" stroke-width="3" class="art-breathe"/>
    <rect x="196" y="98" width="8" height="112" rx="4" fill="#94A3B8"/><rect x="164" y="208" width="72" height="9" rx="4.5" fill="#94A3B8"/>
    <g class="art-beam" style="transform-origin:200px 100px"><rect x="98" y="96" width="204" height="8" rx="4" fill="#475569"/>
      <path d="M116 104 L96 158 M116 104 L136 158" stroke="#94A3B8" stroke-width="2"/><path d="M96 158h40a20 12 0 0 1-40 0z" fill="#FB923C"/>
      <path d="M284 104 L264 158 M284 104 L304 158" stroke="#94A3B8" stroke-width="2"/><path d="M264 158h40a20 12 0 0 1-40 0z" fill="#6366F1"/>
      <g class="art-beam-counter" style="transform-origin:116px 190px"><text x="116" y="190" text-anchor="middle" font-family="Inter" font-size="11" font-weight="800" fill="#9A3412">Fight</text></g>
      <g class="art-beam-counter" style="transform-origin:284px 190px"><text x="284" y="190" text-anchor="middle" font-family="Inter" font-size="11" font-weight="800" fill="#3730A3">Refund</text></g></g>
    <circle cx="200" cy="100" r="9" fill="#F97316"/>
    <rect x="70" y="256" width="260" height="0" fill="none"/></svg>`;

  const retention = `<svg viewBox="0 0 400 280" class="art" role="img" aria-label="A customer who is fading away is kept with the gentlest fix">
    <g class="art-float"><circle cx="82" cy="104" r="36" fill="#E0E7FF"/><circle cx="82" cy="94" r="12" fill="#6366F1"/><path d="M58 128c3-14 14-20 24-20s21 6 24 20" fill="#6366F1"/></g>
    <g class="art-fade"><circle cx="200" cy="104" r="36" fill="#E0E7FF"/><circle cx="200" cy="94" r="12" fill="#818CF8"/><path d="M176 128c3-14 14-20 24-20s21 6 24 20" fill="#818CF8"/></g>
    <circle cx="200" cy="104" r="46" fill="none" stroke="#F59E0B" stroke-width="3" stroke-dasharray="8 8" class="art-spin"/>
    <g class="art-float2"><circle cx="318" cy="104" r="36" fill="#D1FAE5"/><circle cx="318" cy="94" r="12" fill="#10B981"/><path d="M294 128c3-14 14-20 24-20s21 6 24 20" fill="#10B981"/></g>
    <g class="art-lift"><rect x="122" y="176" width="156" height="34" rx="17" fill="#fff" stroke="#A5B4FC" stroke-width="2"/><path d="M147 200V187M147 187l-5 5M147 187l5 5" stroke="#6366F1" stroke-width="2.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>${T(224, 197.5, 'Offer a pause', '#4338CA', 700, 12)}</g>
    ${T(82, 166, 'Happy')}${T(200, 166, 'Fading', '#B45309')}${T(318, 166, 'Kept', '#047857')}
    <rect x="70" y="234" width="260" height="28" rx="14" fill="#ECFDF5"/>${T(200, 253, 'Gentlest fix first, never a hard sell', '#047857', 700, 12.5)}</svg>`;

  const billing = `<svg viewBox="0 0 400 280" class="art" role="img" aria-label="A missing line on an invoice is found and billed">
    <g class="art-float"><rect x="112" y="24" width="176" height="232" rx="14" fill="#fff" stroke="#CBD5E1" stroke-width="2"/><rect x="128" y="42" width="70" height="10" rx="5" fill="#0F172A" opacity=".85"/><rect x="128" y="60" width="44" height="7" rx="3.5" fill="#CBD5E1"/>
      ${[0, 1, 3].map((i) => `<rect x="128" y="${88 + i * 34}" width="82" height="9" rx="4.5" fill="#CBD5E1"/><rect x="230" y="${88 + i * 34}" width="42" height="9" rx="4.5" fill="#94A3B8"/>`).join('')}
      <rect x="122" y="152" width="156" height="30" rx="8" fill="#FEF3C7" stroke="#F59E0B" stroke-dasharray="5 4"><animate attributeName="fill" values="#FEF3C7;#FEF3C7;#D1FAE5;#D1FAE5;#FEF3C7" keyTimes="0;.35;.5;.9;1" dur="5s" repeatCount="indefinite"/><animate attributeName="stroke" values="#F59E0B;#F59E0B;#10B981;#10B981;#F59E0B" keyTimes="0;.35;.5;.9;1" dur="5s" repeatCount="indefinite"/></rect>
      <rect x="230" y="163" width="42" height="9" rx="4.5" fill="#F59E0B" opacity=".55"/>
      <rect x="128" y="200" width="144" height="1.5" fill="#E2E8F0"/><rect x="128" y="214" width="60" height="10" rx="5" fill="#0F172A" opacity=".85"/><rect x="216" y="214" width="56" height="10" rx="5" fill="#6366F1"/></g>
    <g class="art-coin"><circle cx="251" cy="167" r="13" fill="#FBBF24" stroke="#F59E0B" stroke-width="2.5"/>${T(251, 172, '₹', '#92400E', 800, 14)}</g>
    <g class="art-pop" style="transform-origin:110px 170px"><circle cx="102" cy="168" r="14" fill="#F59E0B"/>${T(102, 174, '?', '#fff', 800, 17)}</g>
    ${T(56, 210, 'Never', '#92400E', 700, 12)}${T(56, 225, 'billed', '#92400E', 700, 12)}${T(344, 172, 'Found', '#047857', 800, 13)}${T(344, 188, 'and billed', '#047857', 700, 12)}</svg>`;

  const leaky = `<svg viewBox="0 0 960 300" class="art art-wide" role="img" aria-label="Revenue flows into a business and leaks out in four places">
    <defs><linearGradient id="gbk" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#EEF2FF"/><stop offset="1" stop-color="#C7D2FE"/></linearGradient></defs>
    ${[0, 1, 2, 3, 4].map((i) => `<g><circle cx="${390 + i * 45}" cy="-10" r="11" fill="#FBBF24" stroke="#F59E0B" stroke-width="2.5"><animate attributeName="cy" values="-14;96" dur="${2.2 + i * 0.25}s" begin="${i * 0.45}s" repeatCount="indefinite"/><animate attributeName="opacity" values="0;1;1;0" keyTimes="0;.15;.85;1" dur="${2.2 + i * 0.25}s" begin="${i * 0.45}s" repeatCount="indefinite"/></circle></g>`).join('')}
    ${T(480, 24, 'Money coming in', '#92400E', 700, 12)}
    <path d="M330 104 H630 L602 230 Q600 246 584 246 H376 Q360 246 358 230 Z" fill="url(#gbk)" stroke="#A5B4FC" stroke-width="3"/>${T(480, 186, 'Your revenue', '#3730A3', 800, 17)}
    <path d="M338 150 C 250 150, 214 170, 150 218" fill="none" stroke="#3B82F6" stroke-width="4" stroke-dasharray="4 10" class="art-flow"/><path d="M400 246 C 400 262, 340 268, 300 282" fill="none" stroke="#F97316" stroke-width="4" stroke-dasharray="4 10" class="art-flow"/>
    <path d="M622 150 C 710 150, 746 170, 810 218" fill="none" stroke="#10B981" stroke-width="4" stroke-dasharray="4 10" class="art-flow"/><path d="M560 246 C 560 262, 620 268, 660 282" fill="none" stroke="#F59E0B" stroke-width="4" stroke-dasharray="4 10" class="art-flow"/>
    <g class="art-drip"><circle cx="150" cy="226" r="9" fill="#3B82F6"/></g><g class="art-drip d2"><circle cx="810" cy="226" r="9" fill="#10B981"/></g>
    <rect x="30" y="228" width="200" height="52" rx="14" fill="#fff" stroke="#BFDBFE" stroke-width="2"/>${T(130, 250, 'Payments fail', '#1D4ED8', 800, 14)}${T(130, 268, 'card, bank or balance', '#64748B', 500, 11.5)}
    <rect x="730" y="228" width="200" height="52" rx="14" fill="#fff" stroke="#A7F3D0" stroke-width="2"/>${T(830, 250, 'Customers quietly stop', '#047857', 800, 14)}${T(830, 268, 'cards fade, interest fades', '#64748B', 500, 11.5)}
    <rect x="236" y="262" width="150" height="36" rx="12" fill="#fff" stroke="#FED7AA" stroke-width="2"/>${T(311, 285, 'Money taken back', '#C2410C', 800, 13)}
    <rect x="574" y="262" width="150" height="36" rx="12" fill="#fff" stroke="#FDE68A" stroke-width="2"/>${T(649, 285, 'Never billed', '#B45309', 800, 13)}</svg>`;

  const compare = `<svg viewBox="0 0 440 300" class="art" role="img" aria-label="Two groups compared: your current approach and Impulse">
    <rect x="16" y="20" width="192" height="240" rx="18" fill="#fff" stroke="#E2E8F0" stroke-width="2"/><rect x="232" y="20" width="192" height="240" rx="18" fill="#fff" stroke="#C7D2FE" stroke-width="2"/>
    ${T(112, 52, 'Your current approach', '#475569', 800, 13)}${T(328, 52, 'With Impulse', '#4338CA', 800, 13)}
    ${T(112, 70, 'a small control group', '#94A3B8', 500, 11)}${T(328, 70, 'the rest of the cases', '#94A3B8', 500, 11)}
    <rect x="60" y="120" width="104" height="128" rx="8" fill="#E2E8F0"/><rect x="60" y="120" width="104" height="128" rx="8" fill="#CBD5E1" class="art-grow" style="transform-origin:112px 248px;--h:1"/>
    <rect x="276" y="120" width="104" height="128" rx="8" fill="#C7D2FE" class="art-grow" style="transform-origin:328px 248px;--h:1.0"/><rect x="276" y="86" width="104" height="34" rx="8" fill="#10B981" class="art-grow2" style="transform-origin:328px 120px"/>
    <path d="M388 103h18" stroke="#10B981" stroke-width="2" stroke-dasharray="3 3"/>${T(112, 240, 'recovered anyway', '#475569', 700, 11.5)}${T(328, 240, 'recovered anyway', '#3730A3', 700, 11.5)}
    <rect x="268" y="274" width="120" height="22" rx="11" fill="#D1FAE5"/>${T(328, 289, 'the extra we are paid on', '#047857', 800, 10.5)}</svg>`;

  window.ART = { payments, clawback, retention, billing, leaky, compare };
})();
