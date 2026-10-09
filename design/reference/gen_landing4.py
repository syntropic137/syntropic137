#!/usr/bin/env python3
"""Landing v4: 'Agent work that compounds.' Four pillars in order: repeatable workflows, any harness,
fully observable, compounding improvement (evals). Reuses v3 (S mark, city, explorer)."""
import os, json
import gen_landing3 as v3
v2, v1 = v3.v2, v3.v1

OUT = v1.OUT
MONO, SANS, ORB = v1.MONO, v1.SANS, v1.ORB
DOT, ARROW = v1.DOT, v1.ARROW
head, GRAIN, DOTGRID = v2.head, v2.GRAIN, v2.DOTGRID

PANEL = 'border-radius: 22px; border: 1px solid #1A2032; background: linear-gradient(180deg, #0F1320, #0A0C14); box-shadow: inset 0 1px 0 rgba(255,255,255,0.05)'
CLAUDE, CODEX = '#D97757', '#8E9BBC'


def harness_chip(name, c):
    return f'<span style="display: inline-flex; align-items: center; gap: 6px; height: 22px; padding: 0 9px; border-radius: 11px; border: 1px solid #222A40; background: #111626; font-family: {MONO}; font-size: 11px; color: #C3CCE2; white-space: nowrap"><span style="width: 7px; height: 7px; border-radius: 50%; background: {c}"></span>{name}</span>'


YAML = f'''<pre style="margin: 0; overflow-x: auto; padding: 18px; font-family: {MONO}; font-size: 12.5px; line-height: 1.7; color: #E8EEFB"><span style="color: #9AA8C7">id:</span> implement-and-review
<span style="color: #9AA8C7">inputs:</span>
  - <span style="color: #9AA8C7">name:</span> task
<span style="color: #9AA8C7">phases:</span>
  - <span style="color: #9AA8C7">id:</span> implement
    <span style="color: #9AA8C7">agent:</span> {{ <span style="color: #9AA8C7">provider:</span> <span style="color: {CLAUDE}">claude</span>, <span style="color: #9AA8C7">model:</span> sonnet }}
    <span style="color: #9AA8C7">prompt_template:</span> prompts/implement.md
  - <span style="color: #9AA8C7">id:</span> review
    <span style="color: #9AA8C7">agent:</span> {{ <span style="color: #9AA8C7">provider:</span> <span style="color: {CODEX}">codex</span>, <span style="color: #9AA8C7">model:</span> gpt-5.6-sol }}
    <span style="color: #9AA8C7">prompt_template:</span> prompts/review.md</pre>'''


def code_window(title, body):
    return f'''<div style="{PANEL}; overflow: hidden; min-width: 0">
<div style="display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-bottom: 1px solid #141A2A">
<span style="display: flex; gap: 6px"><span style="width: 9px; height: 9px; border-radius: 50%; background: #283048"></span><span style="width: 9px; height: 9px; border-radius: 50%; background: #283048"></span><span style="width: 9px; height: 9px; border-radius: 50%; background: #283048"></span></span>
<span style="font-family: {MONO}; font-size: 11.5px; color: #6F7FA3">{title}</span>
</div>
{body}
</div>'''


