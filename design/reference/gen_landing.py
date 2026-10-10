#!/usr/bin/env python3
"""Landing page boards (desktop + phone) for syntropic137.com, in the Skyline language."""
import os, math, json

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, 'project')
MONO = "'JetBrains Mono', ui-monospace, monospace"
SANS = "'Instrument Sans', 'Helvetica Neue', system-ui, sans-serif"
ORB = "'Orbitron', 'Eurostile', sans-serif"
AC = 'var(--ac)'
TOP = 'color-mix(in oklab, var(--ac) 58%, white)'
SIDE = 'color-mix(in oklab, var(--ac) 50%, black)'


def face(c, kind):
    if kind == 'top':
        return f'color-mix(in oklab, {c} 58%, white)'
    if kind == 'side':
        return f'color-mix(in oklab, {c} 50%, black)'
    return c


# ------------------------------------------------------------------ isometric city (hero art)
def city_svg(cols, rows, cw, aria):
    """Static isometric skyline: one block per day over ~10 weeks; height = activity."""
    hw, hh = cw / 2, cw / 4
    blocks = []
    for j in range(rows):
        for i in range(cols):
            k = j * cols + i
            # deterministic activity: rises toward the front-right (recent), with weekly rhythm
            base = 0.18 + 0.82 * ((i + j * 0.6) / (cols + rows * 0.6))
            wob = ((k * 37) % 11) / 11
            act = base * (0.45 + 0.55 * wob)
            if (k * 13) % 7 == 0:
                act *= 0.25  # quiet days
            h = 4 + act * cw * 2.3
            color = AC
            if k in (23, 51):
                color = '#FF6F61'
            elif k in (38,):
                color = '#E5B450'
            blocks.append((i, j, h, color, act))
    ox = rows * hw + 24
    oy = max(b[2] for b in blocks) + 24
    W = (cols + rows) * hw + 48
    H = oy + (cols + rows) * hh + 24
    parts = []
    for (i, j, h, color, act) in sorted(blocks, key=lambda b: (b[0] + b[1], b[0])):
        x = ox + (i - j) * hw
        y = oy + (i + j) * hh
        gap = cw * 0.08
        a, b = hw - gap, hh - gap / 2
        top = f'{x},{y - h - b} {x + a},{y - h} {x},{y - h + b} {x - a},{y - h}'
        left = f'{x - a},{y - h} {x},{y - h + b} {x},{y + b} {x - a},{y}'
        right = f'{x},{y - h + b} {x + a},{y - h} {x + a},{y} {x},{y + b}'
        op = 0.35 + 0.65 * min(1, act * 1.4)
        parts.append(f'<g opacity="{op:.2f}"><polygon points="{left}" style="fill: {face(color, "front")}"></polygon><polygon points="{right}" style="fill: {face(color, "side")}"></polygon><polygon points="{top}" style="fill: {face(color, "top")}"></polygon></g>')
    floor_pts = f'{ox},{oy - hh} {ox + cols * hw},{oy + cols * hh - hh} {ox + (cols - rows) * hw},{oy + (cols + rows) * hh - hh} {ox - rows * hw},{oy + rows * hh - hh}'
    return (f'<svg viewBox="0 0 {W:.0f} {H:.0f}" role="img" aria-label="{aria}" style="display: block; width: 100%; height: auto; overflow: visible">'
            f'<polygon points="{floor_pts}" fill="none" stroke="#1A2032" stroke-width="1"></polygon>'
            + ''.join(parts) + '</svg>')


def logo(size=26):
    return f'''<svg width="{size}" height="{size}" viewBox="0 0 24 24" aria-hidden="true">
<polygon points="12,3 21,7.5 12,12 3,7.5" style="fill: {TOP}"></polygon>
<polygon points="3,7.5 12,12 12,21.5 3,17" style="fill: {AC}"></polygon>
<polygon points="12,12 21,7.5 21,17 12,21.5" style="fill: {SIDE}"></polygon>
</svg>'''


def chip(text, icon=''):
    return f'<span style="display: flex; align-items: center; gap: 7px; height: 30px; padding: 0 12px; border-radius: 15px; border: 1px solid #1A2032; background: #0D101A; font-size: 12.5px; color: #C3CCE2; white-space: nowrap">{icon}{text}</span>'


DOT = '<span aria-hidden="true" style="width: 6px; height: 6px; border-radius: 50%; background: var(--ac); box-shadow: 0 0 0 3px color-mix(in oklab, var(--ac) 24%, transparent)"></span>'
ARROW = '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 8h10M9 4l4 4-4 4"></path></svg>'
COPY = '<svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" aria-hidden="true"><rect x="5.5" y="5.5" width="8" height="8" rx="1.5"></rect><path d="M10.5 5.5V3.5a1 1 0 0 0-1-1h-6a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2"></path></svg>'
GH = '<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M8 .2a8 8 0 0 0-2.53 15.59c.4.07.55-.17.55-.38v-1.35c-2.23.48-2.7-1.07-2.7-1.07-.36-.92-.89-1.17-.89-1.17-.73-.5.05-.49.05-.49.8.06 1.23.83 1.23.83.71 1.22 1.87.87 2.33.66.07-.52.28-.87.5-1.07-1.78-.2-3.65-.89-3.65-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.6 7.6 0 0 1 4 0c1.53-1.03 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.28.82 2.15 0 3.07-1.87 3.75-3.66 3.95.29.25.54.73.54 1.48v2.2c0 .21.15.46.55.38A8 8 0 0 0 8 .2z"></path></svg>'


