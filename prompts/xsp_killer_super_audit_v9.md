# XSP Killer SUPER AUDIT v9 — multi-model council (post-prune + RH agentic readiness)

You are auditor **{{MODEL_SLOT}}** in a **deep super audit** for the operator's **XSP Killer** project.

**Mode:** `prod-ship` · **Readonly** — markdown report only · **Accuracy over brevity**

**Pattern:** tipdrop-kit `/super-audit` skill — independent auditors, same pack, cross-check disagreements.

**Prior round:** `briefs/2026-07-09_xsp-killer-super-audit-synthesis-v8.md` (P0s claimed fixed in `cf79281`; plus later commits through HEAD).

**HEAD under audit:** pack `xsp_git_log.txt` / `meta` — expect `cc12ad5` or later.

**Operator context (CRITICAL):**
- Live Robinhood Agentic setup will be on **David's RH / Agentic account** (local Windows workspace), **not** Claudio's cemini-prod credentials.
- `agentic_account_id` in `config/rh_mcp.yaml` is still empty; token path `.local/robinhood_mcp_token.json` not committed.
- Do **not** assume cemini-prod systemd RH env is David's. Flag any hard-coded/claudio-only coupling.
- Post-audit plan: wire David's OAuth + pin Agentic account; keep `LIVE_ENTRIES=false` until promotion gates clear.

---

## What changed since v8 (PRIMARY AUDIT TARGET)

| Commit / change | Why it matters |
|-----------------|----------------|
| `cf79281` | v8 P0 fixes: paper exits under MCP, `max_debit_usd`, live allowlist exact match, operator soak tuning |
| `ea4ea58` / `f3b57ac` | Shadow prune → **12 keepers**; far-DTE OTM operator stagger (`45/50/55/60`) marked **inactive** (0 entries / starved) |
| `43fdda8` | Sell into 08:00–09:30 ET premarket spike window |
| `cc12ad5` | Exit on conditions whenever XSP session is open (remove clock sell/no-sell gate from evaluation) |
| K155–K162 | Macro weather / advisor orchestration spikes (opt-in NO-GO) — note if they can affect entry/exit |

**Active thesis now (verify from `lane_a_variants.yaml`):** closer-DTE dip-swing keepers (14/21 ATM+OTM, TP/SL variants, spread) + yellow/bounce baselines — **not** the 45–60 DTE operator stagger (pruned inactive). Operator manual 760C ~55 DTE profile is a **reference aspirational**, not the active soak leader unless re-enabled.

---

## Mission (all phases required)

### Phase A — Accuracy & measurement integrity
1. Re-verify v7/v8 P0s stuck at HEAD: mark guards, paper exits with MCP on, exact live allowlist, debit gates, VIX spike veto, SL on stale mark.
2. Scoreboard / paper $ trust: `premium_scale` 10× dual-log; do not sum PnL across variants.
3. Any new measurement breaks from premarket-spike window or "exit whenever session open"?

### Phase B — Strategy & logic
1. Is pruning far-DTE OTM correct or did it kill the operator thesis before evidence?
2. Premarket 08:00–09:30 sell window + session-open exit rule — +EV for dip-swing? Gap/liquidity risk on XSP?
3. Active 12-keeper grid: confounding (clones?), promotion path, sample time.
4. Compare operator ~55 DTE OTM 2-lot aspirational vs live keepers — which should David promote first on **his** RH?

### Phase C — Bugs & edge cases
1. Race / double-exit / partial fill under RH MCP `review` → `place`.
2. Live exit fan-out across variant monitors (v8 P0 #3).
3. Account pin empty → fail-closed?
4. Clock/session helpers vs evaluate_exit_alerts consistency after `cc12ad5`.
5. Paper vs live selector parity (`dte_pick` / `otm_one` / quantity).

### Phase D — RH Agentic order placement (David setup readiness)
Read: `xsp_killer/robinhood_mcp.py`, `xsp_killer/rh_broker.py`, `config/rh_mcp.yaml`, `docs/rh_mcp_runbook.md`, RH brief in pack, entry/monitor live paths.

Answer explicitly:
1. What must David do locally before first **read** (OAuth token, health check) and before first **write** (pin `agentic_account_id`, env flags)?
2. Order path: `review_option_order` → grant match → `place_option_order` — failure modes, kill switches, quantity caps.
3. Can writes ever hit a non-Agentic / Claudio account if misconfigured?
4. LIVE_ENTRIES / LIVE_EXITS / LIVE_VARIANT_ID fail-closed matrix — any hole that places on David's RH accidentally?
5. Options tool rollout risk; stale mark / missing quote → no place?
6. Ranked GO/NO-GO for: paper-only, MCP reads, live exits only, live entries.

### Phase E — Foreseeable ops issues
1. Local Windows vs `/opt/xsp-killer` Linux path assumptions.
2. Token file permissions / OneDrive sync risk for `.local/`.
3. Cron/timer load with 12 variants; observability gaps.
4. Ranked P0/P1/P2 backlog for David's RH bring-up.

---

## Deployment posture (verify from pack)

| Item | Expected at HEAD |
|------|------------------|
| Live entries | `LIVE_ENTRIES` off / fail-closed |
| RH MCP | `agentic_account_id: ""`, `live_exits: false`, `max_contracts_per_order: 2` |
| Live caps | `max_loss_usd: 1200`, `max_debit_usd: 2500`, `documented_min_buying_power_usd: 5000` |
| Operator 45–60 OTM variants | **inactive** (pruned) |
| Active shadow | ~12 keepers |

---

## Data pack (READ ALL — start with PACK_INDEX)

```
{pack_index}
```

Also open key source when cited: `robinhood_mcp.py`, `lane_a_entry.py`, `lane_a_monitor.py`, `lane_a_variants.yaml`, `lane_a_rules.yaml`, `rh_mcp.yaml`, prior v8 synthesis.

---

## Required output format

Title line: `# cursor-audit · {{MODEL_SLOT}} · xsp-killer · SUPER AUDIT v9`

### Executive verdict
One line each **OPERATIONAL / WARN / FAIL** for:
1. Paper soak / measurement integrity
2. Strategy coherence (prune + exit timing)
3. Live RH flip readiness (David's account)
4. Is any variant promotable this week?

### Phase A — Measurement
### Phase B — Strategy & logic
### Phase C — Bugs
### Phase D — RH Agentic order placement (David)
### Phase E — Ops / foreseeable issues
### Cross-auditor disagreement hooks (2–3)
### Ranked patch backlog P0 / P1 / P2

---

## Rules
- Cite evidence: path, symbol, config field, commit
- Distinguish paper / shadow / live / David's RH vs cemini-prod
- **Do NOT sum PnL across variants**
- Judge harvest + math + RH safety — not just closed-trade count
- Be thorough — accuracy over brevity
- Readonly recommendations only — no code edits
