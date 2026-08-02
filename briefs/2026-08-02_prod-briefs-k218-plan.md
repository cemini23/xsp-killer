# Plan — prod briefs → XSP Killer (2026-08-02)

**Status:** DONE (Grok) — patterns extract only; no runtime

**Hard stops:** `LIVE_*` false; no Tencent deploy/docker vendor; no ceminiSuite memory replacement; no secrets in briefs; no strategy/gate flips.

## Brief triage

| Brief | Action |
|-------|--------|
| **K218** TencentDB Agent Memory (chat / skill / LLM-wiki / code-graph) | **EXTRACT ONLY** — pattern note mapped to existing xsp surfaces. No new service. |
| K213 Warsh / Capital Flows | Already shipped (`1faae2c`) |
| K214 WuBlock term premium | Already shipped (`64ae1c0`) |
| K215 Macro inflection + WuBlock + Warsh video | Already shipped (`64ae1c0`) |
| PM briefs | Skip |
| Harness K221–K233 | Skip |

## Implement

1. Keep brief copies: `briefs/xsp-k218-tencentdb-agent-memory.md` + `briefs/2026-08-02_k218-tencentdb-agent-memory.md`.
2. Pattern extract note (markdown): four memory-asset ideas → operator notes / decide-session / briefs / research_wiki / docs — **no code path**.
3. Local REFERENCE `.local/adopts/TencentDB-Agent-Memory` **absent** → work from brief + public pattern names only (no curl\|sh install).
4. Runtime: **none**. No YAML, no loader, no tests required.

## Non-goals

- Do not vendor MemoryCore / MemoryHub / deploy stack into this repo or `/opt/cemini`.
- Do not replace or rewire ceminiSuite memory services.
- Do not add Discord LIVE posts from this extract.
