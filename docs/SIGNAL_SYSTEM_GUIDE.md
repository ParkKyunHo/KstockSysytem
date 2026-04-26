# K_stock_trading 신호체계 (V6.2-A)

## 1. SNIPER_TRAP 진입 조건 (3분봉)

```python
# 지표 계산
EMA3 = close.ewm(span=3, adjust=False).mean()
EMA20 = close.ewm(span=20, adjust=False).mean()
EMA60 = close.ewm(span=60, adjust=False).mean()
EMA200 = close.ewm(span=200, adjust=False).mean()

# 진입 조건 (모두 AND)
TrendFilter = (close > EMA200) and (EMA60 > EMA60[5])  # 대세 상승
Zone = (low <= EMA20) and (close >= EMA60)             # 헌팅존
CrossUp = (prev_close < prev_EMA3) and (close >= EMA3) # 3선 돌파
Meaningful = CrossUp and (close > open) and (volume >= prev_volume)
BodySize = (close - open) / open * 100 >= 0.3          # 0.3% 이상
TimeFilter = current_time >= "09:30"

Entry = TrendFilter and Zone and Meaningful and BodySize and TimeFilter
```

## 2. 5필터 스크리닝 (V6.2-B)

| 필터 | 조건 |
|------|------|
| 시가총액 | 1천억 ~ 20조 |
| 등락률 | 2% ~ 29.9% |
| 거래대금 | 200억 이상 |
| 20일고점 | 90% 이상 |
| 갭 | 15% 미만 |
2
## 3. Pool 구조

```
조건검색 신호 → Watchlist(50) → Candidate(20) → Active(10)
                  ↓               ↓              ↓
              6필터 통과      거래대금순      신호 탐지
```

## 4. 청산 조건 (우선순위)

```python
# 1순위: 고정 손절 (-4%)
if bar_low <= entry_price * 0.96:
    exit("Safety Net")

# 2순위: ATR 트레일링 스탑
ATR = atr(high, low, close, period=10)
trailing_stop = highest_close - (ATR * 6.0)  # Structure Warning시 4.5
if close <= trailing_stop:
    exit("ATR TS")

# 3순위: 최대 보유일
if holding_days > 60:
    exit("Max Days")
```

## 5. WebSocket 흐름

```
WebSocket(CNSRLST) → Watchlist → 6필터 → Active → SNIPER_TRAP → 매수
```
