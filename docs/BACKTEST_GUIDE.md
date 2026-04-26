# BACKTEST_GUIDE.md

> **V7 Purple 백테스트 실행 가이드**
> **버전**: V1.0 | **최종 수정**: 2026-01-26

---

## 1. API 호출 제한

### 1.1 키움 REST API 제한

| 환경 | TR별 제한 | 설정값 | 간격 |
|------|----------|--------|------|
| **실전투자** | 초당 5회 | 4.5 calls/sec | 0.22초 |
| **모의투자** | 초당 1회 (불안정) | 0.33 calls/sec | 3초 |

**주의**: 모의투자는 실제로 초당 1회도 불안정하므로 3초 간격 권장

### 1.2 RateLimiter 설정 위치

```python
# src/api/client.py (196-198행)
class KiwoomAPIClient:
    def __init__(self, ...):
        # 모의투자: 3초에 1회, 실전투자: 초당 4.5회
        calls_per_second = 0.33 if self._config.settings.is_paper_trading else 4.5
        self._rate_limiter = RateLimiter(calls_per_second=calls_per_second)
```

### 1.3 백테스트 설정

```python
# scripts/backtest/v7_intraday/config.py (82-85행)
@dataclass
class BacktestConfig:
    api_concurrency: int = 5          # Semaphore 동시 실행 제한
    api_delay_seconds: float = 0.1    # 최소 딜레이 (RateLimiter와 별개)
```

---

## 2. 병렬 처리 방법

### 2.1 asyncio.Semaphore 동시 실행 제한

```python
# main.py (206-223행)
async def process_with_semaphore(sem: asyncio.Semaphore, event: EventDay):
    async with sem:  # 동시 실행 제한
        trade = await process_event(event)
        return trade

# 병렬 실행
semaphore = asyncio.Semaphore(parallel_workers)  # --parallel 옵션
tasks = [process_with_semaphore(semaphore, event) for event in events]
results = await asyncio.gather(*tasks)
```

### 2.2 적정 워커 수 계산

| 요소 | 값 | 계산 |
|------|-----|------|
| API 속도 제한 | 4.5 calls/sec | 키움 실전 기준 |
| 평균 API 호출/이벤트 | 1~2회 | 분봉 페이지네이션 |
| **권장 워커** | **10~15개** | 여유분 포함 |

```
# 계산식
워커 수 = (API calls/sec) × (평균 응답 시간) / (API 호출/이벤트)
       = 4.5 × 2초 / 1.5 = 6개 (이론)
       → 실제: 10~15개 (네트워크 대기 시간 활용)
```

### 2.3 --parallel 옵션

```powershell
# 기본 (10 workers)
"C:\Program Files\Python311\python.exe" -m scripts.backtest.v7_intraday.main --use-cache

# 병렬 워커 지정
"C:\Program Files\Python311\python.exe" -m scripts.backtest.v7_intraday.main --use-cache --parallel 15
```

---

## 3. 백테스트 코드 구조

### 3.1 v7_intraday 모듈 구조

```
scripts/backtest/v7_intraday/
├── __init__.py
├── config.py              # 설정 + 데이터 클래스 (BacktestConfig, Trade 등)
├── data_loader.py         # 3mintest.csv 로딩, 일봉/분봉 API, parquet 캐싱
├── event_filter.py        # Stage A: 거래대금 1000억 이벤트 필터
├── v7_signal_detector.py  # V7 Purple 신호 탐지
├── trade_simulator.py     # 거래 시뮬레이션 (Wave Harvest 청산)
├── analyzer.py            # 결과 분석 (승률, PF, MDD 등)
├── exporter.py            # Excel 출력
└── main.py                # CLI 진입점
```

### 3.2 2단계 파이프라인

