from apps.api.app.services.market_service import MarketService


class FailingProvider:
    provider_name = "akshare"

    def list_instruments(self):
        raise RuntimeError("network down")

    def get_bars(self, symbol, freq="1d", start=None, end=None):
        raise RuntimeError("network down")

    def get_realtime_quotes(self, symbols):
        raise RuntimeError("network down")


def test_market_service_auto_falls_back_to_mock_on_provider_error() -> None:
    service = MarketService()
    service.provider = FailingProvider()
    service.allow_runtime_fallback = True

    instruments = service.list_instruments()
    assert instruments

    bars = service.get_bars("600519.SH")
    assert bars

    quotes = service.get_realtime_quotes(["600519.SH"])
    assert quotes