# ------------------------------------------------------------------ hero
def hero(p):
    s = v3.hero(p)
    s = s.replace('Agents that get better. Provably.', 'Agent work that compounds.')
    s = s.replace('Run Claude Code and Codex as workflows in isolated containers, record every tool call and dollar, and score every model on your real bugs. Then keep what works.',
                  'Turn one-off agent sessions into repeatable workflows. Run them on Claude Code or Codex, see every step, and make every run better than the last.')
    s = s.replace('Evals: score every model out of 100', 'Evals: measure which model and prompt actually work')
    # floaters: workflow, harness, eval
    s = s.replace(f'''<span style="font-family: {MONO}; font-size: 11px; color: #9AA8C7">eval · shared-esp-stream</span>
<span style="display: flex; align-items: baseline; gap: 6px"><span style="font-size: 26px; font-weight: 600; letter-spacing: -0.02em">89</span><span style="font-size: 12px; color: #9AA8C7">/100 · claude-sonnet-5-5</span></span>
<span style="font-size: 12px; font-weight: 600; color: #7FE3B8">+24 pts in 2 weeks, same cost</span>''',
                  f'''<span style="display: flex; align-items: center; gap: 8px; font-family: {MONO}; font-size: 11px; color: #9AA8C7">{DOT}self-heal-ci · run #142</span>
<span style="font-size: 15px; font-weight: 600">Fixed the failing check on PR #311</span>
<span style="font-size: 12px; color: #9AA8C7">Triggered by GitHub · 4m 10s · $0.31</span>''')
    s = s.replace(f'''<span style="display: flex; align-items: center; gap: 8px; font-family: {MONO}; font-size: 11px; color: #9AA8C7">{DOT}running · Deep Dive Analysis</span>
<span style="display: flex; align-items: baseline; gap: 10px"><span style="font-size: 20px; font-weight: 600">$0.104</span><span style="font-family: {MONO}; font-size: 11.5px; color: #9AA8C7">213k tokens</span></span>''',
                  f'''<span style="font-family: {MONO}; font-size: 11px; color: #9AA8C7">implement-and-review</span>
<span style="display: flex; align-items: center; gap: 6px">{harness_chip('implement · claude', CLAUDE)}<span style="color: #6F7FA3">→</span>{harness_chip('review · codex', CODEX)}</span>''')
    s = s.replace(f'''<span style="font-family: {MONO}; font-size: 11px; color: #9AA8C7">verdict · gpt-5.6-sol</span>
<span style="display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 600"><span style="width: 8px; height: 8px; border-radius: 2px; background: #FF6F61"></span>Missed the bug · 58/100</span>''',
                  f'''<span style="font-family: {MONO}; font-size: 11px; color: #9AA8C7">this workflow, 5 weeks</span>
<span style="display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 600"><span style="color: #7FE3B8">−37% time</span><span style="color: #6F7FA3">·</span><span style="color: #7FE3B8">+24 pts quality</span></span>''')
    s = s.replace('<span style="font-size: 12.5px; color: #6F7FA3">judge score</span>', '<span style="font-size: 12.5px; color: #6F7FA3">workflow, run 142 times</span>', 1)
    for a, b in [('>89/100<', '>1<'), ('>$0.52<', '>2<'), ('>per run<', '>harnesses, any phase<'), ('>214<', '>214<'), ('>tool calls recorded<', '>tool calls in the last run, all kept<'), ('>0<', '>+24<'), ('>secrets on your laptop<', '>quality points in 2 weeks<')]:
        s = s.replace(a, b, 1)
    return s


# ------------------------------------------------------------------ what it is
def what_it_is(p):
    run = f'''<div style="display: flex; flex-direction: column; gap: 10px; padding: 18px">
''' + ''.join(f'''<div style="display: flex; flex-direction: column; gap: 8px; padding: 12px 14px; border-radius: 14px; border: 1px solid #1A2032; background: #0A0C14">
<span style="display: flex; align-items: center; justify-content: space-between; gap: 8px"><span style="font-size: 14px; font-weight: 600">{n}</span>{harness_chip(h, c)}</span>
<span style="display: flex; align-items: center; justify-content: space-between; gap: 8px; font-family: {MONO}; font-size: 11px; color: #9AA8C7"><span>container {w}</span><span>{st}</span></span>
<span style="height: 5px; border-radius: 3px; background: {bar}"></span>
</div>''' for n, h, c, w, st, bar in [('implement', 'claude-sonnet-5-5', CLAUDE, 'ws-1', 'done · 3m 02s', 'var(--ac)'),
                                         ('review', 'gpt-5.6-sol', CODEX, 'ws-2', 'running', 'linear-gradient(90deg, var(--ac) 60%, #151A2A 60%)')]) + '</div>'
    rec = f'''<div style="display: flex; flex-direction: column; gap: 12px; padding: 18px">
<div style="display: flex; align-items: baseline; gap: 10px"><span style="font-size: 30px; font-weight: 600; letter-spacing: -0.02em">$0.31</span><span style="font-family: {MONO}; font-size: 12px; color: #9AA8C7">842k tokens · 214 tool calls</span></div>
<div style="display: flex; height: 14px; gap: 2px"><span style="flex: 52; border-radius: 4px 0 0 4px; background: #4C8DEA"></span><span style="flex: 18; background: #E0703A"></span><span style="flex: 21; background: #9085E9"></span><span style="flex: 9; border-radius: 0 4px 4px 0; background: #C98500"></span></div>
<div style="display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 12px; border-radius: 12px; background: #0A0C14; border: 1px solid #1A2032"><span style="font-size: 13px; color: #9AA8C7">Review score</span><span style="font-size: 20px; font-weight: 600">88<span style="font-size: 12px; color: #6F7FA3">/100</span></span></div>
<span style="font-size: 12.5px; color: #7FE3B8">Faster and cheaper than last week's runs</span>
</div>'''
    cols = [('1 · Write it once', 'A workflow is a few phases in YAML with prompts in Markdown.', code_window('workflows/implement-and-review.yaml', YAML)),
            ('2 · Run it anywhere', 'Each phase runs Claude Code or Codex in its own container.', code_window('syn workflow run implement-and-review', run)),
            ('3 · Every run compounds', 'Every step is recorded, scored and compared with the last run.', code_window('localhost:8137', rec))]
    cards = ''.join(f'''<div style="display: flex; flex-direction: column; gap: 12px; min-width: 0">
<span style="font-size: 18px; font-weight: 600; letter-spacing: -0.015em">{t}</span>
<span style="font-size: 14px; line-height: 1.5; color: #9AA8C7">{d}</span>
{w}
</div>''' for t, d, w in cols)
    return f'''<section aria-label="What it is" style="box-sizing: border-box; width: 100%; max-width: 1320px; margin: 0 auto; padding: {'48px 16px' if p else '120px 40px 100px'}">
{head(p, 'What is Syntropic137?', 'Your coding agents, on repeat. Getting better every time.', 'Syntropic137 turns your coding agents into repeatable workflows. Run them on any harness, see every step, and make every run better than the last. Self-hosted and open source.', center=not p)}
<div style="display: grid; grid-template-columns: {'minmax(0, 1fr)' if p else 'repeat(3, minmax(0, 1fr))'}; gap: {'28px' if p else '24px'}; margin-top: {'28px' if p else '56px'}">{cards}</div>
</section>'''


