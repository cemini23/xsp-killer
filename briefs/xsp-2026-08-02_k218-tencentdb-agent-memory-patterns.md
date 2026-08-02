---
title: xsp-k218 — TencentDB Agent Memory patterns (extract only)
type: brief
target: cemini-prod
created: 2026-08-02
updated: 2026-08-02
---

## Target

cemini-prod / XSP killer bot (`/opt/xsp-killer`) — **session continuity patterns only**.

## Summary

MIT **TencentDB Agent Memory** hub ideas (public README pattern names) as analogs for xsp decide/session continuity. **Steal the taxonomy and governance habits** — not the Node services, docker stack, or any TencentDB runtime.

Local OSINT shallow clone (`.local/adopts/TencentDB-Agent-Memory`) was **not present** on this host. Extract uses the brief + publicly documented asset names only. No install.

## Hard bans (unchanged)

- No LIVE Discord without LIVE OK
- No secrets in briefs/handoffs
- Do **not** vendor deploy/docker into `/opt/cemini` or `/opt/xsp-killer`
- Do **not** replace ceminiSuite memory with TencentDB services
- No `LIVE_*` flips; no strategy/gate changes

## Four memory assets → existing xsp surfaces

| Tencent pattern | What it means (public) | Existing xsp surface (use this) | Do **not** |
|-----------------|------------------------|----------------------------------|------------|
| **Chat Memory** | Preferences, facts, decisions, interaction history; L0 raw → L1 atoms → L2 scenarios → L3 persona | Session handoffs (`briefs/handoffs/`), monitor/entry latest JSON, paper JSONL under `logs/`, operator checklist notes in `config/k155_operator_notes.yaml` | Stand up a chat-memory service; dump full agent transcripts into prod monitors |
| **Skill** | Versioned, reusable procedures with trigger boundaries + validation (not just a prompt snippet) | `scripts/` (entry/monitor/adopt), `prompts/`, docs runbooks (`docs/rh_mcp_*.md`, `docs/lane-a-brief.md`), Phase-0 adopt shells | Import Hermes/Skill runtime; auto-promote unverified “skills” into LIVE paths |
| **LLM-Wiki** | Docs compiled into structured pages + link graph (Karpathy-style knowledge base) | `research_wiki/concepts/`, synthesis briefs (`briefs/*super-audit*`), `docs/lane-*.md` | Vendor Wiki ingest pipeline or replace cemini research_wiki automation |
| **Code-Graph** | Symbols, files, call/impact edges for safe edits | Repo layout + architecture notes (`briefs/2026-07-20_cursor-audit-architecture.md`, `docs/`), grep/module map in-agent; shadow scoreboard as “impact of variant knobs” | Deploy CodeGraph indexer service; index private secrets paths |

## Cross-cutting patterns worth adopting (process only)

### 1. Memory assets, not a chat-log warehouse

Public framing: RAG answers “what can be found?”; team memory also answers **who can use it, which version is valid, which agent should load it**.

**xsp analog**

- Version fields already on weather blocks (`k213.version`, …).
- Briefs carry `created`/`updated` + “log-only / no strategy flip” constraints.
- Handoffs name **lane, hard stops, skip list** so the next agent loads a save file, not raw chat.

**Practice:** Prefer a short structured note (plan + pattern extract + constraints) over pasting an entire session into `operator_notes`.

### 2. Agent loadout (not one global prompt)

Public framing: bind different assets to different roles (Scout / Builder / Reviewer); equip only what reduces noise.

**xsp analog**

| Role-ish surface | Loadout |
|------------------|---------|
| Lane A entry/monitor timers | `lane_a_rules.yaml` + `macro_weather_notes` extras (log-only) |
| Variant soak | `lane_a_variants.yaml` + scoreboard — shadow only until promotion rules met |
| Ops / RH MCP | `docs/rh_mcp_runbook.md`, `config/rh_mcp.yaml` |
| Research / weather | `k155`…`k215` YAML blocks + `research_wiki/concepts/` |
| New agent cold-start | This repo’s `README.md` + latest plan under `briefs/` + handoff |

