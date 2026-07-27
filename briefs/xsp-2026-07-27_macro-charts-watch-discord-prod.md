---
title: "xsp — Macro Charts watch Discord alerts on cemini-prod"
type: brief
tags: [xsp, macro-charts, discord, prod, alert-only, guruwatcher]
created: 2026-07-27
updated: 2026-07-27
---

## Target

CeminiSuite / cemini-prod — alert-only Macro Charts parameter watches (GuruWatcher).

## Summary

24/7 systemd timer on **cemini-prod** polls armed Macro Charts level watches and posts Discord when parameters are met. Fluid mind: per-symbol claim ledger, newest published article wins; deploy syncs claims only.

## Body

**Canonical repo:** [cemini23/GuruWatcher](https://github.com/cemini23/GuruWatcher)  
Laptop: `~/Projects/GuruWatcher` · Prod: `/opt/guru-watcher/` · timer: `guru-watcher.timer`

### Fluid mind

- Per-symbol claim ledger; newest Macro Charts article wins on conflicts
- Untouched symbols persist until TTL / invalidation
- Deploy syncs **claims only** — prod `watches.json` authoritative
- Auto: Gmail → inbox → `ingest-issue` → deploy → prod `reconcile --notify`

### Paths

| Path | Role |
|------|------|
| `/opt/guru-watcher/state/watches.json` | Armed watches (prod-owned) |
| `/opt/guru-watcher/state/claims/` | Claim ledger |
| `guru-watcher.timer` | Every 15 min |

### Secrets (names only)

- `UNUSUAL_WHALES_API_KEY` — `/opt/tipdrop-scanner/.env`
- `DISCORD_WEBHOOK_URL` — `/opt/cemini/.env`

### Operator

```bash
cd ~/Projects/GuruWatcher
bash scripts/sync_from_osint_inbox.sh
python3 -m guru_watcher list --mind
```

## Sources

- https://github.com/cemini23/GuruWatcher