# ------------------------------------------------------------------ pillars
def pillar(p, num, eb, title, sub, bullets, visual, flip=False, tint=False):
    bl = ''.join(f'<div style="display: flex; gap: 12px; padding: 12px 0; border-top: 1px solid #141A2A"><svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="var(--ac)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="flex-shrink: 0; margin-top: 2px"><path d="M3.5 8.5l3 3 6-7"></path></svg><span style="display: flex; flex-direction: column; gap: 2px"><span style="font-size: 15px; font-weight: 600">{a}</span><span style="font-size: 14px; line-height: 1.5; color: #9AA8C7">{b}</span></span></div>' for a, b in bullets)
    text = f'''<div style="display: flex; flex-direction: column; gap: 22px; {'' if p else 'flex: 0 0 440px'}">
<span style="display: flex; align-items: center; gap: 12px"><span style="font-family: {ORB}; font-size: 14px; font-weight: 600; color: color-mix(in oklab, var(--ac) 55%, white)">{num}</span><span style="height: 1px; width: 40px; background: color-mix(in oklab, var(--ac) 45%, #1A2032)"></span></span>
{head(p, eb, title, sub)}
<div>{bl}</div>
</div>'''
    vis = f'<div style="flex: 1 1 auto; min-width: 0">{visual}</div>'
    inner = (vis + text) if (flip and not p) else (text + vis)
    bg = f'background: radial-gradient(45% 60% at {"20%" if flip else "80%"} 40%, color-mix(in oklab, var(--ac) 10%, transparent), transparent 70%), #06080E;' if tint else ''
    return f'''<section aria-label="{eb}" style="border-top: 1px solid #10141F; {bg}">
<div style="display: flex; flex-direction: {'column' if p else 'row'}; align-items: {'stretch' if p else 'center'}; gap: {'28px' if p else '72px'}; box-sizing: border-box; max-width: 1320px; margin: 0 auto; padding: {'56px 16px' if p else '120px 40px'}">
{inner}
</div>
</section>'''


