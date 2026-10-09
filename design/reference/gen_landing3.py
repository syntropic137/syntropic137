#!/usr/bin/env python3
"""Landing v3: the real S mark built from cubes, evals front and centre (interactive explorer), then the v2 bento/story."""
import os, json
import gen_landing2 as v2  # re-writes v2 into Landing*.dc.html on import; we overwrite below
v1 = v2.v1

HERE = os.path.dirname(os.path.abspath(__file__))
_src = open(os.path.join(HERE, 'gen_trends.py')).read()
_ns = {'__file__': os.path.join(HERE, 'gen_trends.py')}
exec(_src[:_src.index('# ---------------------------------------------------------------- shared JS')], _ns)
SERIES, RUNS, PASS_AT, RATE = _ns['EVAL_SERIES'], _ns['EVAL_RUNS'], _ns['PASS_AT'], _ns['EVAL_RATE']

OUT = v1.OUT
MONO, SANS, ORB = v1.MONO, v1.SANS, v1.ORB
face, DOT, ARROW, COPY, GH = v1.face, v1.DOT, v1.ARROW, v1.COPY, v1.GH
head, tile, GRAIN, DOTGRID = v2.head, v2.tile, v2.GRAIN, v2.DOTGRID

# ------------------------------------------------------------------ the S mark, in cubes
# Rows top -> bottom, columns left -> right. B blue, D dark, G glass (matches logo.png).
S_GRID = ['BBG', 'B..', 'DDD', '..D', 'DDD']
DARK = {'front': '#1C2236', 'side': '#10141F', 'top': '#2B3350'}


def s_mark(cube, aria='Syntropic137', animate=False, ox=None, oy=None, standalone=True):
    """Cubes stand in one vertical plane that runs down-right, like the logo."""
    hw, hh, ch = cube * 0.866, cube * 0.5, cube
    rows = len(S_GRID)
    cells = []
    for r, line in enumerate(S_GRID):
        for c, t in enumerate(line):
            if t != '.':
                cells.append((c, rows - 1 - r, t))  # c along the plane, k = height level
    W = 3 * hw + hw + 8
    H = rows * ch + 5 * hh + 8
    ox = hw + 4 if ox is None else ox
    oy = rows * ch + hh + 4 if oy is None else oy
    parts = []
    # draw back-to-front: lower first, then left-to-right along the plane
    for idx, (c, k, t) in enumerate(sorted(cells, key=lambda x: (x[0], x[1]))):
        x = ox + c * hw
        y = oy + c * hh - k * ch
        top = f'{x:.1f},{y - ch:.1f} {x + hw:.1f},{y - ch + hh:.1f} {x:.1f},{y - ch + 2 * hh:.1f} {x - hw:.1f},{y - ch + hh:.1f}'
        left = f'{x - hw:.1f},{y - ch + hh:.1f} {x:.1f},{y - ch + 2 * hh:.1f} {x:.1f},{y + 2 * hh:.1f} {x - hw:.1f},{y + hh:.1f}'
        right = f'{x:.1f},{y - ch + 2 * hh:.1f} {x + hw:.1f},{y - ch + hh:.1f} {x + hw:.1f},{y + hh:.1f} {x:.1f},{y + 2 * hh:.1f}'
        if t == 'B':
            f = {'front': 'var(--ac)', 'side': 'color-mix(in oklab, var(--ac) 45%, black)', 'top': 'color-mix(in oklab, var(--ac) 62%, white)'}
            st = ''
        elif t == 'G':
            f = {'front': 'rgba(232,238,251,0.32)', 'side': 'rgba(232,238,251,0.18)', 'top': 'rgba(255,255,255,0.55)'}
            st = ' stroke="rgba(255,255,255,0.55)" stroke-width="1"'
        else:
            f, st = DARK, ' stroke="rgba(120,140,190,0.10)" stroke-width="1"'
        cls = ' class="sb"' if animate else ''
        delay = f' style="animation-delay: {0.25 + idx * 0.09:.2f}s"' if animate else ''
        parts.append(f'<g{cls}{delay}><polygon points="{left}" style="fill: {f["front"]}"{st}></polygon><polygon points="{right}" style="fill: {f["side"]}"{st}></polygon><polygon points="{top}" style="fill: {f["top"]}"{st}></polygon></g>')
    inner = ''.join(parts)
    if not standalone:
        return inner
    return f'<svg viewBox="0 0 {W:.0f} {H:.0f}" role="img" aria-label="{aria}" style="display: block; width: 100%; height: auto; overflow: visible">{inner}</svg>'


