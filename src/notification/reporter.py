"""
일일 리포트 생성 모듈

거래 기록을 집계하여 일일 리포트를 생성합니다.
"""

from datetime import date, datetime, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from src.database import (
    get_trade_repository,
    get_daily_stats_repository,
    get_signal_repository,
    Trade,
    TradeStatus,
)
from src.utils.logger import get_logger


logger = get_logger(__name__)


@dataclass
class DailyReportData:
    """일일 리포트 데이터"""
    date: date

    # 거래 통계
    total_trades: int = 0
    win_trades: int = 0
    loss_trades: int = 0
    win_rate: float = 0.0

    # 손익
    total_profit: int = 0      # 수익 거래의 총 이익
    total_loss: int = 0        # 손실 거래의 총 손실
    net_pnl: int = 0           # 순 손익
    avg_profit: float = 0.0    # 평균 수익 (수익 거래)
    avg_loss: float = 0.0      # 평균 손실 (손실 거래)
    largest_profit: int = 0    # 최대 수익
    largest_loss: int = 0      # 최대 손실

    # 수익률
    avg_profit_rate: float = 0.0
    avg_loss_rate: float = 0.0

    # 보유 시간
    avg_holding_minutes: float = 0.0

    # 신호 통계
    signals_detected: int = 0
    signals_executed: int = 0
    signals_blocked: int = 0

    # 거래 상세
    trades: List[Trade] = None

    def __post_init__(self):
        if self.trades is None:
            self.trades = []


class DailyReporter:
    """일일 리포트 생성기"""

    def __init__(self):
        self._trade_repo = get_trade_repository()
        self._stats_repo = get_daily_stats_repository()
        self._signal_repo = get_signal_repository()

    async def generate_report(
        self,
        target_date: Optional[date] = None,
    ) -> DailyReportData:
        """
        일일 리포트 생성

        Args:
            target_date: 대상 날짜 (기본: 오늘)

        Returns:
            DailyReportData
        """
        if target_date is None:
            target_date = date.today()

        # 거래 내역 조회
        trades = await self._trade_repo.get_trades_by_date(target_date)

        # 청산된 거래만 필터링
        closed_trades = [t for t in trades if t.status == TradeStatus.CLOSED]

        # 리포트 데이터 생성
        report = DailyReportData(
            date=target_date,
            trades=trades,
        )

        if not closed_trades:
            return report

        # 수익/손실 거래 분류
        win_trades = [t for t in closed_trades if t.profit_loss > 0]
        loss_trades = [t for t in closed_trades if t.profit_loss <= 0]

        report.total_trades = len(closed_trades)
        report.win_trades = len(win_trades)
        report.loss_trades = len(loss_trades)

        # 승률
        if report.total_trades > 0:
            report.win_rate = (report.win_trades / report.total_trades) * 100

        # 손익 집계
        report.total_profit = sum(t.profit_loss for t in win_trades)
        report.total_loss = sum(t.profit_loss for t in loss_trades)
        report.net_pnl = report.total_profit + report.total_loss

        # 평균 손익
        if win_trades:
            report.avg_profit = report.total_profit / len(win_trades)
            report.avg_profit_rate = sum(t.profit_loss_rate for t in win_trades) / len(win_trades)
            report.largest_profit = max(t.profit_loss for t in win_trades)

        if loss_trades:
            report.avg_loss = report.total_loss / len(loss_trades)
            report.avg_loss_rate = sum(t.profit_loss_rate for t in loss_trades) / len(loss_trades)
            report.largest_loss = min(t.profit_loss for t in loss_trades)

        # 평균 보유 시간
        holding_times = [t.holding_seconds for t in closed_trades if t.holding_seconds]
        if holding_times:
            report.avg_holding_minutes = (sum(holding_times) / len(holding_times)) / 60

        logger.info(
            f"일일 리포트 생성: {target_date}",
            trades=report.total_trades,
            net_pnl=report.net_pnl,
            win_rate=report.win_rate,
        )

        return report

    async def generate_weekly_summary(self) -> Dict[str, Any]:
        """
        주간 요약 리포트

        Returns:
            주간 통계 딕셔너리
        """
        end_date = date.today()
        start_date = end_date - timedelta(days=6)

        daily_stats = await self._stats_repo.get_range(start_date, end_date)

        if not daily_stats:
            return {
                "period": f"{start_date} ~ {end_date}",
                "total_trades": 0,
                "net_pnl": 0,
                "avg_win_rate": 0,
            }

        total_trades = sum(s.trade_count for s in daily_stats)
        net_pnl = sum(s.net_pnl for s in daily_stats)
        win_rates = [s.win_rate for s in daily_stats if s.win_rate is not None]
        avg_win_rate = sum(win_rates) / len(win_rates) if win_rates else 0

        return {
            "period": f"{start_date} ~ {end_date}",
            "trading_days": len(daily_stats),
            "total_trades": total_trades,
            "net_pnl": net_pnl,
            "avg_daily_pnl": net_pnl / len(daily_stats) if daily_stats else 0,
            "avg_win_rate": avg_win_rate,
        }

    async def save_daily_stats(
        self,
        target_date: Optional[date] = None,
    ) -> None:
        """
        일일 통계를 DB에 저장

        Args:
            target_date: 대상 날짜
        """
        if target_date is None:
            target_date = date.today()

        report = await self.generate_report(target_date)

        await self._stats_repo.upsert(
            target_date=target_date,
            stats={
                "trade_count": report.total_trades,
                "win_count": report.win_trades,
                "loss_count": report.loss_trades,
                "total_profit": report.total_profit,
                "total_loss": abs(report.total_loss),
                "net_pnl": report.net_pnl,
                "avg_profit_rate": report.avg_profit_rate,
                "avg_loss_rate": report.avg_loss_rate,
                "win_rate": report.win_rate,
            }
        )

        logger.info(f"일일 통계 저장 완료: {target_date}")


