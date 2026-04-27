# 키움 REST API 완벽 분석 (V7.1 매핑)

> 키움증권 REST API 공식 문서 (.xlsx, 208 시트, 207 API) 완벽 분석
>
> V7.1 시스템 구현에 필요한 API만 추려서 정리.
>
> 작성: 2026-04-25 | 분석 대상: 키움_REST_API_문서.xlsx

---

## 📊 전체 개요

```yaml
총 API 개수: 207개
시트 개수: 208개 (오류코드 포함)

분류:
  국내주식: 204개 (98.6%)
  OAuth 인증: 2개
  
중분류 분포:
  계좌: 32개
  종목정보: 31개
  시세: 25개
  순위정보: 23개
  실시간시세 (WebSocket): 19개
  차트: 21개
  ELW: 11개
  ETF: 9개
  주문: 8개 (주식 4 + 신용 4)
  업종: 6개
  기관/외국인: 4개
  대차거래: 4개
  조건검색: 4개
  테마: 2개
  공매도: 1개

핵심 도메인:
  운영: https://api.kiwoom.com
  모의투자: https://mockapi.kiwoom.com (KRX만 지원)
  WebSocket: wss://api.kiwoom.com:10000
  WebSocket 모의: wss://mockapi.kiwoom.com:10000
```

---

## 🎯 V7.1에 필요한 API (필수 18개)

### 1. 인증 (2개)

| API ID | 명칭 | 메서드 | URL | 사용 시점 |
|--------|------|--------|-----|-----------|
| **au10001** | 접근토큰 발급 | POST | /oauth2/token | 시스템 시작, 토큰 갱신 |
| au10002 | 접근토큰 폐기 | POST | /oauth2/revoke | 시스템 종료 |

### 2. 종목 정보 (1개)

| API ID | 명칭 | 메서드 | URL | 사용 시점 |
|--------|------|--------|-----|-----------|
| **ka10001** | 주식기본정보요청 | POST | /api/dostk/stkinfo | 종목 등록 시 검증 |
| ka10099 | 종목정보 리스트 | POST | /api/dostk/stkinfo | 종목 마스터 캐시 |
| ka10100 | 종목정보 조회 | POST | /api/dostk/stkinfo | 종목 검색 |
| ka10086 | 일별주가요청 | POST | /api/dostk/mrkcond | 박스 만료 검토 등 |

### 3. 차트 (2개) ★★★

| API ID | 명칭 | 메서드 | URL | V7.1 사용 |
|--------|------|--------|-----|-----------|
| **ka10080** | 주식분봉차트조회 | POST | /api/dostk/chart | **PATH_A 3분봉** |
| **ka10081** | 주식일봉차트조회 | POST | /api/dostk/chart | **PATH_B 일봉** |

### 4. 주문 (4개) ★★★

| API ID | 명칭 | 메서드 | URL | V7.1 사용 |
|--------|------|--------|-----|-----------|
| **kt10000** | 주식 매수주문 | POST | /api/dostk/ordr | 박스 진입 시 매수 |
| **kt10001** | 주식 매도주문 | POST | /api/dostk/ordr | 손절/익절 |
| **kt10002** | 주식 정정주문 | POST | /api/dostk/ordr | 미체결 수량 정정 |
| **kt10003** | 주식 취소주문 | POST | /api/dostk/ordr | 주문 취소 |

### 5. 계좌 (3개) ★★★

| API ID | 명칭 | 메서드 | URL | V7.1 사용 |
|--------|------|--------|-----|-----------|
| **ka10075** | 미체결요청 | POST | /api/dostk/acnt | 재시작 시 미체결 확인 |
| **ka10076** | 체결요청 | POST | /api/dostk/acnt | 체결 내역 확인 |
| **kt00018** | 계좌평가잔고 | POST | /api/dostk/acnt | 정합성 확인 (Reconciler) |
| ka10085 | 계좌수익률 | POST | /api/dostk/acnt | 일일 마감 통계 |

### 6. WebSocket 실시간 (5개) ★★★

| API ID | 명칭 | URL | V7.1 사용 |
|--------|------|-----|-----------|
| **0B** | 주식체결 (실시간) | wss://api.kiwoom.com:10000/api/dostk/websocket | **시세 모니터링** |
| **0D** | 주식호가잔량 | wss + /api/dostk/websocket | 호가 분석 (선택) |
| **00** | 주문체결 (계좌) | wss + /api/dostk/websocket | 주문 상태 실시간 |
| **04** | 잔고 (계좌) | wss + /api/dostk/websocket | 잔고 실시간 |
| **1h** | VI 발동/해제 | wss + /api/dostk/websocket | **VI 처리** |

### 7. 보조 (참고용)

| API ID | 명칭 | 사용 |
|--------|------|------|
| ka10004 | 주식호가요청 | 주문 시 호가 확인 (선택) |
| ka10054 | VI발동종목요청 | VI 종목 일괄 조회 |

---

## 🔑 핵심 1: 인증 (au10001)

### Request

```yaml
URL: POST https://api.kiwoom.com/oauth2/token
Content-Type: application/json;charset=UTF-8

Headers:
  api-id: au10001 (필수)
  
Body:
  grant_type: "client_credentials" (필수)
  appkey: "<KIWOOM_APP_KEY>" (필수)
  secretkey: "<KIWOOM_SECRET>" (필수)
```

### Response

```json
{
  "expires_dt": "20241107083713",  // YYYYMMDDHHMMSS
  "token_type": "bearer",
  "token": "WQJ..."
}
```

### Python 구현 예시