def mark(size):
    return f'<span style="display: block; width: {size}px">{s_mark(12)}</span>'


# ------------------------------------------------------------------ eval explorer data
def series_runs(si):
    return sorted([r for r in RUNS if r[1] == si], key=lambda r: r[0])


def path(points, w=1000, h=260, ymax=100):
    return ' '.join(('M' if i == 0 else 'L') + f'{2 + d / 29 * 96:.2f}' for i, (d, v) in enumerate(points))


def svgpath(points, h, ymax):
    return ' '.join(('M' if i == 0 else 'L') + f'{(2 + d / 29 * 96) * 10:.1f} {h - v / ymax * h:.1f}' for i, (d, v) in enumerate(points))


QH, CH = 230, 120
EX = []
for si, s in enumerate(SERIES):
    rs = series_runs(si)
    q = [(r[0], r[5]) for r in rs if r[5] is not None]
    cst = [(r[0], r[3]) for r in rs]
    last3 = [r[5] for r in rs if r[5] is not None][-3:]
    cost3 = [r[3] for r in rs][-3:]
    score = round(sum(last3) / len(last3))
    cost = sum(cost3) / len(cost3)
    first3 = [r[5] for r in rs if r[5] is not None][:3]
    delta = score - round(sum(first3) / len(first3))
    EX.append({
        'name': s['name'], 'short': s['short'], 'c': s['color'],
        'q': svgpath(q, QH, 100), 'k': svgpath(cst, CH, 1.6),
        'score': score, 'cost': cost, 'delta': delta,
        'per': score / cost, 'runs': len(rs), 'cd': cost - sum(r[3] for r in rs[:3]) / 3,
        'dots': [((2 + d / 29 * 96), 100 - v) for d, v in q],
    })
best = max(range(4), key=lambda i: EX[i]['per'] if EX[i]['runs'] > 4 else 0)


EXPLORER_JS = r'''
const EX = ''' + json.dumps([{k: e[k] for k in ('name', 'short', 'c', 'score', 'cost', 'delta', 'per', 'runs', 'cd')} for e in EX]) + r''';
const BEST = ''' + str(best) + r''';
const sel = typeof st.ev === 'number' ? st.ev : 1;
const lineOp = (i) => (i === sel ? 1 : 0.22);
const lineW = (i) => (i === sel ? 3 : 1.75);
const ex = {};
EX.forEach((e, i) => { ex['o' + i] = lineOp(i); ex['w' + i] = lineW(i); });
const order = EX.map((e, i) => i).sort((a, b) => EX[b].per - EX[a].per);
const rank = order.map((i, n) => {
const e = EX[i];
const on = i === sel;
const fresh = e.runs < 5;
const word = fresh ? 'New' : e.delta >= 5 ? 'Improving' : e.delta <= -5 ? 'Slipping' : 'Steady';
return {
n: String(n + 1),
c: e.c,
name: e.name,
score: String(e.score),
cost: '$' + e.cost.toFixed(2),
per: Math.round(e.per) + ' pts/$',
word,
wfg: fresh ? '#9AA8C7' : e.delta >= 5 ? '#7FE3B8' : e.delta <= -5 ? '#FF8A7D' : '#9AA8C7',
wbg: fresh ? '#171C2B' : e.delta >= 5 ? '#0F241C' : e.delta <= -5 ? '#2A1513' : '#171C2B',
best: i === BEST ? 'true' : 'false',
bestTxt: i === BEST ? 'Best quality per dollar' : '',
bg: on ? '#141A2C' : 'transparent',
bd: on ? 'color-mix(in oklab, ' + e.c + ' 55%, #1A2032)' : 'transparent',
on: on ? 'true' : 'false',
pick: () => this.setState({ ev: i })
};
});
const S = EX[sel];
const pick = {
c: S.c,
name: S.name,
score: String(S.score),
cost: '$' + S.cost.toFixed(2),
delta: (S.delta >= 0 ? '+' : '−') + Math.abs(S.delta),
line: S.runs < 5 ? 'Only ' + S.runs + ' runs so far. Give it a week before trusting the trend.' : (S.delta >= 5 ? 'Up ' + S.delta + ' points since its first runs' : S.delta <= -5 ? 'Down ' + Math.abs(S.delta) + ' points since its first runs' : 'Holding steady on quality') + (S.cd < -0.03 ? ', and $' + Math.abs(S.cd).toFixed(2) + ' cheaper per run.' : S.cd > 0.03 ? ', while costing $' + S.cd.toFixed(2) + ' more per run.' : ', at the same cost.')
};
'''


