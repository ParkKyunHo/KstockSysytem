"""
텔레그램 메시지 템플릿

거래 알림, 상태 보고 등의 메시지 포맷을 정의합니다.
"""

from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime


@dataclass
class TradeNotification:
    """거래 알림 데이터"""
    stock_code: str
    stock_name: str
    quantity: int
    price: int
    total_amount: int
    trade_type: str  # "매수" or "매도"
    result_type: Optional[str] = None  # "익절", "손절", None
    profit_loss_rate: Optional[float] = None


def format_buy_notification(
    stock_code: str,
    stock_name: str,
    quantity: int,
    price: int,
    amount: int,
    strategy: str = "",
    reason: str = "",
) -> str:
    """매수 완료 알림"""
    # 전략 이름 변환
    strategy_display = ""
    if strategy == "CEILING_BREAK":
        strategy_display = "천장파괴"
    elif strategy == "SNIPER_TRAP":
        strategy_display = "스나이퍼"
    elif strategy == "PURPLE_REABS":
        strategy_display = "Purple-ReAbs"
    elif strategy:
        strategy_display = strategy

    # 전략 정보 라인
    strategy_line = f"\n📊 전략: {strategy_display}" if strategy_display else ""
    reason_line = f"\n📝 {reason}" if reason else ""

    return f"""🟢 매수 체결

📌 {stock_name} ({stock_code})
💰 {quantity:,}주 × {price:,}원 = {amount:,}원{strategy_line}{reason_line}

⏰ {datetime.now().strftime('%H:%M:%S')}"""


def format_sell_notification(
    stock_code: str,
    stock_name: str,
    quantity: int,
    entry_price: int,
    exit_price: int,
    pnl: int,
    pnl_rate: float,
    reason: str = "",
) -> str:
    """매도 완료 알림"""
    # 손익 이모지
    pnl_emoji = "📈" if pnl >= 0 else "📉"

    # 매도 사유 변환
    reason_display = ""
    if reason == "HARD_STOP":
        reason_display = "손절"
    elif reason == "TRAILING_STOP":
        reason_display = "트레일링 스탑 (익절)"
    elif reason == "TARGET_PROFIT":
        reason_display = "목표 수익 도달"
    elif reason == "MAX_HOLDING_DAYS":
        reason_display = "최대 보유일 초과"
    elif reason == "END_OF_DAY":
        reason_display = "장 종료 청산"
    elif reason == "STRUCTURE_BREAK":
        reason_display = "구조 붕괴"
    elif reason == "MANUAL":
        reason_display = "수동 청산"
    elif reason:
        reason_display = reason

    reason_line = f"\n🚨 사유: {reason_display}" if reason_display else ""

    # V6.2-G: 손익 금액 숨김 (심리 흔들림 방지)
    return f"""🔴 매도 체결

📌 {stock_name} ({stock_code})
💰 {quantity:,}주

{pnl_emoji} 손익: {pnl_rate:+.2f}%
   매수 {entry_price:,}원 → 매도 {exit_price:,}원{reason_line}

⏰ {datetime.now().strftime('%H:%M:%S')}"""


def format_signal_notification(
    stock_code: str,
    stock_name: str,
    strategy: str,
    price: int,
    reason: str = "",
) -> str:
    """매매 신호 알림"""
    if strategy == "CEILING_BREAK":
        strategy_name = "천장 파괴"
    elif strategy == "PURPLE_REABS":
        strategy_name = "Purple-ReAbs"
    else:
        strategy_name = "스나이퍼"
    return f"""[SIGNAL] {strategy_name}

종목: {stock_name} ({stock_code})
현재가: {price:,}원
근거: {reason}

시간: {datetime.now().strftime('%H:%M:%S')}"""


def format_balance_notification(
    deposit: int,
    available: int,
) -> str:
    """잔고 알림"""
    return f"""💰 **계좌 잔고**

예수금: {deposit:,}원
주문가능: {available:,}원

시간: {datetime.now().strftime('%H:%M:%S')}"""


def format_positions_notification(
    positions: List[dict],
    total_eval: int,
    total_profit_loss: int,
    profit_loss_rate: float,
) -> str:
    """보유종목 알림"""
    if not positions:
        return """📊 **보유종목**

보유 종목이 없습니다."""

    lines = ["📊 **보유종목**\n"]

    for pos in positions:
        emoji = "📈" if pos.get("profit_loss_rate", 0) >= 0 else "📉"
        lines.append(
            f"{emoji} {pos['stock_name']} ({pos['stock_code']})\n"
            f"   {pos['quantity']:,}주 / {pos['profit_loss_rate']:+.2f}%"
        )

    lines.append(f"\n**총평가**: {total_eval:,}원")
    lines.append(f"**총손익**: {total_profit_loss:+,}원 ({profit_loss_rate:+.2f}%)")

    return "\n".join(lines)


def format_status_notification(
    is_running: bool,
    is_paper_trading: bool,
    active_conditions: List[str],
    positions_count: int,
) -> str:
    """상태 알림"""
    status = "🟢 실행 중" if is_running else "🔴 중지됨"
    mode = "모의투자" if is_paper_trading else "실전투자"
    conditions = ", ".join(active_conditions) if active_conditions else "없음"

    return f"""📋 **시스템 상태**

상태: {status}
모드: {mode}
활성 조건식: {conditions}
보유 종목: {positions_count}개

시간: {datetime.now().strftime('%H:%M:%S')}"""