```python
import httpx

async def get_access_token(app_key: str, secret_key: str) -> dict:
    """V7.1 토큰 발급"""
    url = "https://api.kiwoom.com/oauth2/token"
    headers = {
        "api-id": "au10001",
        "Content-Type": "application/json;charset=UTF-8"
    }
    body = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "secretkey": secret_key
    }
    
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        return resp.json()

# 사용
token_data = await get_access_token(KIWOOM_APP_KEY, KIWOOM_SECRET)
access_token = token_data["token"]
expires_at = datetime.strptime(token_data["expires_dt"], "%Y%m%d%H%M%S")
```

### V7.1 토큰 관리 권장

```yaml
유효기간: 만료일시 (expires_dt) 기반
저장: 메모리 + Redis (선택)
갱신: 만료 5분 전 자동 갱신
실패 시: au10002로 폐기 후 재발급

보안:
  ☑ APP_KEY, SECRET_KEY는 .env에서 관리 (PRD §12)
  ☑ Token 발급한 IP와 사용 IP 동일 필수 (오류 8010)
  ☑ 모의/실전 구분 (오류 8030, 8031)
```

---

## 🔑 핵심 2: 분봉차트 (ka10080) - PATH_A

### Request

```yaml
URL: POST https://api.kiwoom.com/api/dostk/chart
Headers:
  api-id: ka10080
  authorization: Bearer <token>
  cont-yn: N (또는 연속조회 시 Y)
  next-key: <전 응답의 next-key>

Body:
  stk_cd: "005930"          # 종목코드
  tic_scope: "3"            # 1:1분, 3:3분, 5:5분, 10:10분, 15:15분, 30:30분, 45:45분, 60:60분
  upd_stkpc_tp: "1"         # 0 or 1 (수정주가 구분)
```

### Response

```json
{
  "stk_cd": "005930",
  "stk_min_pole_chart_qry": [
    {
      "cur_prc": "73500",       // 종가
      "trde_qty": "10000",       // 거래량
      "cntr_tm": "20260425143000",  // 체결시간 YYYYMMDDHHMMSS
      "open_pric": "73000",      // 시가
      "high_pric": "73600",      // 고가
      "low_pric": "72900",       // 저가
      "pred_pre": "+200",        // 전일대비 (현재가 - 전일종가)
      "pred_pre_sig": "2"        // 1:상한가, 2:상승, 3:보합, 4:하한가, 5:하락
    },
    ...
  ]
}
```

### V7.1 PATH_A 구현 핵심

```python
# 3분봉 조회 (PATH_A 진입 검출용)
async def get_3min_candles(stock_code: str, token: str) -> list[Candle]:
    url = "https://api.kiwoom.com/api/dostk/chart"
    headers = {
        "api-id": "ka10080",
        "authorization": f"Bearer {token}",
        "Content-Type": "application/json;charset=UTF-8"
    }
    body = {
        "stk_cd": stock_code,
        "tic_scope": "3",         # ★ 3분봉
        "upd_stkpc_tp": "1"
    }
    
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, headers=headers, json=body)
        data = resp.json()
        
    candles = []
    for item in data.get("stk_min_pole_chart_qry", []):
        candles.append(Candle(
            timestamp=datetime.strptime(item["cntr_tm"], "%Y%m%d%H%M%S"),
            open_price=int(item["open_pric"]),
            high_price=int(item["high_pric"]),
            low_price=int(item["low_pric"]),
            close_price=int(item["cur_prc"]),
            volume=int(item["trde_qty"])
        ))
    return candles

# PATH_A PULLBACK 진입 조건 검사
def check_path_a_pullback(candles: list[Candle], box: Box) -> bool:
    """직전봉 + 현재봉 양봉 + 박스 내 종가"""
    if len(candles) < 2:
        return False
    
    n_minus_1 = candles[-2]
    n = candles[-1]
    
    # 양봉 조건 (Close > Open)
    if not (n_minus_1.close_price > n_minus_1.open_price):
        return False
    if not (n.close_price > n.open_price):
        return False
    
    # 박스 내 종가
    if not (box.lower_price <= n_minus_1.close_price <= box.upper_price):
        return False
    if not (box.lower_price <= n.close_price <= box.upper_price):
        return False
    
    return True  # 매수 트리거!
```

---

## 🔑 핵심 3: 일봉차트 (ka10081) - PATH_B

### Request

```yaml
URL: POST https://api.kiwoom.com/api/dostk/chart
Headers:
  api-id: ka10081
  authorization: Bearer <token>

Body:
  stk_cd: "005930"
  base_dt: "20260425"       # YYYYMMDD 기준일자
  upd_stkpc_tp: "1"
```

### Response

```json
{
  "stk_cd": "005930",
  "stk_dt_pole_chart_qry": [
    {
      "cur_prc": "73500",      // 종가
      "trde_qty": "12345678",
      "trde_prica": "...",       // 거래대금
      "dt": "20260425",          // 일자 YYYYMMDD
      "open_pric": "73000",
      "high_pric": "74000",
      "low_pric": "72500",
      "pred_pre": "+200",
      "pred_pre_sig": "2",
      "trde_tern_rt": "..."      // 거래회전율
    },
    ...
  ]
}
```

### V7.1 PATH_B 구현 핵심

