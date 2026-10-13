#!/usr/bin/env python3
"""Landing v2: 'Living city + bento'. Full-bleed animated isometric city hero, zoom story, bento of live tiles."""
import os, json, math
import gen_landing as v1  # helpers (re-writes v1 files on import; overwritten below)

OUT = v1.OUT
MONO, SANS, ORB = v1.MONO, v1.SANS, v1.ORB
face, logo, DOT, ARROW, COPY, GH = v1.face, v1.logo, v1.DOT, v1.ARROW, v1.COPY, v1.GH

import urllib.parse
_grain_svg = ("<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'>"
              "<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/></filter>"
              "<rect width='100%' height='100%' filter='url(#n)' opacity='0.06'/></svg>")
GRAIN = 'url(data:image/svg+xml,' + urllib.parse.quote(_grain_svg, safe='') + ')'
DOTGRID = "radial-gradient(circle at 1px 1px, rgba(154,168,199,0.14) 1px, transparent 0)"

STYLE = r'''
:root{--ac:#4D80FF}
body{margin:0;background:#06080E}
a{color:#E8EEFB}a:hover{color:#FFFFFF}
button{font-family:inherit}
:focus-visible{outline:2px solid var(--ac);outline-offset:3px}
.b{animation:rise 1.1s cubic-bezier(.2,.8,.2,1) both}
@keyframes rise{from{transform:translateY(-60px);opacity:0}}
.live{animation:rise 1.1s cubic-bezier(.2,.8,.2,1) both, pulse 2.6s ease-in-out 1.6s infinite}
@keyframes pulse{0%,100%{filter:none}50%{filter:brightness(1.55) drop-shadow(0 0 8px var(--ac))}}
.fail{animation:rise 1.1s cubic-bezier(.2,.8,.2,1) both, flash 5s ease-in-out 3s infinite}
@keyframes flash{0%,80%,100%{filter:none}88%{filter:brightness(1.4) drop-shadow(0 0 10px #FF6F61)}}
.drift{animation:drift 22s ease-in-out infinite alternate;transform-origin:50% 60%}
@keyframes drift{from{transform:translate3d(0,0,0) scale(1)}to{transform:translate3d(-1.5%,1%,0) scale(1.05)}}
.plus{animation:plus 2.6s ease-out 1.6s infinite}
@keyframes plus{0%{opacity:0;transform:translateY(6px)}20%{opacity:1}100%{opacity:0;transform:translateY(-26px)}}
.type{display:inline-block;overflow:hidden;white-space:nowrap;vertical-align:bottom;width:0;animation:type 1.8s steps(28) .8s forwards}
@keyframes type{to{width:28ch}}
.caret{display:inline-block;width:8px;height:1.1em;margin-left:2px;vertical-align:-0.15em;background:var(--ac);animation:blink 1s steps(1) infinite}
@keyframes blink{50%{opacity:0}}
.tile{transition:border-color .25s ease, transform .25s ease, box-shadow .25s ease}
.tile:hover{border-color:color-mix(in oklab,var(--ac) 55%,#1A2032);transform:translateY(-3px);box-shadow:0 30px 60px -20px color-mix(in oklab,var(--ac) 35%,transparent)}
.draw{stroke-dasharray:1400;stroke-dashoffset:1400;animation:draw 2.6s cubic-bezier(.4,0,.2,1) .4s forwards}
@keyframes draw{to{stroke-dashoffset:0}}
.scroll{animation:scroll 14s linear infinite}
@keyframes scroll{to{transform:translateY(-50%)}}
.glowtext{background:linear-gradient(180deg,#FFFFFF 0%,#C9D6F5 55%,color-mix(in oklab,var(--ac) 70%,white) 100%);-webkit-background-clip:text;background-clip:text;color:transparent}
.cta{transition:transform .2s ease, box-shadow .2s ease}
.cta:hover{transform:translateY(-1px);box-shadow:0 12px 30px -8px color-mix(in oklab,var(--ac) 70%,transparent)}
.ghost:hover{background:#151A2A}
@media (prefers-reduced-motion: reduce){*,*::before,*::after{animation:none!important;transition:none!important}.type{width:28ch}.draw{stroke-dashoffset:0}}
'''


