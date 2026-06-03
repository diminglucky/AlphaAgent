"""LLM token usage tracking."""
from __future__ import annotations

import json
import logging
import os
from contextlib import nullcontext
from typing import Any

from sqlalchemy.orm import Session

from apps.api.app.core.config import get_settings
from apps.api.app.db.models import LLMUsageORM
from apps.api.app.db.session import session_scope

log = logging.getLogger("quant.llm.usage")


def _int(v: Any) -> int:
    try:
        return int(v or 0)
    except Exception:
        return 0


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value or {}, ensure_ascii=False, default=str))


def _ctx(db: Session | None):
    return nullcontext(db) if db is not None else session_scope()


def _usage_tokens(usage: dict | None) -> tuple[int, int, int]:
    usage = usage or {}
    prompt = _int(
        usage.get("prompt_tokens")
        or usage.get("input_tokens")
        or usage.get("promptTokens")
        or usage.get("inputTokens")
    )
    completion = _int(
        usage.get("completion_tokens")
        or usage.get("output_tokens")
        or usage.get("completionTokens")
        or usage.get("outputTokens")
    )
    total = _int(usage.get("total_tokens") or usage.get("totalTokens"))
    if total <= 0:
        total = prompt + completion
    return prompt, completion, total


def estimate_cost_usd(prompt_tokens: int, completion_tokens: int) -> float:
    settings = get_settings()
    input_rate = float(os.getenv(
        "QUANT_LLM_INPUT_COST_PER_MILLION_TOKENS",
        str(settings.llm_input_cost_per_million_tokens),
    ))
    output_rate = float(os.getenv(
        "QUANT_LLM_OUTPUT_COST_PER_MILLION_TOKENS",
        str(settings.llm_output_cost_per_million_tokens),
    ))
    cost = (
        prompt_tokens * input_rate
        + completion_tokens * output_rate
    ) / 1_000_000
    return round(cost, 8)


def record_usage(
    *,
    provider: str,
    model: str,
    endpoint: str,
    usage: dict | None = None,
    source: str = "",
    success: bool = True,
    error: str = "",
    db: Session | None = None,
) -> None:
    """Best-effort usage recording. Never break the LLM call path."""
    try:
        prompt, completion, total = _usage_tokens(usage)
        with _ctx(db) as session:
            session.add(LLMUsageORM(
                provider=provider or "",
                model=model or "",
                endpoint=endpoint or "chat",
                source=source or "",
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=total,
                estimated_cost_usd=estimate_cost_usd(prompt, completion),
                raw_usage=_jsonable(usage),
                success=success,
                error=(error or "")[:1000],
            ))
    except Exception as exc:  # noqa: BLE001
        log.debug("record llm usage failed: %s", exc)


def usage_summary(*, limit: int = 100, db: Session | None = None) -> dict:
    with _ctx(db) as session:
        rows = (
            session.query(LLMUsageORM)
            .order_by(LLMUsageORM.created_at.desc())
            .limit(max(1, min(limit, 500)))
            .all()
        )
        total_prompt = sum(r.prompt_tokens for r in rows)
        total_completion = sum(r.completion_tokens for r in rows)
        total_tokens = sum(r.total_tokens for r in rows)
        total_cost = sum(r.estimated_cost_usd for r in rows)
        by_model: dict[str, dict] = {}
        for r in rows:
            key = f"{r.provider}/{r.model}"
            item = by_model.setdefault(key, {
                "provider": r.provider,
                "model": r.model,
                "calls": 0,
                "total_tokens": 0,
                "estimated_cost_usd": 0.0,
            })
            item["calls"] += 1
            item["total_tokens"] += r.total_tokens
            item["estimated_cost_usd"] = round(item["estimated_cost_usd"] + r.estimated_cost_usd, 8)

        return {
            "summary": {
                "calls": len(rows),
                "prompt_tokens": total_prompt,
                "completion_tokens": total_completion,
                "total_tokens": total_tokens,
                "estimated_cost_usd": round(total_cost, 8),
                "cost_configured": (
                    float(os.getenv(
                        "QUANT_LLM_INPUT_COST_PER_MILLION_TOKENS",
                        str(get_settings().llm_input_cost_per_million_tokens),
                    )) > 0
                    or float(os.getenv(
                        "QUANT_LLM_OUTPUT_COST_PER_MILLION_TOKENS",
                        str(get_settings().llm_output_cost_per_million_tokens),
                    )) > 0
                ),
            },
            "by_model": list(by_model.values()),
            "records": [
                {
                    "id": r.id,
                    "provider": r.provider,
                    "model": r.model,
                    "endpoint": r.endpoint,
                    "source": r.source,
                    "prompt_tokens": r.prompt_tokens,
                    "completion_tokens": r.completion_tokens,
                    "total_tokens": r.total_tokens,
                    "estimated_cost_usd": r.estimated_cost_usd,
                    "success": r.success,
                    "error": r.error,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ],
        }
