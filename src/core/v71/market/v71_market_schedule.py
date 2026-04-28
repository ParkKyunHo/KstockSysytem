"""V71MarketSchedule -- minimal KRX calendar for V7.1.

Spec:
  - 02_TRADING_RULES.md §7 (폴링 전략 -- 정규장 09:00-15:30)
  - 02_TRADING_RULES.md §10 (VI 휴장일 처리)

V7.0 ``MarketScheduleManager`` bundled holiday DB loading + status text
+ many helpers; the only V7.1 consumer (``box_entry_skill``) needs
``is_holiday(date) -> bool``. This module provides:

  * :class:`V71MarketSchedule` -- in-memory holiday set + simple checks
  * :func:`get_v71_market_schedule` -- module-level singleton accessor
    (matches V7.0 import shape so the skill's monkey-patched indirection
    layer keeps working after Step B import path swap)

Holiday loading: tests inject via ``set_holidays``; production wiring
calls :meth:`load_holidays_from_iter` at attach with a DB-backed list.
Empty holiday set is safe (``is_holiday`` returns False) -- weekend
filter still applies.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta, timezone

from src.core.v71.v71_constants import V71Constants

log = logging.getLogger(__name__)


# KRX market sessions are KST. Hosts may run UTC (default AWS Lightsail),
# so ``is_market_open(now=None)`` must default to KST -- otherwise the
# default path would silently drift by 9 hours and mis-classify market
# phase. Phase A Step F follow-up (P-Wire-14) introduced this guard.
_KST = timezone(timedelta(hours=9))


def _parse_hhmm(text: str) -> time:
    """Parse ``HH:MM`` (KRX V71Constants format) -> ``time`` (naive)."""
    h, m = text.split(":", 1)
    return time(int(h), int(m), 0)


class V71MarketSchedule:
    """In-memory KRX schedule.

    Thread-safety: reads are lock-free (frozenset / immutable time
    constants). Writes (``set_holidays``) are intended for
    boot-time + tests -- not concurrent.
    """

    def __init__(self) -> None:
        self._holidays: frozenset[date] = frozenset()
        self._market_open: time = _parse_hhmm(V71Constants.MARKET_OPEN_TIME)
        self._market_close: time = _parse_hhmm(V71Constants.MARKET_CLOSE_TIME)

    # ------------------------------------------------------------------
    # Holiday API
    # ------------------------------------------------------------------

    def set_holidays(self, holidays: Iterable[date]) -> None:
        """Replace the holiday set. Caller passes a finite iterable
        (DB rows, hard-coded list, etc.). Idempotent."""
        self._holidays = frozenset(holidays)

    def is_holiday(self, check_date: date) -> bool:
        """True iff ``check_date`` is a known KRX holiday. Weekends are
        NOT holidays here -- callers combine with weekday check (see
        :meth:`is_trading_day`)."""
        return check_date in self._holidays

    def is_trading_day(self, check_date: date) -> bool:
        """True iff weekday (Mon-Fri) AND not a known holiday."""
        return check_date.weekday() < 5 and not self.is_holiday(check_date)

    # ------------------------------------------------------------------
    # Market session helpers
    # ------------------------------------------------------------------

    def is_market_open(self, now: datetime | None = None) -> bool:
        """True iff ``now`` is inside the regular session window AND
        today is a trading day.

        The reference clock is KST (KRX market timezone). Behaviour by
        ``now`` shape:

          * ``None`` -- use ``datetime.now(KST)`` (default path is safe
            on UTC hosts).
          * tz-aware ``datetime`` -- normalise to KST before comparing.
          * naive ``datetime`` -- assumed to already be KST (operator
            tooling, fixtures); a WARNING is logged so accidental
            naive UTC values surface in logs instead of silently
            shifting 9 hours.
        """
        if now is None:
            moment = datetime.now(_KST).replace(tzinfo=None)
        elif now.tzinfo is None:
            log.warning(
                "v71_market_schedule.is_market_open received naive "
                "datetime -- assuming KST. Pass tz-aware to silence.",
            )
            moment = now
        else:
            moment = now.astimezone(_KST).replace(tzinfo=None)
        today = moment.date()
        if not self.is_trading_day(today):
            return False
        clock = moment.time()
        return self._market_open <= clock < self._market_close

    def next_trading_day(self, after: date) -> date:
        """Return the first trading day strictly after ``after``.

        Safety bound: 30 calendar days (handles longest known
        consecutive holiday run + safety margin).
        """
        cursor = after + timedelta(days=1)
        for _ in range(30):
            if self.is_trading_day(cursor):
                return cursor
            cursor += timedelta(days=1)
        return cursor  # fallback (should never hit; safety only)


# ---------------------------------------------------------------------------
# Module singleton (matches V7.0 ``get_market_schedule`` shape)
# ---------------------------------------------------------------------------

_singleton: V71MarketSchedule | None = None


def get_v71_market_schedule() -> V71MarketSchedule:
    """Return the process-wide V71MarketSchedule singleton.

    Tests inject holidays via ``set_holidays`` directly on the returned
    instance; production wiring (e.g. trading_bridge) calls this once at
    attach to seed holidays from DB.
    """
    global _singleton
    if _singleton is None:
        _singleton = V71MarketSchedule()
    return _singleton


__all__ = ["V71MarketSchedule", "get_v71_market_schedule"]