# ------------------------------------------------------------------ the living city
def city(cols, rows, cw, aria, live=(), fails=(), errs=(), hot=None):
    hw, hh = cw / 2, cw / 4
    blocks = []
    for j in range(rows):
        for i in range(cols):
            k = j * cols + i
            ramp = (i + (rows - j) * 0.35) / (cols + rows * 0.35)
            wob = ((k * 37) % 13) / 13
            act = (0.12 + 0.88 * ramp) * (0.4 + 0.6 * wob)
            if (k * 17) % 9 == 0:
                act *= 0.2
            if hot is not None and k == hot:
                act = 1.15
            h = 3 + act * cw * 2.6
            blocks.append((i, j, k, h, act))
    ox = rows * hw + 30
    oy = max(b[3] for b in blocks) + 30
    W = (cols + rows) * hw + 60
    H = oy + (cols + rows) * hh + 20
    parts = []
    for (i, j, k, h, act) in sorted(blocks, key=lambda b: (b[0] + b[1], b[0])):
        x = ox + (i - j) * hw
        y = oy + (i + j) * hh
        gap = cw * 0.09
        a, b = hw - gap, hh - gap / 2
        c, cls = 'var(--ac)', 'b'
        if k in fails:
            c, cls = '#FF6F61', 'fail'
        elif k in errs:
            c = '#E5B450'
        elif k in live:
            cls = 'live'
        op = 0.28 + 0.72 * min(1, act * 1.3)
        top = f'{x:.1f},{y - h - b:.1f} {x + a:.1f},{y - h:.1f} {x:.1f},{y - h + b:.1f} {x - a:.1f},{y - h:.1f}'
        left = f'{x - a:.1f},{y - h:.1f} {x:.1f},{y - h + b:.1f} {x:.1f},{y + b:.1f} {x - a:.1f},{y:.1f}'
        right = f'{x:.1f},{y - h + b:.1f} {x + a:.1f},{y - h:.1f} {x + a:.1f},{y:.1f} {x:.1f},{y + b:.1f}'
        delay = 0.15 + (i + j) * 0.035
        parts.append(f'<g class="{cls}" style="animation-delay: {delay:.2f}s, {delay + 1.6:.2f}s; opacity: {op:.2f}"><polygon points="{left}" style="fill: {face(c, "front")}"></polygon><polygon points="{right}" style="fill: {face(c, "side")}"></polygon><polygon points="{top}" style="fill: {face(c, "top")}"></polygon></g>')
        if k == hot:
            parts.append(f'<g class="plus"><text x="{x:.1f}" y="{y - h - 18:.1f}" text-anchor="middle" style="font-family: {MONO}; font-size: {cw * 0.42:.0f}px; fill: color-mix(in oklab, var(--ac) 45%, white)">+1 run</text></g>')
    floor = f'{ox:.1f},{oy - hh:.1f} {ox + cols * hw:.1f},{oy + cols * hh - hh:.1f} {ox + (cols - rows) * hw:.1f},{oy + (cols + rows) * hh - hh:.1f} {ox - rows * hw:.1f},{oy + rows * hh - hh:.1f}'
    return (f'<svg viewBox="0 0 {W:.0f} {H:.0f}" role="img" aria-label="{aria}" style="display: block; width: 100%; height: auto; overflow: visible">'
            f'<defs><radialGradient id="cityglow" cx="55%" cy="55%" r="55%"><stop offset="0" stop-color="var(--ac)" stop-opacity="0.35"></stop><stop offset="1" stop-color="var(--ac)" stop-opacity="0"></stop></radialGradient></defs>'
            f'<ellipse cx="{W * 0.55:.0f}" cy="{H * 0.62:.0f}" rx="{W * 0.5:.0f}" ry="{H * 0.42:.0f}" fill="url(#cityglow)"></ellipse>'
            f'<polygon points="{floor}" fill="none" stroke="#1A2032" stroke-width="1"></polygon>'
            + ''.join(parts) + '</svg>')


def nav(p):
    links = '' if p else f'''<nav aria-label="Site" style="display: flex; align-items: center; gap: 2px; padding: 4px; border-radius: 14px; border: 1px solid rgba(255,255,255,0.06); background: rgba(13,16,26,0.55); backdrop-filter: blur(12px); font-size: 14px">
''' + ''.join(f'<a class="ghost" href="#" style="padding: 8px 14px; border-radius: 10px; color: #C3CCE2; text-decoration: none">{t}</a>' for t in ['Product', 'Docs', 'Evals', 'For agents', 'Changelog']) + '</nav>'
    return f'''<header style="position: relative; z-index: 3; display: flex; align-items: center; justify-content: space-between; gap: 16px; box-sizing: border-box; width: 100%; max-width: 1320px; margin: 0 auto; padding: {'14px 16px' if p else '22px 40px'}">
<a href="#" style="display: flex; align-items: center; gap: 10px; text-decoration: none">{logo(28)}<span style="font-family: {ORB}; font-size: {'13px' if p else '15px'}; font-weight: 600; letter-spacing: 0.06em; color: #E8EEFB">Syntropic<span style="color: var(--ac)">137</span></span></a>
{links}
<div style="display: flex; align-items: center; gap: 8px">
<a class="ghost" href="https://github.com/syntropic137/syntropic137" aria-label="GitHub" style="display: flex; align-items: center; gap: 8px; height: {'44px' if p else '40px'}; padding: 0 12px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.08); color: #E8EEFB; text-decoration: none; font-size: 13.5px">{GH}{'' if p else 'Star on GitHub'}</a>
{'' if p else '<a class="cta" href="#start" style="display: flex; align-items: center; height: 40px; padding: 0 16px; border-radius: 12px; background: var(--ac); color: #FFFFFF; text-decoration: none; font-size: 13.5px; font-weight: 600">Get started</a>'}
</div>
</header>'''


