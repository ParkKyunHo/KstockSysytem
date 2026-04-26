"""
놓친 신호 추적 모듈 (V7.0)

모든 신호 시도를 기록하여 시스템 검증 및 파라미터 튜닝에 활용합니다.

주요 기능:
- 모든 신호 시도 기록 (5/5 충족, 4/5 근접, 쿨다운 스킵 등)
- 일일 리포트 생성 (Near-miss 분석, 쿨다운 스킵 분석)
- 시스템 개선을 위한 데이터 수집

신호 시도 분류:
- notified: 5/5 충족하여 알림 발송됨
- same_bar: 5/5 충족했으나 동일 봉에서 이미 알림 발송됨
- cooldown: 5/5 충족했으나 시간 쿨다운 중
- near_miss: 4/5 이상 충족 (신호 근접)
- insufficient: 3/5 이하 (신호 조건 미충족)
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from typing import Dict, List, Optional, Set
import json
import threading


@dataclass
class SignalAttempt:
    """
    신호 시도 기록

    모든 신호 탐지 시도를 기록하여 분석에 활용합니다.

    Attributes:
        stock_code: 종목 코드
        stock_name: 종목명
        timestamp: 시도 시간
        bar_close_time: 봉 완성 시간
        conditions: 개별 조건 충족 여부
        conditions_met: 충족된 조건 수 (0~5)
        confidence: 신호 강도 (0~1)
        notified: 알림 발송 여부
        skip_reason: 스킵 사유 (same_bar, cooldown, insufficient 등)
        details: 추가 세부 정보 (score, rise_pct 등)
    """
    stock_code: str
    stock_name: str
    timestamp: datetime
    bar_close_time: datetime
    conditions: Dict[str, bool]
    conditions_met: int
    confidence: float = 0.0
    notified: bool = False
    skip_reason: Optional[str] = None
    details: Dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """딕셔너리 변환 (JSON 직렬화용)"""
        return {
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "timestamp": self.timestamp.isoformat(),
            "bar_close_time": self.bar_close_time.isoformat(),
            "conditions": self.conditions,
            "conditions_met": self.conditions_met,
            "confidence": self.confidence,
            "notified": self.notified,
            "skip_reason": self.skip_reason,
            "details": self.details,
        }


class MissedSignalTracker:
    """
    놓친 신호 추적기

    모든 신호 시도를 기록하고 일일 리포트를 생성합니다.

    Features:
    - Thread-safe 동시성 지원
    - 일일 리셋 (다음 날 시작 시 자동 초기화)
    - Near-miss 분석 (4/5 충족 신호)
    - 쿨다운 스킵 분석

    Usage:
        tracker = MissedSignalTracker()

        # 신호 시도 기록
        attempt = SignalAttempt(
            stock_code="005930",
            stock_name="삼성전자",
            timestamp=datetime.now(),
            bar_close_time=bar_close_time,
            conditions={"purple_ok": True, ...},
            conditions_met=5,
            confidence=0.85,
            notified=True,
        )
        tracker.log_attempt(attempt)

        # 일일 리포트 생성
        report = tracker.generate_daily_report()
    """

    def __init__(self):
        """MissedSignalTracker 초기화"""
        self._attempts: List[SignalAttempt] = []
        self._confirmed: Set[str] = set()  # (stock_code, bar_close_time)
        self._lock = threading.RLock()
        self._current_date: Optional[date] = None

    def _check_date_reset(self) -> None:
        """
        날짜 변경 시 자동 리셋

        다음 거래일에 새로운 데이터 수집을 위해 초기화.
        """
        today = date.today()
        if self._current_date != today:
            self._attempts.clear()
            self._confirmed.clear()
            self._current_date = today

    def log_attempt(self, attempt: SignalAttempt) -> None:
        """
        신호 시도 기록

        Args:
            attempt: SignalAttempt 객체
        """
        with self._lock:
            self._check_date_reset()

            self._attempts.append(attempt)

            # 알림 발송된 신호는 confirmed에 추가
            if attempt.notified:
                key = f"{attempt.stock_code}_{attempt.bar_close_time.isoformat()}"
                self._confirmed.add(key)

    def get_attempts(self) -> List[SignalAttempt]:
        """
        전체 시도 목록 조회

        Returns:
            SignalAttempt 리스트 (복사본)
        """
        with self._lock:
            self._check_date_reset()
            return list(self._attempts)

    def get_near_misses(self, min_conditions: int = 4) -> List[SignalAttempt]:
        """
        Near-miss 목록 조회 (신호 근접했으나 미발송)

        Args:
            min_conditions: 최소 조건 충족 수 (기본 4)

        Returns:
            Near-miss SignalAttempt 리스트
        """
        with self._lock:
            self._check_date_reset()
            return [
                a for a in self._attempts
                if a.conditions_met >= min_conditions and not a.notified
            ]

    def get_cooldown_skipped(self) -> List[SignalAttempt]:
        """
        쿨다운으로 스킵된 신호 목록 조회 (5/5 충족했으나 스킵)

        Returns:
            쿨다운 스킵 SignalAttempt 리스트
        """
        with self._lock:
            self._check_date_reset()
            return [
                a for a in self._attempts
                if a.conditions_met == 5 and a.skip_reason in ("same_bar", "cooldown")
            ]

    def get_stats(self) -> dict:
        """
        현재 통계 조회

        Returns:
            통계 딕셔너리
        """
        with self._lock:
            self._check_date_reset()

            total = len(self._attempts)
            notified = len([a for a in self._attempts if a.notified])
            near_misses_4 = len([a for a in self._attempts if a.conditions_met == 4 and not a.notified])
            near_misses_5 = len([a for a in self._attempts if a.conditions_met == 5 and not a.notified])
            cooldown_skipped = len([
                a for a in self._attempts
                if a.conditions_met == 5 and a.skip_reason in ("same_bar", "cooldown")
            ])

            return {
                "date": self._current_date.isoformat() if self._current_date else None,
                "total_attempts": total,
                "total_notified": notified,
                "near_misses_4_of_5": near_misses_4,
                "near_misses_5_of_5_skipped": near_misses_5,
                "cooldown_skipped": cooldown_skipped,
            }

    def generate_daily_report(self) -> dict:
        """
        일일 리포트 생성

        장 종료 후 호출하여 상세 분석 리포트를 생성합니다.

        Returns:
            리포트 딕셔너리:
            - date: 날짜
            - summary: 요약 통계
            - near_misses: 4/5 충족 종목 상세
            - cooldown_skipped: 쿨다운 스킵 종목 상세
        """
        with self._lock:
            self._check_date_reset()

            # 기본 통계
            stats = self.get_stats()

            # 4/5 이상 충족했으나 알림 안 된 종목 (상위 10개)
            near_misses = [
                a for a in self._attempts
                if a.conditions_met >= 4 and not a.notified
            ]
            near_misses_sorted = sorted(
                near_misses,
                key=lambda x: (x.conditions_met, x.confidence),
                reverse=True
            )[:10]

            # 5/5 충족했으나 쿨다운으로 스킵된 종목 (상위 10개)
            cooldown_skipped = [
                a for a in self._attempts
                if a.conditions_met == 5 and a.skip_reason in ("same_bar", "cooldown")
            ]
            cooldown_sorted = sorted(
                cooldown_skipped,
                key=lambda x: x.confidence,
                reverse=True
            )[:10]

            # 종목별 시도 횟수 (가장 많이 시도된 종목)
            stock_attempts: Dict[str, int] = {}
            for a in self._attempts:
                key = a.stock_code
                stock_attempts[key] = stock_attempts.get(key, 0) + 1

            top_stocks = sorted(
                stock_attempts.items(),
                key=lambda x: x[1],
                reverse=True
            )[:5]

            return {
                "date": self._current_date.isoformat() if self._current_date else None,
                "summary": stats,
                "near_misses": {
                    "count": len(near_misses),
                    "samples": [a.to_dict() for a in near_misses_sorted],
                },
                "cooldown_skipped": {
                    "count": len(cooldown_skipped),
                    "samples": [a.to_dict() for a in cooldown_sorted],
                },
                "top_attempt_stocks": [
                    {"stock_code": code, "attempts": count}
                    for code, count in top_stocks
                ],
            }

    def clear(self) -> int:
        """
        전체 시도 기록 초기화

        Returns:
            삭제된 시도 수
        """
        with self._lock:
            count = len(self._attempts)
            self._attempts.clear()
            self._confirmed.clear()
            return count

    def to_json(self) -> str:
        """
        JSON 문자열로 변환 (저장용)

        Returns:
            JSON 문자열
        """
        with self._lock:
            self._check_date_reset()
            return json.dumps(
                {
                    "date": self._current_date.isoformat() if self._current_date else None,
                    "attempts": [a.to_dict() for a in self._attempts],
                },
                ensure_ascii=False,
                indent=2,
            )
