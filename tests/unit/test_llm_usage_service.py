from apps.api.app.db.models import LLMUsageORM
from apps.api.app.services import llm_usage_service


def test_record_usage_persists_tokens_and_configured_cost(db_session, monkeypatch) -> None:
    from apps.api.app.core import config as config_mod

    monkeypatch.setenv("QUANT_LLM_INPUT_COST_PER_MILLION_TOKENS", "1.0")
    monkeypatch.setenv("QUANT_LLM_OUTPUT_COST_PER_MILLION_TOKENS", "2.0")
    config_mod.reset_settings_cache()

    llm_usage_service.record_usage(
        provider="deepseek",
        model="deepseek-chat",
        endpoint="chat",
        usage={"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
        source="test",
        db=db_session,
    )

    row = db_session.query(LLMUsageORM).one()
    assert row.prompt_tokens == 1000
    assert row.completion_tokens == 500
    assert row.total_tokens == 1500
    assert row.estimated_cost_usd == 0.002

    summary = llm_usage_service.usage_summary(limit=10, db=db_session)
    assert summary["summary"]["total_tokens"] == 1500
    assert summary["summary"]["cost_configured"] is True

    config_mod.reset_settings_cache()
