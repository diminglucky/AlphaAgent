from __future__ import annotations

from datetime import date

import pandas as pd

from apps.api.app.services import fundamental_service


def test_get_stock_info_fills_industry_and_list_date(monkeypatch) -> None:
    fundamental_service.clear_cache()

    class FakeAk:
        @staticmethod
        def stock_value_em(symbol: str):
            assert symbol == "300750"
            return pd.DataFrame([{
                "PE(TTM)": 28.5,
                "市净率": 5.2,
                "总市值": 1.1e12,
                "流通市值": 8.8e11,
            }])

        @staticmethod
        def stock_individual_info_em(symbol: str):
            assert symbol == "300750"
            return pd.DataFrame([
                {"item": "股票简称", "value": "宁德时代"},
                {"item": "行业", "value": "电池"},
                {"item": "上市时间", "value": "20180611"},
            ])

    monkeypatch.setattr(fundamental_service, "_ak", lambda: FakeAk)

    from apps.api.app.services import market_service
    monkeypatch.setattr(
        market_service,
        "get_single_quote",
        lambda symbol: {"name": "宁德时代"} if symbol == "300750.SZ" else None,
    )

    info = fundamental_service.get_stock_info("300750.SZ")

    assert info["name"] == "宁德时代"
    assert info["industry"] == "电池"
    assert info["list_date"] == "2018-06-11"
    assert info["days_listed"] is not None
    assert info["pe"] == 28.5
    assert info["float_mv"] == 8.8e11


def test_evaluate_fundamental_includes_industry_score(monkeypatch) -> None:
    monkeypatch.setattr(
        fundamental_service,
        "get_stock_info",
        lambda symbol: {
            "symbol": symbol,
            "code": "300750",
            "name": "宁德时代",
            "industry": "电池",
            "total_mv": 1.1e12,
            "float_mv": 8.8e11,
            "list_date": "2018-06-11",
            "days_listed": 2800,
            "is_st": False,
            "pe": 28.5,
            "pb": 5.2,
        },
    )
    monkeypatch.setattr(
        fundamental_service,
        "get_fund_flow",
        lambda symbol: {"today_net": 1.2e8, "turnover_rate": 4.8},
    )
    monkeypatch.setattr(fundamental_service, "get_lhb_record", lambda symbol: [])
    monkeypatch.setattr(
        fundamental_service,
        "get_northbound_flow",
        lambda symbol: {
            "add_mv_5d": 2.5e8,
            "add_mv_pct_5d": 8.0,
            "add_ratio_float_5d": 0.15,
        },
    )
    monkeypatch.setattr(
        fundamental_service,
        "get_research_rating",
        lambda symbol: {
            "report_count": 6,
            "buy_count": 2,
            "positive_count": 5,
            "negative_count": 0,
            "institutions": ["A证券", "B证券", "C证券"],
            "latest_reports": [],
        },
    )
    monkeypatch.setattr(
        fundamental_service,
        "get_insider_reduction",
        lambda symbol: {
            "reduce_count": 1,
            "total_reduce_amount": 2.0e6,
            "total_reduce_shares": 100000,
            "latest_date": date.today().isoformat(),
            "events": [],
        },
    )
    monkeypatch.setattr(
        fundamental_service,
        "get_industry_rank",
        lambda industry: {
            "rank": 3,
            "total": 86,
            "change_pct": 2.4,
            "net_inflow": 4.2e8,
            "matched_name": industry,
            "leader": "测试龙头",
        },
    )

    result = fundamental_service.evaluate_fundamental("300750.SZ", "宁德时代")

    assert result["industry_score"] == 14
    assert result["northbound_score"] == 10
    assert result["research_score"] == 10
    assert result["insider_reduction_score"] == 6
    assert result["industry_rank"]["rank"] == 3
    assert result["industry_items"][0]["kind"] == "good"
    assert result["northbound_items"][0]["kind"] == "good"
    assert result["research_items"][0]["kind"] == "good"
    assert result["insider_reduction_items"][0]["kind"] == "warn"
    assert "行业 电池 排名 3/86" in result["industry_items"][0]["desc"]


