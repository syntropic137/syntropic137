#!/usr/bin/env python3
"""Add trend charts to the Eval and Workflow boards (desktop + phone) and
sparklines to the Workflows list cards. Idempotent: always starts from
project.bak-trends copies of the boards."""
import json, re, os, math

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, 'project.bak-trends')
DST = os.path.join(ROOT, 'project')
MONO = "'JetBrains Mono', ui-monospace, monospace"

# ---------------------------------------------------------------- sample data
# Eval: shared-esp-stream, 4 verifiers, 30 days from Sep 8 2026 (day 0) to Oct 7 (day 29).
# Verifier series colours: validated categorical set on #0D101A (blue, aqua, violet, magenta).
EVAL_SERIES = [
    {'key': 'opus', 'short': 'opus', 'name': 'claude-opus-5-5', 'color': '#4D80FF'},
    {'key': 'sonnet', 'short': 'sonnet', 'name': 'claude-sonnet-5-5', 'color': '#199E70'},
    {'key': 'sol', 'short': 'sol', 'name': 'gpt-5.6-sol', 'color': '#9085E9'},
    {'key': 'terra', 'short': 'terra', 'name': 'gpt-5.6-terra', 'color': '#D55181'},
]
P, F, E, U = 'PASS', 'FAIL', 'ERROR', 'UNSCORED'
# [day, series, verdict, cost, seconds, score(0-100 or None), judge]
J = 'claude-opus-5-5'
EVAL_RUNS = [
    [0, 0, P, 1.21, 452, 82, J], [4, 0, P, 1.18, 431, 85, J], [8, 0, F, 1.25, 470, 61, J], [12, 0, P, 1.16, 418, 84, J],
    [17, 0, P, 1.09, 392, 88, J], [21, 0, P, 1.06, 381, 90, J], [25, 0, P, 1.02, 366, 91, J], [29, 0, P, 1.04, 372, 92, J],
    [1, 1, F, 0.49, 241, 48, J], [5, 1, F, 0.51, 236, 55, J], [9, 1, P, 0.50, 247, 72, J], [13, 1, F, 0.53, 252, 63, J],
    [16, 1, F, 0.52, 240, 66, J], [19, 1, P, 0.50, 233, 78, J], [22, 1, P, 0.52, 238, 84, J], [26, 1, P, 0.51, 229, 87, J], [28, 1, P, 0.52, 245, 89, J],
    [2, 2, P, 0.55, 262, 80, J], [7, 2, P, 0.58, 255, 78, J], [11, 2, F, 0.61, 249, 64, J], [15, 2, P, 0.63, 240, 76, J],
    [20, 2, F, 0.66, 236, 62, J], [24, 2, P, 0.69, 231, 73, J], [27, 2, F, 0.71, 228, 58, J],
    [23, 3, P, 0.62, 214, 79, J], [25, 3, F, 0.60, 201, 66, J], [27, 3, P, 0.59, 196, 81, J], [29, 3, U, 0.61, 190, None, None],
]
# blended $ per million tokens, used to derive tokens per run for the sample
EVAL_RATE = [9.0, 3.0, 2.5, 2.0]
PASS_AT = 70
EVAL_NOTES = [{'d': 18, 'label': 'verify prompt v2'}]

# Workflow: research-workflow-v2, 12 runs over 5 weeks (Sep 1 = day 0 ... Oct 5 = day 34).
# [day, status, cost, total seconds, [phase seconds x3]]
WF_RUNS = [
    [0, 'completed', 0.162, 418, [96, 188, 134]], [3, 'completed', 0.151, 402, [92, 181, 129]],
    [6, 'failed', 0.071, 196, [88, 108, 0]], [9, 'completed', 0.148, 389, [90, 172, 127]],
    [12, 'completed', 0.139, 371, [84, 166, 121]], [15, 'cancelled', 0.044, 120, [80, 40, 0]],
    [18, 'completed', 0.124, 333, [71, 150, 112]], [21, 'completed', 0.118, 318, [66, 146, 106]],
    [25, 'completed', 0.113, 301, [62, 139, 100]], [28, 'completed', 0.109, 289, [58, 134, 97]],
    [31, 'completed', 0.106, 276, [55, 128, 93]], [34, 'completed', 0.104, 266, [52, 124, 90]],
]
WF_NOTES = [{'d': 16, 'label': 'v2 published'}]
WF_PHASES = ['Discovery Phase', 'Deep Dive Analysis', 'Synthesis & Documentation']

# ---------------------------------------------------------------- shared JS
ENGINE = r'''
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const dayLabel = (d) => { const t = new Date(Date.UTC(T.y, T.m, T.d + d)); return MON[t.getUTCMonth()] + ' ' + t.getUTCDate(); };
const xPct = (d) => 2 + (d / T.span) * 96;
const mins = (s) => { s = Math.round(s); return s < 60 ? s + 's' : Math.floor(s / 60) + 'm ' + String(s % 60).padStart(2, '0') + 's'; };
const tickMin = (s) => (s === 0 ? '0' : s % 60 ? mins(s) : s / 60 + 'm');
const niceMax = (v, steps) => { for (const s of steps) if (v <= s) return s; return steps[steps.length - 1]; };
const pathOf = (pts) => pts.map((p, i) => (i ? 'L' : 'M') + (p[0] * 10).toFixed(1) + ' ' + (T.h - (p[1] * T.h) / 100).toFixed(1)).join(' ');
'''