```python
async def get_daily_candles(stock_code: str, base_date: str, token: str) -> list[Candle]:
    """일봉 조회 (PATH_B 진입 검출용)"""
    url = "https://api.kiwoom.com/api/dostk/chart"
    headers = {
        "api-id": "ka10081",
        "authorization": f"Bearer {token}",
        "Content-Type": "application/json;charset=UTF-8"
    }
    body = {
        "stk_cd": stock_code,
        "base_dt": base_date,    # 예: "20260425"
        "upd_stkpc_tp": "1"
    }
    
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, headers=headers, json=body)
        data = resp.json()
    
    candles = []
    for item in data.get("stk_dt_pole_chart_qry", []):
        candles.append(Candle(
            date=datetime.strptime(item["dt"], "%Y%m%d").date(),
            open_price=int(item["open_pric"]),
            high_price=int(item["high_pric"]),
            low_price=int(item["low_pric"]),
            close_price=int(item["cur_prc"]),
            volume=int(item["trde_qty"])
        ))
    return candles

# PATH_B 진입 조건 (PULLBACK or BREAKOUT)
def check_path_b_entry(today_candle: Candle, box: Box) -> bool:
    """일봉 양봉 + 박스 내 종가 (PULLBACK)
    또는 종가 > 박스 상단 + 양봉 (BREAKOUT)
    """
    is_bullish = today_candle.close_price > today_candle.open_price
    if not is_bullish:
        return False
    
    if box.strategy == "PULLBACK":
        return box.lower_price <= today_candle.close_price <= box.upper_price
    elif box.strategy == "BREAKOUT":
        return today_candle.close_price > box.upper_price
    
    return False
    # 매수: 익일 09:01
```

---

## 🔑 핵심 4: 매수주문 (kt10000)

### Request

```yaml
URL: POST https://api.kiwoom.com/api/dostk/ordr
Headers:
  api-id: kt10000
  authorization: Bearer <token>
  Content-Type: application/json;charset=UTF-8

Body:
  dmst_stex_tp: "KRX"         # KRX/NXT/SOR (필수)
  stk_cd: "005930"            # 종목코드 (필수)
  ord_qty: "10"               # 주문수량 (필수)
  ord_uv: "73500"             # 주문단가 (지정가 시 필수)
  trde_tp: "0"                # 매매구분 (필수, 아래 표 참조)
  cond_uv: ""                 # 조건단가 (선택)
```

### 매매구분 (trde_tp) 상세

| 코드 | 명칭 | V7.1 사용 |
|-----|------|----------|
| **0** | 보통 (지정가) | 기본 매수 (1호가 위) |
| **3** | 시장가 | 폴백, 시장가 매수 |
| 5 | 조건부지정가 | - |
| 81 | 장마감후시간외 | - |
| 61 | 장시작전시간외 | - |
| 62 | 시간외단일가 | VI 발동 시 |
| 6 | 최유리지정가 | 가능 (검토) |
| 7 | 최우선지정가 | 가능 (검토) |
| ... | IOC/FOK 변형들 | - |

### Response

```json
{
  "ord_no": "00024",          // ★ 주문번호
  "dmst_stex_tp": "KRX",
  "return_code": 0,           // 0:정상
  "return_msg": "정상적으로 처리되었습니다"
}
```

### V7.1 매수 구현

```python
async def place_buy_order(
    stock_code: str,
    quantity: int,
    price: int | None = None,  # None이면 시장가
    token: str = ...
) -> dict:
    """V7.1 매수주문"""
    url = "https://api.kiwoom.com/api/dostk/ordr"
    headers = {
        "api-id": "kt10000",
        "authorization": f"Bearer {token}",
        "Content-Type": "application/json;charset=UTF-8"
    }
    
    if price is None:
        # 시장가 (폴백)
        body = {
            "dmst_stex_tp": "KRX",
            "stk_cd": stock_code,
            "ord_qty": str(quantity),
            "trde_tp": "3",          # 시장가
        }
    else:
        # 지정가 (기본)
        body = {
            "dmst_stex_tp": "KRX",
            "stk_cd": stock_code,
            "ord_qty": str(quantity),
            "ord_uv": str(price),
            "trde_tp": "0",          # 보통 (지정가)
        }
    
    async with httpx.AsyncClient(timeout=5) as client:
        resp = await client.post(url, headers=headers, json=body)
        data = resp.json()
    
    if data.get("return_code") != 0:
        raise OrderError(f"매수 실패: {data.get('return_msg')}")
    
    return {
        "order_no": data["ord_no"],
        "submitted_at": datetime.now(),
    }

# V7.1 §3.3 주문 정책: 지정가 1호가 위 → 5초 대기 × 3회 → 시장가
async def execute_buy_with_retry(stock_code: str, quantity: int, base_price: int):
    for attempt in range(3):
        # 1호가 위 지정가
        target_price = base_price + get_tick_size(base_price)  # 호가 단위
        order = await place_buy_order(stock_code, quantity, target_price, token)
        
        # 5초 대기
        await asyncio.sleep(5)
        
        # 미체결 확인
        if not await is_order_filled(order["order_no"]):
            await cancel_order(order["order_no"], stock_code)
            continue
        
        return order
    
    # 3회 실패 → 시장가 폴백
    return await place_buy_order(stock_code, quantity, None, token)
```

### ⚠️ 주의 사항

```yaml
client_order_id 지원 여부:
  키움 API에 client_order_id 필드 없음
  → V7.1 §1.3 "주문 태깅" 항목에서 우려한 부분 확인됨!
  → 박스/포지션 ID 매핑은 자체 DB로 추적 필요
  → ord_no (키움 주문번호)와 V7.1 position_id 매핑 테이블 필요
  
대응 방안:
  - 매수/매도 직후 응답의 ord_no를 즉시 DB에 저장
  - position 또는 box와 매핑 (1:1)
  - WebSocket "00 주문체결"로 추적 시 ord_no로 매칭

응답 구조:
  Response Example에 "return_code: 0, return_msg" 명시됨
  → 응답에서 정상 여부 검증 필수
```

---

## 🔑 핵심 5: 매도/정정/취소 주문

### kt10001 매도주문

매수와 동일 구조 (URL, Body 형식 모두 같음). 차이점은 매도라는 것뿐.