def eyebrow(t):
    return f'<span style="font-family: {MONO}; font-size: 11.5px; letter-spacing: 0.14em; text-transform: uppercase; color: color-mix(in oklab, var(--ac) 55%, white)">{t}</span>'


# ------------------------------------------------------------------ section builders
def nav(p):
    links = '' if p else f'''<nav aria-label="Site" style="display: flex; align-items: center; gap: 4px; font-size: 14px">
<a class="ghost" href="#" style="padding: 8px 12px; border-radius: 10px; color: #9AA8C7; text-decoration: none">Docs</a>
<a class="ghost" href="#" style="padding: 8px 12px; border-radius: 10px; color: #9AA8C7; text-decoration: none">CLI</a>
<a class="ghost" href="#" style="padding: 8px 12px; border-radius: 10px; color: #9AA8C7; text-decoration: none">API</a>
<a class="ghost" href="#" style="padding: 8px 12px; border-radius: 10px; color: #9AA8C7; text-decoration: none">Docs for agents</a>
</nav>'''
    right = f'''<div style="display: flex; align-items: center; gap: 8px">
<a class="ghost" href="https://github.com/syntropic137/syntropic137" aria-label="GitHub" style="display: flex; align-items: center; gap: 8px; height: {'44px' if p else '38px'}; padding: 0 {'12px' if p else '14px'}; border-radius: 12px; border: 1px solid #1A2032; color: #E8EEFB; text-decoration: none; font-size: 13.5px">{GH}{'' if p else 'GitHub'}</a>
<a href="#start" style="display: flex; align-items: center; gap: 7px; height: {'44px' if p else '38px'}; padding: 0 16px; border-radius: 12px; background: var(--ac); color: #FFFFFF; text-decoration: none; font-size: 13.5px; font-weight: 600">Get started</a>
</div>'''
    return f'''<header style="display: flex; align-items: center; justify-content: space-between; gap: 16px; box-sizing: border-box; width: 100%; max-width: 1240px; margin: 0 auto; padding: {'12px 16px' if p else '20px 40px'}">
<a href="#" style="display: flex; align-items: center; gap: 10px; text-decoration: none">{logo(28 if not p else 26)}<span style="font-family: {ORB}; font-size: {'13px' if p else '15px'}; font-weight: 600; letter-spacing: 0.06em; color: #E8EEFB">Syntropic<span style="color: var(--ac)">137</span></span></a>
{links}
{right}
</header>'''


def install_box(p):
    return f'''<div style="display: flex; flex-direction: column; gap: 8px; {'width: 100%' if p else 'max-width: 520px'}">
<div style="display: flex; align-items: center; gap: 10px; box-sizing: border-box; width: 100%; min-height: 54px; padding: 6px 6px 6px 16px; border-radius: 16px; border: 1px solid #283048; background: #0A0C14; box-shadow: inset 0 1px 0 rgba(255,255,255,0.04)">
<span aria-hidden="true" style="font-family: {MONO}; font-size: 14px; color: #6F7FA3">$</span>
<code style="flex: 1 1 auto; min-width: 0; font-family: {MONO}; font-size: {'13px' if p else '14.5px'}; color: #E8EEFB; white-space: nowrap; overflow: hidden; text-overflow: ellipsis">npx @syntropic137/setup init</code>
<button type="button" onClick="{{{{copyInstall}}}}" aria-label="Copy install command" style="display: flex; align-items: center; gap: 7px; height: {'44px' if p else '40px'}; padding: 0 14px; border: 0; border-radius: 11px; background: var(--ac); color: #FFFFFF; font-size: 13.5px; font-weight: 600; cursor: pointer; white-space: nowrap">{COPY}{{{{copyLabel}}}}</button>
</div>
<span style="font-size: 12.5px; color: #6F7FA3">Needs Node 18+ and Docker. The dashboard opens at localhost:8137.</span>
</div>'''