# ---------------------------------------------------------------- eval logic
def eval_js(phone):
    return r'''
const T = { y: 2026, m: 8, d: 8, span: 29, h: 220 };
''' + ENGINE + r'''
const SERIES = ''' + json.dumps(EVAL_SERIES) + r''';
const RAW = ''' + json.dumps(EVAL_RUNS) + r''';
const RATE = ''' + json.dumps(EVAL_RATE) + r''';
const PASS_AT = ''' + str(PASS_AT) + r''';
const NOTES = ''' + json.dumps(EVAL_NOTES) + r''';
const VLOOK = {
PASS: { word: 'Pass', c: 'var(--ac)', fg: 'color-mix(in oklab, var(--ac) 40%, white)', bg: 'color-mix(in oklab, var(--ac) 18%, transparent)', h: '14px' },
FAIL: { word: 'Fail', c: '#FF6F61', fg: '#FF8A7D', bg: '#2A1513', h: '7px' },
ERROR: { word: 'Error', c: '#E5B450', fg: '#EBD9A8', bg: '#1F1A0E', h: '7px' },
UNSCORED: { word: 'Unscored', c: '#4A567A', fg: '#9AA8C7', bg: '#171C2B', h: '3px' }
};
const st = this.state || {};
const metric = st.metric || 'cost';
const runs = RAW.map((r, i) => ({ i, d: r[0], s: r[1], v: r[2], cost: r[3], secs: r[4], score: r[5], judge: r[6], tokens: Math.round((r[3] / RATE[r[1]]) * 1e6) }));
const ktok = (n) => (n >= 1e6 ? (n / 1e6).toFixed(2) + 'M' : Math.round(n / 1000) + 'k');
const EFF = {
cost: { label: 'Cost', unit: 'per run', max: niceMax(Math.max(...runs.map((r) => r.cost)), [0.4, 0.8, 1.2, 1.6, 2, 3.2]), val: (r) => r.cost, fmt: (v) => '$' + v.toFixed(2), tick: (v) => '$' + v.toFixed(2), d: (n) => '$' + Math.abs(n).toFixed(2), tol: 0.02 },
speed: { label: 'Speed', unit: 'time to verdict', max: niceMax(Math.max(...runs.map((r) => r.secs)) / 60, [4, 6, 8, 10, 12, 16]) * 60, val: (r) => r.secs, fmt: mins, tick: (v) => tickMin(Math.round(v)), d: (n) => mins(Math.abs(n)), tol: 10 },
tokens: { label: 'Tokens', unit: 'per run, all phases', max: niceMax(Math.max(...runs.map((r) => r.tokens)), [100e3, 200e3, 300e3, 400e3, 600e3, 800e3, 1e6]), val: (r) => r.tokens, fmt: ktok, tick: (v) => (v === 0 ? '0' : ktok(v)), d: (n) => ktok(Math.abs(n)), tol: 5000 }
};
const E2 = EFF[metric];
const scored = runs.filter((r) => r.score !== null);
const qPct = (v) => v;
const ePct = (v) => (v / E2.max) * 100;
const lineFor = (si, list, val, pct) => pathOf(list.filter((r) => r.s === si).sort((a, b) => a.d - b.d).map((r) => [xPct(r.d), pct(val(r))]));
const qLines = SERIES.map((s, si) => lineFor(si, scored, (r) => r.score, qPct));
const eLines = SERIES.map((s, si) => lineFor(si, runs, E2.val, ePct));
const selIdx = typeof st.sel === 'number' ? st.sel : runs.find((r) => r.s === 1 && r.d === 28).i;
const sel = runs[selIdx];
const pick = (i) => () => this.setState({ sel: i });
const dotOf = (r, top, label) => {
const s = SERIES[r.s];
const on = r.i === selIdx;
return { l: xPct(r.d) + '%', t: top + '%', c: s.color, size: on ? '14px' : '9px', ring: on ? '0 0 0 3px #0D101A, 0 0 0 5px ' + s.color : '0 0 0 2px #0D101A', z: on ? 3 : 2, on: on ? 'true' : 'false', label, pick: pick(r.i) };
};
const qDots = scored.map((r) => dotOf(r, 100 - r.score, dayLabel(r.d) + ', ' + SERIES[r.s].name + ': score ' + r.score + ' of 100, judged by ' + r.judge));
const eDots = runs.map((r) => dotOf(r, 100 - ePct(E2.val(r)), dayLabel(r.d) + ', ' + SERIES[r.s].name + ': ' + E2.fmt(E2.val(r)) + ' ' + E2.unit));
const qTicks = [0, 25, 50, 75, 100].map((v) => ({ t: 100 - v + '%', label: String(v) }));
const eTicks = [0, 1, 2, 3, 4].map((k) => ({ t: 100 - k * 25 + '%', label: E2.tick((E2.max * k) / 4) }));
const xTicks = [0, 7, 14, 21, 28].map((d) => ({ l: xPct(d) + '%', label: dayLabel(d) }));
const notes = NOTES.map((n) => ({ l: xPct(n.d) + '%', label: n.label + ' · ' + dayLabel(n.d) }));
const tabs = Object.keys(EFF).map((k) => ({
label: EFF[k].label,
on: k === metric ? 'true' : 'false',
bg: k === metric ? '#1A2032' : 'transparent',
fg: k === metric ? '#E8EEFB' : '#9AA8C7',
pick: () => this.setState({ metric: k })
}));
const avg = (xs, f) => xs.reduce((a, r) => a + f(r), 0) / xs.length;
const UP = 'M3 10.5l3.5-3.5 2.5 2.5L13 5.5M9.5 5.5H13V9', DOWN = 'M3 5.5L6.5 9 9 6.5l4 4M9.5 10.5H13V7', FLAT = 'M3 8h10';
const legend = SERIES.map((s, si) => {
const mineS = scored.filter((r) => r.s === si).sort((a, b) => a.d - b.d);
const mineE = runs.filter((r) => r.s === si).sort((a, b) => a.d - b.d);
const lastDay = mineE[mineE.length - 1].d;
const nowS = mineS.slice(-3), thenS = mineS.filter((r) => r.d <= lastDay - 14).slice(-3);
const nowE = mineE.slice(-3), thenE = mineE.filter((r) => r.d <= lastDay - 14).slice(-3);
const fresh = !thenS.length;
const sNow = Math.round(avg(nowS, (r) => r.score)), sThen = fresh ? sNow : Math.round(avg(thenS, (r) => r.score));
const eNow = avg(nowE, E2.val), eThen = fresh ? eNow : avg(thenE, E2.val);
const ds = sNow - sThen, de = eNow - eThen;
const qUp = ds >= 3, qDown = ds <= -3, eDown = de < -E2.tol, eUp = de > E2.tol;
const verdict = fresh ? 'New verifier, not enough history' : qDown ? 'Quality is slipping' : qUp && eDown ? 'Better and cheaper' : qUp && eUp ? 'Better, but costs more' : qUp ? 'Getting better' : eDown ? 'Same quality, cheaper' : eUp ? 'Same quality, costs more' : 'Holding steady';
const good = !fresh && !qDown && (qUp || eDown) && !(eUp && !qUp);
const bad = !fresh && (qDown || (eUp && !qUp));
return {
c: s.color,
name: s.name,
score: sNow,
sDelta: fresh ? 'first runs' : (ds > 0 ? '+' : ds < 0 ? '−' : '±') + Math.abs(ds) + ' since ' + dayLabel(thenS[thenS.length - 1].d),
sIcon: qUp ? UP : qDown ? DOWN : FLAT,
sFg: qUp ? '#7FE3B8' : qDown ? '#FF8A7D' : '#9AA8C7',
eLabel: E2.label,
eValue: E2.fmt(eNow),
eDelta: fresh ? 'first runs' : Math.abs(de) <= E2.tol ? 'flat' : (de > 0 ? '+' : '−') + E2.d(de),
eIcon: eDown ? DOWN : eUp ? UP : FLAT,
eFg: eDown ? '#7FE3B8' : eUp ? '#FF8A7D' : '#9AA8C7',
verdict,
vfg: good ? '#7FE3B8' : bad ? '#FF8A7D' : '#9AA8C7',
vbg: good ? '#0F241C' : bad ? '#2A1513' : '#171C2B',
label: s.name + ': score ' + sNow + ' of 100, ' + E2.label.toLowerCase() + ' ' + E2.fmt(eNow) + ', ' + verdict.toLowerCase()
};
});
const lanes = SERIES.map((s, si) => ({
c: s.color,
name: s.name,
ticks: runs.filter((r) => r.s === si).map((r) => {
const k = VLOOK[r.v];
const on = r.i === selIdx;
return { l: xPct(r.d) + '%', c: k.c, h: k.h, ring: on ? '0 0 0 2px #0D101A, 0 0 0 3px #E8EEFB' : 'none', label: dayLabel(r.d) + ', ' + s.name + ': ' + k.word, pick: pick(r.i) };
})
}));
const sk = VLOOK[sel.v];
const readout = {
date: dayLabel(sel.d) + ', 2026',
c: SERIES[sel.s].color,
model: SERIES[sel.s].name,
verdict: sk.word,
vfg: sk.fg,
vbg: sk.bg,
score: sel.score === null ? '—' : String(sel.score),
scoreOf: sel.score === null ? 'not scored yet' : 'of 100 · pass at ' + PASS_AT,
judge: sel.judge || 'waiting for the scorer',
cost: '$' + sel.cost.toFixed(2),
speed: mins(sel.secs),
tokens: ktok(sel.tokens),
hair: xPct(sel.d) + '%'
};
const judges = Array.from(new Set(scored.map((r) => r.judge)));
const trend = {
sub: runs.length + ' runs in 30 days across 4 verifiers. Scores come from the judge model; a run passes at ' + PASS_AT + '.',
judge: judges.join(', '),
eTitle: E2.label,
eUnit: E2.unit,
pass: 100 - PASS_AT + '%',
q1: qLines[0], q2: qLines[1], q3: qLines[2], q4: qLines[3],
e1: eLines[0], e2: eLines[1], e3: eLines[2], e4: eLines[3],
c1: SERIES[0].color, c2: SERIES[1].color, c3: SERIES[2].color, c4: SERIES[3].color
};
const endsOf = (list, val, pct) => {
const raw = SERIES.map((s, si) => { const mine = list.filter((r) => r.s === si).sort((a, b) => a.d - b.d); const last = mine[mine.length - 1]; return { si, t: 100 - pct(val(last)), label: s.short, c: s.color }; });
raw.sort((a, b) => a.t - b.t);
for (let k = 1; k < raw.length; k++) if (raw[k].t - raw[k - 1].t < 11) raw[k].t = raw[k - 1].t + 11;
const over = raw[raw.length - 1].t - 100;
if (over > 0) raw.forEach((e) => (e.t -= over));
return raw.map((e) => ({ t: e.t + '%', label: e.label, c: e.c }));
};
const qEnds = endsOf(scored, (r) => r.score, qPct);
const eEnds = endsOf(runs, E2.val, ePct);
const agentCmd = 'syn eval trend shared-esp-stream --json';
const agentPrompt = ['Read the trend for eval shared-esp-stream and tell me which verifier gives the best quality per dollar, and whether any verifier is regressing.', '', 'Get the data with the Syn137 CLI:', '  ' + agentCmd, '', 'It returns one row per run: date, verifier model, judge model, score (0-100), verdict, cost, duration, tokens.'].join('\n');
const copyAgent = () => { try { if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(agentPrompt).catch(() => {}); } catch (e) {} this.setState({ agentCopied: true }); };
const agentLabel = st.agentCopied ? 'Copied agent prompt' : 'Copy for an agent';
const order = runs.slice().sort((a, b) => a.d - b.d || a.s - b.s);
const at = order.findIndex((r) => r.i === selIdx);
const prev = () => this.setState({ sel: order[(at + order.length - 1) % order.length].i });
const next = () => this.setState({ sel: order[(at + 1) % order.length].i });
'''

