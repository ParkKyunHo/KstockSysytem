"""V71DailyCandleBuilder -- ka10081 EOD polling for PATH_B 일봉.

Spec:
  - 02_TRADING_RULES.md §4.3 (PATH_B 일봉 진입)
  - 02_TRADING_RULES.md §7 (폴링 전략 -- EOD 1회)
  - 04_ARCHITECTURE.md §5.3

Architect Q5 decision: ka10081 EOD polling (not 3-min accumulation +
not parallel verification). PATH_B 매수 timing = 익일 09:01, so 전일
일봉 정확성만 필요. Boot-time 100-bar history fetch + 15:35 EOD daily
poll (manager-driven; this class exposes only the fetch helpers).

Failure isolation: fetch failures (kiwoom transport / business error)
log WARNING + return None so the manager loop survives a single bad
day (Constitution §4 항상 운영).
"""

from __future__ import annotations

import contextlib
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from src.core.v71.candle.types import V71Candle
from src.core.v71.v71_constants import V71Constants, V71Timeframe

log = logging.getLogger(__name__)


OnCandleCompleteFn = Callable[[V71Candle], Awaitable[None]]


# ka10081 response field aliases. Wire-level field names confirmed
# during Phase 7 paper smoke -- the builder stays permissive in the
# interim so a missing or renamed field surfaces as a structured
# WARNING + skip rather than a crash.
_OPEN_KEYS = ("open_pric", "open", "stk_oppr")
_HIGH_KEYS = ("high_pric", "high", "stk_hgpr")
_LOW_KEYS = ("low_pric", "low", "stk_lwpr")
_CLOSE_KEYS = ("cur_prc", "close", "stk_clpr")
_VOLUME_KEYS = ("trde_qty", "volume", "vol")
_DATE_KEYS = ("dt", "date", "trd_dt")


def _coerce_int(raw: Any) -> int:
    """Robust kiwoom 0-padded numeric → int. Negatives clamped to 0."""
    if raw is None:
        return 0
    try:
        value = int(str(raw).strip().lstrip("0") or "0")
    except (TypeError, ValueError):
        return 0
    return max(0, value)


def _parse_date(raw: Any) -> datetime | None:
    """Parse ``YYYYMMDD`` (kiwoom format) into UTC midnight datetime.

    Returns ``None`` (with WARNING) for malformed input -- caller
    routes to skip path.
    """
    if not raw:
        return None
    text = str(raw).strip()
    if len(text) != 8 or not text.isdigit():
        log.warning(
            "v71_daily_builder: invalid date format %r (expected YYYYMMDD)",
            text,
        )
        return None
    try:
        year = int(text[0:4])
        month = int(text[4:6])
        day = int(text[6:8])
        return datetime(year, month, day, 0, 0, 0, tzinfo=timezone.utc)
    except (ValueError, TypeError):
        log.warning(
            "v71_daily_builder: date parse failed for %r", text,
        )
        return None


def _row_to_candle(row: dict[str, Any], stock_code: str) -> V71Candle | None:
    """Convert a ka10081 row into a :class:`V71Candle`. Returns ``None``
    on missing/unparseable fields so callers can skip silently."""
    if not isinstance(row, dict):
        return None
    timestamp = _parse_date(
        next((row[k] for k in _DATE_KEYS if k in row), None),
    )
    if timestamp is None:
        return None
    open_price = _coerce_int(
        next((row[k] for k in _OPEN_KEYS if k in row), None),
    )
    high_price = _coerce_int(
        next((row[k] for k in _HIGH_KEYS if k in row), None),
    )
    low_price = _coerce_int(
        next((row[k] for k in _LOW_KEYS if k in row), None),
    )
    close_price = _coerce_int(
        next((row[k] for k in _CLOSE_KEYS if k in row), None),
    )
    volume = _coerce_int(
        next((row[k] for k in _VOLUME_KEYS if k in row), 0),
    )
    if open_price <= 0 or close_price <= 0:
        log.warning(
            "v71_daily_builder: row missing OHLC for %s on %s",
            stock_code, timestamp.date().isoformat(),
        )
        return None
    return V71Candle(
        stock_code=stock_code,
        timeframe=V71Timeframe.DAILY,
        timestamp=timestamp,
        open=open_price,
        high=max(high_price, open_price, close_price),
        low=low_price if low_price > 0 else min(open_price, close_price),
        close=close_price,
        volume=volume,
        tick_count=0,  # daily aggregates from kiwoom -- tick count unknown
    )