def floating_cards(p):
    if p:
        return ''
    card = 'position: absolute; display: flex; flex-direction: column; gap: 6px; padding: 12px 14px; border-radius: 14px; border: 1px solid #283048; background: color-mix(in oklab, #0D101A 88%, transparent); backdrop-filter: blur(8px); box-shadow: 0 18px 40px rgba(0,0,0,0.45)'
    return f'''<div style="{card}; left: 2%; top: 6%">
<span style="display: flex; align-items: center; gap: 8px; font-family: {MONO}; font-size: 11px; color: #9AA8C7">{DOT}running · exec-66e14f23</span>
<span style="font-size: 14px; font-weight: 600">Deep Dive Analysis</span>
<span style="display: flex; gap: 3px"><span style="width: 44px; height: 6px; border-radius: 3px; background: var(--ac)"></span><span style="width: 44px; height: 6px; border-radius: 3px; background: color-mix(in oklab, var(--ac) 45%, #151A2A)"></span><span style="width: 44px; height: 6px; border-radius: 3px; background: #151A2A"></span></span>
</div>
<div style="{card}; right: 0; top: 34%">
<span style="font-family: {MONO}; font-size: 11px; color: #9AA8C7">this run</span>
<span style="display: flex; align-items: baseline; gap: 10px"><span style="font-size: 20px; font-weight: 600; letter-spacing: -0.02em">$0.104</span><span style="font-family: {MONO}; font-size: 12px; color: #9AA8C7">213k tokens</span></span>
<span style="display: flex; height: 6px; width: 168px; border-radius: 3px; overflow: hidden; gap: 2px"><span style="flex: 5; background: #4C8DEA"></span><span style="flex: 2; background: #E0703A"></span><span style="flex: 2; background: #9085E9"></span><span style="flex: 1; background: #C98500"></span></span>
</div>
<div style="{card}; left: 10%; bottom: 4%">
<span style="font-family: {MONO}; font-size: 11px; color: #9AA8C7">eval · shared-esp-stream</span>
<span style="display: flex; align-items: baseline; gap: 8px"><span style="font-size: 20px; font-weight: 600">89</span><span style="font-size: 12px; color: #9AA8C7">/100 · judged by claude-opus-5-5</span></span>
<span style="font-size: 12px; font-weight: 600; color: #7FE3B8">Better and cheaper than 2 weeks ago</span>
</div>'''


def hero(p):
    h1 = '40px' if p else '68px'
    art = city_svg(14, 7, 34 if not p else 30, 'An isometric city of blocks: one block per day of agent runs, taller when more ran')
    text = f'''<div style="display: flex; flex-direction: column; gap: {'18px' if p else '26px'}; min-width: 0; {'' if p else 'flex: 1 1 520px; max-width: 600px'}">
<div style="display: flex; flex-wrap: wrap; gap: 8px">{chip('Open source · MIT', '')}{chip('Self-hosted', '')}{chip('Claude Code + Codex', '')}</div>
<h1 style="margin: 0; font-size: {h1}; line-height: 1.02; font-weight: 600; letter-spacing: -0.035em; text-wrap: balance">Get out of the loop. <span style="color: color-mix(in oklab, var(--ac) 60%, white)">Get into orchestration.</span></h1>
<p style="margin: 0; font-size: {'16px' if p else '19px'}; line-height: 1.55; color: #9AA8C7; max-width: 540px">Run Claude Code and Codex agents as repeatable workflows in isolated Docker workspaces. Every tool call, token, dollar and artifact is recorded, so you can see your agents getting better with every run.</p>
{install_box(p)}
<div style="display: flex; flex-wrap: wrap; align-items: center; gap: 10px 18px; font-size: 14px">
<a href="#" style="display: flex; align-items: center; gap: 6px; font-weight: 600; text-decoration: none">Read the docs {ARROW}</a>
<a href="#" style="display: flex; align-items: center; gap: 6px; color: #9AA8C7; text-decoration: none">See the dashboard {ARROW}</a>
</div>
</div>'''
    visual = f'''<div style="position: relative; {'width: 100%; margin-top: 8px' if p else 'flex: 1 1 560px; min-width: 0; padding: 40px 0'}">
<div aria-hidden="true" style="position: absolute; inset: -10% -6%; background: radial-gradient(50% 50% at 55% 55%, color-mix(in oklab, var(--ac) 22%, transparent), transparent 70%)"></div>
<div style="position: relative">{art}</div>
{floating_cards(p)}
<span style="position: relative; display: block; margin-top: 10px; text-align: center; font-family: {MONO}; font-size: 11px; color: #6F7FA3">Ten weeks of runs. One block per day, taller when more ran. Coral failed, amber errored.</span>
</div>'''
    return f'''<section aria-label="Hero" style="display: flex; {'flex-direction: column' if p else 'align-items: center'}; gap: {'28px' if p else '48px'}; box-sizing: border-box; width: 100%; max-width: 1240px; margin: 0 auto; padding: {'20px 16px 40px' if p else '40px 40px 72px'}">
{text}
{visual}
</section>'''


def works_with(p):
    items = ['Claude Code', 'OpenAI Codex', 'GitHub', 'Docker', 'Postgres + TimescaleDB', 'Any repo']
    chips = ''.join(f'<span style="font-family: {MONO}; font-size: 13px; color: #9AA8C7; white-space: nowrap">{t}</span>' for t in items)
    return f'''<div style="border-top: 1px solid #12172A; border-bottom: 1px solid #12172A; background: #0B0E17">
<div style="display: flex; flex-wrap: wrap; align-items: center; justify-content: center; gap: {'10px 18px' if p else '12px 40px'}; box-sizing: border-box; max-width: 1240px; margin: 0 auto; padding: {'18px 16px' if p else '22px 40px'}">
<span style="font-size: 12.5px; color: #6F7FA3">Works with</span>{chips}
</div>
</div>'''


def section_head(p, eb, title, sub):
    return f'''<div style="display: flex; flex-direction: column; gap: 12px; max-width: 760px">
{eyebrow(eb)}
<h2 style="margin: 0; font-size: {'30px' if p else '44px'}; line-height: 1.08; font-weight: 600; letter-spacing: -0.03em; text-wrap: balance">{title}</h2>
<p style="margin: 0; font-size: {'15.5px' if p else '17px'}; line-height: 1.6; color: #9AA8C7">{sub}</p>
</div>'''


