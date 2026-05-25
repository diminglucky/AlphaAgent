from apps.api.app.services import feishu_service


def test_send_feishu_returns_false_when_unconfigured(monkeypatch) -> None:
    from apps.api.app.core.config import Settings

    monkeypatch.setattr(
        feishu_service,
        "get_settings",
        lambda: Settings(feishu_webhook_url=""),
    )

    assert feishu_service.send_feishu("title", "content") is False


def test_send_feishu_submits_when_configured(monkeypatch) -> None:
    from apps.api.app.core.config import Settings

    submitted = {}

    class FakePool:
        def submit(self, fn, payload, title, webhook_url):
            submitted["title"] = title
            submitted["webhook_url"] = webhook_url
            submitted["payload"] = payload

    monkeypatch.setattr(
        feishu_service,
        "get_settings",
        lambda: Settings(feishu_webhook_url="https://example.test/hook"),
    )
    monkeypatch.setattr(feishu_service, "_feishu_pool", FakePool())

    assert feishu_service.send_feishu("title", "content") is True
    assert submitted["title"] == "title"
    assert submitted["webhook_url"] == "https://example.test/hook"
