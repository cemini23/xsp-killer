"""Robinhood Agentic Trading MCP adapter — read path + gated writes (Phase 0+).

Headless bridge for systemd cron. Disabled by default; no network calls unless
``XSP_LANE_A_RH_MCP=true`` and a token file exists.

See ``docs/rh_mcp_runbook.md`` and ``config/rh_mcp.yaml``.

Invariants:
- Disabled by default (``XSP_LANE_A_RH_MCP`` false); no MCP network unless
  env + token file.
- Write path enforces HCP I2 (review→place grant chain) and I7 (deny-path
  audit on blocks).
- LOW-confidence MCP reads (``mcp_read_trusted``) must not drive
  position/monitor decisions.
- No live orders without operator GO (I7): ``place_option_order`` requires a
  pinned account plus ``XSP_LANE_A_LIVE_ENTRIES`` for opens (buy-to-open) and
  ``XSP_LANE_A_LIVE_EXITS`` for closes (sell-to-close); every leg must set
  ``position_effect`` to exactly ``open`` or ``close`` (unknown/empty denied).
- I8 kill switch: ``kill_switch_engaged`` (``XSP_LANE_A_KILL_SWITCH`` or a
  sentinel file) blocks all ``place_option_order`` regardless of live-exits;
  cancels are never blocked. IO failure reading the kill file fails closed.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from xsp_killer.data_hazards import (
    classify_mcp_read_confidence,
    fusion_tier,
    mcp_read_trusted,
    unwrap_tool_result,
    wrap_tool_result,
)
from xsp_killer.k37_reviewer_shadow import shadow_review_order

logger = logging.getLogger("xsp_killer.robinhood_mcp")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "rh_mcp.yaml"
_last_mcp_fetch_wrap: dict[str, Any] | None = None
MCP_JSONRPC_VERSION = "2.0"
MCP_ACCEPT = "application/json, text/event-stream"


def parse_mcp_http_response(raw: str) -> dict[str, Any]:
    """Parse Streamable HTTP MCP body (JSON or SSE ``event: message`` frames)."""
    text = raw.strip()
    if not text:
        raise RhMcpError("rh_mcp empty response")
    if text.startswith("{"):
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise RhMcpError("rh_mcp expected JSON object response")
        return parsed
    if text.startswith("event:") or "\ndata:" in text:
        for line in text.splitlines():
            if line.startswith("data:"):
                payload = line[5:].strip()
                if not payload:
                    continue
                parsed = json.loads(payload)
                if isinstance(parsed, dict):
                    return parsed
        raise RhMcpError("rh_mcp SSE response missing data frame")
    raise RhMcpError(f"rh_mcp non-JSON response: {text[:200]}")


READ_TOOLS = frozenset(
    {
        "get_accounts",
        "get_portfolio",
        "get_option_positions",
        "get_option_orders",
        "get_option_chains",
        "get_option_instruments",
        "get_option_quotes",
        "get_equity_historicals",
        "get_indexes",
        "get_index_quotes",
        "search",
    }
)
WRITE_TOOLS = frozenset(
    {
        "review_option_order",
        "place_option_order",
        "cancel_option_order",
    }
)
ALLOWED_TOOLS = READ_TOOLS | WRITE_TOOLS


class RhMcpError(Exception):
    """Base MCP adapter error."""


class RhMcpNotReady(RhMcpError):
    """MCP enabled but token/config missing."""


class RhMcpLiveExitsDisabled(RhMcpError):
    """place_option_order blocked by kill switch."""


class RhMcpAccountRejected(RhMcpError):
    """Order target account is not the pinned Agentic account."""


class RhMcpKillSwitch(RhMcpError):
    """place_option_order blocked by the operator kill switch."""


def kill_switch_engaged() -> bool:
    """True when the operator kill switch is set (env flag or sentinel file).

    Blocks all new order placement regardless of ``XSP_LANE_A_LIVE_EXITS``.
    Cancels are never blocked so open orders can always be pulled.
    IO failure while checking the sentinel file fails closed (blocks placement).
    """
    if os.getenv("XSP_LANE_A_KILL_SWITCH", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return True
    kill_file = os.getenv("XSP_LANE_A_KILL_FILE", "").strip() or str(
        ROOT / ".local" / "KILL_SWITCH"
    )
    try:
        return Path(kill_file).exists()
    except OSError:
        logger.warning(
            "kill switch file check failed (%s) — fail-closed (blocking place)",
            kill_file,
        )
        return True


def rh_mcp_enabled() -> bool:
    return os.getenv("XSP_LANE_A_RH_MCP", "false").strip().lower() in (
        "1",
        "true",
        "yes",
    )


# XSP index instrument UUID (confirmed via get_indexes in the tool audit).
XSP_INDEX_INSTRUMENT_ID = "b8ae3ed3-7f82-4c77-adb4-f25f2cab6a4e"
# XSP listed strikes are $5 apart near the money.
XSP_STRIKE_STEP = 5.0


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class RhMcpConfig:
    agentic_account_id: str = ""
    mcp_url: str = "https://agent.robinhood.com/mcp/trading"
    token_path: Path = field(
        default_factory=lambda: ROOT / ".local/robinhood_mcp_token.json"
    )
    allowed_chain_symbols: tuple[str, ...] = ("XSP", "SPX")
    live_exits: bool = False
    live_entries: bool = False
    max_contracts_per_order: int = 1
    require_review_before_place: bool = True
    audit_log: Path = field(default_factory=lambda: ROOT / "logs/rh_mcp_audit.jsonl")

    @classmethod
    def load(cls, path: Path | None = None) -> RhMcpConfig:
        import yaml

        cfg_path = path or DEFAULT_CONFIG
        data: dict[str, Any] = {}
        if cfg_path.is_file():
            data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        token_raw = str(data.get("token_path") or ".local/robinhood_mcp_token.json")
        audit_raw = str(data.get("audit_log") or "logs/rh_mcp_audit.jsonl")
        symbols = data.get("allowed_chain_symbols") or ["XSP", "SPX"]
        account = os.getenv("RH_AGENTIC_ACCOUNT_ID", "").strip() or str(
            data.get("agentic_account_id") or ""
        )
        return cls(
            agentic_account_id=account,
            mcp_url=str(data.get("mcp_url") or cls.mcp_url),
            token_path=(ROOT / token_raw).resolve()
            if not Path(token_raw).is_absolute()
            else Path(token_raw),
            allowed_chain_symbols=tuple(str(s).upper() for s in symbols),
            live_exits=bool(data.get("live_exits", False)),
            live_entries=bool(data.get("live_entries", False)),
            max_contracts_per_order=int(data.get("max_contracts_per_order") or 1),
            require_review_before_place=bool(
                data.get("require_review_before_place", True)
            ),
            audit_log=(ROOT / audit_raw).resolve()
            if not Path(audit_raw).is_absolute()
            else Path(audit_raw),
        )


def _live_flag(env_name: str, cfg_value: bool, config: RhMcpConfig | None) -> bool:
    env = os.getenv(env_name, "").strip().lower()
    if env in ("1", "true", "yes"):
        flag = True
    elif env in ("0", "false", "no"):
        flag = False
    else:
        flag = cfg_value
    if not flag:
        return False
    cfg = config or RhMcpConfig.load()
    account = os.getenv("RH_AGENTIC_ACCOUNT_ID", "").strip() or cfg.agentic_account_id
    return bool(account)


def live_exits_enabled(*, config: RhMcpConfig | None = None) -> bool:
    cfg = config or RhMcpConfig.load()
    return _live_flag("XSP_LANE_A_LIVE_EXITS", cfg.live_exits, cfg)


def live_entries_enabled(*, config: RhMcpConfig | None = None) -> bool:
    """True when live buy-to-open entries are authorized (separate from exits).

    Requires ``XSP_LANE_A_LIVE_ENTRIES`` (or config) true AND a pinned account.
    """
    cfg = config or RhMcpConfig.load()
    return _live_flag("XSP_LANE_A_LIVE_ENTRIES", cfg.live_entries, cfg)


def _load_token(token_path: Path) -> dict[str, Any]:
    if not token_path.is_file():
        raise RhMcpNotReady(
            f"rh_mcp: token missing at {token_path} — complete desktop OAuth first "
            "(see docs/rh_mcp_runbook.md)"
        )
    try:
        data = json.loads(token_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RhMcpNotReady(
            f"rh_mcp: invalid token JSON at {token_path}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise RhMcpNotReady(f"rh_mcp: token file must be a JSON object: {token_path}")
    return data


def _extract_bearer(token: dict[str, Any]) -> str:
    for key in ("access_token", "token", "bearer"):
        val = token.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    raise RhMcpNotReady(
        "rh_mcp: token file missing access_token — re-export from desktop OAuth session"
    )


def normalize_mcp_position(row: dict[str, Any]) -> dict[str, Any]:
    """Map MCP position payload toward robin_stocks-shaped dicts for monitors."""
    chain = str(
        row.get("chain_symbol")
        or row.get("symbol")
        or row.get("underlying_symbol")
        or ""
    ).upper()
    option_type = str(row.get("type") or row.get("option_type") or "").lower()
    if option_type in ("call", "put"):
        pass
    elif row.get("direction") in ("long", "short"):
        option_type = str(row.get("option_type") or row.get("type") or "").lower()
    strike = row.get("strike_price") or row.get("strike")
    exp = row.get("expiration_date") or row.get("expiration")
    qty = row.get("quantity") or row.get("qty") or row.get("contracts")
    avg = (
        row.get("average_price") or row.get("average_open_price") or row.get("avg_cost")
    )
    # Preserve mark_price=0.0 (do not use falsy ``or`` — zero is a valid mark).
    mark = None
    for key in ("mark_price", "adjusted_mark_price", "mark"):
        if key in row and row[key] is not None:
            mark = row[key]
            break
    oid = row.get("option_id") or row.get("id") or row.get("instrument_id")
    out = dict(row)
    out.update(
        {
            "chain_symbol": chain,
            "type": option_type,
            "strike_price": strike,
            "expiration_date": exp,
            "quantity": qty,
            "average_price": avg,
            "mark_price": mark,
            "option_id": oid,
            "_source": "rh_mcp",
        }
    )
    return out


def _normalize_legs(order: dict[str, Any]) -> list[dict[str, Any]]:
    """Canonical legs list for grant matching (real ``legs[]`` or flat fallback)."""
    legs = order.get("legs")
    if isinstance(legs, list) and legs:
        out: list[dict[str, Any]] = []
        for leg in legs:
            if not isinstance(leg, dict):
                continue
            out.append(
                {
                    "option_id": leg.get("option_id") or leg.get("id"),
                    "side": str(leg.get("side") or "").lower(),
                    "position_effect": str(leg.get("position_effect") or "").lower(),
                    "ratio_quantity": int(leg.get("ratio_quantity") or 1),
                }
            )
        return out
    # Backward-compatible flat single-leg shape.
    if order.get("option_id") or order.get("side"):
        return [
            {
                "option_id": order.get("option_id"),
                "side": str(order.get("side") or "").lower(),
                "position_effect": str(order.get("position_effect") or "").lower(),
                "ratio_quantity": int(order.get("ratio_quantity") or 1),
            }
        ]
    return []


def _review_grant_key(order: dict[str, Any]) -> str:
    payload = {
        "account_number": order.get("account_number") or order.get("account_id"),
        "type": order.get("type"),
        "quantity": str(order.get("quantity"))
        if order.get("quantity") is not None
        else None,
        "price": str(order.get("price")) if order.get("price") is not None else None,
        "stop_price": str(order.get("stop_price"))
        if order.get("stop_price") is not None
        else None,
        "legs": _normalize_legs(order),
    }
    payload = {k: v for k, v in payload.items() if v not in (None, [], "")}
    return json.dumps(payload, sort_keys=True, default=str)


def _review_outcome_approved(result: Any) -> tuple[bool, str]:
    """Return (approved, reason) for a ``review_option_order`` business outcome.

    Fail closed unless the result is a dict with no rejection/warning/error
    signals and no failing ``order_checks`` entries. Transport success alone
    does not authorize a place grant (HCP I2).
    """
    if not isinstance(result, dict):
        return False, "review result is not a dict"
    if result.get("isError") is True:
        return False, "review isError=true"
    if result.get("ok") is False:
        return False, "review ok=false"
    if result.get("approved") is False:
        return False, "review approved=false"
    warnings = result.get("warnings")
    if warnings:
        return False, f"review warnings present: {warnings!r}"
    errors = result.get("errors")
    if errors:
        return False, f"review errors present: {errors!r}"
    if result.get("rejected"):
        return False, f"review rejected: {result.get('rejected')!r}"
    rejection_reason = result.get("rejection_reason")
    if rejection_reason:
        return False, f"review rejection_reason: {rejection_reason!r}"
    order_checks = result.get("order_checks")
    if order_checks:
        checks = order_checks if isinstance(order_checks, list) else [order_checks]
        for check in checks:
            if isinstance(check, dict):
                tokens = " ".join(
                    str(check.get(k) or "")
                    for k in ("status", "result", "state", "outcome", "code", "name")
                ).lower()
            else:
                tokens = str(check).lower()
            if any(tok in tokens for tok in ("fail", "block", "reject")):
                return False, f"review order_checks indicate failure: {check!r}"
    return True, ""


def _session_principal(
    token_data: dict[str, Any] | None,
    *,
    config: RhMcpConfig,
) -> dict[str, Any]:
    account = (
        os.getenv("RH_AGENTIC_ACCOUNT_ID", "").strip() or config.agentic_account_id
    )
    subject = None
    if isinstance(token_data, dict):
        subject = token_data.get("sub") or token_data.get("user_id")
    return {
        "agentic_account_id": account or None,
        "token_subject": subject,
    }


class RobinhoodMCPAdapter:
    """HTTP MCP client with tool allowlist, audit log, and write gates."""

    def __init__(
        self,
        config: RhMcpConfig | None = None,
        *,
        http_post: Callable[..., Any] | None = None,
    ) -> None:
        self.config = config or RhMcpConfig.load()
        self._http_post = http_post or self._default_http_post
        self._last_review: dict[str, Any] | None = None
        self._active_grant: dict[str, Any] | None = None
        self.last_read_wrap: dict[str, Any] | None = None
        self._principal: dict[str, Any] = _session_principal(None, config=self.config)

    def _default_http_post(
        self, url: str, body: bytes, headers: dict[str, str]
    ) -> dict[str, Any]:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RhMcpError(f"rh_mcp HTTP {exc.code}: {detail[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RhMcpError(f"rh_mcp network error: {exc}") from exc
        return parse_mcp_http_response(raw)

    def _audit(
        self,
        tool: str,
        arguments: dict[str, Any],
        *,
        ok: bool,
        result: Any = None,
        error: str | None = None,
        event: str = "allow",
        invariant: str | None = None,
    ) -> None:
        path = self.config.audit_log
        path.parent.mkdir(parents=True, exist_ok=True)
        row: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "tool": tool,
            "ok": ok,
            "arguments": arguments,
            "principal": self._principal,
        }
        if invariant:
            row["invariant"] = invariant
        if error:
            row["error"] = error
        if ok and tool in READ_TOOLS:
            if isinstance(result, list):
                row["result_count"] = len(result)
            elif isinstance(result, dict):
                row["result_keys"] = sorted(result.keys())[:20]
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")

    def _audit_deny(
        self,
        tool: str,
        arguments: dict[str, Any],
        *,
        reason: str,
        invariant: str,
    ) -> None:
        """HCP I7 — deny-path audit with principal + capability + reason."""
        self._audit(
            tool,
            arguments,
            ok=False,
            error=reason,
            event="deny",
            invariant=invariant,
        )

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        if name not in ALLOWED_TOOLS:
            self._audit_deny(
                name,
                arguments or {},
                reason=f"rh_mcp tool not allowlisted: {name}",
                invariant="I5",
            )
            raise RhMcpError(f"rh_mcp tool not allowlisted: {name}")
        args = arguments or {}
        if name in WRITE_TOOLS:
            self._enforce_write_gates(name, args)
        token_data = _load_token(self.config.token_path)
        self._principal = _session_principal(token_data, config=self.config)
        bearer = _extract_bearer(token_data)
        payload = {
            "jsonrpc": MCP_JSONRPC_VERSION,
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {bearer}",
        }
        try:
            response = self._http_post(
                self.config.mcp_url,
                json.dumps(payload).encode("utf-8"),
                headers,
            )
            result = self._unwrap_tool_result(response)
            if name in READ_TOOLS:
                confidence, hazard_class, signals = classify_mcp_read_confidence(
                    result,
                    tool=name,
                )
                wrapped = wrap_tool_result(
                    result,
                    confidence=confidence,
                    signals=signals,
                    hazard_class=hazard_class,
                )
                self.last_read_wrap = wrapped
                self._audit(name, args, ok=True, result=result)
                return wrapped
            self._audit(name, args, ok=True, result=result)
            if name == "review_option_order":
                self._last_review = {"arguments": args, "result": result}
                approved, reject_reason = _review_outcome_approved(result)
                if approved:
                    self._active_grant = {
                        "grant_id": secrets.token_hex(8),
                        "order_key": _review_grant_key(args),
                        "ts": datetime.now(timezone.utc).isoformat(),
                    }
                else:
                    self._active_grant = None
                    self._audit(
                        name,
                        args,
                        ok=False,
                        error=reject_reason,
                        event="review_rejected",
                        invariant="I2",
                    )
            if name == "place_option_order":
                self._active_grant = None
            return result
        except Exception as exc:
            self._audit(name, args, ok=False, error=str(exc))
            raise

    @staticmethod
    def _unwrap_tool_result(response: dict[str, Any]) -> Any:
        if "error" in response:
            err = response["error"]
            if isinstance(err, dict):
                raise RhMcpError(
                    f"rh_mcp tool error: {err.get('message') or err.get('code') or err}"
                )
            raise RhMcpError(f"rh_mcp tool error: {err}")
        result = response.get("result")
        if isinstance(result, dict):
            content = result.get("content")
            if isinstance(content, list):
                texts = [
                    c.get("text")
                    for c in content
                    if isinstance(c, dict) and c.get("type") == "text"
                ]
                if len(texts) == 1:
                    try:
                        return json.loads(texts[0])
                    except (json.JSONDecodeError, TypeError):
                        return texts[0]
            structured = result.get("structuredContent")
            if structured is not None:
                return structured
        return result

    def _enforce_write_gates(self, name: str, args: dict[str, Any]) -> None:
        if name == "place_option_order":
            if kill_switch_engaged():
                reason = (
                    "rh_mcp: place_option_order blocked — kill switch engaged "
                    "(unset XSP_LANE_A_KILL_SWITCH / remove kill file to resume)"
                )
                self._audit_deny(name, args, reason=reason, invariant="I8")
                raise RhMcpKillSwitch(reason)
            # Entries (buy-to-open) and exits (sell-to-close) are gated by
            # separate flags. Every leg must set position_effect to exactly
            # open or close — unknown/empty effects are denied (I7).
            effects = {
                str(leg.get("position_effect") or "").lower()
                for leg in _normalize_legs(args)
            }
            bad_effect = not effects or any(
                effect not in {"open", "close"} for effect in effects
            )
            if bad_effect:
                reason = (
                    "rh_mcp: place_option_order requires explicit position_effect "
                    "open or close on every leg"
                )
                self._audit_deny(name, args, reason=reason, invariant="I7")
                raise RhMcpError(reason)
            pinned = self.config.agentic_account_id
            if not pinned:
                reason = (
                    "rh_mcp: place_option_order blocked — "
                    "agentic_account_id / RH_AGENTIC_ACCOUNT_ID required"
                )
                self._audit_deny(name, args, reason=reason, invariant="I3")
                raise RhMcpAccountRejected(reason)
            needs_entry = "open" in effects
            needs_exit = "close" in effects
            if needs_entry and not live_entries_enabled(config=self.config):
                reason = (
                    "rh_mcp: place_option_order (open) blocked — "
                    "set XSP_LANE_A_LIVE_ENTRIES=true "
                    "and RH_AGENTIC_ACCOUNT_ID after operator GO"
                )
                self._audit_deny(name, args, reason=reason, invariant="I7")
                raise RhMcpLiveExitsDisabled(reason)
            if needs_exit and not live_exits_enabled(config=self.config):
                reason = (
                    "rh_mcp: place_option_order (close) blocked — "
                    "set XSP_LANE_A_LIVE_EXITS=true "
                    "and RH_AGENTIC_ACCOUNT_ID after operator GO"
                )
                self._audit_deny(name, args, reason=reason, invariant="I7")
                raise RhMcpLiveExitsDisabled(reason)
            qty = args.get("quantity") or args.get("contracts") or 1
            try:
                qty_n = float(qty)
            except (TypeError, ValueError):
                qty_n = 1.0
            # Effective contracts = order quantity * max leg ratio_quantity.
            max_ratio = 1
            for leg in _normalize_legs(args):
                max_ratio = max(max_ratio, int(leg.get("ratio_quantity") or 1))
            effective = qty_n * max_ratio
            if effective > self.config.max_contracts_per_order:
                reason = (
                    f"rh_mcp: quantity {effective} exceeds max_contracts_per_order "
                    f"{self.config.max_contracts_per_order}"
                )
                self._audit_deny(name, args, reason=reason, invariant="I5")
                raise RhMcpError(reason)
            account = str(
                args.get("account_number")
                or args.get("account_id")
                or args.get("account")
                or ""
            )
            if account and account != pinned:
                reason = (
                    f"rh_mcp: order account {account!r} != pinned Agentic {pinned!r}"
                )
                self._audit_deny(name, args, reason=reason, invariant="I3")
                raise RhMcpAccountRejected(reason)
            if self.config.require_review_before_place:
                grant_key = _review_grant_key(args)
                if self._active_grant is None:
                    self._audit_deny(
                        name,
                        args,
                        reason=(
                            "rh_mcp: place_option_order requires "
                            "prior review_option_order"
                        ),
                        invariant="I2",
                    )
                    raise RhMcpError(
                        "rh_mcp: place_option_order requires prior review_option_order"
                    )
                if self._active_grant.get("order_key") != grant_key:
                    self._audit_deny(
                        name,
                        args,
                        reason="rh_mcp: place_option_order grant does not match review",
                        invariant="I2",
                    )
                    raise RhMcpError(
                        "rh_mcp: place_option_order grant does not match review"
                    )

    def get_accounts(self) -> list[dict[str, Any]]:
        wrapped = self.call_tool("get_accounts", {})
        raw = unwrap_tool_result(wrapped)
        if isinstance(raw, dict):
            accounts = raw.get("accounts") or raw.get("data", {}).get("accounts")
            if isinstance(accounts, list):
                return [a for a in accounts if isinstance(a, dict)]
        if isinstance(raw, list):
            return [a for a in raw if isinstance(a, dict)]
        return []

    def resolve_account_number(self) -> str:
        pinned = (
            os.getenv("RH_AGENTIC_ACCOUNT_ID", "").strip()
            or self.config.agentic_account_id
        )
        if pinned:
            return pinned
        accounts = self.get_accounts()
        for acct in accounts:
            nickname = str(acct.get("nickname") or "").lower()
            label = str(
                acct.get("brokerage_account_type")
                or acct.get("account_type")
                or acct.get("type")
                or ""
            ).lower()
            if "agentic" in nickname or "agentic" in label:
                num = acct.get("account_number") or acct.get("rhs_account_number")
                if num:
                    return str(num)
        if len(accounts) == 1:
            num = accounts[0].get("account_number") or accounts[0].get(
                "rhs_account_number"
            )
            if num:
                return str(num)
        raise RhMcpNotReady(
            "rh_mcp: set RH_AGENTIC_ACCOUNT_ID — multiple accounts and no Agentic pin"
        )

    def get_open_option_positions(
        self,
        *,
        chain_symbols: tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        account_number = self.resolve_account_number()
        raw = self.call_tool(
            "get_option_positions",
            {"account_number": account_number},
        )
        raw = unwrap_tool_result(raw)
        rows: list[Any]
        if isinstance(raw, list):
            rows = raw
        elif isinstance(raw, dict):
            rows = raw.get("results") or raw.get("positions") or raw.get("data") or []
            if isinstance(rows, dict):
                rows = list(rows.values())
        else:
            rows = []
        allowed = {
            s.upper() for s in chain_symbols or self.config.allowed_chain_symbols
        }
        out: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            normalized = normalize_mcp_position(row)
            chain = str(normalized.get("chain_symbol") or "").upper()
            if allowed and chain and chain not in allowed:
                continue
            out.append(normalized)
        return out

    def get_option_chains(self, underlying_symbol: str) -> dict[str, Any]:
        """Chain metadata + expirations for one underlying.

        MCP expects ``underlying_symbol`` (single string), not ``chain_symbol``.
        Returns the matching chain dict (from ``data.chains[]``) or ``{}``.
        """
        symbol = str(underlying_symbol).upper()
        wrapped = self.call_tool(
            "get_option_chains",
            {"underlying_symbol": symbol},
        )
        raw = unwrap_tool_result(wrapped)
        chains: list[Any] = []
        if isinstance(raw, dict):
            data = raw.get("data")
            if isinstance(data, dict) and isinstance(data.get("chains"), list):
                chains = data["chains"]
            elif isinstance(raw.get("chains"), list):
                chains = raw["chains"]
            elif raw.get("symbol") or raw.get("chain_id"):
                return raw
        elif isinstance(raw, list):
            chains = raw
        for chain in chains:
            if not isinstance(chain, dict):
                continue
            if str(chain.get("symbol") or "").upper() == symbol:
                return chain
        if chains and isinstance(chains[0], dict):
            return chains[0]
        return {}

    def list_option_instruments(self, chain_symbol: str) -> list[dict[str, Any]]:
        """Flat list of option instrument dicts for ``chain_symbol``."""
        wrapped = self.call_tool(
            "get_option_instruments",
            {"chain_symbol": str(chain_symbol).upper()},
        )
        raw = unwrap_tool_result(wrapped)
        out: list[dict[str, Any]] = []

        def _collect(node: Any) -> None:
            if isinstance(node, dict):
                if node.get("id") and node.get("strike_price") and node.get("type"):
                    out.append(node)
                for value in node.values():
                    _collect(value)
            elif isinstance(node, list):
                for item in node:
                    _collect(item)

        _collect(raw)
        return out

    def index_level(self, underlying: str = "XSP") -> float | None:
        """Current index level for ``underlying`` (XSP via known instrument id)."""
        if underlying.upper() != "XSP":
            return None
        raw = unwrap_tool_result(
            self.call_tool(
                "get_index_quotes", {"instrument_ids": [XSP_INDEX_INSTRUMENT_ID]}
            )
        )
        level: float | None = None

        def _walk(node: Any) -> None:
            nonlocal level
            if isinstance(node, dict):
                for key in ("last_trade_price", "price", "value", "mark_price"):
                    got = _to_float(node.get(key))
                    if got:
                        level = got
                for value in node.values():
                    _walk(value)
            elif isinstance(node, list):
                for item in node:
                    _walk(item)

        _walk(raw)
        return level

    def quote_options(self, instrument_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Map instrument_id -> quote dict (bid/ask/mark) for the given ids."""
        if not instrument_ids:
            return {}
        raw = unwrap_tool_result(
            self.call_tool("get_option_quotes", {"instrument_ids": instrument_ids})
        )
        quotes: dict[str, dict[str, Any]] = {}

        def _walk(node: Any) -> None:
            if isinstance(node, dict):
                iid = node.get("instrument_id")
                if iid and ("ask_price" in node or "bid_price" in node):
                    quotes[str(iid)] = node
                for value in node.values():
                    _walk(value)
            elif isinstance(node, list):
                for item in node:
                    _walk(item)

        _walk(raw)
        return quotes

    def instruments_for_strike(
        self, underlying: str, expiration: str, option_type: str, strike: float
    ) -> list[dict[str, Any]]:
        raw = unwrap_tool_result(
            self.call_tool(
                "get_option_instruments",
                {
                    "chain_symbol": underlying.upper(),
                    "expiration_dates": expiration,
                    "type": option_type,
                    "strike_price": f"{float(strike):.4f}",
                    "tradability": "tradable",
                },
            )
        )
        out: list[dict[str, Any]] = []

        def _collect(node: Any) -> None:
            if isinstance(node, dict):
                if node.get("id") and node.get("strike_price"):
                    out.append(node)
                for value in node.values():
                    _collect(value)
            elif isinstance(node, list):
                for item in node:
                    _collect(item)

        _collect(raw)
        return out

    def get_buying_power(self, account_number: str | None = None) -> float:
        """Available options buying power (cash) for the pinned Agentic account."""
        account = account_number or self.resolve_account_number()
        raw = unwrap_tool_result(
            self.call_tool("get_portfolio", {"account_number": account})
        )
        best: float | None = None

        def _walk(node: Any) -> None:
            nonlocal best
            if isinstance(node, dict):
                for key in ("buying_power", "unleveraged_buying_power", "cash"):
                    got = _to_float(node.get(key))
                    if got is not None and (best is None or got < best):
                        # Take the most conservative (smallest) reported figure.
                        best = got
                for value in node.values():
                    _walk(value)
            elif isinstance(node, list):
                for item in node:
                    _walk(item)

        _walk(raw)
        return best if best is not None else 0.0

    def select_entry_contract(
        self,
        *,
        underlying: str = "XSP",
        option_type: str = "call",
        dte_min: int = 14,
        dte_max: int = 60,
        dte_pick: str = "min",
        dte_target: int | None = None,
        atm_steps: int = 1,
        strike_pick: str = "cheapest_near_atm",
        today: date | None = None,
    ) -> dict[str, Any]:
        """Pick the real option contract matching the Lane A entry rules.

        Returns ``{instrument_id, strike, expiration_date, dte, bid, ask,
        mark}`` for the chosen contract. Raises ``RhMcpError`` if no tradable,
        quotable contract fits the DTE/strike window.
        """
        today = today or datetime.now(timezone.utc).date()
        chain = self.get_option_chains(underlying)
        exps = chain.get("expiration_dates") or []
        dated: list[tuple[int, str]] = []
        for exp in exps:
            try:
                dte = (date.fromisoformat(str(exp)) - today).days
            except ValueError:
                continue
            if dte_min <= dte <= dte_max:
                dated.append((dte, str(exp)))
        if not dated:
            raise RhMcpError(
                f"rh_mcp entry: no {underlying} expiration in DTE [{dte_min},{dte_max}]"
            )
        dated.sort()
        dte_mode = (dte_pick or "min").strip().lower()
        if dte_mode == "max":
            dte, expiration = dated[-1]
        elif dte_mode == "target" and dte_target is not None:
            dte, expiration = min(dated, key=lambda x: abs(x[0] - dte_target))
        else:
            dte, expiration = dated[0]
        level = self.index_level(underlying)
        if not level:
            raise RhMcpError(f"rh_mcp entry: no index level for {underlying}")
        atm = round(level / XSP_STRIKE_STEP) * XSP_STRIKE_STEP
        strike_mode = (strike_pick or "cheapest_near_atm").strip().lower()
        otm_target = atm + XSP_STRIKE_STEP * max(1, int(atm_steps))
        strikes = [atm + XSP_STRIKE_STEP * k for k in range(-atm_steps, atm_steps + 1)]
        candidates: list[dict[str, Any]] = []
        for strike in strikes:
            candidates.extend(
                self.instruments_for_strike(underlying, expiration, option_type, strike)
            )
        if not candidates:
            raise RhMcpError(
                f"rh_mcp entry: no tradable {underlying} {option_type} near {atm}"
            )
        quotes = self.quote_options([c["id"] for c in candidates])
        enriched: list[dict[str, Any]] = []
        for cand in candidates:
            quote = quotes.get(str(cand["id"]), {})
            ask = _to_float(quote.get("ask_price"))
            if not ask or ask <= 0:
                continue
            enriched.append(
                {
                    "instrument_id": str(cand["id"]),
                    "strike": _to_float(cand.get("strike_price")),
                    "expiration_date": expiration,
                    "dte": dte,
                    "bid": _to_float(quote.get("bid_price")),
                    "ask": ask,
                    "mark": _to_float(quote.get("mark_price")),
                }
            )
        if not enriched:
            raise RhMcpError(
                f"rh_mcp entry: no quotable {underlying} {option_type} near {atm}"
            )
        if strike_mode == "cheapest_near_atm":
            # Match paper pick_cheapest_atm_strike: nearest to index level
            # first, lowest ask only as a tiebreak.
            return min(
                enriched,
                key=lambda c: (abs((c["strike"] or 0.0) - level), c["ask"]),
            )
        if strike_mode == "otm_one" and option_type.strip().lower() == "call":
            return min(enriched, key=lambda c: abs((c["strike"] or 0.0) - otm_target))
        return min(enriched, key=lambda c: abs((c["strike"] or 0.0) - atm))

    def buy_to_open(
        self,
        *,
        instrument_id: str,
        limit_price: float,
        quantity: int = 1,
        time_in_force: str = "gfd",
        ref_id: str | None = None,
    ) -> dict[str, Any]:
        """Review then place a buy-to-open limit order (gated by write gates)."""
        base = {
            "legs": [
                {
                    "option_id": instrument_id,
                    "side": "buy",
                    "position_effect": "open",
                    "ratio_quantity": 1,
                }
            ],
            "type": "limit",
            "quantity": str(int(quantity)),
            "price": f"{float(limit_price):.2f}",
            "time_in_force": time_in_force,
        }
        review = self.review_option_order(base)
        place_order = dict(base)
        if ref_id:
            place_order["ref_id"] = ref_id
        placed = self.place_option_order(place_order)
        return {"review": review, "placed": placed}

    def phase1_canary_review(
        self, *, underlying: str = "XSP", option_type: str = "call"
    ) -> dict[str, Any]:
        """Live ``review_option_order`` proof-of-life — never places an order.

        Previews a 1-contract buy-to-open on the soonest-expiry tradable
        option at a far-below-market limit. Validates the OAuth token, the MCP
        endpoint and the ``legs[]`` order schema continuously while the account
        holds no positions to review. No order is placed (review only).
        """
        instruments = self.list_option_instruments(underlying)
        tradable = [
            it
            for it in instruments
            if str(it.get("type")) == option_type
            and str(it.get("tradability")) == "tradable"
        ]
        tradable.sort(
            key=lambda it: (
                str(it.get("expiration_date") or "9999-12-31"),
                float(it.get("strike_price") or 0.0),
            )
        )
        if not tradable:
            raise RhMcpError(
                f"rh_mcp phase1 canary: no tradable {underlying} {option_type}"
            )
        inst = tradable[0]
        order = {
            "legs": [
                {
                    "option_id": inst["id"],
                    "side": "buy",
                    "position_effect": "open",
                    "ratio_quantity": 1,
                }
            ],
            "type": "limit",
            "quantity": "1",
            "price": "0.05",
            "time_in_force": "gfd",
        }
        review = self.review_option_order(order)
        return {
            "instrument_id": inst["id"],
            "expiration_date": inst.get("expiration_date"),
            "strike_price": inst.get("strike_price"),
            "review": review,
        }

    def _inject_account(self, order: dict[str, Any]) -> dict[str, Any]:
        patched = dict(order)
        if self.config.agentic_account_id and not (
            patched.get("account_number") or patched.get("account_id")
        ):
            patched["account_number"] = self.config.agentic_account_id
        return patched

    def review_option_order(self, order: dict[str, Any]) -> dict[str, Any]:
        result = self.call_tool("review_option_order", self._inject_account(order))
        return result if isinstance(result, dict) else {"result": result}

    def place_option_order(self, order: dict[str, Any]) -> dict[str, Any]:
        # K37 Phase 1: log-only reviewer shadow. Never blocks; strategy untouched.
        lane_id = str(order.get("lane_id") or "lane_a")
        shadow_review_order(
            "place_option_order",
            order,
            lane_id=lane_id,
        )
        result = self.call_tool("place_option_order", self._inject_account(order))
        return result if isinstance(result, dict) else {"result": result}

    def last_read_confidence(self) -> dict[str, Any] | None:
        return self.last_read_wrap