def loop(p):
    tabs = f'''<div role="tablist" aria-label="The loop" style="display: grid; grid-template-columns: {'repeat(2, minmax(0, 1fr))' if p else 'repeat(4, minmax(0, 1fr))'}; gap: 8px">
<sc-for list="{{{{steps}}}}" as="s" hint-placeholder-count="4">
<button type="button" role="tab" aria-selected="{{{{s.on}}}}" onClick="{{{{s.pick}}}}" onMouseEnter="{{{{s.pick}}}}" style="display: flex; flex-direction: column; align-items: flex-start; gap: 6px; padding: {'14px' if p else '18px 20px'}; border-radius: 16px; border: 1px solid {{{{s.bd}}}}; background: {{{{s.bg}}}}; color: #E8EEFB; text-align: left; cursor: pointer; font-family: inherit">
<span style="font-family: {MONO}; font-size: 11px; color: {{{{s.numFg}}}}">{{{{s.num}}}}</span>
<span style="font-size: {'17px' if p else '20px'}; font-weight: 600; letter-spacing: -0.015em">{{{{s.name}}}}</span>
<span style="font-size: 13px; line-height: 1.45; color: #9AA8C7">{{{{s.line}}}}</span>
</button>
</sc-for>
</div>'''
    panels = []
    # 1 Run: phases pipeline
    run = f'''<div style="display: flex; flex-direction: column; gap: 10px">
<span style="font-family: {MONO}; font-size: 12px; color: #9AA8C7">syn workflow run research-workflow-v2 --task "event sourcing patterns"</span>
<div style="display: flex; flex-direction: {'column' if p else 'row'}; gap: 10px">
''' + ''.join(f'''<div style="flex: 1 1 0; display: flex; flex-direction: column; gap: 8px; padding: 14px; border-radius: 14px; border: 1px solid #1A2032; background: #0A0C14">
<span style="display: flex; align-items: center; justify-content: space-between; gap: 8px"><span style="font-size: 14px; font-weight: 600">{n}</span><span style="height: 22px; padding: 0 9px; border-radius: 11px; background: {bg}; color: {fg}; font-size: 11.5px; font-weight: 600; line-height: 22px">{s}</span></span>
<span style="font-family: {MONO}; font-size: 11.5px; color: #9AA8C7">{m} · container {c}</span>
<span style="height: 6px; border-radius: 3px; background: {bar}"></span>
</div>''' for n, s, bg, fg, m, c, bar in [
        ('Discovery', 'done', 'color-mix(in oklab, var(--ac) 18%, transparent)', 'color-mix(in oklab, var(--ac) 40%, white)', 'claude-opus-5-5', 'ws-1', 'var(--ac)'),
        ('Deep dive', 'running', '#151A2A', '#E8EEFB', 'gpt-5.6-sol', 'ws-2', 'linear-gradient(90deg, var(--ac) 55%, #151A2A 55%)'),
        ('Synthesis', 'queued', '#151A2A', '#9AA8C7', 'claude-sonnet-5-5', 'ws-3', '#151A2A')]) + '''
</div>
<span style="font-size: 13px; color: #9AA8C7">Each phase runs in its own throwaway container, with credentials cleared before the agent starts and outbound traffic going through an egress proxy.</span>
</div>'''
    # 2 Observe: usage band + operations
    obs = f'''<div style="display: flex; flex-direction: column; gap: 12px">
<div style="display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 18px"><span style="font-size: 28px; font-weight: 600; letter-spacing: -0.02em">$0.2162</span><span style="font-family: {MONO}; font-size: 12.5px; color: #9AA8C7">1.12M tokens · 214 tool calls · 6m 12s</span></div>
<div style="display: flex; height: 18px; gap: 2px">
<span style="flex: 52; border-radius: 4px 0 0 4px; background: #4C8DEA"></span><span style="flex: 18; background: #E0703A"></span><span style="flex: 21; background: #9085E9"></span><span style="flex: 9; border-radius: 0 4px 4px 0; background: #C98500"></span>
</div>
<div style="display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 12px; color: #9AA8C7">
<span style="display: flex; align-items: center; gap: 6px"><span style="width: 9px; height: 9px; border-radius: 2px; background: #4C8DEA"></span>Cache read</span>
<span style="display: flex; align-items: center; gap: 6px"><span style="width: 9px; height: 9px; border-radius: 2px; background: #E0703A"></span>Cache write</span>
<span style="display: flex; align-items: center; gap: 6px"><span style="width: 9px; height: 9px; border-radius: 2px; background: #9085E9"></span>Output</span>
<span style="display: flex; align-items: center; gap: 6px"><span style="width: 9px; height: 9px; border-radius: 2px; background: #C98500"></span>Input</span>
</div>
<div style="display: flex; flex-direction: column; gap: 2px; padding: 8px; border-radius: 14px; border: 1px solid #1A2032; background: #0A0C14; font-family: {MONO}; font-size: 12px">
''' + ''.join(f'<span style="display: grid; grid-template-columns: 64px minmax(0,1fr) 64px; gap: 10px; padding: 6px 8px; color: {c}"><span style="color: #6F7FA3">{t}</span><span style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis">{a}</span><span style="text-align: right; color: #9AA8C7">{d}</span></span>'
                for t, a, d, c in [('14:02:11', 'Read src/domain/aggregate.py', '42ms', '#E8EEFB'), ('14:02:14', 'Grep "apply_event" -n', '118ms', '#E8EEFB'), ('14:02:19', 'Bash pytest -q tests/domain', '8.4s', '#E8EEFB'), ('14:02:31', 'Write docs/event-sourcing.md', '12ms', '#E8EEFB')]) + '''
</div>
</div>'''
    # 3 Measure: verdict blocks
    cells = []
    V = [['P', 'P', 'P', 'U'], ['P', 'F', 'P', 'U'], ['P', 'P', 'F', 'U'], ['P', 'P', 'P', 'U'], ['P', 'F', 'F', 'U'], ['F', 'F', 'E', 'U']]
    look = {'P': ('var(--ac)', 24), 'F': ('#FF6F61', 9), 'E': ('#E5B450', 9), 'U': ('#4A567A', 3)}
    for r in V:
        row = ''
        for v in r:
            c, h = look[v]
            y = 34 - h
            row += f'<svg width="44" height="46" viewBox="0 0 56 46" aria-hidden="true"><polygon points="12,{y} 28,{y + 8} 28,42 12,34" style="fill: {face(c, "front")}"></polygon><polygon points="28,{y + 8} 44,{y} 44,34 28,42" style="fill: {face(c, "side")}"></polygon><polygon points="28,{y - 8} 44,{y} 28,{y + 8} 12,{y}" style="fill: {face(c, "top")}"></polygon></svg>'
        cells.append(f'<div style="display: flex; gap: 2px">{row}</div>')
    meas = f'''<div style="display: flex; flex-direction: {'column' if p else 'row'}; gap: 20px; align-items: flex-start">
<div aria-label="Verdict board: 6 known bugs by 4 verifier models" style="display: flex; flex-direction: column; gap: 0">{''.join(cells)}</div>
<div style="display: flex; flex-direction: column; gap: 10px; min-width: 0">
<span style="font-size: 15px; line-height: 1.55; color: #C3CCE2">Replay real bugs from your history against every model you use. A judge model scores each run out of 100, so you know which verifier actually catches regressions, not which one sounds confident.</span>
<div style="display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: 12px; color: #9AA8C7">
<span style="display: flex; align-items: center; gap: 6px"><span style="width: 8px; height: 14px; border-radius: 2px; background: var(--ac)"></span>Caught</span>
<span style="display: flex; align-items: center; gap: 6px"><span style="width: 8px; height: 7px; border-radius: 2px; background: #FF6F61"></span>Missed</span>
<span style="display: flex; align-items: center; gap: 6px"><span style="width: 8px; height: 7px; border-radius: 2px; background: #E5B450"></span>Errored</span>
<span style="display: flex; align-items: center; gap: 6px"><span style="width: 8px; height: 3px; border-radius: 2px; background: #4A567A"></span>Not scored</span>
</div>
</div>
</div>'''
    # 4 Improve: mini trend
    def path(vals, h=120, w=560):
        n = len(vals)
        return ' '.join(('M' if i == 0 else 'L') + f'{i * w / (n - 1):.1f} {h - v / 100 * h:.1f}' for i, v in enumerate(vals))
    imp = f'''<div style="display: flex; flex-direction: column; gap: 12px">
<div style="display: grid; grid-template-columns: {'1fr 1fr' if p else 'repeat(3, minmax(0, 1fr))'}; gap: 10px">
<div style="padding: 12px 14px; border-radius: 14px; border: 1px solid #1A2032; background: #0A0C14"><span style="font-size: 12px; color: #9AA8C7">Quality score</span><div style="font-size: 24px; font-weight: 600">87<span style="font-size: 12px; color: #6F7FA3">/100</span></div><span style="font-family: {MONO}; font-size: 11px; color: #7FE3B8">+24 in 2 weeks</span></div>
<div style="padding: 12px 14px; border-radius: 14px; border: 1px solid #1A2032; background: #0A0C14"><span style="font-size: 12px; color: #9AA8C7">Cost per run</span><div style="font-size: 24px; font-weight: 600">$0.52</div><span style="font-family: {MONO}; font-size: 11px; color: #9AA8C7">flat</span></div>
{'' if p else f'<div style="padding: 12px 14px; border-radius: 14px; border: 1px solid #1A2032; background: #0A0C14"><span style="font-size: 12px; color: #9AA8C7">Time to verdict</span><div style="font-size: 24px; font-weight: 600">3m 57s</div><span style="font-family: {MONO}; font-size: 11px; color: #7FE3B8">−8s</span></div>'}
</div>
<svg viewBox="0 0 560 120" preserveAspectRatio="none" aria-label="Quality score rising from 48 to 89 over 30 days" role="img" style="width: 100%; height: {'110px' if p else '130px'}; overflow: visible">
<line x1="0" x2="560" y1="36" y2="36" stroke="color-mix(in oklab, var(--ac) 55%, #283048)" stroke-dasharray="4 4" vector-effect="non-scaling-stroke"></line>
<line x1="0" x2="560" y1="120" y2="120" stroke="#283048" vector-effect="non-scaling-stroke"></line>
<path d="{path([48, 55, 72, 63, 66, 78, 84, 87, 89])}" fill="none" stroke="#199E70" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"></path>
<path d="{path([80, 78, 64, 76, 62, 73, 58])}" fill="none" stroke="#9085E9" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke" opacity="0.7"></path>
</svg>
<span style="font-size: 13px; color: #9AA8C7"><span style="color: #E8EEFB; font-weight: 600">sonnet</span> climbed from 48 to 89 after the verify prompt change, at the same cost. <span style="color: #E8EEFB; font-weight: 600">sol</span> is slipping. You see it the morning it happens, not a month later.</span>
</div>'''
    panes = [run, obs, meas, imp]
    blocks = ''.join(f'<sc-if value="{{{{show{i}}}}}" hint-placeholder-val="{{{{ {str(i == 0).lower()} }}}}">{pane}</sc-if>' for i, pane in enumerate(panes))
    return f'''<section aria-label="How it works" style="display: flex; flex-direction: column; gap: {'24px' if p else '36px'}; box-sizing: border-box; width: 100%; max-width: 1240px; margin: 0 auto; padding: {'56px 16px' if p else '112px 40px'}">
{section_head(p, 'How it works', 'Run. Observe. Measure. Improve.', 'Every run goes around the same loop, and every lap leaves data behind. That record is what makes the next run better.')}
{tabs}
<div role="tabpanel" style="padding: {'18px' if p else '28px'}; border-radius: 22px; border: 1px solid #1A2032; background: radial-gradient(60% 120% at 100% 0%, color-mix(in oklab, var(--ac) 10%, transparent), transparent 70%), #0D101A; box-shadow: inset 0 1px 0 rgba(255,255,255,0.04)">
{blocks}
</div>
</section>'''