```python
# 매도는 매수와 같은 형식
async def place_sell_order(stock_code: str, quantity: int, price: int | None, token: str):
    url = "https://api.kiwoom.com/api/dostk/ordr"
    headers = {
        "api-id": "kt10001",   # ← 매도는 kt10001
        "authorization": f"Bearer {token}",
        ...
    }
    body = {  # 매수와 동일
        "dmst_stex_tp": "KRX",
        "stk_cd": stock_code,
        "ord_qty": str(quantity),
        "ord_uv": str(price) if price else "",
        "trde_tp": "0" if price else "3",
    }
    ...
```

### kt10002 정정주문

```yaml
Body:
  dmst_stex_tp: "KRX"
  orig_ord_no: "0000139"     # 원주문번호 (필수)
  stk_cd: "005930"
  mdfy_qty: "5"              # 정정수량
  mdfy_uv: "73600"           # 정정단가
  mdfy_cond_uv: ""           # 조건단가 (선택)

Response:
  ord_no: "0000140"          # 새 주문번호
  base_orig_ord_no: "0000139" # 모주문번호
  mdfy_qty: "5"
```

### kt10003 취소주문

```yaml
Body:
  dmst_stex_tp: "KRX"
  orig_ord_no: "0000140"     # 원주문번호 (필수)
  stk_cd: "005930"
  cncl_qty: "0"              # ★ '0' 입력 시 잔량 전부 취소

Response:
  ord_no: "0000141"
  base_orig_ord_no: "0000139"
  cncl_qty: "0"
```

```python
# V7.1 §13 재시작 복구 Step 2: 미완료 주문 모두 취소
async def cancel_all_pending_orders(token: str):
    pending = await get_pending_orders(token)
    for order in pending:
        await cancel_order(
            orig_ord_no=order["ord_no"],
            stock_code=order["stk_cd"],
            cancel_qty="0",  # 잔량 전부 취소
            token=token
        )
```

---

## 🔑 핵심 6: 미체결 조회 (ka10075)

### Request/Response

```yaml
Request Body:
  all_stk_tp: "0"          # 0:전체, 1:종목
  trde_tp: "0"             # 0:전체, 1:매도, 2:매수
  stk_cd: ""               # 선택 (all_stk_tp=1 시 필요)
  stex_tp: "0"             # 0:통합, 1:KRX, 2:NXT

Response Body:
  oso: [                    # 미체결 LIST
    {
      "acnt_no": "1234567890",
      "ord_no": "...",
      "stk_cd": "005930",
      "stk_nm": "삼성전자",
      "ord_stt": "접수",     # 주문상태
      "ord_qty": "10",
      "ord_pric": "73500",
      "oso_qty": "5",        # 미체결수량
      "cntr_tot_amt": "...", # 체결누계금액
      "cntr_pric": "...",    # 체결가
      "cntr_qty": "...",     # 체결량
      "cur_prc": "73600",
      "io_tp_nm": "...",     # 주문구분
      "trde_tp": "...",      # 매매구분
      "tm": "...",           # 시간
      "stex_tp": "1",        # 0:통합, 1:KRX, 2:NXT
      "stex_tp_txt": "KRX"
    }
  ]
```

### V7.1 활용

```python
# 재시작 시 (PRD §13 Step 2)
async def get_all_pending_orders(token: str) -> list[dict]:
    url = "https://api.kiwoom.com/api/dostk/acnt"
    headers = {
        "api-id": "ka10075",
        "authorization": f"Bearer {token}",
    }
    body = {
        "all_stk_tp": "0",  # 전체 종목
        "trde_tp": "0",     # 전체 (매도+매수)
        "stex_tp": "0"       # 통합
    }
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=headers, json=body)
        data = resp.json()
    
    return data.get("oso", [])
```

---

## 🔑 핵심 7: 계좌평가잔고 (kt00018)

V7.1 정합성 엔진(Reconciler)의 핵심 API. 백엔드와 키움 잔고 비교.

### Request/Response

```yaml
Request Body:
  qry_tp: "1"             # 1:합산, 2:개별
  dmst_stex_tp: "KRX"     # 거래소 구분

Response Body:
  tot_pur_amt: "..."           # 총매입금액
  tot_evlt_amt: "..."          # 총평가금액
  tot_evlt_pl: "..."           # 총평가손익금액
  tot_prft_rt: "..."           # 총수익률(%)
  prsm_dpst_aset_amt: "..."    # 추정예탁자산
  
  acnt_evlt_remn_indv_tot: [   # 종목별 평가잔고
    {
      "stk_cd": "005930",
      "stk_nm": "삼성전자",
      "evltv_prft": "...",      # 평가손익
      "prft_rt": "...",         # 수익률(%)
      "pur_pric": "73000",      # 매입가 (= 평단가)
      "pred_close_pric": "...",  # 전일종가
      "rmnd_qty": "100",        # 보유수량 ★
      "trde_able_qty": "100",   # 매매가능수량
      "cur_prc": "73500",       # 현재가 ★
      "pred_buyq": "...",       # 전일매수수량
      "pred_sellq": "...",
      "tdy_buyq": "10",         # 금일매수수량
      "tdy_sellq": "0",         # 금일매도수량
      "pur_amt": "...",         # 매입금액
      "evlt_amt": "...",        # 평가금액
      "poss_rt": "..."          # 보유비중(%)
    }
  ]
```

### V7.1 Reconciler 활용 ★