def workflows_visual(p):
    trig = f'''<div style="{PANEL}; display: flex; flex-direction: column; gap: 10px; padding: 18px">
<span style="display: flex; align-items: center; gap: 8px; font-family: {MONO}; font-size: 11.5px; color: #9AA8C7">{DOT}trigger · self-heal-ci · active</span>
<p style="margin: 0; font-size: 16px; line-height: 1.55"><span style="color: #9AA8C7">When</span> CI fails on a pull request, <span style="color: #9AA8C7">run</span> <span style="color: color-mix(in oklab, var(--ac) 50%, white)">implement-and-review</span>, <span style="color: #9AA8C7">at most</span> 3 times a day, <span style="color: #9AA8C7">under</span> $2.</p>
</div>'''
    ways = ''.join(f'<span style="display: flex; flex-direction: column; gap: 4px; padding: 12px 14px; border-radius: 14px; border: 1px solid #1A2032; background: #0A0C14; min-width: 0"><span style="font-size: 12px; color: #6F7FA3">{a}</span><code style="font-family: {MONO}; font-size: 12px; color: #E8EEFB; overflow-wrap: anywhere">{b}</code></span>' for a, b in [('From the CLI', 'syn workflow run implement-and-review'), ('From a GitHub event', '--event check_run.completed'), ('From a preset', 'syn triggers enable self-healing'), ('From another repo', 'syn workflow install owner/repo --ref main')])
    return f'''<div style="display: flex; flex-direction: column; gap: 12px">
{code_window('workflows/implement-and-review.yaml', YAML)}
<div style="display: grid; grid-template-columns: {'1fr' if p else 'repeat(2, minmax(0, 1fr))'}; gap: 10px">{ways}</div>
{trig}
</div>'''


def harness_visual(p):
    def lane(name, c, cells):
        row = ''.join(f'<span style="flex: {w}; display: flex; align-items: center; height: 44px; padding: 0 12px; border-radius: 12px; {"background: color-mix(in oklab, " + c + " 22%, #0A0C14); border: 1px solid color-mix(in oklab, " + c + " 55%, #1A2032)" if on else "border: 1px dashed #1A2032"}; font-size: 13px; font-weight: 600; color: {"#E8EEFB" if on else "transparent"}; white-space: nowrap; overflow: hidden">{t}</span>' for t, w, on in cells)
        return f'''<div style="display: grid; grid-template-columns: {'86px' if p else '120px'} minmax(0, 1fr); align-items: center; gap: 12px">
<span style="display: flex; align-items: center; gap: 8px; font-family: {MONO}; font-size: 12px; color: #C3CCE2"><span style="width: 9px; height: 9px; border-radius: 50%; background: {c}"></span>{name}</span>
<div style="display: flex; gap: 6px; min-width: 0">{row}</div>
</div>'''
    cells_c = [('plan', 2, True), ('', 3, False), ('fix', 2, True), ('', 2, False)]
    cells_x = [('', 2, False), ('implement', 3, True), ('', 2, False), ('review', 2, True)]
    return f'''<div style="{PANEL}; display: flex; flex-direction: column; gap: 16px; padding: {'18px' if p else '28px'}">
<span style="display: flex; justify-content: space-between; gap: 10px; font-family: {MONO}; font-size: 11.5px; color: #9AA8C7"><span>plan-implement-review · one workflow, two vendors</span><span>{DOT}</span></span>
{lane('claude', CLAUDE, cells_c)}
{lane('codex', CODEX, cells_x)}
<div style="display: grid; grid-template-columns: {'1fr' if p else 'repeat(3, minmax(0, 1fr))'}; gap: 10px; padding-top: 6px">
''' + ''.join(f'<span style="display: flex; flex-direction: column; gap: 2px; padding: 12px 14px; border-radius: 14px; background: #0A0C14; border: 1px solid #1A2032"><span style="font-size: 12px; color: #6F7FA3">{a}</span><span style="font-size: 18px; font-weight: 600">{b}</span></span>' for a, b in [('Phases', '4, across 2 harnesses'), ('Second opinion', 'Codex reviews Claude'), ('Telemetry', 'Identical for both')]) + '''
</div>
</div>'''