def agents(p):
    code = '''<span style="color: #6F7FA3">$</span> syn eval trend shared-esp-stream --json
<span style="color: #6F7FA3">[</span>
  { <span style="color: #9AA8C7">"date"</span>: "2026-10-06", <span style="color: #9AA8C7">"verifier"</span>: "claude-sonnet-5-5",
    <span style="color: #9AA8C7">"judge"</span>: "claude-opus-5-5", <span style="color: #9AA8C7">"score"</span>: <span style="color: #7FE3B8">89</span>,
    <span style="color: #9AA8C7">"verdict"</span>: "PASS", <span style="color: #9AA8C7">"cost_usd"</span>: <span style="color: #EBD9A8">0.52</span>, <span style="color: #9AA8C7">"tokens"</span>: <span style="color: #EBD9A8">172000</span> },
  ...
<span style="color: #6F7FA3">]</span>'''
    items = [
        ('Docs written for agents', 'Every page is also published as plain text for models, alongside an llms.txt index.'),
        ('A CLI for every screen', 'Anything you can see in the dashboard, an agent can query as JSON.'),
        ('Claude Code plugin', 'Start workflows, read runs and check evals from inside your coding session.'),
    ]
    lis = ''.join(f'<div style="display: flex; flex-direction: column; gap: 4px; padding: 14px 0; border-top: 1px solid #1A2032"><span style="font-size: 16px; font-weight: 600">{a}</span><span style="font-size: 14px; line-height: 1.55; color: #9AA8C7">{b}</span></div>' for a, b in items)
    return f'''<section aria-label="Built for agents" style="box-sizing: border-box; width: 100%; max-width: 1240px; margin: 0 auto; padding: {'24px 16px 56px' if p else '24px 40px 112px'}">
<div style="display: flex; flex-direction: {'column' if p else 'row'}; gap: {'24px' if p else '56px'}; align-items: {'stretch' if p else 'center'}">
<div style="display: flex; flex-direction: column; gap: 18px; {'' if p else 'flex: 1 1 0'}">
{section_head(p, 'Built for agents too', 'Your agents read the same data you do.', 'Syntropic137 is run by people and by agents. The dashboard, CLI and API all serve the same facts, so an agent can ask which model gives the best quality per dollar and get a real answer.')}
<div>{lis}</div>
</div>
<pre style="{'' if p else 'flex: 1 1 0; '}margin: 0; overflow-x: auto; padding: {'16px' if p else '24px'}; border-radius: 20px; border: 1px solid #1A2032; background: #080A11; font-family: {MONO}; font-size: {'11.5px' if p else '13px'}; line-height: 1.7; color: #E8EEFB; box-shadow: inset 0 1px 0 rgba(255,255,255,0.04)">{code}</pre>
</div>
</section>'''