```python
# PRD §13 Step 3: 포지션 정합성 (Reconciler)
async def reconcile_positions(token: str, db_positions: list) -> ReconciliationResult:
    """V7.1 백엔드 DB와 키움 잔고 비교"""
    url = "https://api.kiwoom.com/api/dostk/acnt"
    headers = {
        "api-id": "kt00018",
        "authorization": f"Bearer {token}"
    }
    body = {
        "qry_tp": "1",          # 합산
        "dmst_stex_tp": "KRX"
    }
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=headers, json=body)
        data = resp.json()
    
    kiwoom_holdings = {
        item["stk_cd"]: {
            "qty": int(item["rmnd_qty"]),
            "avg_price": int(item["pur_pric"]),
            "current_price": int(item["cur_prc"]),
        }
        for item in data.get("acnt_evlt_remn_indv_tot", [])
    }
    
    # Case A~E 처리 (PRD §13 정의)
    return process_reconciliation_cases(db_positions, kiwoom_holdings)
```

### 💡 알려진 한계 1 (current_price) 해결책 ★

박균호님이 지적하신 `PositionOut.current_price` 부재 문제는 **kt00018로 해결**됩니다.

```yaml
응답에 cur_prc 필드 존재 → 현재가 직접 제공!

대안 1: kt00018 주기 호출
  - 5초마다 또는 박스 진입 임박 시
  - 모든 보유 포지션의 cur_prc 일괄 조회
  - 단점: API 호출 빈도 (rate limit)

대안 2 (★ 권장): WebSocket 0B 실시간 시세
  - 보유 종목에 대해 0B 등록
  - 실시간으로 가격 받아 cur_prc 갱신
  - WebSocket POSITION_PRICE_UPDATE 이벤트 발신
  - 장점: 실시간 + rate limit 무관
  - 단점: WebSocket 끊김 시 5초 폴백 (kt00018)

권장 구현:
  Phase 5 후반:
    1. PositionOut.current_price 필드 추가
    2. 백엔드: WebSocket 0B 구독 (보유 종목)
    3. 백엔드: 키움 0B 수신 → DB 캐시 갱신
    4. UI: REST 응답으로 초기 값 + WebSocket 실시간 갱신
```

---

## 🔑 핵심 8: WebSocket 실시간 0B (주식체결) ★

V7.1 NFR1 (시세 지연 < 1초)의 핵심.

### 연결

```yaml
URL: wss://api.kiwoom.com:10000/api/dostk/websocket
운영: wss://api.kiwoom.com:10000
모의: wss://mockapi.kiwoom.com:10000

Headers (HTTP Upgrade):
  authorization: Bearer <token>
```

### 구독 메시지

```json
// 등록 (REG)
{
  "trnm": "REG",
  "grp_no": "1",
  "refresh": "1",  // 1: 기존 유지, 0: 기존 해지
  "data": [
    {
      "item": "005930",   // 종목코드
      "type": "0B"        // 0B: 주식체결 (실시간 시세)
    }
  ]
}

// 해지 (REMOVE)
{
  "trnm": "REMOVE",
  "grp_no": "1",
  "data": [
    {"item": "005930", "type": "0B"}
  ]
}
```

### 실시간 데이터 (서버 → 클라이언트)

```json
{
  "trnm": "REAL",
  "data": [
    {
      "type": "0B",
      "name": "주식체결",
      "item": "005930",
      "values": {
        "20": "143000",      // 체결시간 HHMMSS
        "10": "73500",       // 현재가 ★
        "11": "+200",        // 전일대비
        "12": "+0.27",       // 등락율
        "27": "73600",       // 매도호가 1
        "28": "73500",       // 매수호가 1
        "15": "+10",         // 거래량 (+:매수, -:매도)
        "13": "12345678",    // 누적거래량
        "14": "...",         // 누적거래대금
        "16": "73000",       // 시가
        "17": "74000",       // 고가
        "18": "72500",       // 저가
        "25": "2",           // 전일대비기호 (1상한가, 2상승, 3보합, 4하한가, 5하락)
        "228": "120.5",      // 체결강도
        "311": "440조",      // 시가총액
        "290": "2",          // 장구분 (1:장전, 2:장중, 3:장후)
        "1314": "...",       // 순매수체결량
        "9081": "1"          // 거래소구분 (0:통합, 1:KRX, 2:NXT)
      }
    }
  ]
}
```

### 주요 필드 매핑 (V7.1용)

| 필드 | 의미 | V7.1 사용 |
|-----|------|-----------|
| **10** | 현재가 | ★ position.current_price 갱신 |
| 11 | 전일대비 | UI 표시 |
| 12 | 등락율 | UI 표시 |
| 13 | 누적거래량 | 통계 |
| 16 | 시가 | 봉 빌더 |
| 17 | 고가 | 봉 빌더 (분봉 합성) |
| 18 | 저가 | 봉 빌더 |
| 20 | 체결시간 (HHMMSS) | 타임스탬프 |
| 27 | 매도호가1 | 매수 시 1호가 위 가격 산출 |
| 28 | 매수호가1 | 매도 시 가격 산출 |
| **290** | 장구분 | 1:장전시간외, 2:장중, 3:장후시간외 |

### V7.1 구현 예시

```python
import websockets
import json

async def kiwoom_websocket_client(token: str, tracked_stocks: list[str]):
    """V7.1 실시간 시세 클라이언트"""
    url = "wss://api.kiwoom.com:10000/api/dostk/websocket"
    headers = {"authorization": f"Bearer {token}"}
    
    async with websockets.connect(url, extra_headers=headers) as ws:
        # 추적 종목 구독
        register_msg = {
            "trnm": "REG",
            "grp_no": "1",
            "refresh": "1",
            "data": [
                {"item": stock_code, "type": "0B"}
                for stock_code in tracked_stocks
            ]
        }
        await ws.send(json.dumps(register_msg))
        
        # 메시지 수신 루프
        async for message in ws:
            data = json.loads(message)
            
            if data.get("trnm") == "REAL":
                for item in data.get("data", []):
                    if item["type"] == "0B":
                        await handle_price_update(item)

async def handle_price_update(item: dict):
    """V7.1 시세 처리"""
    stock_code = item["item"]
    values = item["values"]
    
    current_price = int(values.get("10", "0"))
    timestamp = values.get("20", "")  # HHMMSS
    
    # 1. position.current_price 갱신 (메모리 캐시)
    update_position_price(stock_code, current_price)
    
    # 2. 박스 진입 임박 검사 (±5%)
    check_box_proximity(stock_code, current_price)
    
    # 3. WebSocket으로 UI에 push (POSITION_PRICE_UPDATE)
    await broadcast_to_clients({
        "type": "POSITION_PRICE_UPDATE",
        "stock_code": stock_code,
        "current_price": current_price,
        "timestamp": timestamp
    })
```

