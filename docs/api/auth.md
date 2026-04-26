# 인증 API 상세

## au10001: 접근토큰 발급

### 기본 정보
- **URL**: `/oauth2/token`
- **Method**: POST
- **Content-Type**: application/json;charset=UTF-8

### Request Body
| Element | 한글명 | Type | Required | 설명 |
|---------|--------|------|----------|------|
| grant_type | grant_type | String | Y | "client_credentials" 고정 |
| appkey | 앱키 | String | Y | 발급받은 앱키 |
| secretkey | 시크릿키 | String | Y | 발급받은 시크릿키 |

### Response Body
| Element | 한글명 | Type | 설명 |
|---------|--------|------|------|
| token | 접근토큰 | String | Bearer 토큰 |
| token_type | 토큰타입 | String | "bearer" |
| expires_dt | 만료일시 | String | "YYYYMMDDHHmmss" 형식 |
| return_code | 결과코드 | Number | 0=정상 |
| return_msg | 결과메시지 | String | |

### 예제

**Request:**
```json
{
    "grant_type": "client_credentials",
    "appkey": "AxserEsdcredca.....",
    "secretkey": "SEefdcwcforehDre2fdvc...."
}
```

**Response:**
```json
{
    "expires_dt": "20241107083713",
    "token_type": "bearer",
    "token": "WQJCwyqInphKnR3bSRtB9NE1lv...",
    "return_code": 0,
    "return_msg": "정상적으로 처리되었습니다"
}
```

### 토큰 사용법

모든 API 호출 시 Header에 토큰 포함:
```
authorization: Bearer {token}
```

### 토큰 관리 주의사항

1. **만료 시간**: `expires_dt` 확인 (보통 24시간)
2. **갱신 타이밍**: 만료 5분 전 재발급 권장
3. **저장**: 안전한 장소에 영속화 (환경변수, 암호화 파일)

---

## au10002: 접근토큰 폐기

### 기본 정보
- **URL**: `/oauth2/revoke`
- **Method**: POST

사용 종료 시 토큰 폐기 가능 (선택사항)
