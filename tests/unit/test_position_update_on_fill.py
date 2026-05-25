from apps.api.app.db.models import PositionORM
from apps.api.app.services import alert_service


def test_position_alert_state_reset_single_symbol() -> None:
    alert_service._position_alert_state[("600519.SH", "stop_loss")] = PositionORM._now if hasattr(PositionORM, "_now") else None
    alert_service._position_alert_state[("000001.SZ", "stop_loss")] = None

    alert_service.reset_position_alert_state("600519.SH")

    assert ("600519.SH", "stop_loss") not in alert_service._position_alert_state
    assert ("000001.SZ", "stop_loss") in alert_service._position_alert_state


def test_position_alert_state_reset_all() -> None:
    alert_service._position_alert_state[("600519.SH", "stop_loss")] = None
    alert_service.reset_position_alert_state()
    assert alert_service._position_alert_state == {}