### ⚠️ 주의사항

```yaml
PRD §1.1 헌법 원칙 2 (NFR1):
  시세 모니터링 지연 < 1초
  → WebSocket 사용 필수 (REST 폴링 X)
  → 끊김 시 즉시 재연결 (PRD §8 WebSocket 끊김 처리)

봉 합성:
  키움이 ka10080 (분봉) 제공하지만
  실시간 봉 완성 감지는 0B로 직접 합성 권장
  → 매 1분/3분마다 정확한 봉 완성 시각 필요
  → 또는 5초마다 ka10080 폴링 (단순함, NFR1 만족)
```

---

## 🔑 핵심 9: WebSocket 00 (주문체결) ★

계좌 토큰 발급 후 자동으로 주문체결 이벤트 수신. 종목별 등록 불필요.

### 구독

```json
{
  "trnm": "REG",
  "grp_no": "2",
  "refresh": "1",
  "data": [
    {"item": "", "type": "00"}    // item 빈 문자열 OK
  ]
}
```

### 실시간 데이터 (주요 필드)

| 필드 | 의미 | 값 예시 |
|-----|------|---------|
| 9201 | 계좌번호 | 1234567890 |
| **9203** | 주문번호 | 0000139 |
| 9001 | 종목코드 | 005930 |
| 912 | 주문업무분류 | (지정가/시장가 등) |
| **913** | 주문상태 | 접수, 체결, 확인, 취소, 거부 ★ |
| 302 | 종목명 | 삼성전자 |
| **900** | 주문수량 | 10 |
| 901 | 주문가격 | 73500 |
| **902** | 미체결수량 | 5 |
| **903** | 체결누계금액 | 367500 |
| 904 | 원주문번호 | (정정/취소 시) |
| 905 | 주문구분 | 매도/매수/매도정정/매수정정/매수취소/매도취소 |
| 906 | 매매구분 | 보통/시장가/조건부지정가 등 |
| **907** | 매도수구분 | 1:매도, 2:매수 ★ |
| 908 | 주문/체결시간 | HHMMSS |
| 909 | 체결번호 | - |
| **910** | 체결가 | 73600 |
| **911** | 체결량 | 5 |
| 919 | 거부사유 | - |

### V7.1 활용

```python
async def handle_order_event(values: dict):
    """V7.1 주문/체결 처리"""
    order_no = values.get("9203")
    state = values.get("913")  # 접수/체결/확인/취소/거부
    
    # ord_no 기반으로 V7.1 position/order 매핑 조회
    position_id = lookup_position_by_order_no(order_no)
    if not position_id:
        # MANUAL 거래 (V7.1이 발주 안 한 주문) → §7 시나리오
        await handle_manual_order(values)
        return
    
    if state == "체결":
        contracted_qty = int(values.get("911", "0"))
        contracted_price = int(values.get("910", "0"))
        unfilled_qty = int(values.get("902", "0"))
        
        # 평단가 재계산 (PRD §6)
        await update_position_avg_price(
            position_id, 
            new_qty=contracted_qty,
            new_price=contracted_price
        )
        
        if unfilled_qty == 0:
            # 완전 체결
            await mark_order_completed(order_no)
        
    elif state == "취소":
        await mark_order_cancelled(order_no)
    
    elif state == "거부":
        reason = values.get("919")
        await handle_order_rejection(order_no, reason)
```

---

## 🔑 핵심 10: WebSocket 04 (잔고) + 1h (VI)

### 04 잔고 (계좌)

체결 발생 시 자동 갱신.

```yaml
주요 필드:
  9201: 계좌번호
  9001: 종목코드
  302: 종목명
  10: 현재가
  930: 보유수량 ★
  931: 매입단가 ★ (평단가)
  932: 총매입가 (당일누적)
  933: 주문가능수량
  945: 당일순매수량
  990: 당일실현손익(유가)
  991: 당일실현손익율(유가)
```

### 1h VI 발동/해제 (V7.1 §10 핵심)

```yaml
주요 필드:
  9001: 종목코드
  302: 종목명
  9068: VI발동구분    ← ★ 발동 or 해제 식별
  1221: VI발동가격
  1223: 매매체결처리시각
  1224: VI해제시각    ← ★ 해제 시각
  1225: VI적용구분 (정적/동적/동적+정적)
  1236: 기준가격 정적
  1237: 기준가격 동적
  1238: 괴리율 정적
  1239: 괴리율 동적
  1489: VI발동가 등락율
  1490: VI발동횟수
  9069: 발동방향구분
```

### V7.1 VI 처리 구현

```python
async def handle_vi_event(values: dict):
    """V7.1 §10 VI 처리"""
    stock_code = values.get("9001")
    vi_type = values.get("9068")  # 발동구분
    vi_release_time = values.get("1224")  # 해제시각
    
    if not vi_release_time:
        # VI 발동
        await trigger_vi_state(stock_code, values)
    else:
        # VI 해제
        await release_vi_state(stock_code, vi_release_time)
        # 즉시 재평가 (PRD: VI 해제 < 1초 내)
        await reevaluate_positions(stock_code)
```

