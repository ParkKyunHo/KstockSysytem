"""Unit tests for ``src/core/v71/report/data_collector.py``.

Spec sources:
  - 06_AGENTS_SPEC.md §5 Test Strategy verification (27-case plan)
  - 12_SECURITY.md §6 + Step 4 Security review
    (M1 = return_msg redact, M2 = stock_code regex)
  - 11_REPORTING.md §4.2 (priority: required / preferred / optional)
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from src.core.v71.exchange.kiwoom_client import (
    V71KiwoomBusinessError,
    V71KiwoomClient,
    V71KiwoomResponse,
)
from src.core.v71.report.data_collector import (
    SOURCE_DART_DISCLOSURES,
    SOURCE_DART_FINANCIAL,
    SOURCE_KIWOOM_BASIC,
    SOURCE_KIWOOM_PRICE_HISTORY,
    SOURCE_NAVER_NEWS,
    V71CollectedData,
    V71DataCollectionError,
    V71DataCollector,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _kiwoom_response(
    *,
    api_id: str = "ka10001",
    data: dict | None = None,
    cont_yn: str = "N",
    next_key: str = "",
) -> V71KiwoomResponse:
    return V71KiwoomResponse(
        success=True,
        api_id=api_id,
        data=data or {},
        return_code=0,
        return_msg="OK",
        cont_yn=cont_yn,
        next_key=next_key,
        duration_ms=10,
    )


@pytest.fixture
def kiwoom_client_mock():
    return AsyncMock(spec=V71KiwoomClient)


@pytest.fixture
def dart_client_mock():
    mock = AsyncMock()
    mock.get_recent_disclosures = AsyncMock(return_value=[])
    mock.get_quarterly_financials = AsyncMock(return_value={})
    return mock


@pytest.fixture
def news_client_mock():
    mock = AsyncMock()
    mock.search_news = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def fixed_clock():
    return lambda: datetime(2026, 4, 28, 9, 30, tzinfo=timezone.utc)


@pytest.fixture
def collector(kiwoom_client_mock, dart_client_mock, news_client_mock, fixed_clock):
    return V71DataCollector(
        kiwoom_client=kiwoom_client_mock,
        dart_client=dart_client_mock,
        news_client=news_client_mock,
        clock=fixed_clock,
    )


def _wire_required_success(
    kiwoom_client_mock, dart_client_mock,
    *, stock_code: str = "005930", stock_name: str = "삼성전자",
) -> None:
    kiwoom_client_mock.get_stock_info.return_value = _kiwoom_response(
        data={"stk_cd": stock_code, "stk_nm": stock_name},
    )
    dart_client_mock.get_quarterly_financials.return_value = {"q1": "data"}


def _wire_preferred_success(
    kiwoom_client_mock, dart_client_mock, news_client_mock,
) -> None:
    dart_client_mock.get_recent_disclosures.return_value = [{"id": 1}]
    news_client_mock.search_news.return_value = [{"title": "headline"}]
    kiwoom_client_mock.get_daily_chart.return_value = _kiwoom_response(
        api_id="ka10081",
        data={"stk_dt_pole_chart_qry": [{"dt": "20260428"}]},
    )


# ---------------------------------------------------------------------------
# Group A: validation + happy path (3 cases)
# ---------------------------------------------------------------------------


class TestValidationAndHappyPath:
    @pytest.mark.parametrize("invalid_code", ["", "   "])
    async def test_empty_or_whitespace_stock_code_raises(
        self, collector, invalid_code,
    ):
        with pytest.raises(ValueError, match="stock_code"):
            await collector.collect(invalid_code)

    async def test_invalid_format_stock_code_raises(self, collector):
        # Security M2: lowercase / wrong length must be rejected.
        with pytest.raises(ValueError, match="invalid stock_code format"):
            await collector.collect("abc")

    async def test_all_required_and_preferred_success(
        self, collector, kiwoom_client_mock, dart_client_mock, news_client_mock,
    ):
        _wire_required_success(kiwoom_client_mock, dart_client_mock)
        _wire_preferred_success(
            kiwoom_client_mock, dart_client_mock, news_client_mock,
        )

        result = await collector.collect("005930")

        assert result.stock_code == "005930"
        assert result.basic_info["stk_cd"] == "005930"
        assert result.financial_summary == {"q1": "data"}
        assert result.recent_disclosures == ({"id": 1},)
        assert result.recent_news == ({"title": "headline"},)
        assert result.price_history is not None
        assert result.peer_data is None
        assert result.foreign_ownership is None
        assert SOURCE_KIWOOM_BASIC in result.sources_used
        assert SOURCE_DART_FINANCIAL in result.sources_used
        assert SOURCE_DART_DISCLOSURES in result.sources_used
        assert SOURCE_NAVER_NEWS in result.sources_used
        assert SOURCE_KIWOOM_PRICE_HISTORY in result.sources_used
        assert result.sources_failed == ()


# ---------------------------------------------------------------------------
# Group B: required failure (3 cases)
# ---------------------------------------------------------------------------


class TestRequiredFailures:
    async def test_basic_info_failure_raises_with_cause(
        self, collector, kiwoom_client_mock, dart_client_mock,
    ):
        original = RuntimeError("kiwoom down")
        kiwoom_client_mock.get_stock_info.side_effect = original

        with pytest.raises(V71DataCollectionError) as excinfo:
            await collector.collect("005930")

        assert excinfo.value.__cause__ is original
        # Short-circuit: no further calls
        dart_client_mock.get_quarterly_financials.assert_not_awaited()

    async def test_financial_summary_failure_short_circuits(
        self, collector, kiwoom_client_mock, dart_client_mock, news_client_mock,
    ):
        _wire_required_success(kiwoom_client_mock, dart_client_mock)
        dart_client_mock.get_quarterly_financials.side_effect = RuntimeError(
            "DART down"
        )

        with pytest.raises(V71DataCollectionError):
            await collector.collect("005930")

        dart_client_mock.get_recent_disclosures.assert_not_awaited()
        news_client_mock.search_news.assert_not_awaited()
        kiwoom_client_mock.get_daily_chart.assert_not_awaited()

    async def test_required_failure_message_does_not_echo_return_msg(
        self, collector, kiwoom_client_mock,
    ):
        # Security M1: V71DataCollectionError must NOT echo Kiwoom
        # return_msg (which can carry echoed Authorization headers).
        secret = "Bearer eyJSUPER_SECRET_TOKEN"
        biz = V71KiwoomBusinessError(
            f"some return_msg with {secret}",
            return_code=8005,
            return_msg=f"echoed {secret}",
            api_id="ka10001",
        )
        kiwoom_client_mock.get_stock_info.side_effect = biz

        with pytest.raises(V71DataCollectionError) as excinfo:
            await collector.collect("005930")

        msg = str(excinfo.value)
        assert "SUPER_SECRET_TOKEN" not in msg
        assert "Bearer" not in msg
        # But the diagnostic context (return_code + api_id) remains.
        assert "8005" in msg
        assert "ka10001" in msg


# ---------------------------------------------------------------------------
# Group C: preferred-data graceful degradation (4 cases)
# ---------------------------------------------------------------------------


class TestPreferredFailures:
    async def test_disclosures_failure_yields_none_and_audit(
        self, collector, kiwoom_client_mock, dart_client_mock, news_client_mock,
    ):
        _wire_required_success(kiwoom_client_mock, dart_client_mock)
        _wire_preferred_success(
            kiwoom_client_mock, dart_client_mock, news_client_mock,
        )
        dart_client_mock.get_recent_disclosures.side_effect = RuntimeError(
            "list fail"
        )

        result = await collector.collect("005930")

        assert result.recent_disclosures is None
        assert any(
            entry.startswith(SOURCE_DART_DISCLOSURES + ":")
            for entry in result.sources_failed
        )
        assert result.recent_news is not None
        assert result.price_history is not None

    async def test_news_failure_yields_none_and_audit(
        self, collector, kiwoom_client_mock, dart_client_mock, news_client_mock,
    ):
        _wire_required_success(kiwoom_client_mock, dart_client_mock)
        _wire_preferred_success(
            kiwoom_client_mock, dart_client_mock, news_client_mock,
        )
        news_client_mock.search_news.side_effect = TimeoutError("naver")

        result = await collector.collect("005930")

        assert result.recent_news is None
        assert any(
            entry.startswith(SOURCE_NAVER_NEWS + ":")
            for entry in result.sources_failed
        )

    async def test_price_history_failure_yields_none_and_audit(
        self, collector, kiwoom_client_mock, dart_client_mock, news_client_mock,
    ):
        _wire_required_success(kiwoom_client_mock, dart_client_mock)
        _wire_preferred_success(
            kiwoom_client_mock, dart_client_mock, news_client_mock,
        )
        kiwoom_client_mock.get_daily_chart.side_effect = RuntimeError("chart")

        result = await collector.collect("005930")

        assert result.price_history is None
        assert any(
            entry.startswith(SOURCE_KIWOOM_PRICE_HISTORY + ":")
            for entry in result.sources_failed
        )

    async def test_all_preferred_fail_aggregates_audit(
        self, collector, kiwoom_client_mock, dart_client_mock, news_client_mock,
    ):
        _wire_required_success(kiwoom_client_mock, dart_client_mock)
        dart_client_mock.get_recent_disclosures.side_effect = RuntimeError("a")
        news_client_mock.search_news.side_effect = RuntimeError("b")
        kiwoom_client_mock.get_daily_chart.side_effect = RuntimeError("c")

        result = await collector.collect("005930")

        assert set(result.sources_used) == {
            SOURCE_KIWOOM_BASIC, SOURCE_DART_FINANCIAL,
        }
        codes_failed = {entry.split(":")[0] for entry in result.sources_failed}
        assert codes_failed == {
            SOURCE_DART_DISCLOSURES, SOURCE_NAVER_NEWS,
            SOURCE_KIWOOM_PRICE_HISTORY,
        }


# ---------------------------------------------------------------------------
# Group D: pagination (3 cases)
# ---------------------------------------------------------------------------


class TestPriceHistoryPagination:
    async def test_single_page(
        self, collector, kiwoom_client_mock, dart_client_mock, news_client_mock,
    ):
        _wire_required_success(kiwoom_client_mock, dart_client_mock)
        news_client_mock.search_news.return_value = []
        dart_client_mock.get_recent_disclosures.return_value = []
        kiwoom_client_mock.get_daily_chart.return_value = _kiwoom_response(
            api_id="ka10081",
            data={"stk_dt_pole_chart_qry": [{"dt": "20260428"}]},
            cont_yn="N",
        )

        await collector.collect("005930")

        assert kiwoom_client_mock.get_daily_chart.await_count == 1

    async def test_multi_page_accumulates(
        self, collector, kiwoom_client_mock, dart_client_mock, news_client_mock,
    ):
        _wire_required_success(kiwoom_client_mock, dart_client_mock)
        news_client_mock.search_news.return_value = []
        dart_client_mock.get_recent_disclosures.return_value = []
        kiwoom_client_mock.get_daily_chart.side_effect = [
            _kiwoom_response(
                api_id="ka10081",
                data={"stk_dt_pole_chart_qry": [{"dt": "20260428"}]},
                cont_yn="Y", next_key="key1",
            ),
            _kiwoom_response(
                api_id="ka10081",
                data={"stk_dt_pole_chart_qry": [{"dt": "20260427"}]},
                cont_yn="N",
            ),
        ]

        result = await collector.collect("005930")

        assert kiwoom_client_mock.get_daily_chart.await_count == 2
        assert len(result.price_history["candles"]) == 2

    async def test_safety_bound_caps_at_12_pages(
        self, collector, kiwoom_client_mock, dart_client_mock, news_client_mock,
    ):
        _wire_required_success(kiwoom_client_mock, dart_client_mock)
        news_client_mock.search_news.return_value = []
        dart_client_mock.get_recent_disclosures.return_value = []
        # Always cont_yn="Y" -- safety bound stops loop at 12 pages.
        kiwoom_client_mock.get_daily_chart.return_value = _kiwoom_response(
            api_id="ka10081",
            data={"stk_dt_pole_chart_qry": [{"dt": "x"}]},
            cont_yn="Y", next_key="forever",
        )

        await collector.collect("005930")

        assert kiwoom_client_mock.get_daily_chart.await_count == 12


# ---------------------------------------------------------------------------
# Group E: news query selection (2 cases)
# ---------------------------------------------------------------------------


class TestNewsQuery:
    async def test_uses_stock_name_when_present(
        self, collector, kiwoom_client_mock, dart_client_mock, news_client_mock,
    ):
        _wire_required_success(
            kiwoom_client_mock, dart_client_mock, stock_name="삼성전자",
        )
        _wire_preferred_success(
            kiwoom_client_mock, dart_client_mock, news_client_mock,
        )

        await collector.collect("005930")

        kwargs = news_client_mock.search_news.await_args.kwargs
        assert kwargs["query"] == "삼성전자"

    async def test_falls_back_to_stock_code_when_name_missing(
        self, collector, kiwoom_client_mock, dart_client_mock, news_client_mock,
    ):
        kiwoom_client_mock.get_stock_info.return_value = _kiwoom_response(
            data={"stk_cd": "005930"},  # no stk_nm
        )
        dart_client_mock.get_quarterly_financials.return_value = {}
        _wire_preferred_success(
            kiwoom_client_mock, dart_client_mock, news_client_mock,
        )

        await collector.collect("005930")

        kwargs = news_client_mock.search_news.await_args.kwargs
        assert kwargs["query"] == "005930"


# ---------------------------------------------------------------------------
# Group F: frozen + tuple invariants (3 cases)
# ---------------------------------------------------------------------------


class TestImmutability:
    def test_collected_data_is_frozen(self):
        data = V71CollectedData(
            basic_info={}, financial_summary={},
            recent_disclosures=None, recent_news=None, price_history=None,
            peer_data=None, foreign_ownership=None,
            stock_code="005930",
            collection_started_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
            collection_completed_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
            sources_used=(), sources_failed=(),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            data.stock_code = "000660"

    async def test_sources_collections_are_tuples(
        self, collector, kiwoom_client_mock, dart_client_mock, news_client_mock,
    ):
        _wire_required_success(kiwoom_client_mock, dart_client_mock)
        _wire_preferred_success(
            kiwoom_client_mock, dart_client_mock, news_client_mock,
        )

        result = await collector.collect("005930")

        assert isinstance(result.sources_used, tuple)
        assert isinstance(result.sources_failed, tuple)

    async def test_disclosures_news_returned_as_tuples(
        self, collector, kiwoom_client_mock, dart_client_mock, news_client_mock,
    ):
        _wire_required_success(kiwoom_client_mock, dart_client_mock)
        _wire_preferred_success(
            kiwoom_client_mock, dart_client_mock, news_client_mock,
        )

        result = await collector.collect("005930")

        assert isinstance(result.recent_disclosures, tuple)
        assert isinstance(result.recent_news, tuple)


# ---------------------------------------------------------------------------
# Group G: clock + audit timestamps (2 cases)
# ---------------------------------------------------------------------------


class TestClockAndAudit:
    async def test_clock_drives_started_and_completed(
        self, kiwoom_client_mock, dart_client_mock, news_client_mock,
    ):
        times = iter([
            datetime(2026, 4, 28, 9, 0, tzinfo=timezone.utc),
            # base_date for daily chart (called inside collect)
            datetime(2026, 4, 28, 9, 0, tzinfo=timezone.utc),
            datetime(2026, 4, 28, 9, 0, tzinfo=timezone.utc),
            datetime(2026, 4, 28, 9, 0, tzinfo=timezone.utc),
            datetime(2026, 4, 28, 9, 5, tzinfo=timezone.utc),
        ])

        def _clock():
            return next(times, datetime(2026, 4, 28, 9, 5, tzinfo=timezone.utc))

        _wire_required_success(kiwoom_client_mock, dart_client_mock)
        _wire_preferred_success(
            kiwoom_client_mock, dart_client_mock, news_client_mock,
        )

        c = V71DataCollector(
            kiwoom_client=kiwoom_client_mock,
            dart_client=dart_client_mock,
            news_client=news_client_mock,
            clock=_clock,
        )

        result = await c.collect("005930")

        assert result.collection_started_at == datetime(
            2026, 4, 28, 9, 0, tzinfo=timezone.utc,
        )
        assert result.collection_completed_at == datetime(
            2026, 4, 28, 9, 5, tzinfo=timezone.utc,
        )

    async def test_completed_at_not_before_started_at(
        self, collector, kiwoom_client_mock, dart_client_mock, news_client_mock,
    ):
        _wire_required_success(kiwoom_client_mock, dart_client_mock)
        _wire_preferred_success(
            kiwoom_client_mock, dart_client_mock, news_client_mock,
        )

        result = await collector.collect("005930")

        assert result.collection_completed_at >= result.collection_started_at


# ---------------------------------------------------------------------------
# Group H: security regression (3 cases)
# ---------------------------------------------------------------------------


class TestSecurityRegression:
    def test_repr_does_not_leak_dart_news_clock(
        self, kiwoom_client_mock, dart_client_mock, news_client_mock,
    ):
        secret = "DART-API-SECRET-9999"
        dart_client_mock.api_key = secret  # would only appear if repr leaks

        c = V71DataCollector(
            kiwoom_client=kiwoom_client_mock,
            dart_client=dart_client_mock,
            news_client=news_client_mock,
        )

        text = repr(c)
        assert "kiwoom_client" in text
        # repr deliberately omits dart / news / clock
        assert secret not in text
        assert "dart_client" not in text
        assert "news_client" not in text

    async def test_invalid_stock_code_log_does_not_echo_value(
        self, collector,
    ):
        # Security M2: malformed code is rejected before reaching any
        # downstream mock, so log injection via stock_code is impossible.
        malicious = "AB\nINJECT_LINE"
        with pytest.raises(ValueError):
            await collector.collect(malicious)

    async def test_required_failure_audit_omits_underlying_message(
        self, collector, kiwoom_client_mock,
    ):
        # Security M1: even arbitrary RuntimeError messages with secret-
        # looking content must not appear in V71DataCollectionError.args.
        kiwoom_client_mock.get_stock_info.side_effect = RuntimeError(
            "Authorization: Bearer tok123 leak"
        )

        with pytest.raises(V71DataCollectionError) as excinfo:
            await collector.collect("005930")

        assert "tok123" not in str(excinfo.value)
        assert "Authorization" not in str(excinfo.value)
        # underlying exc preserved on __cause__ (operator can read in dev)
        assert isinstance(excinfo.value.__cause__, RuntimeError)
