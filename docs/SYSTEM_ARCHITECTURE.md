# K_stock_trading 시스템 아키텍처

> **버전**: V7.0 Purple-ReAbs
> **최종 수정**: 2025-01-22
> **상태**: V7 전용 운영 (V6 비활성화)

---

## 1. 시스템 개요

### 1.1 목적
키움증권 REST API 기반 국내 주식 자동매매 시스템

### 1.2 운영 환경
| 항목 | 값 |
|------|-----|
| 서버 | AWS EC2 (Ubuntu) |
| IP | 43.200.235.74 |
| Python | 3.11 |
| DB | PostgreSQL (Supabase) |

### 1.3 거래 모드
| 모드 | 설명 |
|------|------|
| `MANUAL_ONLY` | /add 명령어로 등록한 종목만 거래 |
| `AUTO_UNIVERSE` | 조건검색 자동등록 + /add |
| `SIGNAL_ALERT` | 신호 알림만 전송 + 수동매수 시 자동청산 (V7 권장) |

---

## 2. 핵심 컴포넌트

### 2.1 TradingEngine (`src/core/trading_engine.py`)

메인 거래 엔진 (5,593 라인)

| 라인 범위 | 기능 |
|----------|------|
| 1-100 | import 및 상수 정의 |
| 100-500 | TradingEngine 클래스 초기화 |
| 500-900 | WebSocket 연결 및 틱 데이터 처리 |
| 900-1400 | 조건검색 신호 처리 |
| 1400-1700 | 캔들 업데이트 및 신호 탐지 호출 |
| **1712-1720** | **V7.0: V6 신호 비활성화 분기** |
| 1728-1916 | 신호 처리 및 알림 (_process_signal, _send_signal_alert_notification) |
| 1916-2500 | 주문 실행 및 포지션 관리 |
| 2500-3500 | 포지션 동기화 (HTS 매매 감지) |
| 3500-5593 | 배경 태스크 (청산 체크, 상태 모니터링) |

### 2.2 신호 탐지 시스템

| 모듈 | 파일 | 상태 | 역할 |
|------|------|------|------|
| SignalDetector | `signal_detector.py` | **비활성화** | V6.2-A SNIPER_TRAP 신호 |
| AtrAlertManager | `atr_alert_manager.py` | **비활성화** | V6 Grand Trend 지저깨 알림 |
| PurpleIndicator | `indicator_purple.py` | 활성화 | Purple 지표 계산 |
| SignalPool | `signal_pool.py` | 활성화 | 종목 신호 상태 관리 |
| PurpleSignalDetector | `signal_detector_purple.py` | 활성화 | V7 Purple-ReAbs 신호 탐지 |
| DualPassDetector | `signal_detector_purple.py` | 활성화 | Pre-Check + Confirm-Check |

### 2.3 청산 시스템

| 모듈 | 파일 | 상태 | 역할 |
|------|------|------|------|
| ExitManager | `exit_manager.py` | 호환용 | V6 분할 익절 (레거시) |
| WaveHarvestExit | `wave_harvest_exit.py` | 활성화 | V7 ATR 트레일링 스탑 |
| WatermarkManager | `watermark_manager.py` | 활성화 | 최고가 워터마크 관리 |

### 2.4 기타 핵심 모듈

| 모듈 | 파일 | 역할 |
|------|------|------|
| PositionManager | `position_manager.py` | 포지션 상태 관리 |
| RiskManager | `risk_manager.py` | 리스크 체크 (진입 가능 여부) |
| OrderExecutor | `order_executor.py` | 주문 실행 추상화 |
| AutoScreener | `auto_screener.py` | 자동 유니버스 선별 |
| CandleManager | `candle_builder.py` | 틱 → 캔들 변환 |
| Indicator | `indicator.py` | 기술적 지표 계산 |

---

## 3. V7 Purple-ReAbs 신호 흐름

### 3.1 신호 조건 (5개 모두 충족)

```
Signal = PurpleOK AND Trend AND Zone AND ReAbsStart AND Trigger

PurpleOK: (H1/L1-1)>=4% AND (H2/L2-1)<=7% AND M>=5억
Trend: EMA60 > EMA60[3]
Zone: Close >= EMA60 × 0.995
ReAbsStart: Score > Score[1]
Trigger: CrossUp(Close, EMA3) AND Close > Open
```

### 3.2 신호 탐지 흐름도

```
┌─────────────────┐
│  조건검색 편입   │
│  (WebSocket)    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Pre-Check      │ ← PurpleOK + Trend + Zone
│  (즉시 체크)    │
└────────┬────────┘
         │ 통과 시
         ▼
┌─────────────────┐
│  SignalPool     │ ← Pre-Check 통과 종목 관리
│  등록           │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Confirm-Check  │ ← ReAbsStart + Trigger
│  (캔들 마감 시)  │
└────────┬────────┘
         │ 통과 시
         ▼
┌─────────────────┐
│  알림 전송      │ ← SIGNAL_ALERT 모드
│  (Telegram)     │
└─────────────────┘
```

### 3.3 DualPassDetector 동작

