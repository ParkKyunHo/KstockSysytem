# 키움 REST API 문서 정리

## API 분류

### OAuth 인증
| API ID | API명 | URL | 설명 |
|--------|-------|-----|------|
| au10001 | 접근토큰 발급 | /oauth2/token | Bearer 토큰 발급 |
| au10002 | 접근토큰폐기 | /oauth2/revoke | 토큰 폐기 |

### 주문 (중요!)
| API ID | API명 | URL | 설명 |
|--------|-------|-----|------|
| kt10000 | 주식 매수주문 | /api/dostk/ordr | 매수 |
| kt10001 | 주식 매도주문 | /api/dostk/ordr | 매도 |
| kt10002 | 주식 정정주문 | /api/dostk/ordr | 정정 |
| kt10003 | 주식 취소주문 | /api/dostk/ordr | 취소 |

### 계좌
| API ID | API명 | URL | 설명 |
|--------|-------|-----|------|
| kt00001 | 예수금상세현황요청 | /api/dostk/acnt | 예수금 조회 |
| kt00003 | 추정자산조회요청 | /api/dostk/acnt | 자산 조회 |
| kt00004 | 계좌평가현황요청 | /api/dostk/acnt | 계좌 평가 |
| kt00005 | 체결잔고요청 | /api/dostk/acnt | 보유 종목 |
| ka10075 | 미체결요청 | /api/dostk/acnt | 미체결 주문 |
| ka10076 | 체결요청 | /api/dostk/acnt | 체결 내역 |
| ka10085 | 계좌수익률요청 | /api/dostk/acnt | 수익률 |

### 조건검색 (WebSocket)
| API ID | API명 | URL | 설명 |
|--------|-------|-----|------|
| ka10171 | 조건검색 목록조회 | /api/dostk/websocket | 조건식 목록 |
| ka10172 | 조건검색 요청 일반 | /api/dostk/websocket | 일반 검색 |
| ka10173 | 조건검색 요청 실시간 | /api/dostk/websocket | 실시간 검색 |
| ka10174 | 조건검색 실시간 해제 | /api/dostk/websocket | 실시간 해제 |

### 종목정보
| API ID | API명 | URL | 설명 |
|--------|-------|-----|------|
| ka10001 | 주식기본정보요청 | /api/dostk/stkinfo | 기본정보 |
| ka10099 | 종목정보 리스트 | /api/dostk/stkinfo | 종목 목록 |
| ka10100 | 종목정보 조회 | /api/dostk/stkinfo | 종목 상세 |

### 시세
| API ID | API명 | URL | 설명 |
|--------|-------|-----|------|
| ka10004 | 주식호가요청 | /api/dostk/mrkcond | 호가 |
| ka10005 | 주식일주월시분요청 | /api/dostk/mrkcond | OHLCV |
| ka10079-83 | 차트조회요청 | /api/dostk/chart | 틱/분/일/주/월봉 |

### 실시간 시세 (WebSocket)
| API ID | API명 | 설명 |
|--------|-------|------|
| 00 | 주문체결 | 주문/체결 실시간 |
| 04 | 잔고 | 잔고 변동 |
| 0B | 주식체결 | 체결 시세 |
| 0D | 주식호가잔량 | 호가 실시간 |
| 1h | VI발동/해제 | VI 알림 |

---

## 도메인

- **운영**: `https://api.kiwoom.com`
- **모의투자**: `https://mockapi.kiwoom.com` (KRX만 지원)

---

## 공통 헤더

### Request
| Header | 설명 | 필수 |
|--------|------|------|
| Content-Type | application/json;charset=UTF-8 | Y |
| api-id | TR명 (예: kt10000) | Y |
| authorization | Bearer {token} | Y |
| cont-yn | 연속조회여부 | N |
| next-key | 연속조회키 | N |

### Response
| Header | 설명 |
|--------|------|
| api-id | TR명 |
| cont-yn | 다음 데이터 있으면 Y |
| next-key | 다음 조회 키 |

---

## 참고

- 상세 스펙: `키움 REST API 문서.xlsx` 참조
- 온라인 가이드: https://openapi.kiwoom.com/guide/apiguide