# ---------------------------------------------------------------- workflow logic
def wf_js():
    return r'''
const T = { y: 2026, m: 8, d: 1, span: 34, h: 220 };
''' + ENGINE + r'''
const RAW = ''' + json.dumps(WF_RUNS) + r''';
const NOTES = ''' + json.dumps(WF_NOTES) + r''';
const PHASES = ''' + json.dumps(WF_PHASES) + r''';
const SLOOK = {
completed: { word: 'Completed', c: 'var(--ac)', fg: 'color-mix(in oklab, var(--ac) 40%, white)', bg: 'color-mix(in oklab, var(--ac) 18%, transparent)' },
failed: { word: 'Failed', c: '#FF6F61', fg: '#FF8A7D', bg: '#2A1513' },
cancelled: { word: 'Cancelled', c: '#6F7FA3', fg: '#9AA8C7', bg: '#171C2B' }
};
const st = this.state || {};
const metric = st.pmetric || 'cost';
const runs = RAW.map((r, i) => ({ i, d: r[0], status: r[1], cost: r[2], secs: r[3], ph: r[4], tokens: Math.round(r[2] / 0.5e-6) }));
const ktok = (n) => (n >= 1e6 ? (n / 1e6).toFixed(2) + 'M' : Math.round(n / 1000) + 'k');
const okSoFar = [];
runs.forEach((r) => { okSoFar.push(r.status === 'completed' ? 1 : 0); const w = okSoFar.slice(-5); r.ok = Math.round((100 * w.reduce((a, b) => a + b, 0)) / w.length); });
const done = runs.filter((r) => r.status === 'completed');
const METRICS = {
success: { label: 'Success', unit: 'completed, last 5 runs', max: 100, val: (r) => r.ok, fmt: (v) => v + '%', set: runs, better: 'up' },
speed: { label: 'Speed', unit: 'duration of completed runs', max: niceMax(Math.max(...done.map((r) => r.secs)) / 60, [4, 6, 8, 10, 12]) * 60, val: (r) => r.secs, fmt: mins, set: done, better: 'down' },
cost: { label: 'Cost', unit: 'per completed run', max: niceMax(Math.max(...done.map((r) => r.cost)), [0.1, 0.2, 0.3, 0.5, 1]), val: (r) => r.cost, fmt: (v) => '$' + v.toFixed(3), set: done, better: 'down' },
tokens: { label: 'Tokens', unit: 'per completed run', max: niceMax(Math.max(...done.map((r) => r.tokens)), [100e3, 200e3, 300e3, 400e3, 600e3]), val: (r) => r.tokens, fmt: ktok, set: done, better: 'down' }
};
const M = METRICS[metric];
const yOf = (v) => (v / M.max) * 100;
const line = pathOf(M.set.map((r) => [xPct(r.d), yOf(M.val(r))]));
const selIdx = typeof st.psel === 'number' ? st.psel : runs.length - 1;
const sel = runs[selIdx];
const tabs = Object.keys(METRICS).map((k) => ({
label: METRICS[k].label,
on: k === metric ? 'true' : 'false',
bg: k === metric ? '#1A2032' : 'transparent',
fg: k === metric ? '#E8EEFB' : '#9AA8C7',
pick: () => this.setState({ pmetric: k })
}));
const dots = runs.map((r) => {
const k = SLOOK[r.status];
const on = r.i === selIdx;
const inSet = M.set.indexOf(r) >= 0;
return {
l: xPct(r.d) + '%',
t: inSet ? 100 - yOf(M.val(r)) + '%' : '100%',
c: k.c,
size: on ? '14px' : inSet ? '10px' : '8px',
ring: on ? '0 0 0 3px #0D101A, 0 0 0 5px ' + k.c : '0 0 0 2px #0D101A',
z: on ? 3 : 2,
on: on ? 'true' : 'false',
label: dayLabel(r.d) + ': ' + k.word + (inSet ? ', ' + M.fmt(M.val(r)) : ', not counted'),
pick: () => this.setState({ psel: r.i })
};
});
const yTicks = [0, 1, 2, 3, 4].map((k) => ({ t: 100 - k * 25 + '%', label: metric === 'speed' ? tickMin(Math.round((M.max * k) / 4)) : metric === 'cost' ? '$' + ((M.max * k) / 4).toFixed(2) : metric === 'tokens' ? (k ? ktok((M.max * k) / 4) : '0') : M.fmt((M.max * k) / 4) }));
const xTicks = [0, 7, 14, 21, 28].map((d) => ({ l: xPct(d) + '%', label: dayLabel(d) }));
const notes = NOTES.map((n) => ({ l: xPct(n.d) + '%', label: n.label + ' · ' + dayLabel(n.d) }));
const first = done.slice(0, 3), last = done.slice(-3);
const avg = (xs, f) => xs.reduce((a, r) => a + f(r), 0) / xs.length;
const kpi = (label, now, then, fmt, better, unitWord, dfmt) => {
const diff = now - then;
const good = better === 'up' ? diff > 0 : diff < 0;
const bad = better === 'up' ? diff < 0 : diff > 0;
return { label, value: fmt(now), delta: (diff === 0 ? 'no change' : (diff > 0 ? '+' : '−') + (dfmt || fmt)(Math.abs(diff)) + ' ' + unitWord), word: good ? 'Improving' : bad ? 'Regressing' : 'Flat', wfg: good ? '#7FE3B8' : bad ? '#FF8A7D' : '#9AA8C7', wbg: good ? '#0F241C' : bad ? '#2A1513' : '#171C2B', icon: good ? 'M3 10.5l3.5-3.5 2.5 2.5L13 5.5M9.5 5.5H13V9' : bad ? 'M3 5.5L6.5 9 9 6.5l4 4M9.5 10.5H13V7' : 'M3 8h10' };
};
const kpis = [
kpi('Success, last 5', runs[runs.length - 1].ok, runs[4].ok, (v) => Math.round(v) + '%', 'up', 'vs first 5 runs', (v) => Math.round(v) + ' pts'),
kpi('Median duration', avg(last, (r) => r.secs), avg(first, (r) => r.secs), mins, 'down', 'vs first runs'),
kpi('Cost per run', avg(last, (r) => r.cost), avg(first, (r) => r.cost), (v) => '$' + v.toFixed(3), 'down', 'vs first runs'),
kpi('Tokens per run', avg(last, (r) => r.tokens), avg(first, (r) => r.tokens), ktok, 'down', 'vs first runs')
];
const phases = PHASES.map((name, pi) => {
const xs = done.map((r) => r.ph[pi]);
const mx = Math.max(...xs) * 1.1;
const spark = done.map((r, j) => (j ? 'L' : 'M') + ((j / (done.length - 1)) * 200).toFixed(1) + ' ' + (44 - (r.ph[pi] / mx) * 40).toFixed(1)).join(' ');
const a = avg(done.slice(0, 3), (r) => r.ph[pi]), b = avg(done.slice(-3), (r) => r.ph[pi]);
const pct = Math.round(((b - a) / a) * 100);
return { name, spark, now: mins(b), delta: (pct < 0 ? '−' : '+') + Math.abs(pct) + '% vs first runs', wfg: pct < -2 ? '#7FE3B8' : pct > 2 ? '#FF8A7D' : '#9AA8C7', label: name + ': median ' + mins(b) + ', ' + (pct < 0 ? Math.abs(pct) + '% faster' : pct + '% slower') };
});
const sk = SLOOK[sel.status];
const readout = {
date: dayLabel(sel.d) + ', 2026',
status: sk.word,
sfg: sk.fg,
sbg: sk.bg,
speed: mins(sel.secs),
cost: '$' + sel.cost.toFixed(3),
success: sel.ok + '%',
id: 'exec-' + (0x66e14f23 - (runs.length - 1 - sel.i) * 4099).toString(16).slice(0, 8),
hair: xPct(sel.d) + '%'
};
const perf = { line, title: M.label, unit: M.unit, sub: runs.length + ' runs over 5 weeks. ' + (M.better === 'up' ? 'Higher is better.' : 'Lower is better.') + (metric === 'success' ? '' : ' Failed and cancelled runs sit on the baseline and are not counted.') };
const pprev = () => this.setState({ psel: (selIdx + runs.length - 1) % runs.length });
const pnext = () => this.setState({ psel: (selIdx + 1) % runs.length });
'''