def test_get_northbound_flow_uses_marketwide_cache(monkeypatch) -> None:
    fundamental_service.clear_cache()
    calls = {"n": 0}

    class FakeAk:
        @staticmethod
        def stock_hsgt_hold_stock_em(market: str, indicator: str):
            calls["n"] += 1
            assert market == "北向"
            assert indicator == "5日排行"
            return pd.DataFrame([{
                "代码": "300750",
                "名称": "宁德时代",
                "日期": "2026-06-02",
                "今日持股-市值": 1.5e10,
                "今日持股-占流通股比": 8.5,
                "今日持股-占总股本比": 7.2,
                "5日增持估计-股数": 1000000,
                "5日增持估计-市值": 2.5e8,
                "5日增持估计-市值增幅": 8.0,
                "5日增持估计-占流通股比": 0.15,
                "5日增持估计-占总股本比": 0.12,
                "所属板块": "电池",
            }])

    monkeypatch.setattr(fundamental_service, "_ak", lambda: FakeAk)

    first = fundamental_service.get_northbound_flow("300750.SZ")
    second = fundamental_service.get_northbound_flow("300750.SZ")

    assert calls["n"] == 1
    assert first["_partial"] is False
    assert first["add_mv_5d"] == 2.5e8
    assert second["add_ratio_float_5d"] == 0.15


def test_get_research_rating_scores_recent_reports(monkeypatch) -> None:
    fundamental_service.clear_cache()
    calls = {"n": 0}

    class FakeAk:
        @staticmethod
        def stock_research_report_em(symbol: str):
            calls["n"] += 1
            assert symbol == "300750"
            today = date.today().isoformat()
            return pd.DataFrame([
                {"日期": today, "东财评级": "买入", "报告名称": "盈利能力提升", "机构": "A证券", "报告PDF链接": "https://x/a.pdf"},
                {"日期": today, "东财评级": "增持", "报告名称": "订单改善", "机构": "B证券", "报告PDF链接": "https://x/b.pdf"},
                {"日期": "2020-01-01", "东财评级": "买入", "报告名称": "过期研报", "机构": "C证券", "报告PDF链接": "https://x/c.pdf"},
            ])

    monkeypatch.setattr(fundamental_service, "_ak", lambda: FakeAk)

    research = fundamental_service.get_research_rating("300750.SZ")
    score, items = fundamental_service._score_research_rating(research)
    again = fundamental_service.get_research_rating("300750.SZ")

    assert calls["n"] == 1
    assert research["report_count"] == 2
    assert research["buy_count"] == 1
    assert research["positive_count"] == 2
    assert research["institutions"] == ["A证券", "B证券"]
    assert again["latest_reports"][0]["title"] == "盈利能力提升"
    assert score >= 6
    assert "近 30 天研报 2 篇" in items[0]["desc"]


def test_get_insider_reduction_detects_recent_sells(monkeypatch) -> None:
    fundamental_service.clear_cache()
    calls = {"n": 0}

    class FakeAk:
        @staticmethod
        def stock_hold_management_detail_em():
            calls["n"] += 1
            today = date.today().isoformat()
            return pd.DataFrame([
                {
                    "日期": today,
                    "代码": "300750",
                    "名称": "宁德时代",
                    "变动人": "张三",
                    "变动股数": -1000000,
                    "成交均价": 250,
                    "变动金额": -2.5e8,
                    "变动原因": "二级市场买卖",
                    "变动比例": -0.1,
                    "职务": "董事",
                    "变动人与董监高的关系": "本人",
                },
                {
                    "日期": today,
                    "代码": "000001",
                    "名称": "平安银行",
                    "变动人": "李四",
                    "变动股数": 10000,
                    "成交均价": 10,
                    "变动金额": 100000,
                    "变动原因": "增持",
                },
            ])

    monkeypatch.setattr(fundamental_service, "_ak", lambda: FakeAk)

    reduction = fundamental_service.get_insider_reduction("300750.SZ")
    score, items = fundamental_service._score_insider_reduction(reduction)
    again = fundamental_service.get_insider_reduction("300750.SZ")

    assert calls["n"] == 1
    assert reduction["reduce_count"] == 1
    assert reduction["total_reduce_amount"] == 2.5e8
    assert again["events"][0]["person"] == "张三"
    assert score >= 9
    assert items[0]["score"] < 0
    assert "减持 1 次" in items[0]["desc"]