**Practice:** New session starts from **handoff + plan + hard stops**, not from re-reading every weather essay.

### 3. Layered distillation (L0–L3)

Public layering maps cleanly onto existing xsp artifacts (echoes cemini K154 hierarchical bounded memory REFERENCE):

| Layer | Tencent name | xsp place |
|-------|--------------|-----------|
| L0 | Raw conversation / full context | Agent session transcript (ephemeral); paper JSONL lines |
| L1 | Atoms — facts, constraints, events | YAML note flags; one-line constraints in briefs |
| L2 | Scenario blocks | Dated plans (`briefs/2026-*-plan.md`), steal briefs |
| L3 | Persona / stable patterns | Playbooks (`docs/lane-a-brief.md`), research_wiki concepts, glitch_falcon ops culture |

**Practice:** When a session ends, promote only L1/L2 into `briefs/` or YAML; do not leave critical constraints only in L0 chat.

### 4. Governed sharing (private / team / restricted)

Public visibility: private default; sharing is explicit.

**xsp analog**

- Secrets stay in env / out of git (`.env` gitignored; no secrets in briefs).
- Operator notes and briefs are **team-readable** intel; live credentials and LIVE Discord are **restricted**.
- Marketing / unverified stats (Glitch Falcon precedent) stay private until verified — never default into monitor JSON claims that look like signals.

### 5. Cold start = load the save file

Public: import codebases, docs, and past sessions so new agents do not relearn from zero.

**xsp cold-start checklist (no new tooling)**

1. `README.md` + `docs/lane-a-brief.md` (persona / playbook).
2. Latest plan in `briefs/` for the ticket (scenario).
3. Hard stops from handoff (constraints atoms).
4. Relevant `research_wiki/concepts/*` if strategy/regime context needed.
5. Optional: latest monitor JSON / scoreboard for **state**, not for strategy rewrite.

### 6. Every loop gains experience

Public: valuable interactions → Chat Memory; proven workflows → Skills; doc/code change → Wiki/CodeGraph sync.

**xsp loop**

| After… | Promote to… |
|--------|----------------|
| Weather essay / OSINT steal | Steal brief + (if gates already wired) log-only YAML block |
| Process/culture insight (e.g. Glitch Falcon) | Ops-culture YAML / brief — **no** marketing stats |
| Architecture audit | `briefs/*architecture*` or `docs/` — not runtime |
| Agent handoff | `briefs/handoffs/` with skip list + hard stops |

## What we explicitly reject for this ticket

| Temptation | Why reject |
|------------|------------|
| Clone/start Memory Hub docker | Hard ban; not needed for pattern adopt |
| New memory microservice in xsp-killer | No new service; paper bot stays thin |
| Replace ceminiSuite memory | Out of scope; different product surface |
| YAML weather block for K218 | No macro color / regime claim in the source brief |
| Tests for this extract | Runtime untouched |

## Relation to prior xsp memory work

- **K154** (cemini REFERENCE): hierarchical short/mid/long memory + eviction — architecture cousin; still no QSP port.
- **K155+ weather chain** through **K215**: log-only operator notes attached to monitors — L1/L2 weather atoms, not session memory hub.
- **Glitch Falcon**: agentic discipline / handoff only after human-proven repeatability — aligns with “review before share.”

K218 does **not** extend the weather YAML chain. It is a **meta** note for how agents and operators keep continuity across sessions.

## Optional later (ticket required; not this PR)

- A one-page “session save file” template under `docs/` or `briefs/handoffs/` (fields: goal, hard stops, files touched, next agent loadout).
- Explicit L0→L2 promotion checklist in super-audit prompts.
- Still **no** Tencent runtime.

## Sources

- Brief: `briefs/xsp-k218-tencentdb-agent-memory.md`
- Public pattern names: TencentCloud/TencentDB-Agent-Memory README (Chat Memory, Skill, LLM-Wiki, Code-Graph, agent loadout, L0–L3, governed sharing)
- Related: cemini K154 hierarchical bounded agent memory (REFERENCE); xsp glitch_falcon ops culture; `research_wiki/concepts/`