# ---------------------------------------------------------------- HTML pieces
PANEL = "display: flex; flex-direction: column; gap: {gap}; padding: {pad}; border-radius: 20px; border: 1px solid #1A2032; background: #0D101A; box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04)"
ARROW_L = '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 3.5L5.5 8 10 12.5"></path></svg>'
ARROW_R = '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 3.5L10.5 8 6 12.5"></path></svg>'


def seg(tabs_var, aria):
    return f'''<div role="group" aria-label="{aria}" style="display: flex; gap: 2px; padding: 3px; border-radius: 12px; border: 1px solid #1A2032; background: #0A0C14">
<sc-for list="{{{{{tabs_var}}}}}" as="t" hint-placeholder-count="3">
<button type="button" aria-pressed="{{{{t.on}}}}" onClick="{{{{t.pick}}}}" style="min-height: 34px; padding: 0 14px; border: 0; border-radius: 9px; background: {{{{t.bg}}}}; color: {{{{t.fg}}}}; font-size: 13px; font-weight: 600; cursor: pointer">{{{{t.label}}}}</button>
</sc-for>
</div>'''


def plot(height, lines_svg, dots_var, sel_fn_hint, hair_expr, phone=False, ticks_var='yTicks', note_labels=True, xaxis=True, threshold=None, ends_var=None):
    """y labels column + plot area with svg lines, gridlines, notes, hairline, dot buttons."""
    ylab_w = '40px' if phone else '48px'
    hit = '36px' if phone else '28px'
    hm = '-18px 0 0 -18px' if phone else '-14px 0 0 -14px'
    grid = '\n'.join(
        f'<line x1="0" x2="1000" y1="{height*f}" y2="{height*f}" stroke="{"#283048" if f == 1 else "#161B2B"}" stroke-width="1" vector-effect="non-scaling-stroke"></line>'
        for f in (0, 0.25, 0.5, 0.75, 1))
    note_lbl = (f'<span style="position: absolute; left: {{{{n.l}}}}; top: -30px; transform: translateX(-50%); height: 22px; padding: 0 9px; border-radius: 11px; border: 1px solid #283048; background: #111626; font-family: {MONO}; font-size: 10.5px; line-height: 20px; color: #C3CCE2; white-space: nowrap">{{{{n.label}}}}</span>'
                if note_labels else '')
    thr = ''
    if threshold:
        thr = f'''<span aria-hidden="true" style="position: absolute; left: 0; right: 0; top: {threshold[0]}; height: 0; border-top: 1px dashed color-mix(in oklab, var(--ac) 55%, #283048)"></span>
<span style="position: absolute; left: 6px; top: {threshold[0]}; transform: translateY(-120%); font-family: {MONO}; font-size: 10.5px; color: color-mix(in oklab, var(--ac) 45%, white)">{threshold[1]}</span>'''
    xa = ''
    if xaxis:
        xa = f'''<div aria-hidden="true" style="position: relative; height: 16px">
<sc-for list="{{{{xTicks}}}}" as="x" hint-placeholder-count="5">
<span style="position: absolute; left: {{{{x.l}}}}; transform: translateX(-50%); font-family: {MONO}; font-size: 10.5px; color: #6F7FA3; white-space: nowrap">{{{{x.label}}}}</span>
</sc-for>
</div>'''
    endw = ('64px' if phone else '84px') if ends_var else '0px'
    ends = ''
    if ends_var:
        ends = f'''<div style="position: relative; height: {height}px">
<sc-for list="{{{{{ends_var}}}}}" as="e" hint-placeholder-count="4">
<span style="position: absolute; left: 4px; top: {{{{e.t}}}}; transform: translateY(-50%); display: flex; align-items: center; gap: 5px; font-family: {MONO}; font-size: 11px; color: #C3CCE2; white-space: nowrap"><span aria-hidden="true" style="width: 10px; height: 3px; border-radius: 2px; background: {{{{e.c}}}}"></span>{{{{e.label}}}}</span>
</sc-for>
</div>'''
    return f'''<div style="display: grid; grid-template-columns: {ylab_w} minmax(0, 1fr) {endw}; column-gap: 8px">
<div aria-hidden="true" style="position: relative; height: {height}px">
<sc-for list="{{{{{ticks_var}}}}}" as="y" hint-placeholder-count="5">
<span style="position: absolute; right: 0; top: {{{{y.t}}}}; transform: translateY(-50%); font-family: {MONO}; font-size: 10.5px; color: #6F7FA3; white-space: nowrap">{{{{y.label}}}}</span>
</sc-for>
</div>
<div style="display: flex; flex-direction: column; gap: 8px; min-width: 0">
<div style="position: relative; height: {height}px">
<svg viewBox="0 0 1000 {height}" preserveAspectRatio="none" aria-hidden="true" style="position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible">
{grid}
{lines_svg}
</svg>
{thr}
<sc-for list="{{{{notes}}}}" as="n" hint-placeholder-count="1">
<span aria-hidden="true" style="position: absolute; left: {{{{n.l}}}}; top: {'-6px' if note_labels else '0'}; bottom: 0; width: 0; border-left: 1px dashed #34406A"></span>
{note_lbl}
</sc-for>
<span aria-hidden="true" style="position: absolute; left: {hair_expr}; top: 0; bottom: 0; width: 0; border-left: 1px solid #34406A"></span>
<sc-for list="{{{{{dots_var}}}}}" as="p" hint-placeholder-count="12">
<button type="button" aria-label="{{{{p.label}}}}" aria-pressed="{{{{p.on}}}}" onMouseEnter="{{{{p.pick}}}}" onFocus="{{{{p.pick}}}}" onClick="{{{{p.pick}}}}" style="position: absolute; left: {{{{p.l}}}}; top: {{{{p.t}}}}; z-index: {{{{p.z}}}}; display: flex; align-items: center; justify-content: center; width: {hit}; height: {hit}; margin: {hm}; padding: 0; border: 0; border-radius: 50%; background: transparent; cursor: pointer">
<span style="width: {{{{p.size}}}}; height: {{{{p.size}}}}; border-radius: 50%; background: {{{{p.c}}}}; box-shadow: {{{{p.ring}}}}"></span>
</button>
</sc-for>
</div>
{xa}
</div>
{ends}
</div>'''


