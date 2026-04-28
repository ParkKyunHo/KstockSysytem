"""KRX 휴장일 fallback list (Phase A 후속 P-Wire-14).

Source-of-truth precedence:
  1. ``market_calendar`` table (DB) -- PRD §6.1, operator-managed.
  2. This module's hardcoded constants -- last-resort fallback when
     the DB is empty or unreachable (Constitution §4 — system always
     runs even if the DB is degraded).

The constants below cover the 2026 calendar year. They are NOT a
substitute for operator-managed seed data: half-days, emergency
closures, and post-2026 holidays must be entered via DB. A boot-time
WARNING fires whenever the fallback is in effect so operators know
to seed the table.

Curation notes (KRX-specific additions on top of public holidays):
  - 근로자의 날 (5/1) -- statutory non-work day, KRX closes.
  - 연말 폐장 (12/30 or last business day in December) -- KRX-specific
    HALF_DAY/holiday convention; BookKeeping is HOLIDAY here so the
    fallback is conservative (better to miss a half-session than to
    enter on a known-closed day). Operators can downgrade via DB
    (insert ``HALF_DAY`` row) if/when supported.

References:
  - https://open.krx.co.kr/ (official KRX trading calendar)
  - 02_TRADING_RULES.md §7 / §10
  - 03_DATA_MODEL.md §6.1
"""

from __future__ import annotations

from datetime import date

# 2026 KR public holidays + KRX-specific closures.
# Conservative: when an actual KRX status is uncertain (e.g. weekend
# overlaps, half-days), we mark it HOLIDAY here so the fallback errs on
# the side of *not* trading. The DB row can override with TRADING /
# HALF_DAY when operators verify the official KRX schedule.
KR_HOLIDAYS_2026: frozenset[date] = frozenset(
    {
        date(2026, 1, 1),     # 신정
        date(2026, 2, 16),    # 설날 연휴 (전일)
        date(2026, 2, 17),    # 설날
        date(2026, 2, 18),    # 설날 연휴 (익일)
        date(2026, 3, 2),     # 삼일절 대체 휴일 (3/1 일요일)
        date(2026, 5, 1),     # 근로자의 날 (KRX 휴장)
        date(2026, 5, 5),     # 어린이날
        date(2026, 5, 25),    # 부처님 오신 날
        date(2026, 8, 17),    # 광복절 대체 휴일 (8/15 토요일)
        date(2026, 9, 24),    # 추석 연휴 (전일)
        date(2026, 9, 25),    # 추석
        date(2026, 10, 5),    # 개천절 대체 휴일 (10/3 토요일)
        date(2026, 10, 9),    # 한글날
        date(2026, 12, 25),   # 성탄절
        date(2026, 12, 31),   # KRX 연말 폐장 (보수적 — DB에서 HALF_DAY로 덮어쓰기 가능)
    }
)


__all__ = ["KR_HOLIDAYS_2026"]
