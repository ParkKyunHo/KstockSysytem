# 조건검색 API 상세

## 중요 정보

- **프로토콜**: WebSocket (REST 아님!)
- **운영 도메인**: `wss://api.kiwoom.com:10000`
- **모의투자 도메인**: `wss://mockapi.kiwoom.com:10000`
- **URL**: `/api/dostk/websocket`
- **조건식 생성**: 영웅문4 HTS에서 생성

---

## ka10171: 조건검색 목록조회

HTS에서 만든 조건검색식 목록을 조회합니다.

### Request Body
| Element | 한글명 | Type | Required | 설명 |
|---------|--------|------|----------|------|
| trnm | TR명 | String | Y | "CNSRLST" 고정값 |

### Response Body
| Element | 한글명 | Type | 설명 |
|---------|--------|------|------|
| return_code | 결과코드 | String | 0=정상 |
| return_msg | 결과메시지 | String | |
| trnm | 서비스명 | String | "CNSRLST" |
| data | 조건검색식 목록 | List | |
| - seq | 조건검색식 일련번호 | String | |
| - name | 조건검색식 명 | String | |

### 예제

**Request:**
```json
{
    "trnm": "CNSRLST"
}
```

**Response:**
```json
{
    "return_code": "0",
    "trnm": "CNSRLST",
    "data": [
        {"seq": "000", "name": "주도주매수조건"},
        {"seq": "001", "name": "단타조건"}
    ]
}
```

---

## ka10172: 조건검색 요청 일반

조건식에 해당하는 종목을 한번 검색합니다. (폴링용)

### Request Body
| Element | 한글명 | Type | Required | 설명 |
|---------|--------|------|----------|------|
| trnm | TR명 | String | Y | "CNSRREQ" 고정값 |
| seq | 조건검색식 일련번호 | String | Y | ka10171에서 조회한 seq |

### Response Body
| Element | 한글명 | Type | 설명 |
|---------|--------|------|------|
| return_code | 결과코드 | String | 0=정상 |
| trnm | 서비스명 | String | "CNSRREQ" |
| data | 검색 결과 | List | |
| - stk_cd | 종목코드 | String | |
| - stk_nm | 종목명 | String | |

---

## ka10173: 조건검색 요청 실시간

조건식에 해당하는 종목을 실시간으로 감시합니다.

### Request Body
| Element | 한글명 | Type | Required | 설명 |
|---------|--------|------|----------|------|
| trnm | TR명 | String | Y | "CNSRREAL" 고정값 |
| seq | 조건검색식 일련번호 | String | Y | |

### Response (실시간)
조건 충족/이탈 시 WebSocket으로 푸시됩니다.

| Element | 한글명 | 설명 |
|---------|--------|------|
| stk_cd | 종목코드 | |
| stk_nm | 종목명 | |
| type | 신호유형 | I=편입, O=이탈 |

---

## ka10174: 조건검색 실시간 해제

실시간 조건검색을 중지합니다.

### Request Body
| Element | 한글명 | Type | Required | 설명 |
|---------|--------|------|----------|------|
| trnm | TR명 | String | Y | "CNSRSTOP" 고정값 |
| seq | 조건검색식 일련번호 | String | Y | 해제할 조건식 seq |

---

## WebSocket 연결 예제

```python
import websockets
import json

async def connect_condition():
    uri = "wss://api.kiwoom.com:10000/api/dostk/websocket"

    async with websockets.connect(uri) as ws:
        # 인증
        auth = {
            "authorization": f"Bearer {token}",
            "api-id": "ka10171"
        }

        # 조건식 목록 조회
        await ws.send(json.dumps({
            "trnm": "CNSRLST"
        }))

        response = await ws.recv()
        conditions = json.loads(response)

        # 실시간 조건검색 시작
        await ws.send(json.dumps({
            "trnm": "CNSRREAL",
            "seq": "000"
        }))

        # 실시간 수신
        while True:
            data = await ws.recv()
            signal = json.loads(data)
            if signal.get('type') == 'I':
                print(f"편입: {signal['stk_nm']}")
            elif signal.get('type') == 'O':
                print(f"이탈: {signal['stk_nm']}")
```

---

## 주의사항

1. **영웅문4 필수**: 조건식은 영웅문4 HTS에서만 생성 가능
2. **WebSocket 유지**: 연결이 끊기면 실시간 검색 중단
3. **재연결 로직**: 네트워크 장애 대비 자동 재연결 구현 필요
4. **동시 제한**: 실시간 조건검색 동시 실행 개수 제한 있음