def eval_lines(prefix):
    return '\n'.join(
        f'<path d="{{{{trend.{prefix}{i}}}}}" fill="none" stroke="{{{{trend.c{i}}}}}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"></path>'
        for i in range(1, 5))


ICON = lambda d: f'<svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="{d}"></path></svg>'
JUDGE_ICON = '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 2.5v11M4.5 13.5h7M3 5h10M3 5l-1.75 4.25a1.9 1.9 0 0 0 3.5 0zM13 5l-1.75 4.25a1.9 1.9 0 0 0 3.5 0z"></path></svg>'


def legend_cards(phone):
    cols = 'minmax(0, 1fr)' if phone else 'repeat(auto-fit, minmax(220px, 1fr))'
    return f'''<div aria-label="Each verifier: latest score and {{{{trend.eTitle}}}}" style="display: grid; grid-template-columns: {cols}; gap: {'8px' if phone else '10px'}">
<sc-for list="{{{{legend}}}}" as="g" hint-placeholder-count="4">
<div aria-label="{{{{g.label}}}}" style="display: flex; flex-direction: column; gap: 10px; padding: {'12px 14px' if phone else '14px 16px'}; border-radius: 14px; border: 1px solid #1A2032; background: #0A0C14; min-width: 0">
<span style="display: flex; align-items: center; gap: 8px; min-width: 0">
<span aria-hidden="true" style="flex-shrink: 0; width: 16px; height: 3px; border-radius: 2px; background: {{{{g.c}}}}"></span>
<span style="font-family: {MONO}; font-size: 11.5px; color: #C3CCE2; white-space: nowrap; overflow: hidden; text-overflow: ellipsis">{{{{g.name}}}}</span>
</span>
<div style="display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 12px">
<span style="display: flex; flex-direction: column; gap: 2px; min-width: 0">
<span style="font-size: 11.5px; color: #6F7FA3">Score</span>
<span style="display: flex; align-items: baseline; gap: 3px"><span style="font-size: {'22px' if phone else '24px'}; font-weight: 600; letter-spacing: -0.02em; font-variant-numeric: tabular-nums">{{{{g.score}}}}</span><span style="font-size: 12px; color: #6F7FA3">/100</span></span>
<span style="display: flex; align-items: center; gap: 4px; color: {{{{g.sFg}}}}; font-family: {MONO}; font-size: 11px; white-space: nowrap">{ICON('{{g.sIcon}}')}{{{{g.sDelta}}}}</span>
</span>
<span style="display: flex; flex-direction: column; gap: 2px; min-width: 0">
<span style="font-size: 11.5px; color: #6F7FA3">{{{{g.eLabel}}}}</span>
<span style="font-size: {'22px' if phone else '24px'}; font-weight: 600; letter-spacing: -0.02em; font-variant-numeric: tabular-nums">{{{{g.eValue}}}}</span>
<span style="display: flex; align-items: center; gap: 4px; color: {{{{g.eFg}}}}; font-family: {MONO}; font-size: 11px; white-space: nowrap">{ICON('{{g.eIcon}}')}{{{{g.eDelta}}}}</span>
</span>
</div>
<span style="align-self: flex-start; height: 22px; padding: 0 9px; border-radius: 11px; background: {{{{g.vbg}}}}; color: {{{{g.vfg}}}}; font-size: 12px; font-weight: 600; line-height: 22px">{{{{g.verdict}}}}</span>
</div>
</sc-for>
</div>'''


def readout_eval(phone):
    btn = '44px' if phone else '30px'
    return f'''<div role="status" aria-live="polite" style="display: flex; flex-direction: column; gap: 12px; padding: 16px; border-radius: 16px; border: 1px solid #1A2032; background: #0A0C14; {'' if phone else 'width: 256px; flex-shrink: 0; box-sizing: border-box'}">
<div style="display: flex; align-items: center; justify-content: space-between; gap: 8px">
<span style="font-family: {MONO}; font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: #6F7FA3">Run</span>
<span style="display: flex; gap: 4px">
<button type="button" aria-label="Previous run" onClick="{{{{prev}}}}" class="ghost" style="display: flex; align-items: center; justify-content: center; width: {btn}; height: {btn}; border: 1px solid #283048; border-radius: 9px; background: #0F121C; color: #C3CCE2; cursor: pointer">{ARROW_L}</button>
<button type="button" aria-label="Next run" onClick="{{{{next}}}}" class="ghost" style="display: flex; align-items: center; justify-content: center; width: {btn}; height: {btn}; border: 1px solid #283048; border-radius: 9px; background: #0F121C; color: #C3CCE2; cursor: pointer">{ARROW_R}</button>
</span>
</div>
<div style="display: flex; flex-direction: column; gap: 4px">
<span style="font-size: 16px; font-weight: 600">{{{{readout.date}}}}</span>
<span style="display: flex; align-items: center; gap: 8px; font-family: {MONO}; font-size: 12px; color: #C3CCE2"><span aria-hidden="true" style="width: 16px; height: 3px; border-radius: 2px; background: {{{{readout.c}}}}"></span>{{{{readout.model}}}}</span>
</div>
<div style="display: flex; flex-direction: column; gap: 8px; padding: 12px; border-radius: 12px; background: #0F1320">
<span style="display: flex; align-items: center; justify-content: space-between; gap: 8px">
<span style="display: flex; align-items: baseline; gap: 4px"><span style="font-size: 30px; font-weight: 600; letter-spacing: -0.02em; font-variant-numeric: tabular-nums">{{{{readout.score}}}}</span><span style="font-size: 12px; color: #9AA8C7">{{{{readout.scoreOf}}}}</span></span>
<span style="height: 24px; padding: 0 11px; border-radius: 12px; background: {{{{readout.vbg}}}}; color: {{{{readout.vfg}}}}; font-size: 12.5px; font-weight: 600; line-height: 24px">{{{{readout.verdict}}}}</span>
</span>
<span style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: #9AA8C7"><span style="color: #C3CCE2">{JUDGE_ICON}</span>Judged by <span style="font-family: {MONO}; color: #E8EEFB">{{{{readout.judge}}}}</span></span>
</div>
<div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px">
<span style="display: flex; flex-direction: column; gap: 2px"><span style="font-size: 11.5px; color: #6F7FA3">Cost</span><span style="font-family: {MONO}; font-size: 13px">{{{{readout.cost}}}}</span></span>
<span style="display: flex; flex-direction: column; gap: 2px"><span style="font-size: 11.5px; color: #6F7FA3">Speed</span><span style="font-family: {MONO}; font-size: 13px">{{{{readout.speed}}}}</span></span>
<span style="display: flex; flex-direction: column; gap: 2px"><span style="font-size: 11.5px; color: #6F7FA3">Tokens</span><span style="font-family: {MONO}; font-size: 13px">{{{{readout.tokens}}}}</span></span>
</div>
<a href="{'PhoneExecution' if phone else 'Execution'}.dc.html" style="display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; text-decoration: none">Open this run {ARROW_R}</a>
</div>'''