def triggers(p):
    return f'''<section aria-label="Triggers" style="border-top: 1px solid #12172A; border-bottom: 1px solid #12172A; background: radial-gradient(50% 100% at 0% 50%, color-mix(in oklab, var(--ac) 10%, transparent), transparent 70%), #0B0E17">
<div style="display: flex; flex-direction: {'column' if p else 'row'}; gap: {'20px' if p else '56px'}; align-items: {'stretch' if p else 'center'}; box-sizing: border-box; max-width: 1240px; margin: 0 auto; padding: {'48px 16px' if p else '88px 40px'}">
<div style="{'' if p else 'flex: 1 1 0'}">{section_head(p, 'Triggers', 'Agents that start themselves.', 'Connect a GitHub App and workflows fire on real events: a failing check, a review comment, a new issue. Every trigger has a budget, a cooldown and a log.')}</div>
<div style="{'' if p else 'flex: 1 1 0; '}display: flex; flex-direction: column; gap: 10px; padding: {'18px' if p else '24px'}; border-radius: 20px; border: 1px solid #1A2032; background: #0D101A">
<span style="display: flex; align-items: center; gap: 8px; font-family: {MONO}; font-size: 11.5px; color: #9AA8C7">{DOT}self-heal-ci · active</span>
<p style="margin: 0; font-size: {'17px' if p else '20px'}; line-height: 1.5; letter-spacing: -0.01em"><span style="color: #9AA8C7">When</span> CI fails on a pull request <span style="color: #9AA8C7">in</span> <span style="font-family: {MONO}; font-size: 0.85em">syntropic137/syntropic137</span>, <span style="color: #9AA8C7">run</span> <span style="color: color-mix(in oklab, var(--ac) 50%, white)">self-heal-v3</span> <span style="color: #9AA8C7">at most</span> 3 times a day, <span style="color: #9AA8C7">under</span> $2.00.</p>
<span style="font-size: 13px; color: #9AA8C7">Last fired 2h ago · fixed in 4m 10s · $0.31</span>
</div>
</div>
</section>'''