class V71DailyCandleBuilder:
    """Per-stock 일봉 builder backed by kiwoom ka10081.

    Implements :class:`V71BaseCandleBuilder` Protocol (duck-typed).
    Caller (V71CandleManager) drives :meth:`fetch_eod` / :meth:`fetch_history`
    on a schedule. The builder maintains a per-stock cache + subscriber list.
    """

    _CHART_KEY = "stk_dt_pole_chart_qry"

    def __init__(
        self,
        stock_code: str,
        *,
        kiwoom_client: Any,
        history_max: int | None = None,
    ) -> None:
        self.stock_code: str = stock_code
        self.timeframe: V71Timeframe = V71Timeframe.DAILY
        self._kiwoom = kiwoom_client
        self._history: deque[V71Candle] = deque(
            maxlen=history_max
            if history_max is not None
            else V71Constants.CANDLE_HISTORY_PER_STOCK_MAX,
        )
        self._seen_dates: set[str] = set()  # YYYYMMDD strings
        self._subscribers: list[OnCandleCompleteFn] = []

    # ------------------------------------------------------------------
    # Public API (Protocol surface)
    # ------------------------------------------------------------------

    def get_candles(self, n: int | None = None) -> tuple[V71Candle, ...]:
        """Return cached daily candles ordered oldest → newest."""
        ordered = sorted(self._history, key=lambda c: c.timestamp)
        if n is None:
            return tuple(ordered)
        if n <= 0:
            return ()
        return tuple(ordered[-n:])

    def register_on_complete(self, callback: OnCandleCompleteFn) -> None:
        self._subscribers.append(callback)

    def unregister_on_complete(self, callback: OnCandleCompleteFn) -> None:
        # Idempotent -- silent when callback was never registered.
        with contextlib.suppress(ValueError):
            self._subscribers.remove(callback)

    # ------------------------------------------------------------------
    # Fetch helpers (manager-driven)
    # ------------------------------------------------------------------

    async def fetch_eod(self, base_date: str) -> V71Candle | None:
        """Fetch the most recent daily candle. Idempotent on the same
        ``base_date`` (cache + ``_seen_dates`` skips re-dispatch).

        Returns the new candle (None on miss / cache hit / parse failure).
        """
        try:
            response = await self._kiwoom.get_daily_chart(
                stock_code=self.stock_code,
                base_date=base_date,
            )
        except Exception as exc:  # noqa: BLE001 -- callable must not raise
            log.warning(
                "v71_daily_builder: ka10081 fetch failed for %s "
                "base_date=%s: %s",
                self.stock_code, base_date, type(exc).__name__,
            )
            return None
        rows = self._extract_rows(response)
        if not rows:
            return None
        latest = rows[0]  # ka10081 returns newest first
        candle = _row_to_candle(latest, self.stock_code)
        if candle is None:
            return None
        date_key = candle.timestamp.strftime("%Y%m%d")
        if date_key in self._seen_dates:
            return None  # cache hit, no re-dispatch
        self._history.append(candle)
        self._seen_dates.add(date_key)
        await self._dispatch(candle)
        return candle

    async def fetch_history(self, base_date: str) -> int:
        """Bulk-prime cache with up to maxlen historical candles.

        No subscriber dispatch (boot priming = silent). Returns the
        number of candles cached.
        """
        try:
            response = await self._kiwoom.get_daily_chart(
                stock_code=self.stock_code,
                base_date=base_date,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "v71_daily_builder: ka10081 history fetch failed for %s: %s",
                self.stock_code, type(exc).__name__,
            )
            return 0
        rows = self._extract_rows(response)
        added = 0
        # Newest-first → reverse so deque maintains chronological order.
        for row in reversed(rows):
            candle = _row_to_candle(row, self.stock_code)
            if candle is None:
                continue
            date_key = candle.timestamp.strftime("%Y%m%d")
            if date_key in self._seen_dates:
                continue
            self._history.append(candle)
            self._seen_dates.add(date_key)
            added += 1
        return added

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _extract_rows(self, response: Any) -> list[dict[str, Any]]:
        """Pull the candle list from ka10081 response (architect Q10
        format). Tolerates both ``response.data`` and ``response.body``."""
        body = getattr(response, "data", None) or getattr(
            response, "body", None,
        )
        if not isinstance(body, dict):
            return []
        rows = body.get(self._CHART_KEY) or []
        return [r for r in rows if isinstance(r, dict)]

    async def _dispatch(self, candle: V71Candle) -> None:
        for cb in tuple(self._subscribers):
            try:
                await cb(candle)
            except Exception as exc:  # noqa: BLE001 -- handler isolation
                log.warning(
                    "v71_daily_builder_subscriber_failed for %s: %s",
                    self.stock_code, type(exc).__name__,
                )


__all__ = [
    "OnCandleCompleteFn",
    "V71DailyCandleBuilder",
]