---

## 🔑 핵심 11: 오류코드 (전체 31개)

### 카테고리별

```yaml
1. API 자체 오류 (1500번대):
  1501: API ID Null
  1504: URI에서 미지원 API ID
  1505: API ID 존재하지 않음
  1511: 필수 파라미터 누락
  1512: Http Header 설정 안 됨
  1513: authorization 필드 필요
  1514: authorization 형식 오류
  1515: Grant Type 형식 오류
  1516: Token 미정의
  1517: 입력값 형식 오류
  1687: 재귀 호출 (호출 제한)
  1700: 요청 개수 초과 (Rate Limit) ★
  1901: 시장 코드 없음
  1902: 종목 정보 없음 ★
  1999: 예기치 못한 에러

2. 인증/Token 오류 (8000번대):
  8001~8002: App Key/Secret Key 검증 실패
  8003: Access Token 조회 실패
  8005: Token 유효하지 않음 ★
  8006~8009: Token 발급 실패
  8010: 발급 IP ≠ 사용 IP ★
  8011~8012: grant_type 오류
  8015~8016: Token 폐기 실패
  8020: appkey/secretkey 입력 안 됨
  8030: 투자구분 (실전/모의) Appkey 불일치 ★
  8031: 투자구분 (실전/모의) Token 불일치 ★
  8040: 단말기 인증 실패
  8050: 지정단말기 인증 실패
  8103: 토큰/단말기 인증 실패
```

### V7.1 에러 처리 매핑

| 키움 오류 | V7.1 PRD 대응 |
|-----------|---------------|
| 1700 (Rate Limit) | 지수 백오프 + 알림 (HIGH) |
| 1902 (종목 없음) | 종목 등록 시 검증 실패 |
| 8005 (Token 유효 X) | 자동 재발급 + 재시도 |
| 8010 (IP 불일치) | CRITICAL 알림 + 안전 모드 |
| 8030/8031 (실전/모의 불일치) | 시작 시 검증 + 차단 |

---

## 🚧 V7.1 구현에 영향을 미치는 발견 사항

### 1. ⚠️ client_order_id 필드 없음 (확인됨!)

```yaml
PRD §1.3 우려:
  "키움 API의 client_order_id 지원 여부 확인"

분석 결과:
  ❌ kt10000/kt10001 매수/매도주문 API에 client_order_id 필드 없음
  ✓ 응답에 ord_no (키움 자체 주문번호)만 제공됨

영향:
  V7.1 박스/포지션과 키움 주문 매핑은 자체 DB로 관리 필수
  주문 직후 ord_no를 즉시 DB에 저장
  WebSocket "00 주문체결" 이벤트의 ord_no로 매칭

권장 구현:
  orders 테이블 추가:
    - id (UUID, V7.1)
    - kiwoom_order_no (string)  ← 매핑 키
    - position_id (UUID FK)
    - box_id (UUID FK)
    - state (PENDING, FILLED, CANCELLED, REJECTED)
    - submitted_at
    - filled_at
```

### 2. NXT/SOR 거래소 지원

```yaml
대다수 API에 거래소 구분:
  KRX:039490        # 한국거래소
  NXT:039490_NX     # 넥스트트레이드
  SOR:039490_AL     # SOR (Smart Order Routing)

주문 시 (kt10000):
  dmst_stex_tp 필드: KRX/NXT/SOR

V7.1 결정:
  현재: KRX 만 사용 (PRD 명시)
  추후: NXT 검토 (별도 결정)
  
모의투자: KRX만 지원
```

### 3. Rate Limit 정확한 값 미공개

```yaml
오류 코드 1700: "허용된 요청 개수를 초과하였습니다"
  → 정확한 값은 키움 API 문서에 미명시
  
PRD 가정 (system/status에서 표시):
  rate_limit_max: 4.5/sec (PRD 09_API_SPEC.md 참고)
  
권장:
  - 자체 토큰 버킷 구현 (4req/sec 보수적)
  - 1700 에러 발생 시 즉시 백오프
  - 실제 운영 후 측정값 갱신
```

### 4. 모의투자 환경

```yaml
도메인 차이:
  운영: api.kiwoom.com
  모의: mockapi.kiwoom.com (KRX만 지원)
  WebSocket 운영: wss://api.kiwoom.com:10000
  WebSocket 모의: wss://mockapi.kiwoom.com:10000

V7.1 .env 활용:
  KIWOOM_API_BASE_URL=https://api.kiwoom.com  # 또는 mockapi
  KIWOOM_WS_URL=wss://api.kiwoom.com:10000
  KIWOOM_ENV=PRODUCTION  # 또는 SANDBOX
```

### 5. cont-yn / next-key 페이징

```yaml
모든 조회 API의 공통 패턴:
  Header에 cont-yn, next-key 사용
  
  첫 요청:
    cont-yn: N
    next-key: (없음)
  
  연속 조회:
    cont-yn: Y (응답 헤더값)
    next-key: <응답의 next-key>

V7.1 구현:
  자동 페이징 헬퍼 함수 작성
  (예: get_all_pending_orders 시 모든 페이지 자동 수집)
```

---

## 📋 V7.1 구현 체크리스트

### Phase 4 (현재) - 알림 시스템

```yaml
☐ 키움 API 클라이언트 기본 구조 (선택, Phase 4와 무관할 수도)
```

### Phase 5 (UI) - WebSocket 클라이언트 일부

```yaml
☐ 프론트엔드 WebSocket 연결 (백엔드 → 프론트, 키움 직접 X)
☐ 백엔드가 키움에서 받은 0B 데이터를 프론트에 push
```