```
┌─────────────────────────────────────────────────────────────┐
│  Stage A: 이벤트 필터링 (일봉)                               │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │ 3mintest.csv │ => │ 일봉 API 조회 │ => │ 거래대금 필터 │  │
│  │ 종목 목록     │    │ (캐싱)       │    │ >= 1000억    │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│                                                   ↓         │
│                                          event_days.csv     │
└─────────────────────────────────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────┐
│  Stage B: 신호 탐지 + 시뮬레이션 (3분봉)                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │ event_days   │ => │ 분봉 API 조회 │ => │ V7 신호 탐지  │  │
│  │ (병렬 처리)  │    │ (캐싱)       │    │ PurpleOK 등  │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│                                                   ↓         │
│                                          ┌──────────────┐  │
│                                          │ 거래 시뮬    │  │
│                                          │ Wave Harvest │  │
│                                          └──────────────┘  │
│                                                   ↓         │
│                              trades.csv, v7_backtest_result.xlsx│
└─────────────────────────────────────────────────────────────┘
```

### 3.3 필수 파일 설명

| 파일 | 역할 | 주요 클래스/함수 |
|------|------|------------------|
| `config.py` | 모든 설정 및 데이터 모델 | `BacktestConfig`, `Trade`, `V7Signal` |
| `data_loader.py` | 데이터 로딩/캐싱 | `load_daily_candles()`, `load_minute_candles()` |
| `event_filter.py` | Stage A 이벤트 필터 | `filter_event_days()`, `save_event_days()` |
| `v7_signal_detector.py` | V7 신호 로직 | `get_first_signal()`, `calculate_indicators()` |
| `trade_simulator.py` | 청산 시뮬레이션 | `simulate_trade()`, `simulate_intraday_trade()` |
| `main.py` | CLI + 실행 흐름 | `V7BacktestRunner`, `run_stage_a()`, `run_stage_b()` |

---

## 4. 데이터 캐싱

### 4.1 캐시 경로

```
C:\K_stock_trading\data\backtest\v7_purple_3min\
├── cache/
│   ├── daily/           # 일봉 캐시
│   │   ├── 005930.parquet
│   │   ├── 000660.parquet
│   │   └── ...
│   └── minute/          # 분봉 캐시 (날짜별)
│       ├── 005930_20260101.parquet
│       ├── 005930_20260102.parquet
│       └── ...
├── event_days.csv       # Stage A 결과
├── event_summary.csv    # 종목별 이벤트 요약
├── trades.csv           # 거래 내역
├── summary.csv          # 결과 요약
└── v7_backtest_result.xlsx  # 전체 분석 보고서
```

### 4.2 캐시 파일 포맷

**일봉 캐시** (`cache/daily/{stock_code}.parquet`):
```
Columns: date, open, high, low, close, volume, trading_value
```

**분봉 캐시** (`cache/minute/{stock_code}_{date}.parquet`):
```
Index: datetime
Columns: open, high, low, close, volume
```

### 4.3 캐시 활용

```powershell
# 캐시 없이 API 조회 (첫 실행)
"C:\Program Files\Python311\python.exe" -m scripts.backtest.v7_intraday.main --fetch --parallel 15

# 캐시 사용 (재실행 - 빠름)
"C:\Program Files\Python311\python.exe" -m scripts.backtest.v7_intraday.main --use-cache --parallel 15
```

### 4.4 캐시 관련 설정

```python
# config.py
use_cache: bool = True  # 캐시 사용 여부

# 수동 캐시 삭제
# del C:\K_stock_trading\data\backtest\v7_purple_3min\cache\daily\*.parquet
# del C:\K_stock_trading\data\backtest\v7_purple_3min\cache\minute\*.parquet
```

---

## 5. 자주 발생하는 오류 및 해결

### 5.1 클라이언트 미초기화

```
에러: APIError: 클라이언트 미초기화. async with 사용 필요
원인: KiwoomAPIClient를 컨텍스트 매니저 없이 사용
해결: async with KiwoomAPIClient() as client: 또는 await client.__aenter__() 호출
```

```python
# 올바른 사용법
async with KiwoomAPIClient() as client:
    response = await client.post(...)

# 또는 (백테스트 코드처럼)
client = KiwoomAPIClient()
await client.__aenter__()  # 명시적 진입
try:
    # 사용
finally:
    await client.__aexit__(None, None, None)  # 정리
```

### 5.2 모듈 Import 오류

```
에러: ModuleNotFoundError: No module named 'scripts.backtest.v7_intraday'
원인: 작업 디렉토리가 프로젝트 루트가 아님
해결: 프로젝트 루트에서 -m 옵션으로 실행
```