def observe_visual(p):
    log_rows = [('14:02:11', 'Read', 'src/domain/aggregate.py', '42ms'), ('14:02:14', 'Grep', '"apply_event" -n', '118ms'), ('14:02:19', 'Bash', 'pytest -q tests/domain', '8.4s'),
                ('14:02:31', 'Write', 'docs/event-sourcing.md', '12ms'), ('14:02:33', 'Read', 'src/projections/list.py', '31ms'), ('14:02:40', 'Edit', 'projection.py +12 −3', '9ms'),
                ('14:02:52', 'Bash', 'ruff check .', '1.2s'), ('14:03:01', 'Read', 'tests/test_replay.py', '28ms')]
    lr = ''.join(f'<span style="display: grid; grid-template-columns: 64px 46px minmax(0,1fr) 52px; gap: 10px; padding: 6px 10px; font-family: {MONO}; font-size: 12px"><span style="color: #6F7FA3">{t}</span><span style="color: color-mix(in oklab, var(--ac) 50%, white)">{k}</span><span style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis">{a}</span><span style="text-align: right; color: #9AA8C7">{d}</span></span>' for t, k, a, d in log_rows)
    legend = ''.join(f'<span style="display: flex; align-items: center; gap: 6px"><span style="width: 9px; height: 9px; border-radius: 2px; background: {c}"></span>{l}</span>' for c, l in [('#4C8DEA', 'Cache read'), ('#E0703A', 'Cache write'), ('#9085E9', 'Output'), ('#C98500', 'Input')])
    return f'''<div style="{PANEL}; display: flex; flex-direction: column; gap: 14px; padding: {'18px' if p else '28px'}; background: radial-gradient(80% 80% at 100% 0%, color-mix(in oklab, var(--ac) 16%, transparent), transparent 70%), linear-gradient(180deg, #0F1320, #0A0C14)">
<span style="display: flex; align-items: center; gap: 8px; font-family: {MONO}; font-size: 11.5px; color: #9AA8C7">{DOT}live · implement-and-review · run #142</span>
<div style="display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 20px"><span style="font-size: {'34px' if p else '44px'}; font-weight: 600; letter-spacing: -0.03em">$0.2162</span><span style="font-family: {MONO}; font-size: 13px; color: #9AA8C7">1.12M tokens · 214 tool calls · 6m 12s</span></div>
<div style="display: flex; height: 22px; gap: 2px"><span style="flex: 52; border-radius: 6px 0 0 6px; background: #4C8DEA"></span><span style="flex: 18; background: #E0703A"></span><span style="flex: 21; background: #9085E9"></span><span style="flex: 9; border-radius: 0 6px 6px 0; background: #C98500"></span></div>
<div style="display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 12px; color: #9AA8C7">{legend}</div>
<div style="position: relative; height: 176px; overflow: hidden; border-radius: 14px; border: 1px solid #1A2032; background: #080A11; -webkit-mask-image: linear-gradient(180deg, transparent, #000 18%, #000 82%, transparent); mask-image: linear-gradient(180deg, transparent, #000 18%, #000 82%, transparent)">
<div class="scroll" style="display: flex; flex-direction: column">{lr}{lr}</div>
</div>
</div>'''


def compounding(p):
    s = v3.explorer(p)
    s = s.replace('New · Evals', '04 · Compounding improvement')
    s = s.replace('Stop guessing which model is better.', 'Every run makes the next one better.')
    s = s.replace("Replay real bugs against every model and workflow you run. A judge scores each run out of 100, and you see quality next to cost, over time. Try it: pick a model on the right.",
                  "Your run history becomes evals: real bugs replayed against every model and workflow, scored out of 100 by a judge, next to what each run cost. Change a prompt or a model, and see whether it actually helped. Try it: pick a model on the right.")
    return s.replace('aria-label="Evals"', 'id="evals" aria-label="Evals"', 1)


def use_cases(p):
    cases = [('Self-healing CI', 'A check fails, an agent fixes it and pushes the fix to the PR.', 'GitHub: check_run failed'),
             ('Second-opinion review', 'Claude implements, Codex reviews, every PR, on a budget.', 'GitHub: PR opened'),
             ('Research and docs', 'Investigate a codebase or topic and write it up with sources.', 'CLI or Claude Code'),
             ('Migrations and refactors', 'Split a large change into planned, reviewed phases.', 'CLI, one repo or many'),
             ('Issue to pull request', 'Label an issue and get a tested PR back.', 'GitHub issue event'),
             ('Nightly maintenance', 'Dependency bumps, flaky-test hunts, changelog upkeep.', 'CLI on a schedule')]
    cs = ''.join(f'''<div class="tile" style="{PANEL}; display: flex; flex-direction: column; gap: 10px; padding: 22px; min-width: 0">
<span style="font-size: 18px; font-weight: 600; letter-spacing: -0.015em">{t}</span>
<span style="font-size: 14px; line-height: 1.5; color: #9AA8C7">{d}</span>
<span style="margin-top: auto; align-self: flex-start; display: flex; align-items: center; gap: 6px; height: 24px; padding: 0 10px; border-radius: 12px; border: 1px solid #222A40; font-family: {MONO}; font-size: 11px; color: #C3CCE2">{tr}</span>
</div>''' for t, d, tr in cases)
    return f'''<section aria-label="Use cases" style="border-top: 1px solid #10141F; background: {DOTGRID} 0 0 / 28px 28px, #080A11">
<div style="box-sizing: border-box; max-width: 1320px; margin: 0 auto; padding: {'56px 16px' if p else '120px 40px'}">
{head(p, 'What people build with it', 'Write it once. Let it run.', 'A few of the workflows people run on Syntropic137. Each ships as a starting point you can install and change.', center=not p)}
<div style="display: grid; grid-template-columns: {'minmax(0, 1fr)' if p else 'repeat(3, minmax(0, 1fr))'}; gap: {'12px' if p else '16px'}; margin-top: {'24px' if p else '56px'}">{cs}</div>
</div>
</section>'''