def lanes(phone):
    return f'''<div style="display: flex; flex-direction: column; gap: 6px; padding-top: 14px; border-top: 1px solid #1A2032">
<div style="display: flex; flex-wrap: wrap; align-items: center; gap: 6px 14px">
<span style="font-family: {MONO}; font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: #6F7FA3">Verdicts</span>
<span style="display: flex; flex-wrap: wrap; gap: 6px 12px; font-size: 12px; color: #9AA8C7">
<span style="display: flex; align-items: center; gap: 5px"><span aria-hidden="true" style="width: 8px; height: 14px; border-radius: 2px; background: var(--ac)"></span>Pass</span>
<span style="display: flex; align-items: center; gap: 5px"><span aria-hidden="true" style="width: 8px; height: 7px; border-radius: 2px; background: #FF6F61"></span>Fail</span>
<span style="display: flex; align-items: center; gap: 5px"><span aria-hidden="true" style="width: 8px; height: 7px; border-radius: 2px; background: #E5B450"></span>Error</span>
<span style="display: flex; align-items: center; gap: 5px"><span aria-hidden="true" style="width: 8px; height: 3px; border-radius: 2px; background: #4A567A"></span>Unscored</span>
</span>
</div>
<sc-for list="{{{{lanes}}}}" as="ln" hint-placeholder-count="4">
<div style="display: grid; grid-template-columns: {'40px' if phone else '48px'} minmax(0, 1fr); column-gap: 8px; align-items: end">
<span aria-hidden="true" style="justify-self: end; width: 16px; height: 3px; margin-bottom: 4px; border-radius: 2px; background: {{{{ln.c}}}}"></span>
<div aria-label="{{{{ln.name}}}} verdicts" style="position: relative; height: 22px; border-bottom: 1px solid #1A2032">
<sc-for list="{{{{ln.ticks}}}}" as="k" hint-placeholder-count="6">
<button type="button" aria-label="{{{{k.label}}}}" onMouseEnter="{{{{k.pick}}}}" onFocus="{{{{k.pick}}}}" onClick="{{{{k.pick}}}}" style="position: absolute; left: {{{{k.l}}}}; bottom: 0; display: flex; align-items: flex-end; justify-content: center; width: {'24px' if phone else '18px'}; height: 22px; margin-left: {'-12px' if phone else '-9px'}; padding: 0 0 1px; border: 0; background: transparent; cursor: pointer"><span style="width: 8px; height: {{{{k.h}}}}; border-radius: 2px; background: {{{{k.c}}}}; box-shadow: {{{{k.ring}}}}"></span></button>
</sc-for>
</div>
</div>
</sc-for>
</div>'''


def eval_section(phone):
    pad = '20px' if phone else '24px'
    head = f'''<div style="display: flex; flex-wrap: wrap; align-items: flex-start; justify-content: space-between; gap: 12px 24px">
<div style="display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1 1 320px">
<h2 style="margin: 0; font-size: {'18px' if phone else '20px'}; font-weight: 600; letter-spacing: -0.015em">Is it getting better, and at what cost?</h2>
<span style="font-size: {'13px' if phone else '14px'}; color: #9AA8C7">{{{{trend.sub}}}}</span>
</div>
<span style="display: flex; flex-direction: column; align-items: {'flex-start' if phone else 'flex-end'}; gap: 4px">
<button type="button" onClick="{{{{copyAgent}}}}" class="ghost" style="display: flex; align-items: center; gap: 7px; min-height: {'44px' if phone else '34px'}; padding: 0 12px; border-radius: 10px; border: 1px solid #283048; background: #0F121C; color: #E8EEFB; font-size: 13px; font-weight: 600; cursor: pointer"><svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" aria-hidden="true"><rect x="5.5" y="5.5" width="8" height="8" rx="1.5"></rect><path d="M10.5 5.5V3.5a1 1 0 0 0-1-1h-6a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2"></path></svg>{{{{agentLabel}}}}</button>
<span style="font-family: {MONO}; font-size: 11px; color: #6F7FA3">{{{{agentCmd}}}}</span>
</span>
</div>
<div aria-label="How to read this" style="display: flex; flex-wrap: wrap; align-items: center; gap: 6px 18px; padding: 10px 14px; border-radius: 12px; background: #0A0C14; font-size: 12.5px; color: #9AA8C7">
<span style="display: flex; align-items: center; gap: 6px"><svg width="22" height="10" viewBox="0 0 22 10" aria-hidden="true"><path d="M1 8L8 4L14 6L21 2" fill="none" stroke="#C3CCE2" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path></svg>One line per verifier model, named at its end</span>
<span style="display: flex; align-items: center; gap: 6px"><span aria-hidden="true" style="width: 9px; height: 9px; border-radius: 50%; background: #C3CCE2"></span>One dot per run</span>
<span>Top: quality score from the judge. Bottom: what each run cost you.</span>
<span>Hover a dot for the run.</span>
</div>'''
    q_caption = f'''<span style="display: flex; flex-wrap: wrap; align-items: center; gap: 6px 10px; font-size: 12.5px; color: #9AA8C7"><span style="font-weight: 600; color: #E8EEFB">Quality score</span><span>0 to 100</span><span style="display: flex; align-items: center; gap: 5px; height: 22px; padding: 0 9px; border-radius: 11px; border: 1px solid #222A40; background: #111626; color: #C3CCE2">{JUDGE_ICON}judge <span style="font-family: {MONO}; color: #E8EEFB">{{{{trend.judge}}}}</span></span></span>'''
    e_caption = f'''<div style="display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px 16px">
<span style="font-size: 12.5px; color: #9AA8C7"><span style="font-weight: 600; color: #E8EEFB">{{{{trend.eTitle}}}}</span> · {{{{trend.eUnit}}}}</span>
{seg('tabs', 'Efficiency metric')}
</div>'''
    qh, eh = (170, 130) if phone else (200, 150)
    q_plot = plot(qh, eval_lines('q'), 'qDots', None, '{{readout.hair}}', phone, ticks_var='qTicks', note_labels=True, xaxis=False, threshold=('{{trend.pass}}', 'pass 70'), ends_var='qEnds')
    e_plot = plot(eh, eval_lines('e'), 'eDots', None, '{{readout.hair}}', phone, ticks_var='eTicks', note_labels=False, xaxis=True, ends_var='eEnds')
    charts = f'''<div style="flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; gap: 10px">
{q_caption}
<div style="padding-top: 30px">{q_plot}</div>
<div style="height: 6px"></div>
{e_caption}
{e_plot}
</div>'''
    if phone:
        body = f'''{head}
{legend_cards(True)}
{charts}
{readout_eval(True)}
{lanes(True)}'''
    else:
        body = f'''{head}
{legend_cards(False)}
<div style="display: flex; gap: 20px; align-items: stretch">
{charts}
{readout_eval(False)}
</div>
{lanes(False)}'''
    return f'''<section aria-label="Trend" style="{PANEL.format(gap='18px', pad=pad)}">
{body}
</section>'''