```powershell
# 올바른 실행 (프로젝트 루트에서)
cd C:\K_stock_trading
"C:\Program Files\Python311\python.exe" -m scripts.backtest.v7_intraday.main --fetch
```

### 5.3 API 429 에러 (Rate Limit)

```
에러: RateLimitError 또는 HTTP 429
원인: API 호출 빈도 초과 (모의투자에서 자주 발생)
해결: calls_per_second 낮추기
```

```python
# src/api/client.py 수정
# 모의투자: 더 보수적으로
calls_per_second = 0.25  # 4초 간격

# 또는 백테스트 config에서 딜레이 증가
api_delay_seconds: float = 0.5  # 추가 딜레이
```

### 5.4 한글 깨짐

```
에러: UnicodeDecodeError 또는 깨진 종목명
원인: 인코딩 불일치 (cp949 vs utf-8)
해결: 파일별 인코딩 확인
```

| 파일 | 인코딩 |
|------|--------|
| `3mintest.csv` | `cp949` |
| 출력 CSV | `utf-8-sig` (BOM 포함) |
| parquet | 바이너리 (인코딩 무관) |

```python
# 로딩
df = pd.read_csv("3mintest.csv", encoding="cp949")

# 저장
df.to_csv("output.csv", encoding="utf-8-sig", index=False)
```

### 5.5 Circuit Breaker 차단

```
에러: CircuitBreakerOpenError
원인: 연속 5회 API 실패로 차단됨
해결: 60초 대기 후 자동 복구, 또는 네트워크/토큰 확인
```

```python
# 상태 확인
client._circuit_breaker.state  # CLOSED, OPEN, HALF_OPEN

# 수동 리셋 (필요시)
client._circuit_breaker.reset()
```

---

## 6. 실행 명령어 예시

### 6.1 전체 흐름

```powershell
# 1. 전체 데이터 수집 + 백테스트 (첫 실행)
"C:\Program Files\Python311\python.exe" -m scripts.backtest.v7_intraday.main --fetch --parallel 15

# 2. 캐시 사용 백테스트 (재실행)
"C:\Program Files\Python311\python.exe" -m scripts.backtest.v7_intraday.main --use-cache --parallel 15

# 3. 특정 기간만
"C:\Program Files\Python311\python.exe" -m scripts.backtest.v7_intraday.main --fetch --start 2025-12-01 --end 2026-01-15 --parallel 15

# 4. 당일 청산만 (빠름, 익일 이월 없음)
"C:\Program Files\Python311\python.exe" -m scripts.backtest.v7_intraday.main --use-cache --intraday-only --parallel 15

# 5. 특정 종목만
"C:\Program Files\Python311\python.exe" -m scripts.backtest.v7_intraday.main --use-cache --stock 005930
```

### 6.2 CLI 옵션 정리

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `--fetch` | API에서 데이터 조회 (Stage A + B) | - |
| `--use-cache` | 캐시된 이벤트일 사용 (Stage B만) | - |
| `--intraday-only` | 당일 청산만 (익일 이월 없음) | False |
| `--stock CODE` | 특정 종목만 테스트 | 전체 |
| `--start YYYY-MM-DD` | 시작일 | config.event_start |
| `--end YYYY-MM-DD` | 종료일 | config.event_end |
| `--parallel N` | 병렬 워커 수 | 10 |

### 6.3 실행 시간 예상

| 조건 | 예상 시간 |
|------|----------|
| Stage A (500 종목, 캐시 없음) | 30~60분 |
| Stage B (1000 이벤트, 캐시 없음) | 2~4시간 |
| Stage B (캐시 사용) | 5~15분 |
| --intraday-only (캐시 사용) | 3~10분 |

---

## 7. 성능 최적화 체크리스트

### 7.1 실행 전 확인

- [ ] **API 속도**: 실전투자 4.5 calls/sec (src/api/client.py 확인)
- [ ] **병렬 워커**: 10~15개 (--parallel 15)
- [ ] **캐시 활용**: 재실행 시 --use-cache 사용
- [ ] **불필요한 딜레이 제거**: api_delay_seconds = 0.1

### 7.2 모의투자 환경

- [ ] calls_per_second = 0.33 (자동 설정 확인)
- [ ] 장시간 실행 시 토큰 만료 주의 (24시간)
- [ ] Circuit Breaker 로그 모니터링

