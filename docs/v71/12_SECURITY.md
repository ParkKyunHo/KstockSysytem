# V7.1 보안 (Security)

> 이 문서는 V7.1 시스템의 **보안 아키텍처와 정책**을 정의합니다.
> 
> 1인 시스템이지만 **실거래 자금**을 다루므로 보안이 매우 중요합니다.
> 
> Security Reviewer Agent가 모든 보안 관련 코드를 검증합니다.

---

## 목차

- [§0. 보안 철학](#0-보안-철학)
- [§1. 위협 모델](#1-위협-모델)
- [§2. 통신 보안 (HTTPS)](#2-통신-보안-https)
- [§3. 인증 (Authentication)](#3-인증-authentication)
- [§4. 권한 (Authorization)](#4-권한-authorization)
- [§5. 입력 검증](#5-입력-검증)
- [§6. 시크릿 관리](#6-시크릿-관리)
- [§7. 감사 로그](#7-감사-로그)
- [§8. 외부 시스템 보안](#8-외부-시스템-보안)
- [§9. 인프라 보안](#9-인프라-보안)
- [§10. 사고 대응](#10-사고-대응)

---

## §0. 보안 철학

### 0.1 5대 원칙

```yaml
원칙 1: Zero Trust (모든 입력 의심)
  사용자 입력 검증
  외부 API 응답 검증
  내부 시스템 간에도 검증
  "신뢰하지 말고 검증하라"

원칙 2: Defense in Depth (다층 방어)
  단일 보안 레이어 의존 X
  여러 레이어 (네트워크 → 인증 → 권한 → 입력 → DB)
  하나 뚫려도 다른 레이어가 막음

원칙 3: Least Privilege (최소 권한)
  필요한 최소한의 권한만
  DB 사용자 권한 분리
  API 키 범위 제한
  세션 짧게

원칙 4: Audit Everything (모든 것 기록)
  모든 사용자 액션 audit_logs
  로그인, 설정 변경, 거래
  6개월 이상 보존
  사후 추적 가능

원칙 5: Fail Secure (안전하게 실패)
  에러 시 기본은 차단
  예외 처리 누락 시 거부
  의심스러우면 차단

위 원칙은 V7.1 헌법과 정합:
  - 헌법 1 (사용자 판단): 보안도 사용자가 최종 통제
  - 헌법 4 (시스템 계속 운영): 보안 사고 시에도 안전 모드만
```

### 0.2 1인 시스템 vs 보안

```yaml
1인 시스템이라도 보안 중요한 이유:
  1. 실거래 자금 (수천만원~수억원)
  2. 키움증권 API 키 (탈취 시 무단 거래)
  3. 개인정보 (텔레그램 ID 등)
  4. 거래 이력 (민감 정보)

확장 가능 설계:
  - 다중 사용자 지원 (역할 분리)
  - role 필드 (OWNER, ADMIN, VIEWER)
  - RLS 정책 추후 추가 가능
```

### 0.3 위협 vs 비용 균형

```yaml
보안과 편의성의 균형:
  - 너무 강하면: 사용자 불편 → 우회
  - 너무 약하면: 사고 위험

V7.1 선택:
  - 강력한 인증 (2FA 필수)
  - 자동 로그아웃 (30분)
  - 감사 로그 (모든 것)
  - HTTPS 강제
  
  사용자 편의:
    - 새 IP 즉시 알림 (수동 차단 X, 알림으로)
    - 백업 코드 (TOTP 분실 대비)
    - Refresh 토큰 (24시간, 자주 로그인 안 해도)
```

---

## §1. 위협 모델

### 1.1 주요 위협 시나리오

```yaml
위협 1: 외부 공격자가 시스템 침입
  목표: 무단 거래, 자금 탈취, 데이터 유출
  
  공격 벡터:
    - 약한 비밀번호 (무차별 대입)
    - SQL Injection
    - XSS
    - CSRF
    - 세션 탈취 (XSS 또는 MITM)
    - 키움 API 키 탈취

위협 2: 합법 사용자의 실수
  목표: 본인이 본인 시스템에 손해
  
  시나리오:
    - 비밀번호 노출
    - TOTP 분실
    - 잘못된 설정 변경
    - 실수로 안전 모드 해제

위협 3: 내부자 위협 (1인 시스템에서는 거의 없음)
  목표: 데이터 유출
  → 향후 다중 사용자 시 대비

위협 4: 외부 시스템 침해
  목표: V7.1을 경유한 공격
  
  시나리오:
    - 키움 API 침해 → V7.1로 전파
    - Supabase 침해 → 데이터 탈취
    - Cloudflare 침해 → 트래픽 가로채기

위협 5: 디도스 (DDoS)
  목표: 서비스 마비
  → Cloudflare로 일차 방어
```

### 1.2 자산 분류

```yaml
극도로 민감 (Critical):
  - 키움 API 키 (실거래 가능)
  - JWT 시크릿
  - DB 비밀번호
  - 로그인 비밀번호 해시
  - TOTP 시크릿

매우 민감 (High):
  - 거래 이력 (positions, trade_events)
  - 박스 설정 (전략 노출)
  - 텔레그램 chat_id
  - 사용자 IP 주소

중간 민감 (Medium):
  - 추적 종목 리스트
  - 알림 이력
  - 시스템 로그

공개 가능 (Low):
  - 시스템 상태 (운영 중)
  - 페이지 제목 등 UI
```

---

## §2. 통신 보안 (HTTPS)

### 2.1 HTTPS 강제

```yaml
모든 통신 HTTPS:
  - 웹 대시보드 (HTTPS)
  - WebSocket (WSS)
  - API (HTTPS)

HTTP 접근 시:
  자동 HTTPS 리다이렉트 (Nginx)

HSTS 헤더:
  Strict-Transport-Security: max-age=31536000; includeSubDomains; preload
  → 1년간 HTTPS만 사용
  → 브라우저가 HTTP 시도 자체를 차단
```

### 2.2 SSL/TLS 인증서

```yaml
인증서: Let's Encrypt (무료, 자동 갱신)
  발급: certbot
  갱신: 90일마다 자동
  설치 위치: Nginx

설정:
  TLS 1.2+ (TLS 1.0, 1.1 비활성)
  Strong Cipher Suites만
  Forward Secrecy

A+ 등급 목표:
  https://www.ssllabs.com/ssltest/ 로 검증
```

### 2.3 Cloudflare 통합

```yaml
용도:
  - DDoS 방어
  - WAF (Web Application Firewall)
  - DNS
  - SSL/TLS 추가 레이어

설정:
  Full (Strict) SSL: Cloudflare ↔ Origin 모두 HTTPS
  
  방화벽 규칙:
    - Bot Fight Mode 활성화
    - Challenge 의심스러운 트래픽
    - 한국 외 트래픽 차단 (선택, 강력)

  Rate Limiting:
    - /api/v71/auth/login: IP당 5회/분
    - /api/v71/*: IP당 100회/분
    - 일반 페이지: 200회/분
```

### 2.4 Nginx 설정 예시

```nginx
# /etc/nginx/sites-available/v71

server {
    listen 80;
    server_name v71.example.com;
    
    # HTTPS 강제 리다이렉트
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name v71.example.com;
    
    # SSL 인증서
    ssl_certificate /etc/letsencrypt/live/v71.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/v71.example.com/privkey.pem;
    
    # SSL 설정 (강력)
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    
    # HSTS
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
    
    # 보안 헤더
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
    
    # CSP (Content Security Policy)
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' wss://v71.example.com;" always;
    
    # 백엔드 프록시
    location /api/ {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # 타임아웃
        proxy_connect_timeout 30s;
        proxy_send_timeout 30s;
        proxy_read_timeout 30s;
    }
    
    # WebSocket
    location /api/v71/ws {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        
        # WebSocket 타임아웃 (긴 연결)
        proxy_read_timeout 300s;
    }
    
    # 정적 파일 (React 빌드)
    location / {
        root /home/ubuntu/K_stock_trading/frontend/build;
        try_files $uri $uri/ /index.html;
    }
}
```

---

## §3. 인증 (Authentication)

### 3.1 인증 방식: JWT + 2FA

```yaml
1단계: 비밀번호 (ID/PW)
2단계: TOTP (Google Authenticator)

JWT 토큰:
  Access Token:
    유효 기간: 1시간
    저장: 메모리 (또는 sessionStorage)
    Header: Authorization: Bearer <token>
  
  Refresh Token:
    유효 기간: 24시간
    저장: HttpOnly Secure Cookie (XSS 방어)
    경로: /api/v71/auth/refresh 만
```

### 3.2 비밀번호 정책

```yaml
요구사항:
  - 최소 8자 이상
  - 영문 대소문자 + 숫자 + 특수문자 중 3종 이상
  - 사용자명/이메일과 다름
  - 일반적인 약한 비밀번호 차단 (top 1000)

저장:
  bcrypt (cost=12)
  ※ MD5, SHA1 절대 금지
  ※ 평문 저장 절대 금지

변경 정책:
  - 강제 주기 변경 없음 (NIST 가이드)
  - 침해 의심 시 즉시 변경
  - 마지막 변경일 추적
```

### 3.3 2FA (Two-Factor Authentication)

```yaml
방식: TOTP (Time-based One-Time Password)
  RFC 6238 표준
  Google Authenticator, Authy 호환

설정 플로우:
  1. /api/v71/auth/totp/setup 호출
  2. 서버: TOTP secret 생성 (BASE32, 160비트)
  3. QR 코드 + 수동 입력 코드 표시
  4. 사용자: 앱에 등록
  5. 6자리 코드 입력하여 검증
  6. /api/v71/auth/totp/confirm 호출
  7. users.totp_enabled = true
  8. 백업 코드 10개 표시 (1회용)

백업 코드:
  - 8자리 숫자 (예: 12345678)
  - 10개 생성
  - 해시 저장 (bcrypt)
  - 1회 사용 후 폐기
  - TOTP 분실 시 사용
  - 안전한 곳 보관 (사용자 책임)

검증 (로그인 시):
  - TOTP 6자리 입력
  - 또는 백업 코드 8자리
  - 시간 동기화 (서버 NTP)
  - 시간 차이 ±30초 허용 (드리프트)

비활성화 (보안 위험):
  - 비활성화 시 강제 비밀번호 재입력
  - audit_logs 기록
  - 텔레그램 CRITICAL 알림
```

### 3.4 로그인 플로우 상세

```python
# src/web/auth/login.py 의사 코드

async def login(username, password, ip_address):
    # 1. Rate Limit (IP당 5회/분)
    if rate_limited(ip_address):
        await audit_log(action='LOGIN_FAILED', ip=ip_address, reason='RATE_LIMIT')
        raise HTTPException(429, 'Too many attempts')
    
    # 2. 사용자 조회 (parameterized query)
    user = await user_repo.get_by_username(username)
    
    # 3. Timing Attack 방어 (사용자 없어도 동일 시간)
    if not user:
        await asyncio.sleep(random.uniform(0.1, 0.3))
        await audit_log(action='LOGIN_FAILED', ip=ip_address, reason='USER_NOT_FOUND')
        raise HTTPException(401, 'Invalid credentials')
    
    # 4. 비밀번호 검증 (bcrypt)
    if not bcrypt.checkpw(password.encode(), user.password_hash.encode()):
        await audit_log(user_id=user.id, action='LOGIN_FAILED', ip=ip_address, reason='WRONG_PASSWORD')
        raise HTTPException(401, 'Invalid credentials')
    
    # 5. 활성 사용자 확인
    if not user.is_active:
        raise HTTPException(403, 'Account disabled')
    
    # 6. TOTP 활성 시 별도 단계
    if user.totp_enabled:
        # 임시 세션 (15분)
        temp_session_id = create_temp_session(user.id, ip_address)
        return {
            'totp_required': True,
            'session_id': temp_session_id,
        }
    
    # 7. TOTP 비활성 시 토큰 발급
    return await issue_tokens(user, ip_address)


async def verify_totp(temp_session_id, totp_code, ip_address):
    # 1. 임시 세션 조회
    session = await get_temp_session(temp_session_id)
    if not session or session.expired or session.ip != ip_address:
        raise HTTPException(401, 'Invalid session')
    
    user = await user_repo.get_by_id(session.user_id)
    
    # 2. TOTP 검증
    if not pyotp.TOTP(user.totp_secret).verify(totp_code, valid_window=1):
        await audit_log(user_id=user.id, action='LOGIN_FAILED', ip=ip_address, reason='WRONG_TOTP')
        raise HTTPException(401, 'Invalid TOTP code')
    
    # 3. 임시 세션 삭제
    await delete_temp_session(temp_session_id)
    
    # 4. 토큰 발급
    return await issue_tokens(user, ip_address)


async def issue_tokens(user, ip_address):
    # 1. 새 IP 감지
    if user.last_login_ip and user.last_login_ip != ip_address:
        await send_critical_notification(
            event_type='NEW_IP_LOGIN',
            payload={'ip': ip_address, 'previous_ip': user.last_login_ip},
        )
    
    # 2. JWT 생성
    access_token = jwt.encode({
        'user_id': str(user.id),
        'role': user.role,
        'exp': datetime.utcnow() + timedelta(hours=1),
    }, get_jwt_secret(), algorithm='HS256')
    
    refresh_token = jwt.encode({
        'user_id': str(user.id),
        'exp': datetime.utcnow() + timedelta(hours=24),
        'type': 'refresh',
    }, get_jwt_secret(), algorithm='HS256')
    
    # 3. 세션 기록
    await session_repo.create(
        user_id=user.id,
        access_token_hash=hash_token(access_token),
        refresh_token_hash=hash_token(refresh_token),
        ip_address=ip_address,
    )
    
    # 4. 사용자 정보 업데이트
    await user_repo.update_last_login(user.id, ip_address)
    
    # 5. 감사 로그
    await audit_log(user_id=user.id, action='LOGIN', ip=ip_address)
    
    return {
        'access_token': access_token,
        'refresh_token': refresh_token,
        'expires_in': 3600,
    }
```

### 3.5 자동 로그아웃

```yaml
30분 비활성 자동 로그아웃:
  - user_sessions.last_activity_at 추적
  - 미들웨어가 매 요청마다 갱신
  - 30분 초과 시 세션 무효
  - 다음 요청 시 401 반환

구현:
  미들웨어에서:
    if (now - session.last_activity_at) > 30분:
        session.revoked = True
        return 401 SESSION_EXPIRED
    else:
        session.last_activity_at = now
```

### 3.6 로그아웃

```yaml
명시적 로그아웃:
  POST /api/v71/auth/logout
  
  처리:
    - user_sessions.revoked = true
    - access_token + refresh_token 무효화
    - audit_logs (LOGOUT)
    - 클라이언트: 토큰 삭제

전체 세션 종료:
  POST /api/v71/auth/logout_all
  → 모든 활성 세션 폐기 (다른 기기도)
  → 보안 사고 시
```

---

## §4. 권한 (Authorization)

### 4.1 역할 정의

```yaml
현재 (1인 시스템):
  OWNER: 모든 권한

확장 가능:
  ADMIN: 거의 모든 권한 (사용자 관리 제외)
  TRADER: 거래 + 조회
  VIEWER: 조회만

권한 분리 매트릭스 (향후):
  | 액션 | OWNER | ADMIN | TRADER | VIEWER |
  | 조회 | ✓ | ✓ | ✓ | ✓ |
  | 박스 등록/수정 | ✓ | ✓ | ✓ |  |
  | 추적 종료 | ✓ | ✓ | ✓ |  |
  | Feature Flag 변경 | ✓ |  |  |  |
  | 사용자 관리 | ✓ |  |  |  |
```

### 4.2 권한 검사 미들웨어

```python
# src/web/auth/middleware.py

from fastapi import HTTPException, Depends, Request

async def get_current_user(request: Request) -> User:
    """JWT 검증 + 사용자 조회."""
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        raise HTTPException(401, 'Missing token')
    
    token = auth_header[7:]
    
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=['HS256'])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, 'Token expired')
    except jwt.InvalidTokenError:
        raise HTTPException(401, 'Invalid token')
    
    user = await user_repo.get_by_id(payload['user_id'])
    if not user or not user.is_active:
        raise HTTPException(401, 'User not active')
    
    # 세션 검증 (revoked, expired)
    session = await session_repo.get_by_token_hash(hash_token(token))
    if not session or session.revoked or session.expired:
        raise HTTPException(401, 'Session invalid')
    
    # 30분 비활성 체크
    if (datetime.utcnow() - session.last_activity_at) > timedelta(minutes=30):
        await session_repo.revoke(session.id)
        raise HTTPException(401, 'Session expired (inactivity)')
    
    # 활동 시간 갱신
    await session_repo.update_activity(session.id)
    
    return user


async def require_owner(user: User = Depends(get_current_user)) -> User:
    """OWNER 권한 필수."""
    if user.role != 'OWNER':
        raise HTTPException(403, 'OWNER role required')
    return user


# 사용 예
@router.delete("/api/v71/users/{user_id}")
async def delete_user(user_id: UUID, current_user: User = Depends(require_owner)):
    ...
```

### 4.3 텔레그램 봇 권한

```yaml
authorized_chat_ids:
  - 환경 변수 또는 DB 저장
  - 등록된 chat_id만 봇 응답

검증 (모든 명령어):
  if update.message.chat_id not in authorized_chat_ids:
      # 응답 안 함 (silent ignore)
      # audit_logs (UNAUTHORIZED_TELEGRAM_ACCESS)
      return
  
  # 정상 명령 처리
  ...

이유:
  봇 토큰이 알려져도
  허용된 chat_id에서만 동작
  추가 안전망
```

---

## §5. 입력 검증

### 5.1 모든 입력 검증

```yaml
원칙:
  - 클라이언트는 신뢰 안 함
  - 서버에서 모두 검증
  - Pydantic 활용

검증 항목:
  1. 타입 (string, int, datetime)
  2. 범위 (min, max)
  3. 형식 (regex, enum)
  4. 길이 (min_length, max_length)
  5. 비즈니스 룰 (박스 가격 범위 등)
```

### 5.2 Pydantic 사용

```python
# src/web/api/boxes.py

from pydantic import BaseModel, Field, validator
from typing import Literal, Optional

class CreateBoxRequest(BaseModel):
    """박스 생성 요청 검증."""
    
    tracked_stock_id: str = Field(..., regex=r'^[0-9a-f-]{36}$')  # UUID
    
    upper_price: int = Field(..., ge=1, le=10_000_000_000)  # 1원 ~ 100억
    lower_price: int = Field(..., ge=1, le=10_000_000_000)
    
    position_size_pct: float = Field(..., gt=0, le=100)
    
    stop_loss_pct: float = Field(default=-0.05, lt=0, gt=-1)  # -100% ~ 0% 미만
    
    strategy_type: Literal['PULLBACK', 'BREAKOUT']
    
    memo: Optional[str] = Field(None, max_length=500)
    
    @validator('lower_price')
    def lower_must_be_less_than_upper(cls, v, values):
        if 'upper_price' in values and v >= values['upper_price']:
            raise ValueError('lower_price must be less than upper_price')
        return v
    
    @validator('memo')
    def sanitize_memo(cls, v):
        if v is None:
            return v
        # XSS 방어
        import bleach
        return bleach.clean(v, tags=[], strip=True)
```

### 5.3 SQL Injection 방어

```yaml
원칙:
  Parameterized Query만 사용
  문자열 연결 절대 금지

좋은 예 (asyncpg):
  await conn.execute(
      "SELECT * FROM users WHERE username = $1",
      username,  # 파라미터로
  )

나쁜 예 (절대 금지):
  await conn.execute(
      f"SELECT * FROM users WHERE username = '{username}'"
  )
  # ← SQL Injection 가능

ORM 사용 시 (SQLAlchemy):
  자동 parameterized
  단, raw query 사용 시 주의

검증 도구:
  bandit (Python 보안 lint)
  - 위험 패턴 자동 감지
```

### 5.4 XSS 방어

```yaml
서버 측:
  - 사용자 입력에 HTML 태그 제거 (bleach)
  - HTML 인코딩 (memo, stock_name 등 출력 시)

클라이언트 측 (React):
  - JSX는 자동 escape (기본 안전)
  - dangerouslySetInnerHTML 사용 금지
  - URL 검증 (javascript: 등 차단)

CSP 헤더:
  Content-Security-Policy:
    default-src 'self';
    script-src 'self';
    style-src 'self' 'unsafe-inline';  # Tailwind 위해
    img-src 'self' data:;
    connect-src 'self' wss://v71.example.com;
  
  → 외부 스크립트 실행 차단
```

### 5.5 CSRF 방어

```yaml
JWT 사용:
  Authorization Header (자동 X)
  CSRF 거의 무관

Cookie 기반 Refresh:
  SameSite=Strict
  HttpOnly
  Secure
  
  + CSRF 토큰 (선택, double submit)

API:
  POST/PUT/DELETE 모두 JWT 검증
  쿠키 기반 인증 안 사용 (Refresh 제외)
```

---

## §6. 시크릿 관리

### 6.1 시크릿 분류

```yaml
극도 민감 (Critical Secrets):
  - 키움 API 키 (App Key, Secret)
  - JWT 시크릿 (HS256 키)
  - DB 비밀번호 (Supabase service_role)
  - Anthropic API 키
  - 텔레그램 봇 토큰

민감 (Sensitive):
  - 사용자 비밀번호 해시 (DB에)
  - TOTP secret
  - Refresh 토큰 해시
```

### 6.2 저장 방식

```yaml
환경 변수 (.env):
  - 코드와 분리
  - .gitignore에 .env
  - 절대 커밋 금지
  
구조:
  .env
  ├── DB_HOST
  ├── DB_PASSWORD
  ├── KIWOOM_APP_KEY
  ├── KIWOOM_APP_SECRET
  ├── JWT_SECRET
  ├── ANTHROPIC_API_KEY
  ├── TELEGRAM_BOT_TOKEN
  └── ...

운영 환경:
  - AWS Lightsail의 환경 변수
  - 또는 .env 파일 (chmod 600)
  - 시스템 사용자만 읽기

백업:
  - 시크릿은 별도 안전한 곳 (1Password 등)
  - 정기 백업
```

### 6.3 시크릿 노출 방지

```yaml
로그 출력 금지:
  - logger.info(f"API key: {key}")  ← 절대 금지
  - 자동 마스킹: ****1234

코드 검색:
  - git-secrets 또는 truffleHog 사용
  - 커밋 전 자동 검사
  - .gitignore 정확

Git 히스토리:
  - 실수로 커밋 시:
    - git filter-branch 또는 BFG로 제거
    - 키 즉시 폐기 + 재발급

API 응답:
  - 비밀번호, 토큰 응답에 포함 X
  - users 조회 시 password_hash 제외
```

### 6.4 키 로테이션

```yaml
정기 로테이션:
  - JWT 시크릿: 6개월
  - DB 비밀번호: 1년
  - 키움 API 키: 12개월 또는 침해 의심 시
  - 텔레그램 봇 토큰: 12개월

긴급 로테이션:
  - 침해 의심 즉시
  - 노출 의심 즉시

자동화 (선택):
  - 스크립트로 키 갱신
  - 스케줄러로 만료 알림
```

---

## §7. 감사 로그

### 7.1 기록 대상

```yaml
모든 로그인:
  - LOGIN (성공)
  - LOGIN_FAILED (실패: 사유 포함)
  - LOGOUT

세션 관리:
  - SESSION_REVOKED
  - SESSION_EXPIRED

설정 변경:
  - SETTINGS_CHANGED
  - PASSWORD_CHANGED
  - TOTP_ENABLED / TOTP_DISABLED

거래 관련:
  - BOX_CREATED / BOX_MODIFIED / BOX_DELETED
  - TRACKING_REGISTERED / TRACKING_REMOVED

시스템:
  - FEATURE_FLAG_CHANGED
  - SAFE_MODE_ACTIVATED / DEACTIVATED
  - SYSTEM_RESTARTED

보안:
  - NEW_IP_DETECTED
  - UNAUTHORIZED_TELEGRAM_ACCESS
  - API_KEY_ROTATED
```

### 7.2 로그 항목

```yaml
audit_logs 테이블 (03_DATA_MODEL.md §5.3):
  - id (UUID)
  - user_id
  - action (ENUM)
  - target_type, target_id (변경 대상)
  - before_state (JSONB)
  - after_state (JSONB)
  - ip_address (INET)
  - user_agent (TEXT)
  - success (boolean)
  - error_message (실패 시)
  - occurred_at (TIMESTAMPTZ)
```

### 7.3 보존 정책

```yaml
보존 기간:
  - audit_logs: 6개월 이상 (보안 사고 추적)
  - 보안 관련 (LOGIN, LOGIN_FAILED): 1년
  - 거래 관련: 영구 (legal/compliance)

보관:
  - 활성: PostgreSQL
  - 1년 이상: 별도 archive 테이블 또는 S3
  - 백업: 정기 (월 1회)
```

### 7.4 로그 분석

```yaml
정기 검토:
  - 주 1회: 비정상 로그인 시도
  - 월 1회: 전체 audit 리뷰
  - 분기: 보안 사고 분석

알림:
  - LOGIN_FAILED 5회/시간: 자동 알림
  - NEW_IP: 즉시 알림 (CRITICAL)
  - UNAUTHORIZED_TELEGRAM: 즉시 알림

대시보드 (선택):
  - 최근 10건 로그인
  - 실패 시도 그래프
  - 활성 세션 목록
```

---

## §8. 외부 시스템 보안

### 8.1 키움 API 보안

```yaml
API 키:
  - App Key + App Secret (2개)
  - 환경 변수에만 저장
  - DB에도 저장 안 함

OAuth 토큰:
  - 갱신 자동 (1시간 만료)
  - 메모리만 (DB 저장 안 함)
  - 갱신 실패 시 알림

호출 제한:
  - Rate Limiter (초당 4.5회)
  - 모든 호출 kiwoom_api_skill 통해서

이상 감지:
  - 비정상 주문 패턴
  - 갑작스러운 잔고 변화
  - 미인지 거래 → 즉시 알림 + 안전 모드
```

### 8.2 Anthropic API 보안

```yaml
API 키:
  - 환경 변수만
  - 사용량 모니터링
  - 월 한도 설정 (Anthropic 콘솔)

호출 제한:
  - 리포트 시스템에만 사용
  - 사용자 요청 시에만
  - 월 한도 (예: 30건)

오용 방지:
  - 사용자 입력 그대로 프롬프트에 X
  - 종목 코드 검증 후 사용
```

### 8.3 텔레그램 봇 보안

```yaml
봇 토큰:
  - 환경 변수
  - 노출 시 즉시 새 토큰

Chat ID 화이트리스트:
  - authorized_chat_ids (DB 또는 설정)
  - 외부 chat_id 무시
  - 시도 시 audit_logs

명령어 검증:
  - 모든 명령어 권한 검증
  - /stop, /resume 같은 위험한 명령어는 추가 확인
  - audit_logs 기록
```

### 8.4 DB (Supabase) 보안

```yaml
연결:
  - SSL 강제
  - service_role 키는 백엔드만 (절대 프론트 X)
  - anon 키도 가급적 사용 안 함 (서버에서 처리)

권한 분리 (Postgres):
  - app_user: 일반 CRUD (긴 권한 없음)
  - migration_user: DDL (마이그레이션만)
  - readonly_user: 분석/모니터링

RLS (Row Level Security):
  현재 (1인): 사용 안 함 (단순)
  향후 (다중): 활성화 필수

백업:
  - Supabase 자동 (7일 PITR)
  - 별도 S3 백업 (월 1회)
  - 백업 암호화
```

### 8.5 Cloudflare 보안

```yaml
설정:
  SSL: Full (Strict)
  DNS: A 레코드 → 서버 IP
  Proxy: 활성화 (오렌지 클라우드)

WAF 규칙:
  - SQL Injection 패턴 차단
  - XSS 패턴 차단
  - Path Traversal 차단

방화벽:
  - 의심스러운 IP 차단
  - Bot Fight Mode
  - 한국 외 트래픽 모니터링 (선택 차단)
```

---

## §9. 인프라 보안

### 9.1 AWS Lightsail 보안

```yaml
SSH 접근:
  - Key 기반 인증만 (비밀번호 비활성)
  - SSH 포트 22 → 22XXX (변경)
  - root 직접 로그인 차단
  - sudo 사용

방화벽:
  - 22XXX (SSH): 사용자 IP만 (또는 VPN)
  - 80, 443 (Web): 모두
  - 기타: 모두 차단

자동 업데이트:
  - 보안 패치 자동
  - unattended-upgrades

백업:
  - Lightsail 자동 스냅샷 (일 1회)
  - 7일 보관
  - 외부 백업 (S3, 월 1회)
```

### 9.2 시스템 사용자

```yaml
사용자 분리:
  - root: 시스템 관리
  - ubuntu: 일반 사용자
  - kstock: 애플리케이션 전용 (sudo 없음)

권한:
  - 애플리케이션은 kstock 사용자로 실행
  - systemd User=kstock
  - 파일 권한 최소화

로그:
  - /var/log/syslog
  - /var/log/auth.log
  - 정기 모니터링
```

### 9.3 시크릿 파일 권한

```yaml
.env 파일:
  - chmod 600 (소유자만 읽기)
  - chown kstock:kstock
  - 다른 사용자 접근 차단

systemd 설정:
  EnvironmentFile=/home/kstock/.env

로그 파일:
  - chmod 640 (그룹 읽기)
  - 시크릿 노출 방지 (마스킹)
```

### 9.4 모니터링

```yaml
시스템:
  - htop, df 정기 확인
  - 디스크 80% 초과 알림
  - 메모리 90% 초과 알림

로그:
  - journalctl 모니터링
  - /var/log/auth.log 검토
  - failed login 추적

침입 탐지 (선택):
  - fail2ban (SSH 무차별 대입 차단)
  - rkhunter (rootkit 탐지)
```

---

## §10. 사고 대응

### 10.1 사고 분류

```yaml
Level 1 (긴급, 즉시 대응):
  - 무단 거래 발생
  - API 키 탈취 의심
  - 다수 로그인 실패 (공격)
  - 서비스 다운

Level 2 (긴급, 1시간 내):
  - 새 IP 로그인 (확인 후 정상)
  - 비정상 거래 패턴
  - 인증 실패 급증

Level 3 (관찰):
  - 단일 로그인 실패
  - 알 수 없는 봇 트래픽
  - 정상 운영 외 활동
```

### 10.2 즉시 대응 (Level 1)

```yaml
Step 1: 안전 모드 진입 (1분 내)
  ssh 서버
  systemctl stop kstock-v71
  또는 Feature Flag 모두 OFF
  
  목적: 추가 거래 차단

Step 2: 키움 API 키 폐기 (5분 내)
  키움 OpenAPI 콘솔 접속
  기존 키 비활성
  새 키 발급

Step 3: 비밀번호 변경 (10분 내)
  웹 비밀번호
  DB 비밀번호 (Supabase 콘솔)
  JWT 시크릿
  
  systemctl restart kstock-v71 (새 시크릿 적용)

Step 4: 침해 범위 파악 (30분 내)
  audit_logs 검토
  거래 이력 확인
  키움 거래 내역 대조
  
  손실 추정

Step 5: 복구 또는 재구성 (24시간 내)
  손실 시: 키움증권 신고 + 보험 청구
  데이터 복원 (백업에서)
  시스템 재시작 (확인 후)
```

### 10.3 대응 체크리스트

```yaml
사고 발생 즉시:
  ☐ 안전 모드 진입
  ☐ 시간 기록 (사고 발생 시각)
  ☐ 증거 수집 (로그, 스크린샷)
  ☐ 텔레그램 알림 (있다면)

1시간 내:
  ☐ 키움 API 키 폐기
  ☐ 모든 비밀번호 변경
  ☐ 모든 세션 종료 (logout_all)
  ☐ 외부 침해 범위 파악

24시간 내:
  ☐ 손실 추정
  ☐ 키움 신고 (필요 시)
  ☐ 사고 분석 보고서
  ☐ 대응 조치 실행

1주일 내:
  ☐ 재발 방지 대책
  ☐ 보안 강화 (취약점 패치)
  ☐ 시스템 재구성
  ☐ 모의 침투 테스트 (선택)
```

### 10.4 사고 분석 (Post-Mortem)

```yaml
보고서 항목:
  1. 사고 개요
     - 시간
     - 영향 범위
     - 손실 금액
  
  2. 발생 원인
     - 기술적 원인
     - 절차적 원인
     - 사용자 원인
  
  3. 대응 과정
     - 시간순 액션
     - 효과적이었던 조치
     - 부족했던 부분
  
  4. 재발 방지
     - 단기 조치 (즉시)
     - 중기 조치 (1개월 내)
     - 장기 조치 (3개월 내)
  
  5. 교훈
     - 이번 사고에서 배운 것
     - 시스템 개선 사항

저장:
  docs/incidents/YYYY-MM-DD_<incident_name>.md
  Git에 영구 보존
```

### 10.5 정기 보안 점검

```yaml
주간:
  ☐ audit_logs 확인 (이상 없는지)
  ☐ 시스템 업데이트 확인
  ☐ 백업 정상 작동 확인

월간:
  ☐ 비밀번호 재검토
  ☐ 활성 세션 정리
  ☐ Cloudflare 트래픽 분석
  ☐ 사용량 이상 패턴 확인

분기:
  ☐ 시크릿 키 로테이션 검토
  ☐ 보안 취약점 스캔 (npm audit, pip-audit)
  ☐ 의존성 업데이트 (취약점 패치)
  ☐ SSL 인증서 점검

연간:
  ☐ 전체 보안 감사
  ☐ 모의 침투 테스트 (선택)
  ☐ 사고 대응 훈련
  ☐ 백업 복원 테스트
```

---

## 부록 A: 보안 체크리스트 (배포 전)

```yaml
인증:
  ☐ 비밀번호 bcrypt cost 12+
  ☐ 2FA 활성화 (사용자에게 안내)
  ☐ Rate Limit (로그인 5회/분)
  ☐ Timing attack 방어
  ☐ JWT 시크릿 강력 (256비트+)
  ☐ 30분 자동 로그아웃

통신:
  ☐ HTTPS 강제 (HTTP 리다이렉트)
  ☐ HSTS 헤더
  ☐ TLS 1.2+ 만 허용
  ☐ Cloudflare Full (Strict) SSL
  ☐ 보안 헤더 (CSP, X-Frame-Options 등)

입력:
  ☐ Pydantic 검증
  ☐ SQL Injection 방어 (parameterized)
  ☐ XSS 방어 (bleach)
  ☐ CSRF (JWT 사용으로 거의 OK)
  ☐ 파일 업로드 검증 (있다면)

시크릿:
  ☐ 환경 변수만 사용
  ☐ .gitignore에 .env
  ☐ git-secrets 검사
  ☐ 로그에 시크릿 노출 금지

권한:
  ☐ DB 사용자 권한 분리
  ☐ 텔레그램 chat_id 화이트리스트
  ☐ JWT 검증 미들웨어
  ☐ 30분 비활성 자동 로그아웃

감사:
  ☐ audit_logs 모든 중요 액션
  ☐ 새 IP 즉시 알림
  ☐ 로그인 실패 추적

인프라:
  ☐ SSH Key 기반만 (비밀번호 비활성)
  ☐ 방화벽 (UFW)
  ☐ 자동 업데이트
  ☐ 정기 백업
```

---

## 부록 B: 미정 사항

```yaml
B.1 다중 사용자 시 RLS 정책:
  현재 미적용 (1인)
  향후 추가 필요

B.2 침입 탐지 시스템 (IDS):
  fail2ban 도입 여부
  Snort 등 고급 IDS

B.3 로그 중앙화:
  현재: 서버 로컬
  향후: ELK 또는 CloudWatch

B.4 사용자 행동 분석 (UEBA):
  비정상 패턴 자동 감지
  머신러닝 기반

B.5 보험:
  사이버 보험 가입 검토
  거래 손실 보전 가능 여부
```

---

*이 문서는 V7.1 보안의 단일 진실 원천입니다.*  
*Security Reviewer Agent가 모든 보안 코드 검증.*  
*보안 사고 시 §10 사고 대응 절차 즉시 실행.*

*최종 업데이트: 2026-04-25*