def wf_section(phone):
    pad = '20px' if phone else '24px'
    kp = f'''<div style="display: grid; grid-template-columns: {'minmax(0, 1fr)' if phone else 'repeat(4, minmax(0, 1fr))'}; gap: 10px">
<sc-for list="{{{{kpis}}}}" as="g" hint-placeholder-count="3">
<div style="display: flex; {'align-items: center; justify-content: space-between; ' if phone else 'flex-direction: column; '}gap: 6px; padding: {'12px 14px' if phone else '14px 16px'}; border-radius: 14px; border: 1px solid #1A2032; background: #0A0C14">
<span style="display: flex; flex-direction: column; gap: 2px"><span style="font-size: 12px; color: #9AA8C7">{{{{g.label}}}}</span><span style="font-size: {'20px' if phone else '24px'}; font-weight: 600; letter-spacing: -0.02em; font-variant-numeric: tabular-nums">{{{{g.value}}}}</span></span>
<span style="display: flex; flex-direction: column; {'align-items: flex-end; ' if phone else ''}gap: 4px">
<span style="align-self: {'flex-end' if phone else 'flex-start'}; display: flex; align-items: center; gap: 4px; height: 20px; padding: 0 7px; border-radius: 10px; background: {{{{g.wbg}}}}; color: {{{{g.wfg}}}}; font-size: 11.5px; font-weight: 600"><svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="{{{{g.icon}}}}"></path></svg>{{{{g.word}}}}</span>
<span style="font-family: {MONO}; font-size: 11px; color: #9AA8C7">{{{{g.delta}}}}</span>
</span>
</div>
</sc-for>
</div>'''
    line = '<path d="{{perf.line}}" fill="none" stroke="var(--ac)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"></path>'
    chart = plot(180 if phone else 220, line, 'dots', None, '{{readout.hair}}', phone)
    legend = f'''<span style="display: flex; flex-wrap: wrap; gap: 6px 12px; font-size: 12px; color: #9AA8C7">
<span style="display: flex; align-items: center; gap: 5px"><span aria-hidden="true" style="width: 9px; height: 9px; border-radius: 50%; background: var(--ac)"></span>Completed</span>
<span style="display: flex; align-items: center; gap: 5px"><span aria-hidden="true" style="width: 9px; height: 9px; border-radius: 50%; background: #FF6F61"></span>Failed</span>
<span style="display: flex; align-items: center; gap: 5px"><span aria-hidden="true" style="width: 9px; height: 9px; border-radius: 50%; background: #6F7FA3"></span>Cancelled</span>
</span>'''
    readout = f'''<div role="status" aria-live="polite" style="display: flex; flex-direction: column; gap: 12px; padding: 16px; border-radius: 16px; border: 1px solid #1A2032; background: #0A0C14; {'' if phone else 'width: 248px; flex-shrink: 0; box-sizing: border-box'}">
<div style="display: flex; align-items: center; justify-content: space-between; gap: 8px">
<span style="font-family: {MONO}; font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: #6F7FA3">Run</span>
<span style="display: flex; gap: 4px">
<button type="button" aria-label="Previous run" onClick="{{{{pprev}}}}" class="ghost" style="display: flex; align-items: center; justify-content: center; width: {'44px' if phone else '30px'}; height: {'44px' if phone else '30px'}; border: 1px solid #283048; border-radius: 9px; background: #0F121C; color: #C3CCE2; cursor: pointer">{ARROW_L}</button>
<button type="button" aria-label="Next run" onClick="{{{{pnext}}}}" class="ghost" style="display: flex; align-items: center; justify-content: center; width: {'44px' if phone else '30px'}; height: {'44px' if phone else '30px'}; border: 1px solid #283048; border-radius: 9px; background: #0F121C; color: #C3CCE2; cursor: pointer">{ARROW_R}</button>
</span>
</div>
<div style="display: flex; flex-direction: column; gap: 4px">
<span style="font-size: 16px; font-weight: 600">{{{{readout.date}}}}</span>
<span style="font-family: {MONO}; font-size: 12px; color: #9AA8C7">{{{{readout.id}}}}</span>
</div>
<span style="align-self: flex-start; height: 24px; padding: 0 11px; border-radius: 12px; background: {{{{readout.sbg}}}}; color: {{{{readout.sfg}}}}; font-size: 12.5px; font-weight: 600; line-height: 24px">{{{{readout.status}}}}</span>
<div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px">
<span style="display: flex; flex-direction: column; gap: 2px"><span style="font-size: 11.5px; color: #6F7FA3">Duration</span><span style="font-family: {MONO}; font-size: 13px">{{{{readout.speed}}}}</span></span>
<span style="display: flex; flex-direction: column; gap: 2px"><span style="font-size: 11.5px; color: #6F7FA3">Cost</span><span style="font-family: {MONO}; font-size: 13px">{{{{readout.cost}}}}</span></span>
<span style="display: flex; flex-direction: column; gap: 2px"><span style="font-size: 11.5px; color: #6F7FA3">Success</span><span style="font-family: {MONO}; font-size: 13px">{{{{readout.success}}}}</span></span>
</div>
<a href="{'PhoneExecution' if phone else 'Execution'}.dc.html" style="display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; text-decoration: none">Open this run {ARROW_R}</a>
</div>'''
    phases = f'''<div style="display: flex; flex-direction: column; gap: 10px; padding-top: 14px; border-top: 1px solid #1A2032">
<span style="font-family: {MONO}; font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: #6F7FA3">Phase duration, completed runs</span>
<div style="display: grid; grid-template-columns: {'minmax(0, 1fr)' if phone else 'repeat(3, minmax(0, 1fr))'}; gap: 10px">
<sc-for list="{{{{phases}}}}" as="ph" hint-placeholder-count="3">
<div aria-label="{{{{ph.label}}}}" style="display: grid; grid-template-columns: minmax(0, 1fr) 96px; align-items: center; gap: 12px; padding: 12px 14px; border-radius: 14px; border: 1px solid #1A2032; background: #0A0C14">
<span style="display: flex; flex-direction: column; gap: 3px; min-width: 0">
<span style="font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis">{{{{ph.name}}}}</span>
<span style="font-family: {MONO}; font-size: 12px">{{{{ph.now}}}} <span style="color: {{{{ph.wfg}}}}">{{{{ph.delta}}}}</span></span>
</span>
<svg viewBox="0 0 200 48" preserveAspectRatio="none" aria-hidden="true" style="width: 96px; height: 32px; overflow: visible"><path d="{{{{ph.spark}}}}" fill="none" stroke="var(--ac)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"></path></svg>
</div>
</sc-for>
</div>
</div>'''
    head = f'''<div style="display: flex; flex-wrap: wrap; align-items: flex-start; justify-content: space-between; gap: 12px 24px">
<div style="display: flex; flex-direction: column; gap: 2px; min-width: 0">
<h2 style="margin: 0; font-size: {'18px' if phone else '20px'}; font-weight: 600; letter-spacing: -0.015em">Performance</h2>
<span style="font-size: {'13px' if phone else '14px'}; color: #9AA8C7">{{{{perf.sub}}}}</span>
</div>
{seg('tabs', 'Metric')}
</div>'''
    caption = f'<span style="display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 6px 16px"><span style="font-size: 12.5px; color: #9AA8C7"><span style="font-weight: 600; color: #E8EEFB">{{{{perf.title}}}}</span> · {{{{perf.unit}}}}</span>{legend}</span>'
    if phone:
        body = f'''{head}
{kp}
{caption}
<div style="padding-top: 30px">{chart}</div>
{readout}
{phases}'''
    else:
        body = f'''{head}
{kp}
<div style="display: flex; gap: 20px; align-items: stretch">
<div style="flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; gap: 4px">
{caption}
<div style="padding-top: 30px">{chart}</div>
</div>
{readout}
</div>
{phases}'''
    return f'''<section aria-label="Performance" style="{PANEL.format(gap='18px', pad=pad)}">
{body}
</section>'''


