#!/usr/bin/env python3
"""Pre-market smoke test (Design Doc §10.4).

Run before market open to verify all critical paths:
1. Database connectivity
2. Market data provider responsiveness
3. QMT gateway connectivity (if configured)
4. Account / position sync
5. Recommendation pipeline
6. LLM API connectivity (if configured)
7. Risk engine loaded

Exits with code 0 on full pass, 1 on any failure.

Usage:
    python infra/scripts/smoke_test.py
    python infra/scripts/smoke_test.py --base-url http://localhost:8000
    python infra/scripts/smoke_test.py --json   # machine-readable output
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx


@dataclass
class CheckResult:
    name: str
    ok: bool
    duration_ms: float
    detail: str = ""
    error: Optional[str] = None


@dataclass
class SmokeReport:
    started_at: str
    base_url: str
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.ok for c in self.checks)

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "base_url": self.base_url,
            "all_passed": self.all_passed,
            "n_checks": len(self.checks),
            "n_passed": sum(1 for c in self.checks if c.ok),
            "checks": [
                {"name": c.name, "ok": c.ok, "duration_ms": round(c.duration_ms, 1),
                 "detail": c.detail, "error": c.error}
                for c in self.checks
            ],
        }


def _timed(fn):
    """Decorator to time a check function."""
    def wrapped(*args, **kw):
        t0 = time.monotonic()
        try:
            ok, detail = fn(*args, **kw)
            return CheckResult(
                name=fn.__name__.replace("check_", ""), ok=ok,
                duration_ms=(time.monotonic() - t0) * 1000, detail=detail,
            )
        except Exception as exc:  # noqa: BLE001
            return CheckResult(
                name=fn.__name__.replace("check_", ""), ok=False,
                duration_ms=(time.monotonic() - t0) * 1000,
                error=f"{type(exc).__name__}: {exc}",
            )
    return wrapped


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

@_timed
def check_health(client: httpx.Client) -> tuple[bool, str]:
    r = client.get("/api/v1/health", timeout=5)
    r.raise_for_status()
    data = r.json()
    return data.get("status") == "ok", f"{data}"


@_timed
def check_market_data(client: httpx.Client) -> tuple[bool, str]:
    r = client.get("/api/v1/market/instruments", timeout=10)
    r.raise_for_status()
    data = r.json()
    n = len(data) if isinstance(data, list) else len(data.get("instruments", []))
    return n > 0, f"{n} instruments returned"


@_timed
def check_realtime_quote(client: httpx.Client) -> tuple[bool, str]:
    r = client.get("/api/v1/market/quotes/realtime", params={"symbols": "600519.SH"}, timeout=10)
    r.raise_for_status()
    data = r.json()
    quotes = data if isinstance(data, list) else data.get("quotes", [])
    return len(quotes) > 0, f"{len(quotes)} quotes"


@_timed
def check_account_sync(client: httpx.Client) -> tuple[bool, str]:
    r = client.get("/api/v1/portfolio/summary", timeout=5)
    r.raise_for_status()
    data = r.json()
    return "total_asset" in data, f"total_asset={data.get('total_asset')}"


@_timed
def check_recommendation_pipeline(client: httpx.Client) -> tuple[bool, str]:
    r = client.get("/api/v1/recommendations/latest", timeout=15)
    r.raise_for_status()
    data = r.json()
    items = data.get("items", []) if isinstance(data, dict) else data
    return True, f"{len(items)} recommendations available"


@_timed
def check_risk_rules(client: httpx.Client) -> tuple[bool, str]:
    r = client.get("/api/v1/risk/rules", timeout=5)
    r.raise_for_status()
    data = r.json()
    rules = data if isinstance(data, list) else data.get("rules", [])
    return len(rules) > 0, f"{len(rules)} risk rules loaded"


@_timed
def check_background_loops(client: httpx.Client) -> tuple[bool, str]:
    r = client.get("/api/v1/ws/status", timeout=5)
    r.raise_for_status()
    data = r.json()
    feed = data.get("feed_running")
    advisor = data.get("advisor_running")
    scanner = data.get("scanner_running")
    monitor = data.get("monitor_running")
    all_running = all([feed, advisor, scanner, monitor])
    return all_running, (
        f"feed={feed} advisor={advisor} scanner={scanner} monitor={monitor}"
    )


@_timed
def check_llm_config(client: httpx.Client) -> tuple[bool, str]:
    r = client.get("/api/v1/llm/config", timeout=5)
    r.raise_for_status()
    data = r.json()
    eff = data.get("effective", {})
    available = eff.get("is_llm_available", False)
    provider = eff.get("provider", "?")
    # Pass even if not configured (fallback is acceptable),
    # but record clearly in the detail.
    if available:
        return True, f"LLM ready: {provider} / {eff.get('model')}"
    return True, f"LLM not configured (Agent fallback mode), provider={provider}"


@_timed
def check_agents_skills(client: httpx.Client) -> tuple[bool, str]:
    r = client.get("/api/v1/agents/skills", timeout=5)
    r.raise_for_status()
    data = r.json()
    return data.get("count", 0) >= 12, f"{data.get('count')} skills registered"


@_timed
def check_backtest_run(client: httpx.Client) -> tuple[bool, str]:
    """Verify POST /backtest/run returns metrics for a quick buy-hold run."""
    r = client.post(
        "/api/v1/backtest/run",
        json={"symbols": ["600519.SH"], "strategy": "buy_hold"},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    ok = data.get("ok") is True and "metrics" in data
    trades = len(data.get("trades", []))
    return ok, f"trades={trades} total_return={data.get('metrics', {}).get('total_return', '?')}"


@_timed
def check_walk_forward(client: httpx.Client) -> tuple[bool, str]:
    """Verify POST /backtest/walk-forward returns folds."""
    r = client.post(
        "/api/v1/backtest/walk-forward",
        json={
            "symbols": ["600519.SH"],
            "strategy": "buy_hold",
            "in_sample_bars": 60,
            "oos_bars": 20,
            "min_folds": 2,
        },
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    ok = data.get("ok") is True
    n = data.get("n_folds", 0)
    consistency = data.get("aggregate", {}).get("consistency_score", "?")
    return ok, f"n_folds={n} consistency={consistency}"


@_timed
def check_portfolio_rebalance(client: httpx.Client) -> tuple[bool, str]:
    """Verify POST /portfolio/rebalance returns a valid rebalancing plan."""
    r = client.post(
        "/api/v1/portfolio/rebalance",
        json={
            "signals": {"600519.SH": 0.8, "000001.SZ": 0.5},
            "prices": {"600519.SH": 1719.0, "000001.SZ": 12.5},
            "scheme": "signal_proportional",
        },
        headers={"Authorization": "Bearer trader-token"},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    ok = "actions" in data and "expected_turnover" in data
    n = len(data.get("actions", []))
    return ok, f"{n} rebalance actions, turnover={data.get('expected_turnover', '?'):.3f}"


@_timed
def check_qmt_gateway(client: httpx.Client) -> tuple[bool, str]:
    """QMT gateway status: passes if not configured (acceptable on Linux/Mac)."""
    # QMT gateway is a separate service on Windows; without explicit config
    # we treat absence as acceptable.
    import os
    qmt_url = os.getenv("QUANT_QMT_GATEWAY_URL", "")
    if not qmt_url:
        return True, "QMT gateway not configured (skipping live trade check)"
    try:
        r = httpx.get(qmt_url + "/health", timeout=3)
        return r.status_code == 200, f"qmt={qmt_url} status={r.status_code}"
    except Exception as exc:
        return False, f"qmt at {qmt_url} unreachable: {exc}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000",
                        help="API base URL")
    parser.add_argument("--json", action="store_true",
                        help="Output machine-readable JSON instead of text")
    args = parser.parse_args()

    from datetime import datetime
    report = SmokeReport(
        started_at=datetime.now().isoformat(), base_url=args.base_url,
    )

    with httpx.Client(base_url=args.base_url) as client:
        report.checks.extend([
            check_health(client),
            check_market_data(client),
            check_realtime_quote(client),
            check_account_sync(client),
            check_recommendation_pipeline(client),
            check_risk_rules(client),
            check_background_loops(client),
            check_llm_config(client),
            check_agents_skills(client),
            check_backtest_run(client),
            check_walk_forward(client),
            check_portfolio_rebalance(client),
            check_qmt_gateway(client),
        ])

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        _print_human(report)

    return 0 if report.all_passed else 1


def _print_human(report: SmokeReport) -> None:
    print(f"\n=== Pre-Market Smoke Test === {report.started_at}")
    print(f"Target: {report.base_url}\n")
    width = 32
    for c in report.checks:
        status = "✓ PASS" if c.ok else "✗ FAIL"
        marker = "\033[32m" if c.ok else "\033[31m"
        reset = "\033[0m"
        ms = f"{c.duration_ms:6.1f}ms"
        print(f"  {marker}{status}{reset}  {c.name:<{width}} {ms}  {c.detail or c.error or ''}")
    n_pass = sum(1 for c in report.checks if c.ok)
    print(f"\n{'-'*60}")
    if report.all_passed:
        print(f"\033[32m✓ ALL CHECKS PASSED ({n_pass}/{len(report.checks)})\033[0m\n")
    else:
        print(f"\033[31m✗ {len(report.checks)-n_pass} CHECK(S) FAILED ({n_pass}/{len(report.checks)})\033[0m\n")


if __name__ == "__main__":
    sys.exit(main())