### Phase 후속 (백엔드 거래) - 키움 통합

```yaml
필수 구현 API (18개):

인증 (2개):
☐ au10001 토큰 발급 + 자동 갱신
☐ au10002 토큰 폐기

종목 정보 (1개):
☐ ka10001 주식기본정보 (종목 등록 검증)

차트 (2개) ★:
☐ ka10080 분봉차트 (PATH_A 3분봉)
☐ ka10081 일봉차트 (PATH_B)

주문 (4개) ★:
☐ kt10000 매수
☐ kt10001 매도
☐ kt10002 정정
☐ kt10003 취소
☐ ord_no ↔ position_id 매핑 테이블

계좌 (3개) ★:
☐ ka10075 미체결 (재시작 복구)
☐ ka10076 체결내역
☐ kt00018 계좌평가잔고 (Reconciler)

WebSocket (5개) ★:
☐ 0B 주식체결 (실시간 시세)
☐ 00 주문체결
☐ 04 잔고
☐ 1h VI 발동/해제
☐ 0D 주식호가잔량 (선택)

공통 인프라:
☐ httpx 비동기 HTTP 클라이언트
☐ websockets 라이브러리
☐ Token 자동 갱신 (만료 5분 전)
☐ Rate Limit 토큰 버킷
☐ 오류 코드 매핑 (31개)
☐ cont-yn 자동 페이징
☐ Circuit Breaker (오류 다발 시)
☐ Retry with Exponential Backoff
```

---

## 📁 PRD 영향 요약

### 09_API_SPEC.md 갱신 필요 사항

```yaml
1. PositionOut에 current_price 추가 (한계 1):
   → kt00018의 cur_prc 필드 활용
   → 또는 WebSocket 0B 실시간

2. orders 리소스 추가 (신규):
   → kiwoom_order_no ↔ position_id 매핑
   → 주문 상태 추적

3. WebSocket 채널 보강:
   → POSITION_PRICE_UPDATE: 키움 0B 매핑
   → ORDER_STATUS_UPDATE: 키움 00 매핑
   → BALANCE_UPDATE: 키움 04 매핑
   → VI_EVENT: 키움 1h 매핑
```

### 03_DATA_MODEL.md 갱신 필요 사항

```yaml
신규 테이블:
  orders:
    - id UUID PK
    - kiwoom_order_no VARCHAR(20)  -- 키움 ord_no
    - position_id UUID FK
    - box_id UUID FK NULL
    - direction ENUM ('BUY', 'SELL')
    - quantity INTEGER
    - price NUMERIC NULL  -- NULL이면 시장가
    - state ENUM ('SUBMITTED', 'PARTIAL', 'FILLED', 'CANCELLED', 'REJECTED')
    - submitted_at TIMESTAMPTZ
    - filled_at TIMESTAMPTZ NULL
    - cancelled_at TIMESTAMPTZ NULL
    - reject_reason TEXT NULL
    - filled_quantity INTEGER DEFAULT 0
    - filled_avg_price NUMERIC NULL

인덱스:
  idx_orders_kiwoom_no (kiwoom_order_no)  ★ 매핑 핵심
  idx_orders_position (position_id)
  idx_orders_state (state) WHERE state IN ('SUBMITTED', 'PARTIAL')
```

### 12_SECURITY.md 보강

```yaml
키움 API 보안:
  ☑ APP_KEY/SECRET_KEY는 .env 관리
  ☑ Token 발급 IP 고정 (오류 8010 방지)
  ☑ 실전/모의 환경 명시 분리 (오류 8030/8031 방지)
  ☑ Token 만료 자동 갱신 (만료 5분 전)
  ☑ Token 메모리 보관, DB 저장 금지 (보안)
```

---

## 🎯 결론 및 다음 단계

### V7.1 키움 통합 핵심 (요약)

```yaml
필수 18개 API:
  ✓ 인증 2개
  ✓ 종목 정보 1개
  ✓ 차트 2개 (PATH_A 3분봉, PATH_B 일봉)
  ✓ 주문 4개 (매수/매도/정정/취소)
  ✓ 계좌 3개 (미체결, 체결, 잔고)
  ✓ WebSocket 5개 (시세 + 주문 + 잔고 + VI + 호가)
  ✓ 보조 1개 (호가)

발견된 PRD 보강 사항:
  1. PositionOut.current_price → kt00018 또는 WebSocket 0B
  2. orders 테이블 신규 (kiwoom_order_no 매핑)
  3. NXT/SOR 거래소 분기 (현재 KRX만)
  4. Rate Limit 토큰 버킷 (4req/sec 보수적)

알려진 한계 1 해결:
  ✓ current_price는 kt00018 cur_prc 또는 WebSocket 0B (10번 필드)로 즉시 가능
  ✓ 별도 시세 채널 구축 불필요 (키움이 제공)
```

### 박균호님 결정 필요 사항

```yaml
1. orders 테이블 추가 (PRD Patch #5 후보):
   → ord_no ↔ position_id 매핑 필수
   → 데이터 모델 갱신 필요

2. WebSocket 0B vs kt00018 폴링 결정:
   ⭐ 권장: WebSocket 0B (NFR1 만족)
   ◯ 대안: kt00018 5초 폴링 (단순함)

3. 거래소 KRX 외 지원:
   현재 PRD: KRX 만
   유지 vs NXT 추가?

4. Rate Limit 정책:
   토큰 버킷 4req/sec (보수적)?
   1700 에러 시 백오프 정책?
```

---

*키움 REST API 완벽 분석 완료 (2026-04-25)*
*분석 대상: 키움_REST_API_문서.xlsx (208 시트, 207 API)*
*V7.1 핵심 18개 API 매핑 + 구현 예시 + PRD 보강 사항 도출*
