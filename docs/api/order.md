# 주문 API 상세

## 공통 정보

- **URL**: `/api/dostk/ordr`
- **Method**: POST
- **Content-Type**: application/json;charset=UTF-8

---

## kt10000: 주식 매수주문

### Request Body
| Element | 한글명 | Type | Required | 설명 |
|---------|--------|------|----------|------|
| dmst_stex_tp | 국내거래소구분 | String | Y | KRX, NXT, SOR |
| stk_cd | 종목코드 | String | Y | 6자리 (예: 005930) |
| ord_qty | 주문수량 | String | Y | |
| ord_uv | 주문단가 | String | N | 지정가일 때 필수 |
| trde_tp | 매매구분 | String | Y | 아래 참조 |
| cond_uv | 조건단가 | String | N | 스톱지정가용 |

### 매매구분 (trde_tp)
| 코드 | 설명 |
|------|------|
| 0 | 보통 (지정가) |
| 3 | 시장가 |
| 5 | 조건부지정가 |
| 6 | 최유리지정가 |
| 7 | 최우선지정가 |
| 10 | 보통(IOC) |
| 13 | 시장가(IOC) |
| 16 | 최유리(IOC) |
| 20 | 보통(FOK) |
| 23 | 시장가(FOK) |
| 26 | 최유리(FOK) |
| 28 | 스톱지정가 |
| 29 | 중간가 |
| 30 | 중간가(IOC) |
| 31 | 중간가(FOK) |
| 61 | 장시작전시간외 |
| 62 | 시간외단일가 |
| 81 | 장마감후시간외 |

### Response Body
| Element | 한글명 | Type | 설명 |
|---------|--------|------|------|
| ord_no | 주문번호 | String | 7자리 |
| dmst_stex_tp | 국내거래소구분 | String | |
| return_code | 결과코드 | Number | 0=정상 |
| return_msg | 결과메시지 | String | |

### 예제

**Request:**
```json
{
    "dmst_stex_tp": "KRX",
    "stk_cd": "005930",
    "ord_qty": "1",
    "ord_uv": "",
    "trde_tp": "3",
    "cond_uv": ""
}
```

**Response:**
```json
{
    "ord_no": "00024",
    "return_code": 0,
    "return_msg": "정상적으로 처리되었습니다"
}
```

---

## kt10001: 주식 매도주문

kt10000과 동일한 구조

---

## kt10002: 주식 정정주문

### Request Body
| Element | 한글명 | Type | Required | 설명 |
|---------|--------|------|----------|------|
| dmst_stex_tp | 국내거래소구분 | String | Y | KRX, NXT, SOR |
| org_ord_no | 원주문번호 | String | Y | 정정할 주문번호 |
| stk_cd | 종목코드 | String | Y | |
| ord_qty | 주문수량 | String | Y | 정정 수량 |
| ord_uv | 주문단가 | String | N | 정정 단가 |
| trde_tp | 매매구분 | String | Y | |

---

## kt10003: 주식 취소주문

### Request Body
| Element | 한글명 | Type | Required | 설명 |
|---------|--------|------|----------|------|
| dmst_stex_tp | 국내거래소구분 | String | Y | KRX, NXT, SOR |
| org_ord_no | 원주문번호 | String | Y | 취소할 주문번호 |
| stk_cd | 종목코드 | String | Y | |
| ord_qty | 주문수량 | String | Y | 취소 수량 |
