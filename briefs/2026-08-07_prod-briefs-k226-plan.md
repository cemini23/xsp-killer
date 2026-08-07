# Plan — prod briefs → XSP Killer (2026-08-07)

**Status:** SHIPPED (log-only weather notes)
**Lane:** hard (log-only weather)

## Sources scanned
- `/opt/cemini/briefs/xsp-k226-clarity-heston-manip.md` → **CODE**
- `/opt/cemini/briefs/pm-k226-forecastEx-volume.md` → skip (PM)
- Harness K249–K258 / older K226 vetclaw → skip (not XSP weather)
- Phase0/1 adopt scripts: **none new today** for K226

## Prior
K225 shipped `c7cd2ff` — overnight was `keep_tight_vs_k224`.

## Implement
See `briefs/handoffs/2026-08-07_k226-handoff.md` (full YAML + test rewrite plan).

### Delivered
1. YAML `k226:` after k225 in `config/k155_operator_notes.yaml`
2. `load_k226_notes` + merge after k225 in `build_monitor_macro_weather_extras`
3. Tests: k226 load/includes/from-prod; from-prod overnight → `keep_tight_vs_k225`; isolated k225 keeps `keep_tight_vs_k224`
4. Overnight chain ends: `keep_tight_vs_k225` + `no_posture_change_on_teaser` + `no_prod_manip_detector`