def explorer(p):
    lines_q = ''.join(f'<path d="{e["q"]}" fill="none" stroke="{e["c"]}" stroke-width="{{{{ex.w{i}}}}}" stroke-opacity="{{{{ex.o{i}}}}}" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"></path>' for i, e in enumerate(EX))
    lines_c = ''.join(f'<path d="{e["k"]}" fill="none" stroke="{e["c"]}" stroke-width="{{{{ex.w{i}}}}}" stroke-opacity="{{{{ex.o{i}}}}}" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"></path>' for i, e in enumerate(EX))
    grid = lambda h: ''.join(f'<line x1="0" x2="1000" y1="{h * f}" y2="{h * f}" stroke="{"#283048" if f == 1 else "#141A2A"}" vector-effect="non-scaling-stroke"></line>' for f in (0, .25, .5, .75, 1))
    chart = f'''<div style="display: flex; flex-direction: column; gap: 6px; min-width: 0">
<span style="display: flex; align-items: center; justify-content: space-between; gap: 10px; font-size: 12.5px; color: #9AA8C7"><span><span style="color: #E8EEFB; font-weight: 600">Quality score</span> · 0 to 100, from the judge</span><span style="font-family: {MONO}; font-size: 11px">judge: claude-opus-5-5</span></span>
<div style="position: relative; height: {QH * (0.72 if p else 1):.0f}px">
<svg viewBox="0 0 1000 {QH}" preserveAspectRatio="none" aria-hidden="true" style="position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible">{grid(QH)}
<line x1="0" x2="1000" y1="{QH * (1 - PASS_AT / 100):.0f}" y2="{QH * (1 - PASS_AT / 100):.0f}" stroke="color-mix(in oklab, var(--ac) 55%, #283048)" stroke-dasharray="5 5" vector-effect="non-scaling-stroke"></line>
{lines_q}</svg>
<span style="position: absolute; left: 6px; top: {100 - PASS_AT}%; transform: translateY(-120%); font-family: {MONO}; font-size: 10.5px; color: color-mix(in oklab, var(--ac) 45%, white)">pass 70</span>
</div>
<span style="display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 14px; font-size: 12.5px; color: #9AA8C7"><span><span style="color: #E8EEFB; font-weight: 600">Cost</span> · per run</span></span>
<div style="position: relative; height: {CH * (0.72 if p else 1):.0f}px">
<svg viewBox="0 0 1000 {CH}" preserveAspectRatio="none" aria-hidden="true" style="position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible">{grid(CH)}{lines_c}</svg>
</div>
<span style="display: flex; justify-content: space-between; font-family: {MONO}; font-size: 10.5px; color: #6F7FA3"><span>Sep 8</span><span>Sep 15</span><span>Sep 22</span><span>Sep 29</span><span>Oct 7</span></span>
</div>'''
    board = f'''<div style="display: flex; flex-direction: column; gap: 6px; min-width: 0">
<span style="font-family: {MONO}; font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; color: #6F7FA3">Ranked by quality per dollar</span>
<sc-for list="{{{{rank}}}}" as="r" hint-placeholder-count="4">
<button type="button" aria-pressed="{{{{r.on}}}}" onClick="{{{{r.pick}}}}" onMouseEnter="{{{{r.pick}}}}" onFocus="{{{{r.pick}}}}" style="display: grid; grid-template-columns: 18px minmax(0, 1fr) auto; align-items: center; gap: 4px 12px; width: 100%; padding: 12px; border-radius: 14px; border: 1px solid {{{{r.bd}}}}; background: {{{{r.bg}}}}; color: #E8EEFB; text-align: left; cursor: pointer; font-family: inherit">
<span style="font-family: {MONO}; font-size: 12px; color: #6F7FA3">{{{{r.n}}}}</span>
<span style="display: flex; flex-direction: column; gap: 3px; min-width: 0">
<span style="display: flex; align-items: center; gap: 8px; min-width: 0"><span aria-hidden="true" style="flex-shrink: 0; width: 14px; height: 3px; border-radius: 2px; background: {{{{r.c}}}}"></span><span style="font-family: {MONO}; font-size: 12.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis">{{{{r.name}}}}</span></span>
<span style="font-size: 11.5px; color: color-mix(in oklab, var(--ac) 45%, white)">{{{{r.bestTxt}}}}</span>
</span>
<span style="display: flex; align-items: center; gap: 12px">
<span style="display: flex; flex-direction: column; align-items: flex-end"><span style="font-size: 18px; font-weight: 600; font-variant-numeric: tabular-nums">{{{{r.score}}}}</span><span style="font-family: {MONO}; font-size: 10.5px; color: #6F7FA3">{{{{r.cost}}}}/run</span></span>
<span style="height: 22px; padding: 0 9px; border-radius: 11px; background: {{{{r.wbg}}}}; color: {{{{r.wfg}}}}; font-size: 11.5px; font-weight: 600; line-height: 22px">{{{{r.word}}}}</span>
</span>
</button>
</sc-for>
<div style="display: flex; flex-direction: column; gap: 6px; margin-top: 10px; padding: 14px; border-radius: 14px; background: #0A0C14; border: 1px solid #1A2032">
<span style="display: flex; align-items: baseline; gap: 10px"><span style="font-size: 34px; font-weight: 600; letter-spacing: -0.03em">{{{{pick.score}}}}</span><span style="font-size: 12.5px; color: #9AA8C7">/100 · {{{{pick.cost}}}} a run · {{{{pick.delta}}}} pts</span></span>
<span style="font-size: 13.5px; line-height: 1.5; color: #C3CCE2">{{{{pick.line}}}}</span>
</div>
</div>'''
    window = f'''<div style="position: relative; border-radius: 26px; padding: 1px; background: linear-gradient(140deg, color-mix(in oklab, var(--ac) 70%, white), rgba(40,48,72,0.6) 35%, rgba(40,48,72,0.3) 70%, color-mix(in oklab, var(--ac) 50%, transparent)); box-shadow: 0 60px 120px -40px color-mix(in oklab, var(--ac) 45%, transparent)">
<div style="border-radius: 25px; background: linear-gradient(180deg, #0F1320, #090B12); overflow: hidden">
<div style="display: flex; align-items: center; gap: 10px; padding: 12px 16px; border-bottom: 1px solid #141A2A">
<span style="display: flex; gap: 6px"><span style="width: 10px; height: 10px; border-radius: 50%; background: #283048"></span><span style="width: 10px; height: 10px; border-radius: 50%; background: #283048"></span><span style="width: 10px; height: 10px; border-radius: 50%; background: #283048"></span></span>
<span style="font-family: {MONO}; font-size: 11.5px; color: #6F7FA3; white-space: nowrap; overflow: hidden; text-overflow: ellipsis">localhost:8137/evals/shared-esp-stream</span>
</div>
<div style="display: grid; grid-template-columns: {'minmax(0, 1fr)' if p else 'minmax(0, 1.55fr) minmax(0, 1fr)'}; gap: {'18px' if p else '28px'}; padding: {'16px' if p else '28px'}">
{chart}
{board}
</div>
</div>
</div>'''
    steps = [('Capture', 'A real bug from your history becomes a case: the baseline commit, the task, and what "caught it" means.'),
             ('Replay', 'Every model or workflow you want to compare runs the case in its own clean workspace.'),
             ('Judge', 'A judge model scores each run out of 100 and writes down its evidence.'),
             ('Decide', 'Rank by quality per dollar, catch regressions the day they happen, and keep the winner.')]
    st = ''.join(f'''<div style="display: flex; flex-direction: column; gap: 8px; padding: {'0' if p else '0 4px'}; min-width: 0">
<span style="display: flex; align-items: center; gap: 10px"><span style="display: flex; align-items: center; justify-content: center; width: 28px; height: 28px; border-radius: 9px; border: 1px solid color-mix(in oklab, var(--ac) 45%, #1A2032); font-family: {MONO}; font-size: 12px; color: color-mix(in oklab, var(--ac) 50%, white)">{i + 1}</span><span style="font-size: 17px; font-weight: 600">{t}</span></span>
<span style="font-size: 14px; line-height: 1.55; color: #9AA8C7">{d}</span>
</div>''' for i, (t, d) in enumerate(steps))
    return f'''<section aria-label="Evals" style="position: relative; overflow: hidden; border-top: 1px solid #10141F; background: radial-gradient(45% 50% at 70% 30%, color-mix(in oklab, var(--ac) 14%, transparent), transparent 70%), #06080E">
<div style="display: flex; flex-direction: column; gap: {'24px' if p else '44px'}; box-sizing: border-box; max-width: 1320px; margin: 0 auto; padding: {'56px 16px' if p else '130px 40px 120px'}">
<div style="display: flex; flex-direction: {'column' if p else 'row'}; align-items: {'stretch' if p else 'flex-end'}; justify-content: space-between; gap: 24px">
{head(p, 'New · Evals', 'Stop guessing which model is better.', 'Replay real bugs against every model and workflow you run. A judge scores each run out of 100, and you see quality next to cost, over time. Try it: pick a model on the right.')}
<a class="cta" href="#" style="flex-shrink: 0; align-self: {'flex-start' if p else 'flex-end'}; display: flex; align-items: center; gap: 8px; height: 46px; padding: 0 18px; border-radius: 14px; border: 1px solid #283048; color: #E8EEFB; text-decoration: none; font-size: 14px; font-weight: 600">Read the evals guide {ARROW}</a>
</div>
{window}
<div style="display: grid; grid-template-columns: {'minmax(0, 1fr)' if p else 'repeat(4, minmax(0, 1fr))'}; gap: {'20px' if p else '28px'}; padding-top: 8px">{st}</div>
</div>
</section>'''