def terminal(p, big=True):
    return f'''<div style="display: flex; flex-direction: column; gap: 10px; {'width: 100%' if p else 'width: 560px'}">
<div style="position: relative; display: flex; align-items: center; gap: 12px; box-sizing: border-box; width: 100%; min-height: 60px; padding: 8px 8px 8px 18px; border-radius: 18px; border: 1px solid rgba(255,255,255,0.09); background: linear-gradient(180deg, rgba(20,25,40,0.85), rgba(10,12,20,0.85)); backdrop-filter: blur(14px); box-shadow: 0 1px 0 rgba(255,255,255,0.06) inset, 0 30px 80px -30px color-mix(in oklab, var(--ac) 60%, transparent)">
<span aria-hidden="true" style="font-family: {MONO}; font-size: 15px; color: color-mix(in oklab, var(--ac) 55%, white)">❯</span>
<code style="flex: 1 1 auto; min-width: 0; font-family: {MONO}; font-size: {'13px' if p else '15px'}; color: #E8EEFB; overflow: hidden"><span class="type">npx @syntropic137/setup init</span><span class="caret" aria-hidden="true"></span></code>
<button type="button" class="cta" onClick="{{{{copyInstall}}}}" aria-label="Copy install command" style="display: flex; align-items: center; gap: 7px; height: 44px; padding: 0 16px; border: 0; border-radius: 12px; background: var(--ac); color: #FFFFFF; font-size: 14px; font-weight: 600; cursor: pointer; white-space: nowrap">{COPY}{{{{copyLabel}}}}</button>
</div>
<span style="font-size: 12.5px; color: #6F7FA3">Open source, MIT. Node 18+ and Docker. Your dashboard is live at localhost:8137 in about five minutes.</span>
</div>'''


def hero(p):
    art = city(16 if p else 26, 8 if p else 11, 30 if p else 36,
               'A city of blocks, one per day of agent runs; blocks rise as runs land, a few pulse live and one flashes red when it fails',
               live=(150, 171, 199, 222) if not p else (90, 101, 118), fails=(88, 260) if not p else (52,), errs=(141,) if not p else (77,),
               hot=(10 * 26 + 24) if not p else (7 * 16 + 14))
    h1 = '52px' if p else '112px'
    head = f'''<div style="position: relative; z-index: 2; display: flex; flex-direction: column; align-items: {'flex-start' if p else 'center'}; gap: {'18px' if p else '26px'}; box-sizing: border-box; width: 100%; max-width: 1320px; margin: 0 auto; padding: {'28px 16px 0' if p else '72px 40px 0'}; text-align: {'left' if p else 'center'}">
<a href="#" style="display: flex; align-items: center; gap: 10px; height: 32px; padding: 0 14px 0 6px; border-radius: 16px; border: 1px solid rgba(255,255,255,0.08); background: rgba(13,16,26,0.6); font-size: 13px; color: #C3CCE2; text-decoration: none"><span style="height: 22px; padding: 0 9px; border-radius: 11px; background: color-mix(in oklab, var(--ac) 22%, transparent); color: color-mix(in oklab, var(--ac) 40%, white); font-size: 12px; font-weight: 600; line-height: 22px">New</span>Evals with a judge score and cost trends {ARROW}</a>
<h1 class="glowtext" style="margin: 0; font-size: {h1}; line-height: 0.95; font-weight: 600; letter-spacing: -0.045em; text-wrap: balance; max-width: 1100px">Your agents, on the record.</h1>
<p style="margin: 0; font-size: {'17px' if p else '21px'}; line-height: 1.5; color: #9AA8C7; max-width: 680px">Run Claude Code and Codex as repeatable workflows in isolated containers. Every tool call, token, dollar and verdict is kept, so you can prove they're getting better.</p>
{terminal(p)}
</div>'''
    city_block = f'''<div aria-hidden="false" style="position: relative; z-index: 1; width: {'150%' if p else '112%'}; margin: {'-10px 0 0 -25%' if p else '-40px 0 0 -6%'}">
<div class="drift">{art}</div>
</div>'''
    ticker = ''.join(f'<span style="display: flex; align-items: center; gap: 8px; white-space: nowrap"><span style="font-family: {MONO}; font-size: {"16px" if p else "22px"}; font-weight: 500; color: #E8EEFB">{n}</span><span style="font-size: 12.5px; color: #6F7FA3">{l}</span></span>' for n, l in [('214', 'tool calls in the last run'), ('1.12M', 'tokens, by type'), ('$0.2162', 'to the cent'), ('89/100', 'judge score')])
    return f'''<section aria-label="Hero" style="position: relative; overflow: hidden; background: radial-gradient(60% 50% at 50% 0%, color-mix(in oklab, var(--ac) 22%, transparent), transparent 70%), {DOTGRID} 0 0 / 28px 28px, #06080E">
<div aria-hidden="true" style="position: absolute; inset: 0; background: {GRAIN}; pointer-events: none; z-index: 3"></div>
<div aria-hidden="true" style="position: absolute; left: 50%; top: -20%; width: 2px; height: 70%; transform: translateX(-50%) rotate(18deg); background: linear-gradient(180deg, transparent, color-mix(in oklab, var(--ac) 70%, white), transparent); filter: blur(1px); opacity: 0.35"></div>
{nav(p)}
{head}
{city_block}
<div style="position: relative; z-index: 2; display: flex; flex-wrap: wrap; justify-content: center; gap: {'12px 20px' if p else '14px 56px'}; box-sizing: border-box; width: 100%; max-width: 1320px; margin: {'-24px auto 0' if p else '-120px auto 0'}; padding: {'0 16px 40px' if p else '0 40px 72px'}">{ticker}</div>
<div aria-hidden="true" style="position: absolute; left: 0; right: 0; bottom: 0; height: 160px; background: linear-gradient(180deg, transparent, #06080E); z-index: 1"></div>
</section>'''


