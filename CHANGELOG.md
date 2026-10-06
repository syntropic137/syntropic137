# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- feat(orchestration): per-phase max_cost_usd cost limit (#1376) (#1654)
- feat(workflows): verify phases screenshot UI changes instead of asking a human (#1648)
- feat(workflows): re-verify an existing PR head (sdlc-reverify-pr-v1) (#1653)
- feat(pit-stop): prove a real execution starts before declaring DONE (#1644)
- feat(evals): eval API and CLI (#967 step 6) (#1649)
- feat(dashboard-ui): headless screenshot script for UI verification (#1028) (#1642)
- feat(orchestration): record per-phase workspace resource usage at teardown (#1310 step 0) (#1608)
- feat(syn-perf): ScriptedAgentProfile, the token-free load-test contract (#1310 step 7a) (#1609)
- feat(#967): eval read models and execution eval filter (evals step 5) (#1620)
- feat: generated compose env passthrough + justfile release split (CODEOWNERS narrowing) (#1622)
- feat(#1547): tell the PR when a phase's work is quarantined (#1589)
- feat(feedback): 0.34 UI-feedback batch D - CSP blob:, defaults, 1/2 hotkeys, responsive filter bar (#1576)
- feat(observability): make request stalls diagnosable from gateway and API logs (#1583) (#1584)
- feat(#1546): tell the agent its phase deadline (#1578)
- feat(dashboard,api): live server version label with deploy-time tooltip (#1548)
- feat(workflows): bounded fix/reverify repair rounds in sdlc-implement-v3 (PC-63) (#1613)
- feat(#967): verify and record the pinned checkout before the agent runs (evals step 4B) (#1615)
- feat(executions): show failure classification on failed phases and in syn execution show (#1592)
- feat(#967): eval runs record their frozen baseline; GitHub revision resolver (#1591)
- feat(dashboard): updating state on list filters + /repos page (#1579)
- feat(preflight): run the pytest ci/fitness invariants in preflight-agent (#1581)
- feat(fitness): enforce ADR-060 'every in-memory adapter is guarded' (#1551)
- feat(#967): workflow default eval and execution eval membership (evals step 3) (#1562)
- feat: search all workflows server-side; list rows open in new tab on modifier-click (#1566)
- feat(dashboard,api): show dispatched task and per-phase start pins (#1561)
- feat(#1513): a resumed execution continues its parent's branch and PR (#1537)
- feat(orchestration): Eval aggregate and typed contracts (evals steps 1-2) (#1539)
- feat(#967): edit execution and workflow tags over HTTP and the CLI (#1541)
- feat: tags on workflows and executions (#967) (#1526)
- feat(orchestration): provision a resume at its parent's recorded commits (#1458) (#1525)

### Changed

- docs(skills): learning-loop - turn runs, failures and escaped bugs into evals (#1659)
- docs(skills): orchestrating tick - resume first (#1670)
- chore(workflows): run premise, prepare and finalize on Opus 5.5 (#1666)
- docs(skills): orchestrating skill - purpose, operating loop, lessons (#1660)
- docs(retro): 2026-10-06 merge-down and the dropped start (#1657)
- test: run every unmarked test in CI and make the marker ratchet zero-tolerance (#1428) (#1646)
- test(session-inventory): assert acquisition fence, not journal max (#1639) (#1643)
- perf(E2): page /sessions and /artifacts in one SQL statement (fix red main latency gate) (#1636)
- chore(images): pin agentic-workspace browser QA release (#1028) (#1594)
- chore(codeowners): own trust boundaries, not ordinary code (#1595)
- docs(plans): evals and execution tags plan (#967), with a progress table (#1610)
- docs(north-star): correct #865 (fixed in Sept); 100 needs more nodes (#1604)
- docs: north star - 20 concurrent now, 100 next, 1,000 production (#1601)
- docs(retro): 2026-10-04 dogfood orchestrator day, with a scorecard (#1599)
- perf(E2): executions, sessions and artifacts read in milliseconds (#1580)
- chore: bump syntropic137-claude-plugin to 0a2fced3 (closes #1501) (#1572)
- perf(E1): /metrics and heatmap read a usage rollup, plus a latency gate (#1558)
- chore(lib): bump syntropic137-skills to the completed migration (#1565)
- chore(lib): add syntropic137-skills as a submodule (#1533)
- ci(security): OSV scan was scanning nothing; bump to v2.3.8 + scan nested lockfile (#1535)
- chore(security): click 8.3.3, esbuild 0.28.1, record braces (no fix) (#1531)
- chore(release): bump to 0.33.1 (#1523)
- chore(images): pin agentic-workspace degradable session store (#1276) (#1517)

### Fixed

- fix(pit-stop): precheck the probe workflow before building; keep the API password off argv (#1656)
- fix(artifacts): keep binary artifacts byte-for-byte through collection, handoff and API (#990) (#1652)
- fix(#1650): a queued execution can be cancelled (withdraw its request) (#1651)
- fix(#1640): unapplied_starts reads pages the gRPC transport can carry (#1645)
- fix(#1557): an execution request gets its own stream id; every direct start was dropped as a duplicate (#1641)
- fix(workflows): settle checks the workspace cannot run from CI on the same head SHA (#1587)
- fix(workspace): apply configured workspace limits at the adapter (#1607)
- fix(#1557): one execution concurrency budget; queued starts visible; no duplicate resume tasks (#1574)
- fix(PC-66): refuse an empty or whitespace-only task at admission (#1621)
- fix(cli): prune only server-attributed workflows, opt-in with confirmation (#1588) (#1614)
- fix(#1560): disk space health signal, admission floor, orphaned workspace dir cleanup (#1577)
- fix(read-path): detect and document silently dropped execution starts (#1545) (#1550)
- fix(#1600): stop agent workspaces starving the control plane of CPU (#1602)
- fix(session-inventory): stop the inventory ProcessManager spinning on stale jobs (#1528) (#1529)
- fix(github): retry transient GitHub failures during workspace provisioning (#1593) (#1611)
- fix(cli): parse workflow YAML with a real parser so anchors/merge keys work (#1618) (#1619)
- fix(orchestration): fail a phase whose declared delegation did not happen (#894) (#1590)
- fix(feedback): bound ticket list requests so View Tickets cannot spin forever (#1603)
- fix(api,pit-stop): startup migrations no longer fail liveness; pit stop recovers a slow swap (#1575) (#1582)
- fix(dashboard): status, token and token-unit numbers tell the truth (#1564)
- fix(#1554): pin ESP with position-planned subscription tracks (#1556)
- fix(orchestration): grant the Skill tool to phases that declare skills (#1269) (#1540)
- fix(pit-stop): stage on hosts whose compose pins syn-api/syn-gateway by digest (#1538)
- fix(preflight): run fitness-check in preflight-agent, loudly when it cannot (#1498) (#1536)
- fix(guard): a submodule gitlink git moved is not unsaved work (#1527)
- fix(#1528): pin ESP with ProcessManagers drained off the subscription cursor (#1532)
- fix(#1519): pin the event-store INDEX digest, not a child manifest (#1522)

### Security

- security(deps): clear katex and source-map-js advisories, ignore unfixable sprintf-js (#1638)

## [0.33.1] - 2026-10-03

See the [v0.33.1 release notes](https://github.com/syntropic137/syntropic137/releases/tag/v0.33.1). Earlier versions: [GitHub releases](https://github.com/syntropic137/syntropic137/releases).

[unreleased]: https://github.com/syntropic137/syntropic137/compare/v0.33.1...HEAD
[0.33.1]: https://github.com/syntropic137/syntropic137/releases/tag/v0.33.1
