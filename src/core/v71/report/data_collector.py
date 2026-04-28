"""V71DataCollector -- on-demand stock report data aggregation.

Spec sources:
  - 11_REPORTING.md §4.1 (4 data sources: Kiwoom / DART / Naver news / Claude
    pre-trained -- last is downstream, not this unit)
  - 11_REPORTING.md §4.2 (priority: required vs preferred vs optional)
  - 11_REPORTING.md §4.3 (V71DataCollector code shape)
  - 11_REPORTING.md §4.4 (caching policy -- not implemented this unit;
    future work as a wrapping layer)
  - 06_AGENTS_SPEC.md §1 (V71 Architect Q1~Q8 + recommendation #1~#9 absorbed)

Design summary (architect-approved):
  * Three external clients via DI: V71KiwoomClient (real, P5-Kiwoom-2),
    V71DartClient (Protocol -- concrete impl ships in P6.1.2),
    V71NewsClient (Protocol -- P6.1.3). The collector is testable today
    with all three mocked; real wiring lands when the Protocols get
    concrete implementations.
  * Sequential collection -- V71RateLimiter inside V71KiwoomClient
    handles 4.5/sec already; parallelising via asyncio.gather is a
    follow-up optimisation, not a Phase 6 P6.1 requirement.
  * Graceful degradation:
      - required (basic_info, financial_summary) failure → V71DataCollectionError
      - preferred failure → ``None`` + ``sources_failed`` audit entry
      - optional failure → silent (logger.warning trace only)
  * V71CollectedData is a frozen dataclass with tuple sources (immutable
    audit trail -- caller cannot accidentally mutate after the fact).
  * All datetimes are timezone-aware UTC (``datetime.now(timezone.utc)``)
    so the audit row is unambiguous and ``utcnow()`` deprecation in
    Python 3.12+ is avoided.

Out of scope (future units):
  * Quarterly financials directly from Kiwoom -- if/when Kiwoom adds the
    endpoint, the collector adds a private helper; today the financial
    summary lives behind V71DartClient.
  * Caching layer -- 11_REPORTING.md §4.4 explicit "최초 구현: 캐시 없이".
  * asyncio.gather optimisation across providers -- separate unit if
    profile shows latency is the bottleneck.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Final, Protocol

from src.core.v71.exchange.kiwoom_client import (
    V71KiwoomBusinessError,
    V71KiwoomClient,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Source identifiers (single source of truth -- shared with downstream units)
# ---------------------------------------------------------------------------


SOURCE_KIWOOM_BASIC: Final[str] = "kiwoom_basic"
SOURCE_KIWOOM_PRICE_HISTORY: Final[str] = "kiwoom_price_history"
SOURCE_DART_FINANCIAL: Final[str] = "dart_financial"
SOURCE_DART_DISCLOSURES: Final[str] = "dart_disclosures"
SOURCE_NAVER_NEWS: Final[str] = "naver_news"
SOURCE_PEER_DATA: Final[str] = "peer_data"
SOURCE_FOREIGN_OWNERSHIP: Final[str] = "foreign_ownership"


# Default lookback windows (11_REPORTING.md §4.2).
_DISCLOSURES_LOOKBACK_DAYS: Final[int] = 30
_NEWS_LOOKBACK_DAYS: Final[int] = 14
_NEWS_LIMIT: Final[int] = 20
_PRICE_HISTORY_PAGE_LIMIT: Final[int] = 12  # cont_yn safety bound

# Security M2 (Step 4 review): mirror reconciler.py whitelist so a
# malformed stock_code never reaches Kiwoom / DART / Naver. KRX = 6
# digits, NXT = 5-8 alphanumeric.
_VALID_STOCK_CODE: Final[re.Pattern[str]] = re.compile(r"^[A-Z0-9]{5,8}$")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class V71DataCollectionError(Exception):
    """Raised when a *required* data source fails.

    The underlying exception is preserved via ``__cause__`` (PEP 3134
    ``raise ... from``) so callers retain full diagnostic detail.
    """


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class V71CollectedData:
    """Immutable snapshot of everything the report generator needs.

    ``sources_used`` / ``sources_failed`` are tuples (not lists) so the
    audit trail cannot be silently mutated downstream.
    """

    # Required
    basic_info: dict[str, Any]
    financial_summary: dict[str, Any]

    # Preferred (None when the upstream call failed)
    recent_disclosures: tuple[dict[str, Any], ...] | None
    recent_news: tuple[dict[str, Any], ...] | None
    price_history: dict[str, Any] | None

    # Optional (None when absent / failed)
    peer_data: tuple[dict[str, Any], ...] | None
    foreign_ownership: dict[str, Any] | None

    # Audit / metadata
    stock_code: str
    collection_started_at: datetime
    collection_completed_at: datetime
    sources_used: tuple[str, ...]
    sources_failed: tuple[str, ...]


# ---------------------------------------------------------------------------
# Protocols (concrete impls ship in P6.1.2 / P6.1.3)
# ---------------------------------------------------------------------------


class V71DartClient(Protocol):
    """DART OPEN API surface needed by V71DataCollector."""

    async def get_recent_disclosures(
        self,
        stock_code: str,
        *,
        from_date: datetime,
        to_date: datetime,
    ) -> list[dict[str, Any]]: ...

    async def get_quarterly_financials(
        self,
        stock_code: str,
        *,
        num_quarters: int = 4,
    ) -> dict[str, Any]: ...


class V71NewsClient(Protocol):
    """Naver / news search surface needed by V71DataCollector."""

    async def search_news(
        self,
        *,
        query: str,
        from_date: datetime,
        limit: int = _NEWS_LIMIT,
    ) -> list[dict[str, Any]]: ...


# ---------------------------------------------------------------------------
# Helpers (module-private)
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _date_str(dt: datetime) -> str:
    """``YYYYMMDD`` Kiwoom-friendly string."""
    return dt.strftime("%Y%m%d")


def _as_tuple(maybe_seq: Any) -> tuple[dict[str, Any], ...] | None:
    """Normalise an optional list-of-dicts into an immutable tuple, or
    ``None`` when missing. Preserves frozen dataclass invariants."""
    if maybe_seq is None:
        return None
    if isinstance(maybe_seq, tuple):
        return maybe_seq
    if isinstance(maybe_seq, list):
        return tuple(maybe_seq)
    # Defensive: caller handed an unexpected shape -- keep audit honest.
    return None


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


class V71DataCollector:
    """On-demand stock-report data aggregator.

    DI slots (architect Q1 / P1):
      - ``kiwoom_client``: V71KiwoomClient (P5-Kiwoom-2). Used for
        basic_info (ka10001) and 5-year price history (ka10081 paginated).
      - ``dart_client``: V71DartClient Protocol -- supplies financial
        summary (required) + 1-month disclosure list (preferred).
      - ``news_client``: V71NewsClient Protocol -- 2-week news (preferred).
      - ``clock``: optional UTC clock injection for deterministic test
        timestamps; defaults to ``datetime.now(timezone.utc)``.
    """

    def __init__(
        self,
        *,
        kiwoom_client: V71KiwoomClient,
        dart_client: V71DartClient,
        news_client: V71NewsClient,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._kiwoom = kiwoom_client
        self._dart = dart_client
        self._news = news_client
        self._clock = clock or _utcnow

    def __repr__(self) -> str:
        return f"V71DataCollector(kiwoom_client={self._kiwoom!r})"

    @staticmethod
    def _safe_error_message(
        source: str, stock_code: str, exc: BaseException,
    ) -> str:
        """Security M1: build the V71DataCollectionError message without
        echoing broker-supplied ``return_msg`` (potential token leak per
        P5-Kiwoom-Notify findings). The original exception is preserved
        on ``__cause__`` for full diagnostic detail.
        """
        if isinstance(exc, V71KiwoomBusinessError):
            return (
                f"{source} ({stock_code}): "
                f"V71KiwoomBusinessError(return_code={exc.return_code}, "
                f"api_id={exc.api_id})"
            )
        return f"{source} ({stock_code}): {type(exc).__name__}"

    async def collect(self, stock_code: str) -> V71CollectedData:
        """Aggregate all data needed for a stock report.

        Sequence (architect Q4 -- sequential, V71RateLimiter handles
        4.5/sec broker quota):
          1. Required: basic_info (kiwoom) → financial_summary (dart)
          2. Preferred: recent_disclosures (dart) / recent_news (naver)
             / price_history (kiwoom 5y, paginated)
          3. Optional: peer_data / foreign_ownership

        Required failures raise :class:`V71DataCollectionError` with the
        underlying exception attached via ``__cause__``. Preferred
        failures yield ``None`` + a ``sources_failed`` entry. Optional
        failures only emit a warning log -- the audit row stays terse.
        """
        if not stock_code:
            raise ValueError("stock_code is required")
        if not _VALID_STOCK_CODE.match(stock_code):
            # Security M2: never reach Kiwoom / DART / Naver with a
            # malformed code (boundary defence + log-injection guard).
            raise ValueError(
                f"invalid stock_code format (len={len(stock_code)})"
            )

        started_at = self._clock()
        sources_used: list[str] = []
        sources_failed: list[str] = []

        # --- Required ---------------------------------------------------
        try:
            basic_info_response = await self._kiwoom.get_stock_info(
                stock_code=stock_code,
            )
            basic_info = dict(basic_info_response.data or {})
            sources_used.append(SOURCE_KIWOOM_BASIC)
        except Exception as exc:  # noqa: BLE001 -- broad: required → fail-fast
            raise V71DataCollectionError(
                self._safe_error_message("basic_info", stock_code, exc),
            ) from exc

        try:
            financial_summary = await self._dart.get_quarterly_financials(
                stock_code, num_quarters=4,
            )
            sources_used.append(SOURCE_DART_FINANCIAL)
        except Exception as exc:  # noqa: BLE001 -- broad: required → fail-fast
            raise V71DataCollectionError(
                self._safe_error_message(
                    "financial_summary", stock_code, exc,
                ),
            ) from exc

        # --- Preferred --------------------------------------------------
        recent_disclosures = await self._collect_disclosures(
            stock_code, sources_used, sources_failed,
        )
        recent_news = await self._collect_news(
            stock_code, basic_info, sources_used, sources_failed,
        )
        price_history = await self._collect_price_history(
            stock_code, sources_used, sources_failed,
        )

        # --- Optional ---------------------------------------------------
        peer_data = await self._collect_peer_data(stock_code, sources_used)
        foreign_ownership = await self._collect_foreign_ownership(
            stock_code, sources_used,
        )

        completed_at = self._clock()
        return V71CollectedData(
            basic_info=basic_info,
            financial_summary=dict(financial_summary or {}),
            recent_disclosures=_as_tuple(recent_disclosures),
            recent_news=_as_tuple(recent_news),
            price_history=price_history,
            peer_data=_as_tuple(peer_data),
            foreign_ownership=foreign_ownership,
            stock_code=stock_code,
            collection_started_at=started_at,
            collection_completed_at=completed_at,
            sources_used=tuple(sources_used),
            sources_failed=tuple(sources_failed),
        )

    # -------------------- Preferred sub-collectors ---------------------

    async def _collect_disclosures(
        self,
        stock_code: str,
        sources_used: list[str],
        sources_failed: list[str],
    ) -> list[dict[str, Any]] | None:
        now = self._clock()
        try:
            entries = await self._dart.get_recent_disclosures(
                stock_code,
                from_date=now - timedelta(days=_DISCLOSURES_LOOKBACK_DAYS),
                to_date=now,
            )
        except Exception as exc:  # noqa: BLE001 -- preferred → soft-fail
            logger.warning(
                "v71_data_collector_dart_disclosures_failed",
                stock_code=stock_code,
                error=type(exc).__name__,
            )
            sources_failed.append(f"{SOURCE_DART_DISCLOSURES}: {type(exc).__name__}")
            return None
        sources_used.append(SOURCE_DART_DISCLOSURES)
        return entries

    async def _collect_news(
        self,
        stock_code: str,
        basic_info: dict[str, Any],
        sources_used: list[str],
        sources_failed: list[str],
    ) -> list[dict[str, Any]] | None:
        # The news search uses the Korean stock name (basic_info["stk_nm"])
        # so a single search hits the right thread of coverage. If the
        # broker payload is missing the name, fall back to the code.
        query = str(basic_info.get("stk_nm") or stock_code).strip() or stock_code
        now = self._clock()
        try:
            entries = await self._news.search_news(
                query=query,
                from_date=now - timedelta(days=_NEWS_LOOKBACK_DAYS),
                limit=_NEWS_LIMIT,
            )
        except Exception as exc:  # noqa: BLE001 -- preferred → soft-fail
            logger.warning(
                "v71_data_collector_naver_news_failed",
                stock_code=stock_code,
                error=type(exc).__name__,
            )
            sources_failed.append(f"{SOURCE_NAVER_NEWS}: {type(exc).__name__}")
            return None
        sources_used.append(SOURCE_NAVER_NEWS)
        return entries

    async def _collect_price_history(
        self,
        stock_code: str,
        sources_used: list[str],
        sources_failed: list[str],
    ) -> dict[str, Any] | None:
        """Walk ka10081 cont_yn pages until empty or the safety bound."""
        try:
            history = await self._paginate_daily_chart(stock_code)
        except Exception as exc:  # noqa: BLE001 -- preferred → soft-fail
            logger.warning(
                "v71_data_collector_kiwoom_price_history_failed",
                stock_code=stock_code,
                error=type(exc).__name__,
            )
            sources_failed.append(
                f"{SOURCE_KIWOOM_PRICE_HISTORY}: {type(exc).__name__}",
            )
            return None
        sources_used.append(SOURCE_KIWOOM_PRICE_HISTORY)
        return history

    async def _paginate_daily_chart(self, stock_code: str) -> dict[str, Any]:
        """Aggregate up to ``_PRICE_HISTORY_PAGE_LIMIT`` ka10081 pages.

        Each page returns a chunk of daily candles; we concatenate them
        into a single ``{"candles": [...]}`` dict so the report consumer
        sees a flat history. The safety bound prevents a misbehaving
        ``cont_yn`` server from looping forever.
        """
        candles: list[dict[str, Any]] = []
        cont_yn = "N"
        next_key = ""
        for _ in range(_PRICE_HISTORY_PAGE_LIMIT):
            base_date = _date_str(self._clock())
            response = await self._kiwoom.get_daily_chart(
                stock_code=stock_code,
                base_date=base_date,
                cont_yn=cont_yn,
                next_key=next_key,
            )
            data = response.data or {}
            page = data.get("stk_dt_pole_chart_qry") or []
            if isinstance(page, list):
                candles.extend(item for item in page if isinstance(item, dict))
            cont_yn = response.cont_yn
            next_key = response.next_key
            if cont_yn != "Y" or not next_key:
                break
        return {"candles": candles, "page_count_capped": _PRICE_HISTORY_PAGE_LIMIT}

    # -------------------- Optional sub-collectors ----------------------

    async def _collect_peer_data(
        self,
        stock_code: str,
        sources_used: list[str],  # noqa: ARG002 -- reserved for future impl
    ) -> list[dict[str, Any]] | None:
        # No Kiwoom endpoint maps cleanly to "peers" today; the optional
        # source is wired but the implementation is deliberately deferred
        # to a follow-up unit. ``sources_used`` is kept on the signature
        # so the future implementation can append SOURCE_PEER_DATA without
        # a signature change.
        logger.debug(
            "v71_data_collector_peer_data_not_implemented",
            stock_code=stock_code,
        )
        return None

    async def _collect_foreign_ownership(
        self,
        stock_code: str,
        sources_used: list[str],  # noqa: ARG002 -- reserved for future impl
    ) -> dict[str, Any] | None:
        # Same rationale as ``_collect_peer_data``. Kept as an explicit
        # method so a future Kiwoom endpoint addition slots in cleanly.
        logger.debug(
            "v71_data_collector_foreign_ownership_not_implemented",
            stock_code=stock_code,
        )
        return None


__all__ = [
    "SOURCE_DART_DISCLOSURES",
    "SOURCE_DART_FINANCIAL",
    "SOURCE_FOREIGN_OWNERSHIP",
    "SOURCE_KIWOOM_BASIC",
    "SOURCE_KIWOOM_PRICE_HISTORY",
    "SOURCE_NAVER_NEWS",
    "SOURCE_PEER_DATA",
    "V71CollectedData",
    "V71DartClient",
    "V71DataCollectionError",
    "V71DataCollector",
    "V71NewsClient",
]
