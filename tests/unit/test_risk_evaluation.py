from apps.api.app.db.models import PositionORM
from apps.api.app.services import alert_service


def test_check_position_alerts_ignores_zero_price(db_session, monkeypatch) -> None:
    db_session.add(PositionORM(symbol="600519.SH", name="贵州茅台", quantity=100, avg_cost=100.0))
    db_session.commit()
    monkeypatch.setattr(alert_service.feishu_service, "send_sell_alert", lambda **kwargs: True)

    triggered = alert_service.check_position_alerts(
        db_session,
        [{"symbol": "600519.SH", "price": 0}],
    )

    assert triggered == []


def test_check_position_alerts_triggers_stop_loss(db_session, monkeypatch) -> None:
    db_session.add(PositionORM(symbol="600519.SH", name="贵州茅台", quantity=100, avg_cost=100.0))
    db_session.commit()
    alert_service.reset_position_alert_state()
    monkeypatch.setattr(alert_service.feishu_service, "send_sell_alert", lambda **kwargs: True)

    triggered = alert_service.check_position_alerts(
        db_session,
        [{"symbol": "600519.SH", "name": "贵州茅台", "price": 90.0}],
    )

    assert len(triggered) == 1
    assert triggered[0]["kind"] == "stop_loss"
