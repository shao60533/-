import{c,j as e,l as x,m as d,g as n}from"./card-C8roQ90A.js";/**
 * @license lucide-react v0.460.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const h=c("ArrowDownRight",[["path",{d:"m7 7 10 10",key:"1fmybs"}],["path",{d:"M17 7v10H7",key:"6fjiku"}]]);/**
 * @license lucide-react v0.460.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const p=c("ArrowUpRight",[["path",{d:"M7 7h10v10",key:"1tivn9"}],["path",{d:"M7 17 17 7",key:"1vkiza"}]]);function f({label:o,value:i,delta:t,hint:a,icon:r,className:l,...m}){const s=(t??0)>=0;return e.jsx(x,{className:n("h-full",l),...m,children:e.jsxs(d,{className:"pt-5",children:[e.jsxs("div",{className:"flex items-center justify-between",children:[e.jsx("span",{className:"text-[11px] font-medium uppercase tracking-wider text-[var(--color-text-muted)]",children:o}),r&&e.jsx("span",{className:"text-[var(--color-text-muted)]",children:r})]}),e.jsx("div",{className:"mt-3 font-mono font-semibold tracking-tight truncate overflow-hidden",style:{fontSize:"var(--fs-stat)",fontVariantNumeric:"tabular-nums"},children:i}),e.jsxs("div",{className:"mt-2 flex items-center gap-1.5 text-xs text-[var(--color-text-secondary)]",children:[t!==void 0&&e.jsxs("span",{className:n("inline-flex items-center gap-0.5 font-medium font-mono tabular-nums",s?"text-[var(--color-accent-green)]":"text-[var(--color-accent-red)]"),children:[s?e.jsx(p,{className:"h-3 w-3"}):e.jsx(h,{className:"h-3 w-3"}),(s?"+":"")+t.toFixed(2)+"%"]}),a&&e.jsx("span",{className:"truncate",children:a})]})]})})}export{f as S};