def selfhost(p):
    steps = [('1', 'Install', 'npx @syntropic137/setup init', 'Checks Docker, generates secrets and starts the stack.'),
             ('2', 'Run a workflow', 'syn workflow run research-package-v1 --task "…"', 'Starter workflows ship in the repo, or write your own in YAML.'),
             ('3', 'Watch it live', 'open http://localhost:8137', 'Every phase, tool call and dollar, as it happens.')]
    cards = ''.join(f'''<div style="display: flex; flex-direction: column; gap: 10px; padding: 20px; border-radius: 18px; border: 1px solid #1A2032; background: #0D101A; min-width: 0">
<span style="display: flex; align-items: center; justify-content: center; width: 32px; height: 32px; border-radius: 10px; background: color-mix(in oklab, var(--ac) 16%, transparent); color: var(--ac); font-family: {MONO}; font-weight: 600">{n}</span>
<span style="font-size: 17px; font-weight: 600">{t}</span>
<code style="font-family: {MONO}; font-size: 12px; color: #C3CCE2; overflow-wrap: anywhere">{c}</code>
<span style="font-size: 13.5px; line-height: 1.5; color: #9AA8C7">{d}</span>
</div>''' for n, t, c, d in steps)
    facts = [('Yours', 'Runs on your machine or server. Your keys, your data, your bill.'),
             ('MIT licensed', 'Read it, fork it, ship it. No usage caps, no seat pricing.'),
             ('Isolated by default', 'Throwaway containers, cleared credentials, egress proxies.'),
             ('Nothing is lost', 'An immutable event store keeps every decision forever.')]
    fl = ''.join(f'<div style="display: flex; flex-direction: column; gap: 4px; min-width: 0"><span style="font-size: 15px; font-weight: 600">{a}</span><span style="font-size: 13.5px; line-height: 1.5; color: #9AA8C7">{b}</span></div>' for a, b in facts)
    return f'''<section id="start" aria-label="Self-host" style="display: flex; flex-direction: column; gap: {'24px' if p else '36px'}; box-sizing: border-box; width: 100%; max-width: 1240px; margin: 0 auto; padding: {'56px 16px' if p else '112px 40px'}">
{section_head(p, 'Self-hosted, open source', 'Up and running in five minutes.', 'One command installs the whole stack with Docker Compose. No account, no cloud, no YAML to write first.')}
<div style="display: grid; grid-template-columns: {'minmax(0, 1fr)' if p else 'repeat(3, minmax(0, 1fr))'}; gap: 12px">{cards}</div>
<div style="display: grid; grid-template-columns: {'repeat(2, minmax(0, 1fr))' if p else 'repeat(4, minmax(0, 1fr))'}; gap: {'18px 16px' if p else '24px'}; padding-top: 8px">{fl}</div>
</section>'''


def final_cta(p):
    return f'''<section aria-label="Get started" style="box-sizing: border-box; width: 100%; max-width: 1240px; margin: 0 auto; padding: {'0 16px 56px' if p else '0 40px 112px'}">
<div style="display: flex; flex-direction: {'column' if p else 'row'}; align-items: {'stretch' if p else 'center'}; justify-content: space-between; gap: 24px; padding: {'24px 20px' if p else '48px'}; border-radius: 28px; border: 1px solid color-mix(in oklab, var(--ac) 35%, #1A2032); background: radial-gradient(60% 140% at 100% 0%, color-mix(in oklab, var(--ac) 26%, transparent), transparent 70%), #0D101A">
<div style="display: flex; flex-direction: column; gap: 10px; max-width: 520px">
<h2 style="margin: 0; font-size: {'28px' if p else '40px'}; line-height: 1.08; font-weight: 600; letter-spacing: -0.03em">Stop babysitting agents.</h2>
<p style="margin: 0; font-size: 16px; line-height: 1.55; color: #9AA8C7">Give them workflows, watch the numbers, and let the data tell you what to change.</p>
</div>
{install_box(p)}
</div>
</section>'''