| 단계 | 시점 | 체크 조건 |
|------|------|----------|
| Pre-Check | 조건검색 편입 즉시 | PurpleOK, Trend, Zone |
| Confirm-Check | 캔들 마감 시 | ReAbsStart, Trigger |

---

## 4. V7 Wave Harvest 청산 흐름

### 4.1 청산 조건

| 조건 | 설명 |
|------|------|
| Hard Stop | -4% 고정 손절 (최우선) |
| ATR Trailing Stop | ATR 배수 기반 트레일링 |
| Trend Hold Filter | 청산 차단 조건 |

### 4.2 ATR 배수 단계

| R-Multiple | ATR 배수 |
|-----------|---------|
| 초기 진입 | 6.0 |
| 구조 경고 | 4.5 |
| R >= 1 | 4.0 |
| R >= 2 | 3.5 |
| R >= 3 | 2.5 |
| R >= 5 | 2.0 |

### 4.3 청산 흐름도

```
┌─────────────────┐
│  틱 데이터 수신  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Hard Stop 체크 │ ← -4% 이하?
│  (최우선)       │
└────────┬────────┘
         │ 미충족
         ▼
┌─────────────────┐
│  R-Multiple 계산 │ ← (현재가-진입가)/(진입가×0.04)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  ATR 배수 조정   │ ← R 단계에 따라 배수 감소
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Trailing Stop  │ ← BasePrice - ATR × Multiplier
│  계산           │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Trend Hold     │ ← EMA20 > EMA60 AND HH(20) > HH(60)
│  Filter 체크    │
└────────┬────────┘
         │ NOT TrendHold
         ▼
┌─────────────────┐
│  Close < TS?    │ ← 트레일링 스탑 이탈
│  → 청산 실행    │
└─────────────────┘
```

---

## 5. 핵심 파일 맵

### 5.1 src/core/

| 파일 | 라인 수 | 역할 |
|------|--------|------|
| trading_engine.py | 5,593 | 메인 거래 엔진 |
| signal_detector_purple.py | ~800 | V7 신호 탐지 |
| wave_harvest_exit.py | ~400 | V7 청산 로직 |
| indicator_purple.py | ~300 | Purple 지표 계산 |
| signal_pool.py | ~200 | 신호 상태 관리 |
| watermark_manager.py | ~150 | 워터마크 관리 |
| position_manager.py | ~500 | 포지션 관리 |
| exit_manager.py | ~600 | V6 청산 (레거시) |
| signal_detector.py | ~800 | V6 신호 (비활성화) |

### 5.2 src/api/

| 파일 | 역할 |
|------|------|
| client.py | 키움 REST API 클라이언트 |
| websocket.py | 실시간 틱 데이터 수신 |
| endpoints/order.py | 주문 API |
| endpoints/market.py | 시세 조회 API |
| endpoints/account.py | 계좌 조회 API |

### 5.3 src/notification/

| 파일 | 역할 |
|------|------|
| telegram.py | 텔레그램 봇 |
| templates.py | 알림 템플릿 |
| notification_queue.py | 알림 큐 관리 |

---

## 6. 환경 설정

### 6.1 V7 전용 설정 (.env)

```bash
# V7 Purple-ReAbs 전용 설정
V7_PURPLE_ENABLED=true
SNIPER_TRAP_ENABLED=false  # V6 SNIPER_TRAP 비활성화
ATR_ALERT_ENABLED=false    # V6 지저깨 알림 비활성화

# 권장 거래 모드
TRADING_MODE=SIGNAL_ALERT
```

### 6.2 비활성화된 V6 기능

| 기능 | 환경변수 | 상태 |
|------|---------|------|
| SNIPER_TRAP 신호 | `SNIPER_TRAP_ENABLED=false` | 비활성화 |
| Grand Trend 지저깨 | `ATR_ALERT_ENABLED=false` | 비활성화 |

### 6.3 활성화된 V7 기능

| 기능 | 환경변수 | 상태 |
|------|---------|------|
| Purple-ReAbs 신호 | `V7_PURPLE_ENABLED=true` | 활성화 |
| Wave Harvest 청산 | (기본 활성화) | 활성화 |
| DualPass 탐지 | (기본 활성화) | 활성화 |

---

## 7. 수정 불가 항목 (V7 불변조건)

```
- Score 가중치: (C/W-1)*2, LZ*0.8, recovery*1.2
- PurpleOK 임계값: 상승률 4%, 수렴률 7%, 거래대금 5억
- Zone 허용 범위: EMA60 × 0.995
- ATR 배수 단계: 6.0 → 4.5 → 4.0 → 3.5 → 2.5 → 2.0
- Trend Hold Filter 조건
- EMA adjust=False
- Risk-First: 고정 손절 -4% 최우선
- TS 상향 전용: 트레일링 스탑 하락 불가
```

---

## 8. 참조 문서

| 문서 | 용도 |
|------|------|
| `CLAUDE.md` | Claude 작업 지침 |
| `docs/TECHNICAL_DOCUMENTATION.md` | 상세 기술 문서 |
| `docs/BACKTEST_GUIDELINES.md` | 백테스팅 가이드 |
| `docs/DEPLOYMENT_GUIDE.md` | 배포 가이드 |
| `docs/CHANGELOG.md` | 버전 히스토리 |