### 7.3 대용량 데이터

- [ ] 이벤트 수 1000개 초과 시: 배치 분할 고려
- [ ] 메모리 모니터링 (pandas DataFrame 누적)
- [ ] 디스크 여유 공간 확인 (parquet 캐시)

### 7.4 성능 튜닝 (고급)

```python
# config.py 수정

# API 동시성 증가 (네트워크 빠를 때)
api_concurrency: int = 10  # 기본 5

# 분봉 페이지 제한 (최근 데이터만)
max_minute_pages: int = 100  # 기본 500

# 일봉 조회 수 축소
daily_candle_count: int = 300  # 기본 500
```

---

## 8. 결과 파일

### 8.1 출력 경로

```
C:\K_stock_trading\data\backtest\v7_purple_3min\
```

### 8.2 파일 설명

| 파일 | 내용 | 주요 컬럼 |
|------|------|----------|
| `event_days.csv` | Stage A 이벤트일 목록 | date, stock_code, stock_name, trading_value |
| `event_summary.csv` | 종목별 이벤트 요약 | stock_code, event_count, max_value_billion |
| `trades.csv` | 거래 내역 | entry_dt, exit_dt, net_return_pct, exit_type |
| `summary.csv` | 결과 요약 | total_trades, win_rate, profit_factor |
| `stock_analysis.csv` | 종목별 분석 | stock_code, trades, avg_return |
| `v7_backtest_result.xlsx` | 전체 보고서 (다중 시트) | Summary, Trades, StockAnalysis, Exit, Monthly |

### 8.3 결과 해석

**기본 지표**:
- **승률 (Win Rate)**: 수익 거래 / 전체 거래 (%)
- **평균 수익률**: 전체 거래 평균 (비용 차감 후)
- **Profit Factor**: 총 이익 / 총 손실 (1.5 이상 권장)
- **MDD**: 최대 낙폭 (%)

**청산 유형**:
- `HARD_STOP`: 고정 손절 -4%
- `ATR_TS`: 트레일링 스탑 돌파
- `END_OF_DAY`: 장 종료 청산
- `MAX_HOLD`: 최대 보유일(5일) 도달

---

## 9. 추가 팁

### 9.1 디버깅

```python
# 로그 레벨 변경
logger.setLevel(logging.DEBUG)

# 단일 종목 테스트
"C:\Program Files\Python311\python.exe" -m scripts.backtest.v7_intraday.main --use-cache --stock 005930
```

### 9.2 결과 검증

```python
# 거래 내역 확인
import pandas as pd
trades = pd.read_csv("data/backtest/v7_purple_3min/trades.csv")
trades.groupby("exit_type")["net_return_pct"].describe()
```

### 9.3 관련 문서

| 문서 | 용도 |
|------|------|
| `docs/BACKTEST_GUIDELINES.md` | 네이밍 규칙, 지표 계산 표준 |
| `docs/TECHNICAL_DOCUMENTATION.md` | V7 전략 상세 |
| `CLAUDE.md` | 수정 불가 항목, 불변조건 |

---

## 10. 빠른 참조

### 10.1 핵심 명령어

```powershell
# 처음 실행 (데이터 수집)
"C:\Program Files\Python311\python.exe" -m scripts.backtest.v7_intraday.main --fetch --parallel 15

# 재실행 (캐시 사용)
"C:\Program Files\Python311\python.exe" -m scripts.backtest.v7_intraday.main --use-cache --parallel 15
```

### 10.2 핵심 설정

```python
# API 속도: src/api/client.py
calls_per_second = 4.5  # 실전투자

# 병렬 워커: CLI 옵션
--parallel 15

# 캐시 경로: config.py
cache_dir = Path("C:/K_stock_trading/data/backtest/v7_purple_3min/cache")
```

### 10.3 오류 대응 요약

| 오류 | 해결 |
|------|------|
| 클라이언트 미초기화 | `async with` 사용 |
| ModuleNotFoundError | 프로젝트 루트에서 `-m` 실행 |
| 429 Rate Limit | `calls_per_second` 낮추기 |
| 한글 깨짐 | 입력 `cp949`, 출력 `utf-8-sig` |