def story(p):
    """City → one run → its trend, as the scroll story (stepped here)."""
    mini = city(10, 5, 22, 'Ten weeks of runs with one block highlighted', live=(), fails=(12,), errs=(), hot=46)
    run = f'''<div style="display: flex; flex-direction: column; gap: 10px">
<span style="display: flex; align-items: center; gap: 8px; font-family: {MONO}; font-size: 11.5px; color: #9AA8C7">{DOT}exec-66e14f23 · research-workflow-v2</span>
''' + ''.join(f'''<div style="display: grid; grid-template-columns: 1fr auto; gap: 6px 12px; padding: 12px 14px; border-radius: 14px; border: 1px solid #1A2032; background: #0A0C14">
<span style="font-size: 14px; font-weight: 600">{n}</span><span style="font-family: {MONO}; font-size: 12px; color: #9AA8C7">{t}</span>
<span style="grid-column: 1 / -1; display: flex; height: 6px; gap: 2px"><span style="flex: {a}; border-radius: 3px 0 0 3px; background: #4C8DEA"></span><span style="flex: {b}; background: #E0703A"></span><span style="flex: {c}; background: #9085E9"></span><span style="flex: {d}; border-radius: 0 3px 3px 0; background: #C98500"></span></span>
</div>''' for n, t, a, b, c, d in [('Discovery', '0m 55s · $0.021', 5, 2, 2, 1), ('Deep dive', '2m 09s · $0.052', 6, 2, 3, 1), ('Synthesis', '1m 33s · $0.031', 4, 1, 4, 1)]) + '</div>'
    def path(vals, h=110, w=420):
        n = len(vals)
        return ' '.join(('M' if i == 0 else 'L') + f'{i * w / (n - 1):.1f} {h - v / 100 * h:.1f}' for i, v in enumerate(vals))
    trend = f'''<div style="display: flex; flex-direction: column; gap: 10px">
<span style="display: flex; align-items: baseline; gap: 10px"><span style="font-size: 30px; font-weight: 600; letter-spacing: -0.02em">−37%</span><span style="font-size: 13px; color: #9AA8C7">time per run since v2, same success rate</span></span>
<svg viewBox="0 0 420 110" preserveAspectRatio="none" role="img" aria-label="Run duration falling from 7 minutes to 4.5 minutes" style="width: 100%; height: 120px; overflow: visible">
<line x1="0" x2="420" y1="110" y2="110" stroke="#283048" vector-effect="non-scaling-stroke"></line>
<line x1="190" x2="190" y1="0" y2="110" stroke="#34406A" stroke-dasharray="4 4" vector-effect="non-scaling-stroke"></line>
<path class="draw" d="{path([82, 80, 78, 77, 72, 66, 63, 60, 57, 55, 53, 52])}" fill="none" stroke="var(--ac)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"></path>
</svg>
<span style="font-family: {MONO}; font-size: 11px; color: #6F7FA3">v2 published · Sep 17</span>
</div>'''
    frames = [('01', 'Ten weeks at a glance', 'Every day of agent work as one block. The tall ones are busy days, coral ones failed.', f'<div style="padding: 8px 0">{mini}</div>'),
              ('02', 'Open any block', 'Each block opens into its runs: every phase, model, tool call and cent.', run),
              ('03', 'Follow the trend', 'Change a prompt, swap a model, and see whether it actually helped.', trend)]
    cards = ''.join(f'''<div class="tile" style="position: relative; display: flex; flex-direction: column; gap: 14px; padding: {'18px' if p else '24px'}; border-radius: 22px; border: 1px solid #1A2032; background: linear-gradient(180deg, #0F1320, #0A0C14); min-width: 0">
<span style="font-family: {MONO}; font-size: 12px; color: color-mix(in oklab, var(--ac) 55%, white)">{n}</span>
<span style="font-size: 22px; font-weight: 600; letter-spacing: -0.02em">{t}</span>
<span style="font-size: 14px; line-height: 1.5; color: #9AA8C7">{d}</span>
<div style="margin-top: auto">{body}</div>
</div>''' for n, t, d, body in frames)
    arrow = '' if p else f'<span aria-hidden="true" style="position: absolute; top: 50%; right: -22px; z-index: 2; display: flex; align-items: center; justify-content: center; width: 28px; height: 28px; border-radius: 50%; border: 1px solid #283048; background: #0D101A; color: #9AA8C7">{ARROW}</span>'
    return f'''<section aria-label="Zoom in" style="box-sizing: border-box; width: 100%; max-width: 1320px; margin: 0 auto; padding: {'48px 16px' if p else '120px 40px'}">
{head(p, 'Zoom in', 'From ten weeks to one decision.', 'On scroll, the city zooms into a single block, opens its run, then pulls back to the trend that run belongs to.')}
<div style="display: grid; grid-template-columns: {'minmax(0, 1fr)' if p else 'repeat(3, minmax(0, 1fr))'}; gap: {'12px' if p else '20px'}; margin-top: {'24px' if p else '48px'}">{cards}</div>
</section>'''