def last_mcp_fetch_confidence() -> dict[str, Any] | None:
    """Confidence wrapper from the most recent MCP positions fetch."""
    return _last_mcp_fetch_wrap


def fetch_option_positions_via_mcp() -> tuple[list[dict[str, Any]], str | None]:
    """Return MCP option positions or ( [], error ) when not ready."""
    global _last_mcp_fetch_wrap
    if not rh_mcp_enabled():
        _last_mcp_fetch_wrap = None
        return [], None
    try:
        adapter = RobinhoodMCPAdapter()
        rows = adapter.get_open_option_positions()
        _last_mcp_fetch_wrap = adapter.last_read_confidence()
        wrap = _last_mcp_fetch_wrap
        if wrap and not mcp_read_trusted(wrap):
            tier = fusion_tier(float(wrap.get("confidence") or 0.0))
            reason = f"MCP read confidence {tier} ({wrap.get('confidence')})"
            deny_path = adapter.config.audit_log
            deny_path.parent.mkdir(parents=True, exist_ok=True)
            deny_row = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "event": "deny",
                "tool": "get_option_positions",
                "ok": False,
                "invariant": "I6",
                "error": reason,
                "principal": adapter._principal,
                "confidence": wrap.get("confidence"),
                "hazard_class": wrap.get("hazard_class"),
            }
            with deny_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(deny_row, default=str) + "\n")
            return [], reason
        return rows, None
    except RhMcpNotReady as exc:
        return [], str(exc)
    except RhMcpError as exc:
        return [], str(exc)
    except Exception as exc:
        logger.exception("rh_mcp fetch failed")
        return [], str(exc)