def footer(p):
    cols = [('Product', ['Docs', 'CLI reference', 'API reference', 'Docs for agents']),
            ('Guides', ['Getting started', 'Workflows', 'Evals', 'Self-hosting']),
            ('Community', ['GitHub', 'X', 'Changelog', 'Security'])]
    cs = ''.join(f'<div style="display: flex; flex-direction: column; gap: 10px"><span style="font-family: {MONO}; font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; color: #6F7FA3">{h}</span>' + ''.join(f'<a href="#" style="font-size: 14px; color: #9AA8C7; text-decoration: none">{x}</a>' for x in xs) + '</div>' for h, xs in cols)
    return f'''<footer style="border-top: 1px solid #12172A">
<div style="display: flex; flex-direction: {'column' if p else 'row'}; justify-content: space-between; gap: 32px; box-sizing: border-box; max-width: 1240px; margin: 0 auto; padding: {'32px 16px 40px' if p else '48px 40px 56px'}">
<div style="display: flex; flex-direction: column; gap: 12px; max-width: 320px">
<span style="display: flex; align-items: center; gap: 10px">{logo(24)}<span style="font-family: {ORB}; font-size: 13px; font-weight: 600; letter-spacing: 0.06em">Syntropic<span style="color: var(--ac)">137</span></span></span>
<span style="font-size: 13.5px; line-height: 1.5; color: #6F7FA3">The agentic engineering platform. MIT licensed.</span>
</div>
<div style="display: grid; grid-template-columns: repeat({2 if p else 3}, minmax(0, 1fr)); gap: {'24px 16px' if p else '24px 72px'}">{cs}</div>
</div>
</footer>'''


SCRIPT = r'''
class Component extends DCLogic {
renderVals() {
const st = this.state || {};
const step = typeof st.step === 'number' ? st.step : 0;
const STEPS = [
['Run', 'Repeatable multi-phase workflows on Claude Code or Codex, each phase in its own container.'],
['Observe', 'Every tool call, token and dollar, live, for every phase and session.'],
['Measure', 'Evals replay real bugs; a judge model scores every run out of 100.'],
['Improve', 'Trends show which change made agents better, faster or cheaper.']
];
const steps = STEPS.map((s, i) => ({
num: '0' + (i + 1),
name: s[0],
line: s[1],
on: i === step ? 'true' : 'false',
bd: i === step ? 'color-mix(in oklab, var(--ac) 60%, #1A2032)' : '#1A2032',
bg: i === step ? '#121729' : '#0D101A',
numFg: i === step ? 'color-mix(in oklab, var(--ac) 55%, white)' : '#6F7FA3',
pick: () => this.setState({ step: i })
}));
const copied = !!st.copied;
const copyInstall = () => {
try { if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText('npx @syntropic137/setup init').catch(() => {}); } catch (e) {}
this.setState({ copied: true });
};
return {
accent: this.props.accent ?? '#4D80FF',
steps,
show0: step === 0, show1: step === 1, show2: step === 2, show3: step === 3,
copyInstall,
copyLabel: copied ? 'Copied' : 'Copy'
};
}
}
'''


def page(p):
    W, H = (390, 5200) if p else (1440, 4300)
    body = '\n'.join([nav(p), hero(p), works_with(p), loop(p), agents(p), triggers(p), selfhost(p), final_cta(p), footer(p)])
    props = json.dumps({"accent": {"editor": "color", "default": "#4D80FF", "options": ["#4D80FF", "#4CC9F0", "#45E0A0", "#A78BFA"]}, "$preview": {"width": W, "height": H}})
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Syntropic137 landing{' (phone)' if p else ''}</title>
<script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=Orbitron:wght@500;600;700&display=swap">
<style>
:root{{--ac:#4D80FF}}
body{{margin:0;background:#080A11}}
a{{color:#E8EEFB}}a:hover{{color:#FFFFFF}}
.ghost:hover{{background:#151A2A}}
button{{font-family:inherit}}
:focus-visible{{outline:2px solid var(--ac);outline-offset:2px}}
</style>
</helmet>
<div style="--ac: {{{{accent}}}}; display: flex; flex-direction: column; min-height: 100vh; background: radial-gradient(70% 40% at 70% 0%, color-mix(in oklab, var(--ac) 12%, transparent), transparent 70%), #080A11; color: #E8EEFB; font-family: {SANS}; font-size: 14px; line-height: 1.45; -webkit-font-smoothing: antialiased; overflow-x: hidden">
{body}
</div>
</x-dc>
<script type="text/x-dc" data-dc-script data-props='{props}'>{SCRIPT}</script>
</body>
</html>
'''


open(os.path.join(OUT, 'Landing.dc.html'), 'w').write(page(False))
open(os.path.join(OUT, 'PhoneLanding.dc.html'), 'w').write(page(True))
print('ok')