def nav_fix(s):
    for a, b in [('>Product<', '>Workflows<'), ('>Docs<', '>Harnesses<'), ('>Evals<', '>Observability<'), ('>For agents<', '>Evals<'), ('>Changelog<', '>Docs<')]:
        s = s.replace(a, b, 1)
    return s


def start(p):
    return v3.start(p).replace('Stop babysitting agents.', 'Make your agent work compound.').replace(
        'Self-hosted, MIT licensed, no account. Your keys, your data, your bill.',
        'Repeatable workflows, any harness, every step on the record, better every run. Self-hosted and MIT licensed.')


def page(p):
    W, H = (390, 9400) if p else (1440, 8600)
    pillars = [
        pillar(p, '01', 'Repeatable workflows', 'Write it once. Run it forever.',
               'Turn the prompt you keep retyping into a workflow: phases in YAML, prompts in Markdown. Run it by hand, from the API, or let GitHub events start it.',
               [('Phases with inputs and outputs', 'Each phase hands its artifacts to the next, with timeouts and budgets.'),
                ('Start it from anywhere', 'The CLI, the API, or a GitHub event through a trigger.'),
                ('Share and reuse', 'Install workflows from any repo and pin the version.')], workflows_visual(p), tint=True),
        pillar(p, '02', 'Any harness', 'Claude Code or Codex. Per phase.',
               'Pick the best agent for each step instead of one vendor for everything. Build with one, review with the other, and delegate subtasks between them.',
               [('Mix vendors in one workflow', 'Each phase names its provider and model.'),
                ('A second opinion built in', 'Cross-vendor review catches what one model misses.'),
                ('One record for both', 'The same telemetry, costs and evals, whichever harness ran.')], harness_visual(p), flip=True),
        pillar(p, '03', 'Fully observable', 'See every step. Pay for none of the surprises.',
               'Every tool call, token and dollar, per phase, live. Every agent runs in a throwaway container with credentials cleared and outbound traffic proxied.',
               [('Live and permanent', 'Watch runs as they happen; the event store keeps every decision.'),
                ('Cost to the cent', 'Per run, per phase, per token type, per model.'),
                ('Readable by agents too', 'The CLI and API return the same facts as JSON.')], observe_visual(p), tint=True),
    ]
    body = '\n'.join([nav_fix(hero(p)), what_it_is(p)] + pillars + [compounding(p), use_cases(p), v2.compare(p), start(p), v3.footer(p)])
    props = json.dumps({"accent": {"editor": "color", "default": "#4D80FF", "options": ["#4D80FF", "#4CC9F0", "#45E0A0", "#A78BFA"]}, "$preview": {"width": W, "height": H}})
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Syntropic137 landing v4{' (phone)' if p else ''}</title>
<script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=Orbitron:wght@500;600;700&display=swap">
<style>{v3.STYLE}</style>
</helmet>
<div style="--ac: {{{{accent}}}}; display: flex; flex-direction: column; min-height: 100vh; background: #06080E; color: #E8EEFB; font-family: {SANS}; font-size: 14px; line-height: 1.45; -webkit-font-smoothing: antialiased; overflow-x: hidden">
{body}
</div>
</x-dc>
<script type="text/x-dc" data-dc-script data-props='{props}'>{v3.SCRIPT}</script>
</body>
</html>
'''


# v3 becomes the comparison board
open(os.path.join(OUT, 'LandingV3.dc.html'), 'w').write(v3.page(False))
open(os.path.join(OUT, 'PhoneLandingV3.dc.html'), 'w').write(v3.page(True))
open(os.path.join(OUT, 'Landing.dc.html'), 'w').write(page(False))
open(os.path.join(OUT, 'PhoneLanding.dc.html'), 'w').write(page(True))
print('ok v4')