def format_daily_report_detailed(report: DailyReportData) -> str:
    """
    상세 일일 리포트 포맷팅

    Args:
        report: DailyReportData

    Returns:
        포맷된 리포트 문자열
    """
    date_str = report.date.strftime("%Y-%m-%d")

    # 승률 이모지
    if report.win_rate >= 70:
        win_emoji = "🔥"
    elif report.win_rate >= 50:
        win_emoji = "👍"
    elif report.win_rate > 0:
        win_emoji = "⚠️"
    else:
        win_emoji = "📊"

    # 손익 이모지
    if report.net_pnl > 0:
        pnl_emoji = "💰"
    elif report.net_pnl < 0:
        pnl_emoji = "📉"
    else:
        pnl_emoji = "➖"

    lines = [
        f"📊 **일일 거래 리포트**",
        f"",
        f"날짜: {date_str}",
        f"",
        f"**거래 현황**",
        f"총 거래: {report.total_trades}건",
        f"수익: {report.win_trades}건 / 손실: {report.loss_trades}건",
        f"{win_emoji} 승률: {report.win_rate:.1f}%",
        f"",
        f"**손익 현황**",
        f"{pnl_emoji} 순손익: {report.net_pnl:+,}원",
        f"총 수익: {report.total_profit:+,}원",
        f"총 손실: {report.total_loss:+,}원",
        f"",
    ]

    if report.win_trades > 0:
        lines.append(f"**수익 거래**")
        lines.append(f"평균 수익: {report.avg_profit:+,.0f}원 ({report.avg_profit_rate:+.2f}%)")
        lines.append(f"최대 수익: {report.largest_profit:+,}원")
        lines.append(f"")

    if report.loss_trades > 0:
        lines.append(f"**손실 거래**")
        lines.append(f"평균 손실: {report.avg_loss:+,.0f}원 ({report.avg_loss_rate:+.2f}%)")
        lines.append(f"최대 손실: {report.largest_loss:+,}원")
        lines.append(f"")

    if report.avg_holding_minutes > 0:
        lines.append(f"**보유 시간**")
        lines.append(f"평균: {report.avg_holding_minutes:.1f}분")
        lines.append(f"")

    lines.append("---")
    lines.append("🤖 K_stock_trading")

    return "\n".join(lines)


def format_weekly_summary(summary: Dict[str, Any]) -> str:
    """
    주간 요약 포맷팅

    Args:
        summary: 주간 통계 딕셔너리

    Returns:
        포맷된 문자열
    """
    pnl = summary.get("net_pnl", 0)
    pnl_emoji = "💰" if pnl > 0 else "📉" if pnl < 0 else "➖"

    return f"""📅 **주간 거래 요약**

기간: {summary.get('period', '')}
거래일: {summary.get('trading_days', 0)}일

**거래 현황**
총 거래: {summary.get('total_trades', 0)}건
평균 승률: {summary.get('avg_win_rate', 0):.1f}%

**손익 현황**
{pnl_emoji} 순손익: {pnl:+,}원
일평균: {summary.get('avg_daily_pnl', 0):+,.0f}원

---
🤖 K_stock_trading"""


# 싱글톤 인스턴스
_reporter: Optional[DailyReporter] = None


def get_reporter() -> DailyReporter:
    """DailyReporter 싱글톤"""
    global _reporter
    if _reporter is None:
        _reporter = DailyReporter()
    return _reporter