def head(p, eb, title, sub, center=False):
    return f'''<div style="display: flex; flex-direction: column; gap: 14px; max-width: 820px; {'margin: 0 auto; text-align: center; align-items: center' if center else ''}">
<span style="font-family: {MONO}; font-size: 12px; letter-spacing: 0.16em; text-transform: uppercase; color: color-mix(in oklab, var(--ac) 55%, white)">{eb}</span>
<h2 class="glowtext" style="margin: 0; font-size: {'36px' if p else '64px'}; line-height: 1; font-weight: 600; letter-spacing: -0.04em; text-wrap: balance">{title}</h2>
<p style="margin: 0; font-size: {'16px' if p else '19px'}; line-height: 1.55; color: #9AA8C7">{sub}</p>
</div>'''


def tile(p, span, rows, eb, title, body, accent=False):
    grid = '' if p else f'grid-column: span {span}; grid-row: span {rows};'
    bg = ('radial-gradient(80% 80% at 100% 0%, color-mix(in oklab, var(--ac) 18%, transparent), transparent 70%), linear-gradient(180deg, #0F1320, #0A0C14)'
          if accent else 'linear-gradient(180deg, #0F1320, #0A0C14)')
    return f'''<div class="tile" style="{grid} position: relative; overflow: hidden; display: flex; flex-direction: column; gap: 12px; padding: {'18px' if p else '26px'}; border-radius: 24px; border: 1px solid #1A2032; background: {bg}; box-shadow: inset 0 1px 0 rgba(255,255,255,0.05); min-width: 0">
<span style="font-family: {MONO}; font-size: 11.5px; letter-spacing: 0.12em; text-transform: uppercase; color: #6F7FA3">{eb}</span>
<span style="font-size: {'20px' if p else '24px'}; line-height: 1.15; font-weight: 600; letter-spacing: -0.02em">{title}</span>
<div style="margin-top: auto; min-width: 0">{body}</div>
</div>'''