def format_eod_alert() -> str:
    """장 종료 알림 (15:15)"""
    return """⏰ **장 종료 알림**

15:15입니다. 보유 종목 처리 방법을 선택해주세요.

응답이 없으면 설정된 기본 동작이 실행됩니다."""


def format_daily_report(
    date: str,
    total_trades: int,
    buy_count: int,
    sell_count: int,
    realized_profit_loss: int,
    win_rate: float,
    final_balance: int,
) -> str:
    """일일 리포트"""
    return f"""📊 **일일 거래 리포트**

날짜: {date}

**거래 현황**
총 거래: {total_trades}건
매수: {buy_count}건 / 매도: {sell_count}건

**수익 현황**
실현 손익: {realized_profit_loss:+,}원
승률: {win_rate:.1f}%

**계좌 현황**
최종 잔고: {final_balance:,}원

---
🤖 K_stock_trading"""


def format_error_notification(
    error_type: str,
    error_message: str,
    context: str = "",
) -> str:
    """에러 알림"""
    ctx = f"\n상황: {context}" if context else ""
    return f"""🚨 **에러 발생**

유형: {error_type}
메시지: {error_message}{ctx}

시간: {datetime.now().strftime('%H:%M:%S')}"""


def format_start_notification(is_paper_trading: bool) -> str:
    """시작 알림"""
    mode = "모의투자" if is_paper_trading else "실전투자"
    return f"""✅ **거래 시작**

모드: {mode}
시간: {datetime.now().strftime('%H:%M:%S')}

실시간 조건검색과 자동 매매가 시작되었습니다."""


def format_stop_notification() -> str:
    """중지 알림"""
    return f"""⛔ **거래 중지**

시간: {datetime.now().strftime('%H:%M:%S')}

모든 거래 활동이 중지되었습니다."""


def format_help_message() -> str:
    """도움말 메시지 (V7.0)"""
    return """[명령어 목록 - V7.0]

[거래 제어]
/start - 거래 시작
/stop - 거래 중지
/pause - 신규 매수 일시 중지
/resume - 매수 재개
/status - 시스템 상태 조회

[계좌 조회]
/balance - 잔고 조회
/positions - 보유종목 조회

[수동 매매]
/buy <종목코드> <금액|수량> - 수동 매수
/sell <종목코드> <전량|비율|수량> - 수동 매도

[설정]
/ratio [비중%] - 매수 비중 조회/변경
/ignore <종목코드> - 시스템 청산 제외
/unignore <종목코드> - 청산 제외 해제

[시스템]
/substatus - 조건검색 구독 상태
/subscribe - 조건검색 수동 재구독
/wsdiag - WebSocket 진단
/health - 시스템 헬스 체크
/help - 도움말

[청산 로직 - V7.0 Wave Harvest]
1. R-Multiple 기반 ATR 배수 축소 (6.0→4.5→4.0→3.5→2.5→2.0)
2. Trend Hold Filter (추세 보호)
3. 고정 손절 -4% (Safety Net)"""


def format_signal_alert_notification(
    stock_code: str,
    stock_name: str,
    current_price: int,
    signal_metadata: dict,
) -> str:
    """
    SIGNAL_ALERT 모드용 매수 추천 알림 (V7.0)

    Args:
        stock_code: 종목코드
        stock_name: 종목명
        current_price: 현재가
        signal_metadata: 신호 메타데이터 (EMA, reason 등)

    Returns:
        알림 텍스트
    """
    # 예상 손절가 (-4%)
    stop_loss_price = int(current_price * 0.96)

    # 지표 정보 추출
    ema3 = signal_metadata.get("ema3", 0)
    ema20 = signal_metadata.get("ema20", 0)
    ema60 = signal_metadata.get("ema60", 0)
    ema200 = signal_metadata.get("ema200", 0)

    # 신호 사유
    reason = signal_metadata.get("reason", "Purple-ReAbs 조건 충족")

    # 신호 강도 (있는 경우)
    strength = signal_metadata.get("strength", "")
    strength_line = f"\n신호 강도: {strength:.2f}" if isinstance(strength, (int, float)) and strength > 0 else ""

    # 지표 라인 (값이 있는 것만)
    ema_lines = []
    if ema3 > 0:
        ema_lines.append(f"EMA3: {ema3:,}원")
    if ema20 > 0:
        ema_lines.append(f"EMA20: {ema20:,}원")
    if ema60 > 0:
        ema_lines.append(f"EMA60: {ema60:,}원")
    if ema200 > 0:
        ema_lines.append(f"EMA200: {ema200:,}원")
    ema_section = "\n".join(ema_lines) if ema_lines else "지표 정보 없음"

    return f"""=== Purple-ReAbs 매수 추천 ===

종목: {stock_name} ({stock_code})
현재가: {current_price:,}원

[예상 진입/손절]
진입가: {current_price:,}원
손절가: {stop_loss_price:,}원 (-4.0%)

[지표 현황]
{ema_section}{strength_line}

[신호 사유]
{reason}

-------------------------
매수: /buy {stock_code} <금액>
예시: /buy {stock_code} 500000

{datetime.now().strftime('%H:%M:%S')}"""