# ------------------------------------------------------------------ hero with the S
def nav(p):
    s = v2.nav(p)
    return s.replace(v1.logo(28), mark(24 if p else 26))


def hero(p):
    art = v2.city(16 if p else 26, 8 if p else 11, 30 if p else 36,
                  'A city of blocks, one per day of agent runs, with the Syntropic137 S rising from the middle',
                  live=(150, 171, 199, 222) if not p else (90, 101, 118), fails=(88, 260) if not p else (52,), errs=(141,) if not p else (77,),
                  hot=None)
    big_s = s_mark(64 if not p else 44, aria='The Syntropic137 S, built from cubes', animate=True)
    h1 = '50px' if p else '104px'
    card = 'display: flex; flex-direction: column; gap: 6px; padding: 12px 14px; border-radius: 16px; border: 1px solid rgba(255,255,255,0.09); background: rgba(13,16,26,0.66); backdrop-filter: blur(14px); box-shadow: 0 24px 60px -20px rgba(0,0,0,0.6)'
    floaters = '' if p else f'''<div class="float1" style="position: absolute; left: 6%; top: 30%; z-index: 3; {card}">
<span style="font-family: {MONO}; font-size: 11px; color: #9AA8C7">eval · shared-esp-stream</span>
<span style="display: flex; align-items: baseline; gap: 6px"><span style="font-size: 26px; font-weight: 600; letter-spacing: -0.02em">89</span><span style="font-size: 12px; color: #9AA8C7">/100 · claude-sonnet-5-5</span></span>
<span style="font-size: 12px; font-weight: 600; color: #7FE3B8">+24 pts in 2 weeks, same cost</span>
</div>
<div class="float2" style="position: absolute; right: 7%; top: 22%; z-index: 3; {card}">
<span style="display: flex; align-items: center; gap: 8px; font-family: {MONO}; font-size: 11px; color: #9AA8C7">{DOT}running · Deep Dive Analysis</span>
<span style="display: flex; align-items: baseline; gap: 10px"><span style="font-size: 20px; font-weight: 600">$0.104</span><span style="font-family: {MONO}; font-size: 11.5px; color: #9AA8C7">213k tokens</span></span>
</div>
<div class="float1" style="position: absolute; right: 12%; top: 58%; z-index: 3; {card}; animation-delay: 1.2s">
<span style="font-family: {MONO}; font-size: 11px; color: #9AA8C7">verdict · gpt-5.6-sol</span>
<span style="display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 600"><span style="width: 8px; height: 8px; border-radius: 2px; background: #FF6F61"></span>Missed the bug · 58/100</span>
</div>'''
    text = f'''<div style="position: relative; z-index: 4; display: flex; flex-direction: column; align-items: {'flex-start' if p else 'center'}; gap: {'18px' if p else '24px'}; box-sizing: border-box; width: 100%; max-width: 1320px; margin: 0 auto; padding: {'24px 16px 0' if p else '64px 40px 0'}; text-align: {'left' if p else 'center'}">
<a href="#evals" style="display: flex; align-items: center; gap: 10px; height: 32px; padding: 0 14px 0 6px; border-radius: 16px; border: 1px solid rgba(255,255,255,0.08); background: rgba(13,16,26,0.6); font-size: 13px; color: #C3CCE2; text-decoration: none"><span style="height: 22px; padding: 0 9px; border-radius: 11px; background: color-mix(in oklab, var(--ac) 22%, transparent); color: color-mix(in oklab, var(--ac) 40%, white); font-size: 12px; font-weight: 600; line-height: 22px">New</span>Evals: score every model out of 100 {ARROW}</a>
<h1 class="glowtext" style="margin: 0; font-size: {h1}; line-height: 0.95; font-weight: 600; letter-spacing: -0.045em; text-wrap: balance; max-width: 1120px">Agents that get better. Provably.</h1>
<p style="margin: 0; font-size: {'17px' if p else '21px'}; line-height: 1.5; color: #9AA8C7; max-width: 700px">Run Claude Code and Codex as workflows in isolated containers, record every tool call and dollar, and score every model on your real bugs. Then keep what works.</p>
{v2.terminal(p)}
</div>'''
    stage = f'''<div style="position: relative; z-index: 1; width: {'150%' if p else '112%'}; margin: {'0 0 0 -25%' if p else '-30px 0 0 -6%'}">
<div class="drift" style="position: relative">{art}
<div style="position: absolute; left: 50%; top: {'6%' if p else '2%'}; width: {'26%' if p else '15%'}; transform: translateX(-50%); filter: drop-shadow(0 30px 40px color-mix(in oklab, var(--ac) 45%, transparent))">{big_s}</div>
</div>
{floaters}
</div>'''
    ticker = ''.join(f'<span style="display: flex; align-items: center; gap: 8px; white-space: nowrap"><span style="font-family: {MONO}; font-size: {"16px" if p else "22px"}; font-weight: 500; color: #E8EEFB">{n}</span><span style="font-size: 12.5px; color: #6F7FA3">{l}</span></span>' for n, l in [('89/100', 'judge score'), ('$0.52', 'per run'), ('214', 'tool calls recorded'), ('0', 'secrets on your laptop')])
    return f'''<section aria-label="Hero" style="position: relative; overflow: hidden; background: radial-gradient(60% 50% at 50% 0%, color-mix(in oklab, var(--ac) 22%, transparent), transparent 70%), {DOTGRID} 0 0 / 28px 28px, #06080E">
<div aria-hidden="true" style="position: absolute; inset: 0; background: {GRAIN}; pointer-events: none; z-index: 5"></div>
{nav(p)}
{text}
{stage}
<div style="position: relative; z-index: 4; display: flex; flex-wrap: wrap; justify-content: center; gap: {'12px 20px' if p else '14px 56px'}; box-sizing: border-box; width: 100%; max-width: 1320px; margin: {'-20px auto 0' if p else '-110px auto 0'}; padding: {'0 16px 40px' if p else '0 40px 72px'}">{ticker}</div>
<div aria-hidden="true" style="position: absolute; left: 0; right: 0; bottom: 0; height: 160px; background: linear-gradient(180deg, transparent, #06080E); z-index: 2"></div>
</section>'''


