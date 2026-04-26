"""
통합 신호 Pool 관리 모듈 (V7.0)

V6의 3단계 Pool (Watchlist → Candidate → Active) 구조를 단순화.
1단계 통합 Pool로 변경하여 알림 전용 시스템에 최적화.

특징:
- P1: TTL 기반 자동 만료 (24시간)
- P1: 크기 제한 (10,000개)
- Thread-safe 동시성 관리
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any


# P1: Pool 크기 및 TTL 제한
MAX_POOL_SIZE = 10000          # 최대 Pool 크기
POOL_TTL_HOURS = 24            # 종목 TTL (시간)


@dataclass
class StockInfo:
    """
    Pool 내 종목 정보

    Attributes:
        stock_code: 종목코드 (6자리)
        stock_name: 종목명
        added_at: Pool 추가 시간
        last_signal_at: 마지막 신호 발생 시간 (알림 발송 기준)
        last_signal_bar: 마지막 신호 발생 봉 완성 시간 (봉 단위 쿨다운용)
        signal_count: 신호 발생 횟수
        metadata: 추가 정보 (거래대금, 등락률 등)
    """
    stock_code: str
    stock_name: str
    added_at: datetime = field(default_factory=datetime.now)
    last_signal_at: Optional[datetime] = None
    last_signal_bar: Optional[datetime] = None
    signal_count: int = 0
    metadata: dict = field(default_factory=dict)
    # PreCheck PurpleOK 캐시 (실시간 volume 스케일 차이로 ConfirmCheck에서 거짓 음성 방지)
    purple_ok_cached: Optional[bool] = None
    purple_ok_cached_at: Optional[datetime] = None
    # C-007 FIX: 동시 접근 보호 Lock (병렬 Confirm-Check에서 동일 봉 중복 신호 방지)
    _signal_lock: threading.Lock = field(default_factory=threading.Lock)

    def update_signal(self) -> None:
        """신호 발생 기록 갱신"""
        self.last_signal_at = datetime.now()
        self.signal_count += 1

    def can_signal_new_bar(self, current_bar_time: datetime) -> bool:
        """
        새 봉에서만 신호 허용 (봉 단위 쿨다운)

        같은 봉에서 중복 신호 발송을 방지합니다.

        Args:
            current_bar_time: 현재 봉 완성 시간

        Returns:
            True: 신호 가능 (새 봉), False: 같은 봉에서 이미 신호 발송됨
        """
        if self.last_signal_bar is None:
            return True
        return current_bar_time > self.last_signal_bar

    def update_signal_bar(self, bar_close_time: datetime) -> bool:
        """
        신호 발생 봉 기록 (원자적 연산)

        봉 단위 쿨다운과 시간 기반 쿨다운 모두 업데이트.
        C-007 FIX: Lock으로 동시 접근 보호하여 중복 신호 방지.

        Args:
            bar_close_time: 신호 발생 봉의 완성 시간

        Returns:
            True: 신호 기록 성공 (새 봉), False: 이미 같은 봉에서 신호 발생
        """
        with self._signal_lock:
            # 동일 봉 체크 (Lock 내에서 다시 확인)
            if self.last_signal_bar is not None and bar_close_time <= self.last_signal_bar:
                return False  # 이미 같은 봉에서 신호 발생

            self.last_signal_bar = bar_close_time
            self.last_signal_at = datetime.now()
            self.signal_count += 1
            return True

    def get_signal_cooldown_elapsed(self, cooldown_seconds: int) -> bool:
        """
        신호 쿨다운 경과 여부 확인

        Args:
            cooldown_seconds: 쿨다운 시간 (초)

        Returns:
            True: 쿨다운 경과 (신호 가능), False: 쿨다운 중
        """
        if self.last_signal_at is None:
            return True

        elapsed = (datetime.now() - self.last_signal_at).total_seconds()
        return elapsed >= cooldown_seconds


class SignalPool:
    """
    통합 신호 Pool

    조건검색에서 포착된 종목을 관리하고, 신호 탐지 대상으로 제공.
    3단계 Pool 구조를 단순화하여 1단계 통합 Pool로 운영.

    Features:
    - Thread-safe 동시성 지원 (RLock 사용)
    - P1: TTL 기반 자동 만료 (24시간)
    - P1: 크기 제한 (10,000개)
    - 신호 쿨다운 관리

    Usage:
        pool = SignalPool()
        pool.add("005930", "삼성전자", {"change_rate": 5.2})
        if pool.contains("005930"):
            info = pool.get("005930")
            info.update_signal()
        pool.remove("005930")
    """

    def __init__(self):
        """SignalPool 초기화"""
        self._pool: Dict[str, StockInfo] = {}
        self._lock = threading.RLock()
        # P1: 만료/정리 통계
        self._evicted_count = 0
        self._expired_count = 0

    def _is_expired(self, info: StockInfo) -> bool:
        """
        P1: 종목 TTL 만료 여부 확인

        Args:
            info: StockInfo 객체

        Returns:
            True: 만료됨, False: 유효
        """
        elapsed_hours = (datetime.now() - info.added_at).total_seconds() / 3600
        return elapsed_hours >= POOL_TTL_HOURS

    def _evict_oldest(self) -> int:
        """
        P1: 가장 오래된 종목 제거 (크기 제한 초과 시)

        Returns:
            제거된 종목 수
        """
        # Lock 내부에서 호출되어야 함
        if len(self._pool) < MAX_POOL_SIZE:
            return 0

        # added_at 기준 정렬하여 가장 오래된 10% 제거
        sorted_items = sorted(
            self._pool.items(),
            key=lambda x: x[1].added_at
        )
        evict_count = max(1, len(self._pool) // 10)  # 최소 1개, 최대 10%

        for code, _ in sorted_items[:evict_count]:
            del self._pool[code]
            self._evicted_count += 1

        return evict_count

    def cleanup_expired(self) -> int:
        """
        P1: 만료된 종목 정리

        Returns:
            제거된 종목 수
        """
        with self._lock:
            expired_codes = [
                code for code, info in self._pool.items()
                if self._is_expired(info)
            ]
            for code in expired_codes:
                del self._pool[code]
                self._expired_count += 1
            return len(expired_codes)

    def add(
        self,
        stock_code: str,
        stock_name: str,
        metadata: Optional[dict] = None
    ) -> StockInfo:
        """
        종목 추가

        이미 존재하는 종목은 metadata만 업데이트 (added_at 유지).
        P1: 크기 제한 초과 시 가장 오래된 종목 제거.

        Args:
            stock_code: 종목코드
            stock_name: 종목명
            metadata: 추가 정보 (선택)

        Returns:
            추가/업데이트된 StockInfo
        """
        with self._lock:
            if stock_code in self._pool:
                # 기존 종목: metadata만 업데이트
                existing = self._pool[stock_code]
                if metadata:
                    existing.metadata.update(metadata)
                return existing
            else:
                # P1: 크기 제한 체크
                if len(self._pool) >= MAX_POOL_SIZE:
                    self._evict_oldest()

                # 신규 종목 추가
                info = StockInfo(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    metadata=metadata or {}
                )
                self._pool[stock_code] = info
                return info

    def remove(self, stock_code: str) -> bool:
        """
        종목 제거

        Args:
            stock_code: 종목코드

        Returns:
            True: 제거 성공, False: 존재하지 않음
        """
        with self._lock:
            if stock_code in self._pool:
                del self._pool[stock_code]
                return True
            return False

    def get(self, stock_code: str) -> Optional[StockInfo]:
        """
        종목 정보 조회

        Args:
            stock_code: 종목코드

        Returns:
            StockInfo 또는 None
        """
        with self._lock:
            return self._pool.get(stock_code)

    def get_all(self) -> List[StockInfo]:
        """
        전체 종목 조회

        Returns:
            StockInfo 리스트 (복사본)
        """
        with self._lock:
            return list(self._pool.values())

    def get_all_codes(self) -> List[str]:
        """
        전체 종목코드 조회

        Returns:
            종목코드 리스트
        """
        with self._lock:
            return list(self._pool.keys())

    def contains(self, stock_code: str) -> bool:
        """
        종목 존재 여부 확인

        Args:
            stock_code: 종목코드

        Returns:
            True: 존재, False: 미존재
        """
        with self._lock:
            return stock_code in self._pool

    def size(self) -> int:
        """
        Pool 크기

        Returns:
            종목 수
        """
        with self._lock:
            return len(self._pool)

    def clear(self) -> int:
        """
        Pool 초기화 (전체 제거)

        Returns:
            제거된 종목 수
        """
        with self._lock:
            count = len(self._pool)
            self._pool.clear()
            return count

    def update_signal(self, stock_code: str) -> bool:
        """
        종목의 신호 발생 기록 갱신

        Args:
            stock_code: 종목코드

        Returns:
            True: 갱신 성공, False: 종목 없음
        """
        with self._lock:
            info = self._pool.get(stock_code)
            if info:
                info.update_signal()
                return True
            return False

    def can_signal(self, stock_code: str, cooldown_seconds: int = 300) -> bool:
        """
        신호 발생 가능 여부 (쿨다운 체크)

        Args:
            stock_code: 종목코드
            cooldown_seconds: 쿨다운 시간 (초, 기본 5분)

        Returns:
            True: 신호 가능, False: 쿨다운 중 또는 종목 없음
        """
        with self._lock:
            info = self._pool.get(stock_code)
            if info:
                return info.get_signal_cooldown_elapsed(cooldown_seconds)
            return False

    def get_signal_ready_stocks(self, cooldown_seconds: int = 300) -> List[StockInfo]:
        """
        신호 발생 가능 종목 조회 (쿨다운 경과)

        Args:
            cooldown_seconds: 쿨다운 시간 (초)

        Returns:
            신호 가능 종목 리스트
        """
        with self._lock:
            return [
                info for info in self._pool.values()
                if info.get_signal_cooldown_elapsed(cooldown_seconds)
            ]

    def get_recent_stocks(self, seconds: float = 30.0) -> List[StockInfo]:
        """
        최근 N초 이내 추가된 종목 조회 (Late-Arriving 처리용)

        Pre-Check 후보에 등록되지 않았지만 최근 SignalPool에 추가된
        종목들을 Confirm-Check에서 함께 검사할 수 있도록 합니다.

        Args:
            seconds: 조회 시간 범위 (초, 기본 30초)

        Returns:
            최근 추가된 종목 리스트
        """
        with self._lock:
            cutoff = datetime.now() - timedelta(seconds=seconds)
            return [
                info for info in self._pool.values()
                if info.added_at >= cutoff
            ]

    def get_stats(self) -> dict:
        """
        Pool 통계

        Returns:
            통계 딕셔너리
        """
        with self._lock:
            total = len(self._pool)
            signaled = sum(1 for info in self._pool.values() if info.signal_count > 0)
            never_signaled = total - signaled

            return {
                "total": total,
                "signaled": signaled,
                "never_signaled": never_signaled,
                "total_signals": sum(info.signal_count for info in self._pool.values()),
                # P1: 크기 제한/TTL 통계
                "max_pool_size": MAX_POOL_SIZE,
                "pool_ttl_hours": POOL_TTL_HOURS,
                "evicted_count": self._evicted_count,
                "expired_count": self._expired_count,
            }

    def to_dict(self) -> Dict[str, dict]:
        """
        Pool을 딕셔너리로 변환 (직렬화용)

        Returns:
            {stock_code: {name, added_at, signal_count, ...}}
        """
        with self._lock:
            return {
                code: {
                    "stock_name": info.stock_name,
                    "added_at": info.added_at.isoformat(),
                    "last_signal_at": info.last_signal_at.isoformat() if info.last_signal_at else None,
                    "last_signal_bar": info.last_signal_bar.isoformat() if info.last_signal_bar else None,
                    "signal_count": info.signal_count,
                    "metadata": info.metadata,
                }
                for code, info in self._pool.items()
            }

    def __len__(self) -> int:
        """Pool 크기 (len() 지원)"""
        return self.size()

    def __contains__(self, stock_code: str) -> bool:
        """in 연산자 지원"""
        return self.contains(stock_code)

    def __iter__(self):
        """for 루프 지원 (종목코드 순회)"""
        with self._lock:
            return iter(list(self._pool.keys()))
