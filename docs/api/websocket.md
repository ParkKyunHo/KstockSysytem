# WebSocket API 메시지 형식

> 출처: `키움 REST API 문서.xlsx` (ka10171~ka10174)

## 연결 정보

| 환경 | URL |
|------|-----|
| 운영 | `wss://api.kiwoom.com:10000/api/dostk/websocket` |
| 모의투자 | `wss://mockapi.kiwoom.com:10000/api/dostk/websocket` |

### 인증
- HTTP Header에 `authorization: Bearer {token}` 포함
- 또는 LOGIN 메시지로 토큰 전송 (현재 구현 방식)

---

## 조건식 목록 조회 (CNSRLST)

**API ID**: ka10171

### Request
```json
{"trnm": "CNSRLST"}
```

### Response
```json
{
    "trnm": "CNSRLST",
    "return_code": 0,
    "return_msg": "",
    "data": [
        ["0", "조건식이름1"],
        ["1", "조건식이름2"],
        ...
    ]
}
```

**주의**: `data`는 `[["seq", "name"], ...]` 형식 (리스트의 리스트)

---

## 실시간 조건검색 시작 (CNSRREQ)

**API ID**: ka10173

### Request
```json
{
    "trnm": "CNSRREQ",
    "seq": "0",
    "search_type": "1",
    "stex_tp": "K"
}
```

| 필드 | 설명 | 값 |
|------|------|-----|
| seq | 조건식 번호 | "0", "1", ... |
| search_type | 검색 타입 | "0"=1회, "1"=실시간 |
| stex_tp | 시장 구분 | "K"=KRX |

### Response (초기 종목 리스트)
```json
{
    "trnm": "CNSRREQ",
    "seq": "0",
    "return_code": 0,
    "data": [
        {"jmcode": "005930"},
        {"jmcode": "000660"},
        ...
    ]
}
```

---

## 실시간 신호 수신 (REAL)

조건검색 시작 후 종목 편입/이탈 시 수신

### Response
```json
{
    "data": [{
        "trnm": "REAL",
        "type": "0A",
        "values": {
            "9001": "A005930",
            "302": "삼성전자",
            "843": "I",
            "20": "093015"
        }
    }]
}
```

### 필드 설명

| 필드코드 | 설명 | 예시 |
|---------|------|------|
| 9001 | 종목코드 | "A005930" (A 접두사 제거 필요) |
| 302 | 종목명 | "삼성전자" |
| 843 | **신호방향** | "I"=매수(편입), "D"=매도(이탈) |
| 20 | 체결시간 | "093015" (HHMMSS) |
| seq | 조건식 번호 | "0" |

---

## 실시간 조건검색 해제 (CNSRCLR)

**API ID**: ka10174

### Request
```json
{
    "trnm": "CNSRCLR",
    "seq": "0"
}
```

### Response
```json
{
    "trnm": "CNSRCLR",
    "seq": "0",
    "return_code": 0,
    "return_msg": ""
}
```

---

## 실시간 시세 등록/해제

### 등록 (REGSUB)
```json
{
    "trnm": "REGSUB",
    "data_type": "S3_",
    "stk_cd_list": ["A005930", "A000660"]
}
```

### 해제 (UNREGSUB)
```json
{
    "trnm": "UNREGSUB",
    "data_type": "S3_",
    "stk_cd_list": ["A005930"]
}
```

| data_type | 설명 |
|-----------|------|
| S3_ | 주식 체결가 (틱) |
| S4_ | 주식 호가 |

---

## 주의사항

1. **동시 조건식 제한**: 최대 4개까지 동시 모니터링 가능
2. **종목코드 형식**: API 응답의 종목코드는 "A" 접두사 포함 → 제거 필요
3. **신호방향**: 문서에 따라 "I"=매수(편입), "D"=매도(이탈)