# ---------------------------------------------------------------- patching
def read(name):
    return open(os.path.join(SRC, name)).read()


def write(name, s):
    open(os.path.join(DST, name), 'w').write(s)


def cut_section(s, label):
    i = s.index(f'<section aria-label="{label}"')
    j = s.index('</section>', i) + len('</section>')
    return s[:i], s[i:j], s[j:]


def add_logic(s, js, keys):
    """Insert js before the renderVals return statement and add keys to the returned object."""
    m = list(re.finditer(r'\n\s*return \{', s))
    m = [x for x in m if s.rfind('renderVals', 0, x.start()) > 0][-1]
    js = 'const __t = (() => {' + js + 'return { ' + ', '.join(keys) + ' };\n})();\n'
    s = s[:m.start()] + '\n' + js + s[m.start():]
    k = s.index('return {', m.start() + len(js))
    s = s[:k + len('return {')] + ' ...__t,' + s[k + len('return {'):]
    return s


def bump_height(s, delta):
    return re.sub(r'("\$preview":\{"width":(\d+),"height":)(\d+)', lambda m: m.group(1) + str(int(m.group(3)) + delta), s, count=1)


EVAL_KEYS = ['trend', 'tabs', 'legend', 'qDots', 'eDots', 'qTicks', 'eTicks', 'xTicks', 'notes', 'lanes', 'readout', 'prev', 'next', 'qEnds', 'eEnds', 'copyAgent', 'agentLabel', 'agentCmd']
WF_KEYS = ['perf', 'tabs', 'kpis', 'dots', 'yTicks', 'xTicks', 'notes', 'phases', 'readout', 'pprev', 'pnext']

# Eval desktop: replace "Runs over time" with full-width Trend placed right after the hero.
s = read('Eval.dc.html')
a, _, b = cut_section(s, 'Runs over time')
s = a + b
hero_end = s.index('</section>', s.index('<section aria-label="Eval"')) + len('</section>')
s = s[:hero_end] + '\n\n' + eval_section(False) + s[hero_end:]
s = add_logic(s, eval_js(False), EVAL_KEYS)
s = bump_height(s, 900)
write('Eval.dc.html', s)

# Eval phone: replace "Runs over time" in place, then move it after the hero.
s = read('PhoneEval.dc.html')
a, _, b = cut_section(s, 'Runs over time')
s = a + b
hero_end = s.index('</section>', s.index('<section aria-label="Eval"')) + len('</section>')
s = s[:hero_end] + '\n\n' + eval_section(True) + s[hero_end:]
s = add_logic(s, eval_js(True), EVAL_KEYS)
s = bump_height(s, 1700)
write('PhoneEval.dc.html', s)

# Workflow desktop + phone: Performance after the hero (before the Pipeline row).
for name, phone, grow in [('Workflow.dc.html', False, 600), ('PhoneWorkflow.dc.html', True, 1060)]:
    s = read(name)
    hero = 'Research Workflow'
    hero_end = s.index('</section>', s.index(f'<section aria-label="{hero}"')) + len('</section>')
    s = s[:hero_end] + '\n\n' + wf_section(phone) + s[hero_end:]
    s = add_logic(s, wf_js(), WF_KEYS)
    s = bump_height(s, grow)
    write(name, s)

# Workflows list: replace each card's run-share bar with a duration sparkline + trend word.
for name in ['Workflows.dc.html', 'PhoneWorkflows.dc.html']:
    s = read(name)
    old = re.search(r'<span style="flex-grow: 1; height: 6px; border-radius: 3px; background: #121727">\s*<span style="display: block; width: \{\{w\.pct\}\}; height: 6px; border-radius: 3px; background: #8E9BBC"></span>\s*</span>', s)
    anchor = '<div style="display: flex; align-items: center; gap: 14px">\n<span style="display: flex; align-items: center; gap: 10px; flex-grow: 1">'
    new = f'''<span aria-label="{{{{w.trendLabel}}}}" style="display: flex; align-items: center; gap: 10px; flex-grow: 1; min-width: 0">
<svg viewBox="0 0 200 40" preserveAspectRatio="none" aria-hidden="true" style="flex: 1 1 auto; min-width: 48px; height: 26px; overflow: visible"><path d="{{{{w.spark}}}}" fill="none" stroke="{{{{w.sparkC}}}}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"></path></svg>
<span style="display: flex; flex-direction: column; align-items: flex-end; gap: 1px; flex-shrink: 0">
<span style="font-size: 11.5px; font-weight: 600; color: {{{{w.trendFg}}}}; white-space: nowrap">{{{{w.trendWord}}}}</span>
<span style="font-family: {MONO}; font-size: 10.5px; color: #6F7FA3; white-space: nowrap">{{{{w.trendSub}}}}</span>
</span>
</span>'''
    if old:
        s = s[:old.start()] + new + s[old.end():]
    else:
        s = s.replace(anchor, '<div style="display: flex; padding: 2px 0">' + new + '</div>\n' + anchor, 1)
    # Extend each row object with trend fields, derived deterministically from its run count.
    js = r'''
const trendOf = (n, k) => {
if (!n) return { spark: 'M0 38 L200 38', sparkC: '#283048', trendWord: 'No runs yet', trendFg: '#6F7FA3', trendSub: '—', trendLabel: 'No runs yet' };
const pts = Math.max(2, Math.min(n, 12));
const slope = ((k * 37) % 7) - 3;
const ys = Array.from({ length: pts }, (_, j) => { const base = 22 + slope * (j / (pts - 1)) * 5; const wob = ((j * 13 + k * 7) % 5) - 2; return Math.max(4, Math.min(36, base + wob)); });
const spark = ys.map((y, j) => (j ? 'L' : 'M') + ((j / (pts - 1)) * 200).toFixed(1) + ' ' + y.toFixed(1)).join(' ');
const faster = slope > 0, slower = slope < 0;
const pct = Math.abs(slope) * 6;
return { spark, sparkC: 'var(--ac)', trendWord: pts < 3 ? 'Too few runs' : faster ? 'Faster' : slower ? 'Slower' : 'Steady', trendFg: pts < 3 ? '#9AA8C7' : faster ? '#7FE3B8' : slower ? '#FF8A7D' : '#9AA8C7', trendSub: pts < 3 ? n + (n === 1 ? ' run' : ' runs') : (faster ? '−' : slower ? '+' : '±') + pct + '% time, last ' + pts, trendLabel: 'Duration trend: ' + (faster ? pct + '% faster' : slower ? pct + '% slower' : 'steady') + ' over the last ' + pts + ' runs' };
};
'''
    s = s.replace("const rows = matched", js + "const rows = matched", 1)
    s = s.replace("runLabel: 'Run ' + r[0]", "runLabel: 'Run ' + r[0], ...trendOf(r[4], r[0].length + r[3])", 1)
    write(name, s)

print('ok')