def start(p):
    s = v2.start(p)
    # replace the outlined SYN137 sign-off with the S + wordmark
    i = s.index('<div aria-hidden="true" style="position: relative; overflow: hidden; padding: 0')
    j = s.index('</div>', i) + len('</div>')
    sign = f'''<div aria-hidden="true" style="position: relative; display: flex; align-items: flex-end; justify-content: center; gap: {'14px' if p else '36px'}; padding: 0 {'16px' if p else '40px'}; transform: translateY(12%)">
<span style="display: block; width: {'54px' if p else '150px'}">{s_mark(30)}</span>
<span style="font-family: {ORB}; font-size: {'44px' if p else '170px'}; font-weight: 700; line-height: 0.8; letter-spacing: 0.02em; color: transparent; -webkit-text-stroke: 1px color-mix(in oklab, var(--ac) 40%, #1A2032); white-space: nowrap">SYNTROPIC137</span>
</div>'''
    return s[:i] + sign + s[j:]


def footer(p):
    return v1.footer(p).replace(v1.logo(24), mark(22))


STYLE = v2.STYLE + r'''
.sb{animation:sdrop .9s cubic-bezier(.2,.9,.25,1.15) both}
@keyframes sdrop{from{transform:translateY(-120px);opacity:0}}
.float1{animation:bob 7s ease-in-out infinite}
.float2{animation:bob 8s ease-in-out .6s infinite reverse}
@keyframes bob{50%{transform:translateY(-10px)}}
'''