def bento(p):
    log_rows = [('14:02:11', 'Read', 'src/domain/aggregate.py', '42ms'), ('14:02:14', 'Grep', '"apply_event" -n', '118ms'), ('14:02:19', 'Bash', 'pytest -q tests/domain', '8.4s'),
                ('14:02:31', 'Write', 'docs/event-sourcing.md', '12ms'), ('14:02:33', 'Read', 'src/projections/list.py', '31ms'), ('14:02:40', 'Edit', 'projection.py +12 −3', '9ms'),
                ('14:02:52', 'Bash', 'ruff check .', '1.2s'), ('14:03:01', 'Read', 'tests/test_replay.py', '28ms')]
    lr = ''.join(f'<span style="display: grid; grid-template-columns: 64px 46px minmax(0,1fr) 52px; gap: 10px; padding: 6px 10px; font-family: {MONO}; font-size: 12px"><span style="color: #6F7FA3">{t}</span><span style="color: color-mix(in oklab, var(--ac) 50%, white)">{k}</span><span style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis">{a}</span><span style="text-align: right; color: #9AA8C7">{d}</span></span>' for t, k, a, d in log_rows)
    live = f'''<div style="display: flex; flex-direction: column; gap: 14px">
<div style="display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 20px"><span style="font-size: 40px; font-weight: 600; letter-spacing: -0.03em">$0.2162</span><span style="font-family: {MONO}; font-size: 13px; color: #9AA8C7">1.12M tokens · 214 tool calls · 6m 12s</span></div>
<div style="display: flex; height: 22px; gap: 2px"><span style="flex: 52; border-radius: 6px 0 0 6px; background: #4C8DEA"></span><span style="flex: 18; background: #E0703A"></span><span style="flex: 21; background: #9085E9"></span><span style="flex: 9; border-radius: 0 6px 6px 0; background: #C98500"></span></div>
<div style="display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 12px; color: #9AA8C7">''' + ''.join(f'<span style="display: flex; align-items: center; gap: 6px"><span style="width: 9px; height: 9px; border-radius: 2px; background: {c}"></span>{l}</span>' for c, l in [('#4C8DEA', 'Cache read'), ('#E0703A', 'Cache write'), ('#9085E9', 'Output'), ('#C98500', 'Input')]) + f'''</div>
<div style="position: relative; height: 168px; overflow: hidden; border-radius: 14px; border: 1px solid #1A2032; background: #080A11; -webkit-mask-image: linear-gradient(180deg, transparent, #000 18%, #000 82%, transparent); mask-image: linear-gradient(180deg, transparent, #000 18%, #000 82%, transparent)">
<div class="scroll" style="display: flex; flex-direction: column">{lr}{lr}</div>
</div>
</div>'''
    look = {'P': ('var(--ac)', 24), 'F': ('#FF6F61', 9), 'E': ('#E5B450', 9), 'U': ('#4A567A', 3)}
    V = [['P', 'P', 'P', 'U'], ['P', 'F', 'P', 'U'], ['P', 'P', 'F', 'U'], ['P', 'P', 'P', 'U'], ['P', 'F', 'F', 'U']]
    vb = ''
    for r in V:
        row = ''
        for v in r:
            c, h = look[v]
            y = 34 - h
            row += f'<svg width="{"40" if p else "48"}" height="{"42" if p else "48"}" viewBox="0 0 56 46" aria-hidden="true"><polygon points="12,{y} 28,{y + 8} 28,42 12,34" style="fill: {face(c, "front")}"></polygon><polygon points="28,{y + 8} 44,{y} 44,34 28,42" style="fill: {face(c, "side")}"></polygon><polygon points="28,{y - 8} 44,{y} 28,{y + 8} 12,{y}" style="fill: {face(c, "top")}"></polygon></svg>'
        vb += f'<div style="display: flex">{row}</div>'
    verdict = f'''<div style="display: flex; flex-direction: column; gap: 10px"><div role="img" aria-label="Verdict board: 5 real bugs by 4 models" style="display: flex; flex-direction: column">{vb}</div>
<span style="display: flex; gap: 8px; font-family: {MONO}; font-size: 11px; color: #9AA8C7"><span>opus</span><span>·</span><span>sonnet</span><span>·</span><span>sol</span><span>·</span><span>terra</span></span></div>'''
    def path(vals, h=120, w=480):
        n = len(vals)
        return ' '.join(('M' if i == 0 else 'L') + f'{i * w / (n - 1):.1f} {h - v / 100 * h:.1f}' for i, v in enumerate(vals))
    tr = f'''<div style="display: flex; flex-direction: column; gap: 10px">
<svg viewBox="0 0 480 120" preserveAspectRatio="none" role="img" aria-label="sonnet's score rises from 48 to 89; sol's falls to 58" style="width: 100%; height: 130px; overflow: visible">
<line x1="0" x2="480" y1="36" y2="36" stroke="color-mix(in oklab, var(--ac) 55%, #283048)" stroke-dasharray="4 4" vector-effect="non-scaling-stroke"></line>
<line x1="0" x2="480" y1="120" y2="120" stroke="#283048" vector-effect="non-scaling-stroke"></line>
<path class="draw" d="{path([48, 55, 72, 63, 66, 78, 84, 87, 89])}" fill="none" stroke="#199E70" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"></path>
<path class="draw" d="{path([80, 78, 64, 76, 62, 73, 58])}" fill="none" stroke="#9085E9" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke" style="animation-delay: .9s"></path>
</svg>
<span style="display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 12.5px"><span style="display: flex; align-items: center; gap: 6px"><span style="width: 14px; height: 3px; border-radius: 2px; background: #199E70"></span>sonnet <span style="color: #7FE3B8">89 · better, same cost</span></span><span style="display: flex; align-items: center; gap: 6px"><span style="width: 14px; height: 3px; border-radius: 2px; background: #9085E9"></span>sol <span style="color: #FF8A7D">58 · slipping</span></span></span>
</div>'''
    iso = f'''<div style="display: flex; gap: 8px">''' + ''.join(f'<span style="flex: 1; display: flex; flex-direction: column; gap: 6px; padding: 12px 10px; border-radius: 12px; border: 1px dashed #283048; font-family: {MONO}; font-size: 11px; color: #9AA8C7"><span style="color: #E8EEFB">{n}</span>{m}</span>' for n, m in [('ws-1', 'opus'), ('ws-2', 'sol'), ('ws-3', 'sonnet')]) + f'''</div>
<span style="display: block; margin-top: 10px; font-size: 12.5px; color: #9AA8C7">Throwaway containers · credentials cleared before start · egress proxy</span>'''
    trig = f'''<p style="margin: 0; font-size: 16px; line-height: 1.55"><span style="color: #9AA8C7">When</span> CI fails on a PR, <span style="color: #9AA8C7">run</span> <span style="color: color-mix(in oklab, var(--ac) 50%, white)">self-heal-v3</span>, <span style="color: #9AA8C7">at most</span> 3×/day <span style="color: #9AA8C7">under</span> $2.</p>
<span style="display: flex; align-items: center; gap: 8px; margin-top: 10px; font-family: {MONO}; font-size: 11.5px; color: #9AA8C7">{DOT}fired 2h ago · fixed in 4m 10s · $0.31</span>'''
    agent = f'''<pre style="margin: 0; overflow: hidden; padding: 14px; border-radius: 14px; border: 1px solid #1A2032; background: #080A11; font-family: {MONO}; font-size: 11.5px; line-height: 1.65; color: #E8EEFB"><span style="color: #6F7FA3">❯</span> syn eval trend esp --json
{{ <span style="color: #9AA8C7">"verifier"</span>: "sonnet", <span style="color: #9AA8C7">"score"</span>: <span style="color: #7FE3B8">89</span>,
  <span style="color: #9AA8C7">"judge"</span>: "opus", <span style="color: #9AA8C7">"cost_usd"</span>: <span style="color: #EBD9A8">0.52</span> }}</pre>'''
    tiles = [
        tile(p, 7, 2, 'Observe', 'Watch every run as it happens, down to the cent.', live, accent=True),
        tile(p, 5, 1, 'Measure', 'Replay real bugs against every model you use.', verdict),
        tile(p, 5, 1, 'Improve', 'Know which change made it better, and what it cost.', tr),
        tile(p, 4, 1, 'Isolate', 'Every phase in its own container.', iso),
        tile(p, 4, 1, 'Trigger', 'Agents that start themselves.', trig),
        tile(p, 4, 1, 'For agents', 'Agents query the same facts you see.', agent),
    ]
    return f'''<section aria-label="Product" style="box-sizing: border-box; width: 100%; max-width: 1320px; margin: 0 auto; padding: {'24px 16px 48px' if p else '40px 40px 120px'}">
{head(p, 'The platform', 'Everything an agent does, measured.', 'Not a wrapper around a chat window. Workflows, isolation, telemetry, evals and triggers, in one self-hosted stack.', center=not p)}
<div style="display: grid; grid-template-columns: {'minmax(0, 1fr)' if p else 'repeat(12, minmax(0, 1fr))'}; gap: {'12px' if p else '16px'}; margin-top: {'24px' if p else '56px'}">{''.join(tiles)}</div>
</section>'''