SCRIPT = r'''
class Component extends DCLogic {
renderVals() {
const st = this.state || {};
const copied = !!st.copied;
const copyInstall = () => {
try { if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText('npx @syntropic137/setup init').catch(() => {}); } catch (e) {}
this.setState({ copied: true });
};
''' + EXPLORER_JS + r'''
return { accent: this.props.accent ?? '#4D80FF', copyInstall, copyLabel: copied ? 'Copied' : 'Copy', ex, rank, pick };
}
}
'''


def bento(p):
    # evals now have their own section; reframe the bento title
    return v2.bento(p).replace('Everything an agent does, measured.', 'Everything around the eval, too.').replace(
        'Not a wrapper around a chat window. Workflows, isolation, telemetry, evals and triggers, in one self-hosted stack.',
        'Evals need clean runs and honest numbers. The rest of the platform is how you get them.')


def page(p):
    W, H = (390, 6900) if p else (1440, 6300)
    body = '\n'.join([hero(p), explorer(p).replace('aria-label="Evals"', 'id="evals" aria-label="Evals"', 1), bento(p), v2.story(p), v2.compare(p), start(p), footer(p)])
    props = json.dumps({"accent": {"editor": "color", "default": "#4D80FF", "options": ["#4D80FF", "#4CC9F0", "#45E0A0", "#A78BFA"]}, "$preview": {"width": W, "height": H}})
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Syntropic137 landing v3{' (phone)' if p else ''}</title>
<script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=Orbitron:wght@500;600;700&display=swap">
<style>{STYLE}</style>
</helmet>
<div style="--ac: {{{{accent}}}}; display: flex; flex-direction: column; min-height: 100vh; background: #06080E; color: #E8EEFB; font-family: {SANS}; font-size: 14px; line-height: 1.45; -webkit-font-smoothing: antialiased; overflow-x: hidden">
{body}
</div>
</x-dc>
<script type="text/x-dc" data-dc-script data-props='{props}'>{SCRIPT}</script>
</body>
</html>
'''


# keep v2 for comparison
open(os.path.join(OUT, 'LandingV2.dc.html'), 'w').write(v2.page(False).replace('<title>Syntropic137 landing v2', '<title>Syntropic137 landing v2'))
open(os.path.join(OUT, 'PhoneLandingV2.dc.html'), 'w').write(v2.page(True))
open(os.path.join(OUT, 'Landing.dc.html'), 'w').write(page(False))
open(os.path.join(OUT, 'PhoneLanding.dc.html'), 'w').write(page(True))
print('ok v3', 'best', EX[best]['name'], [(e['short'], e['score'], round(e['cost'], 2), round(e['per'])) for e in EX])