def compare(p):
    rows = [('What the agent did', 'Scroll back through a terminal', 'Every tool call, kept forever'),
            ('What it cost', 'Check the invoice next month', 'Per run, per phase, per token type'),
            ('Is it getting better', 'Gut feel', 'Judge scores and trends over time'),
            ('Where it ran', 'Your laptop, with your keys', 'A throwaway container'),
            ('Who starts it', 'You, every time', 'GitHub events, on a budget')]
    rr = ''.join(f'''<div style="display: grid; grid-template-columns: {'1fr' if p else '1.1fr 1fr 1.2fr'}; gap: {'4px' if p else '24px'}; padding: {'14px 0' if p else '18px 0'}; border-top: 1px solid #141A2A">
<span style="font-size: 15px; font-weight: 600">{a}</span><span style="font-size: 14px; color: #6F7FA3; {'text-decoration: line-through; text-decoration-color: #34406A' if True else ''}">{b}</span><span style="display: flex; align-items: center; gap: 8px; font-size: 14px; color: #E8EEFB"><svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="var(--ac)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3.5 8.5l3 3 6-7"></path></svg>{c}</span>
</div>''' for a, b, c in rows)
    return f'''<section aria-label="Why" style="border-top: 1px solid #10141F; border-bottom: 1px solid #10141F; background: {DOTGRID} 0 0 / 28px 28px, #080A11">
<div style="display: flex; flex-direction: {'column' if p else 'row'}; gap: {'24px' if p else '72px'}; box-sizing: border-box; max-width: 1320px; margin: 0 auto; padding: {'48px 16px' if p else '112px 40px'}">
<div style="{'' if p else 'flex: 0 0 420px'}">{head(p, 'Why a platform', 'Running agents is easy. Trusting them is not.', 'Syntropic137 is the difference between a demo and a team of agents you can depend on.')}</div>
<div style="flex: 1 1 auto; min-width: 0">{rr}</div>
</div>
</section>'''


def start(p):
    steps = [('Install', 'npx @syntropic137/setup init'), ('Run', 'syn workflow run research-package-v1 --task "…"'), ('Watch', 'open http://localhost:8137')]
    st = ''.join(f'<div style="display: flex; align-items: center; gap: 14px; padding: 14px 0; border-top: 1px solid #141A2A"><span style="display: flex; align-items: center; justify-content: center; flex-shrink: 0; width: 30px; height: 30px; border-radius: 9px; background: color-mix(in oklab, var(--ac) 18%, transparent); color: var(--ac); font-family: {MONO}; font-size: 13px; font-weight: 600">{i + 1}</span><span style="width: 64px; flex-shrink: 0; font-size: 15px; font-weight: 600">{t}</span><code style="min-width: 0; font-family: {MONO}; font-size: 12.5px; color: #C3CCE2; overflow-wrap: anywhere">{c}</code></div>' for i, (t, c) in enumerate(steps))
    return f'''<section id="start" aria-label="Get started" style="position: relative; overflow: hidden; background: radial-gradient(50% 70% at 50% 100%, color-mix(in oklab, var(--ac) 28%, transparent), transparent 70%), #06080E">
<div aria-hidden="true" style="position: absolute; inset: 0; background: {GRAIN}; pointer-events: none"></div>
<div style="position: relative; display: flex; flex-direction: {'column' if p else 'row'}; align-items: {'stretch' if p else 'center'}; gap: {'28px' if p else '80px'}; box-sizing: border-box; max-width: 1320px; margin: 0 auto; padding: {'56px 16px 32px' if p else '140px 40px 80px'}">
<div style="flex: 1 1 0; display: flex; flex-direction: column; gap: 22px">
<h2 class="glowtext" style="margin: 0; font-size: {'44px' if p else '84px'}; line-height: 0.95; font-weight: 600; letter-spacing: -0.045em">Stop babysitting agents.</h2>
<p style="margin: 0; font-size: {'16px' if p else '19px'}; line-height: 1.55; color: #9AA8C7; max-width: 520px">Self-hosted, MIT licensed, no account. Your keys, your data, your bill.</p>
{terminal(p)}
</div>
<div style="flex: 1 1 0; padding: {'4px 0' if p else '8px 0'}">{st}</div>
</div>
<div aria-hidden="true" style="position: relative; overflow: hidden; padding: 0 {'16px' if p else '40px'}; text-align: center; font-family: {ORB}; font-size: {'64px' if p else '220px'}; font-weight: 700; line-height: 0.8; letter-spacing: 0.02em; color: transparent; -webkit-text-stroke: 1px color-mix(in oklab, var(--ac) 40%, #1A2032); white-space: nowrap; transform: translateY(18%)">SYN137</div>
</section>'''


def footer(p):
    return v1.footer(p)


SCRIPT = r'''
class Component extends DCLogic {
renderVals() {
const st = this.state || {};
const copied = !!st.copied;
const copyInstall = () => {
try { if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText('npx @syntropic137/setup init').catch(() => {}); } catch (e) {}
this.setState({ copied: true });
};
return { accent: this.props.accent ?? '#4D80FF', copyInstall, copyLabel: copied ? 'Copied' : 'Copy' };
}
}
'''


def page(p):
    W, H = (390, 5600) if p else (1440, 5000)
    body = '\n'.join([hero(p), bento(p), story(p), compare(p), start(p), footer(p)])
    props = json.dumps({"accent": {"editor": "color", "default": "#4D80FF", "options": ["#4D80FF", "#4CC9F0", "#45E0A0", "#A78BFA"]}, "$preview": {"width": W, "height": H}})
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Syntropic137 landing v2{' (phone)' if p else ''}</title>
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


open(os.path.join(OUT, 'Landing.dc.html'), 'w').write(page(False))
open(os.path.join(OUT, 'PhoneLanding.dc.html'), 'w').write(page(True))
print('ok v2')
