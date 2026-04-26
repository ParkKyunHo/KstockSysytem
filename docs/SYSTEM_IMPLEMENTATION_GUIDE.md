# System Implementation Guide

> K_stock_trading - 키움증권 REST API 국내 주식 자동매매 시스템 구현 레퍼런스
>
> 이 문서만으로 동일한 인프라를 재구축할 수 있는 수준의 상세도를 목표로 합니다.

---

## 목차

1. [시스템 개요](#1-시스템-개요)
2. [AWS 인프라 구성](#2-aws-인프라-구성)
3. [배포 파이프라인](#3-배포-파이프라인)
4. [키움 REST API 인증 (OAuth2)](#4-키움-rest-api-인증-oauth2)
5. [HTTP 클라이언트 아키텍처](#5-http-클라이언트-아키텍처)
6. [REST API 엔드포인트](#6-rest-api-엔드포인트)
7. [WebSocket 실시간 연결](#7-websocket-실시간-연결)
8. [조건검색식 구독](#8-조건검색식-구독)
9. [애플리케이션 런처](#9-애플리케이션-런처)
10. [데이터베이스 구성](#10-데이터베이스-구성)
11. [환경변수 관리](#11-환경변수-관리)
12. [모니터링 & 로깅](#12-모니터링--로깅)

---

## 1. 시스템 개요

### 1.1 전체 아키텍처

```
+------------------+       SSH/SCP        +------------------------+
|  Windows 개발PC  | ──────────────────── |   AWS Lightsail        |
|  C:\K_stock_trading                     |   Ubuntu 22.04         |
|                  |                      |   43.200.235.74        |
|  deploy.ps1      |                      |                        |
|  hotfix.ps1      |                      |   systemd service      |
|  status.ps1      |                      |   └─ launcher.py       |
+------------------+                      |       └─ src/main.py   |
                                          |           └─ Engine    |
                                          +-----+------+-----------+
                                                |      |
                                 +--------------+      +--------------+
                                 |                                    |
                          +------+-------+                   +--------+--------+
                          | Kiwoom API   |                   | Supabase        |
                          | REST + WS    |                   | PostgreSQL      |
                          +--------------+                   +-----------------+
                          | REST:                            | async psycopg3  |
                          |  api.kiwoom.com                  | pool: 5+10      |
                          | WebSocket:                       | fallback: SQLite|
                          |  wss://api.kiwoom.com:10000      +-----------------+
                          +--------------+
                                 |
                          +------+-------+
                          | Telegram Bot |
                          | 알림 & 명령어 |
                          +--------------+
```

### 1.2 기술 스택

| 분류 | 기술 | 용도 |
|------|------|------|
| 언어 | Python 3.11 | 메인 런타임 |
| 비동기 | AsyncIO | 이벤트 루프 |
| HTTP | httpx (async) | REST API 통신 |
| WebSocket | websockets | 실시간 데이터 |
| 설정 | Pydantic Settings v2 | 환경변수 → 타입 검증 |
| ORM | SQLAlchemy 2.0+ async | DB 추상화 |
| DB 드라이버 | psycopg3 (async), aiosqlite | PostgreSQL, SQLite |
| 로깅 | structlog | JSON 구조화 로깅 |
| 재시도 | tenacity | 지수 백오프 재시도 |
| 알림 | Telegram Bot API | 시스템 알림 + 명령어 |

### 1.3 인프라

| 항목 | 값 |
|------|-----|
| 클라우드 | AWS Lightsail |
| 리전 | ap-northeast-2 (서울) |
| OS | Ubuntu 22.04 LTS |
| 스펙 | 1GB RAM, 1 vCPU, $5/month |
| DB (Primary) | Supabase PostgreSQL |
| DB (Fallback) | SQLite (aiosqlite) |
| 고정 IP | 43.200.235.74 |

### 1.4 데이터 흐름

```
실시간 틱 (WebSocket)
    |
    v
CandleBuilder (틱 -> 3분봉)
    |
    v
SignalDetector (매수 신호 탐지)
    |
    v
RiskManager (진입 가능 여부)
    |
    v
OrderAPI (주문 실행)
    |
    v
PositionManager (포지션 모니터링)
    |
    v
ExitCoordinator (청산 판단)
```

---

## 2. AWS 인프라 구성

### 2.1 Lightsail 인스턴스

| 항목 | 값 |
|------|-----|
| 인스턴스명 | k-stock-trading |
| 플랜 | $5/month (1GB RAM, 1 vCPU) |
| OS | Ubuntu 22.04 LTS |
| 리전 | ap-northeast-2 |
| 네트워크 | Dual-stack (IPv4 + IPv6) |
| SSH 키 | k-stock-trading-key |
| 고정 IP | 43.200.235.74 |
| 자동 스냅샷 | 06:00 UTC |

### 2.2 서버 디렉토리 구조

```
/home/ubuntu/K_stock_trading/
|
+-- current/                  <- 심볼릭 링크 (현재 활성 버전)
|   +-- src/                     소스 코드
|   +-- venv/                    Python 3.11 가상환경
|   +-- launcher.py              프로덕션 런처
|   +-- requirements.txt         의존성
|   +-- VERSION                  버전 파일 (예: v2025.12.14.001)
|   +-- logs -> shared/logs/     심볼릭 링크
|   +-- data -> shared/data/     심볼릭 링크
|   +-- .env -> shared/.env      심볼릭 링크
|
+-- releases/                 <- 버전별 릴리스 (최대 5개 보관)
|   +-- v2025.12.14.001/
|   +-- v2025.12.14.002/
|   +-- ...
|
+-- shared/                   <- 버전 간 공유 (영속 저장소)
|   +-- logs/                    애플리케이션 로그
|   +-- data/                    트레이딩 데이터
|   +-- .env                     환경변수 (chmod 600)
|
+-- scripts/                  <- 서버 관리 스크립트
    +-- setup.sh                 서버 초기 세팅
    +-- install.sh               릴리스 설치 (venv 생성)
    +-- rollback.sh              버전 롤백
    +-- health-check.sh          헬스체크
    +-- cleanup.sh               오래된 릴리스 정리
```

### 2.3 systemd 서비스 설정

파일: `/etc/systemd/system/k-stock-trading.service`

```ini
[Unit]
Description=K-Stock Trading System
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu

WorkingDirectory=/home/ubuntu/K_stock_trading/current
Environment=PYTHONPATH=/home/ubuntu/K_stock_trading/current
EnvironmentFile=/home/ubuntu/K_stock_trading/shared/.env

ExecStart=/home/ubuntu/K_stock_trading/current/venv/bin/python \
          /home/ubuntu/K_stock_trading/current/launcher.py
ExecStop=/bin/kill -TERM $MAINPID

# 재시작 정책 (launcher.py 내부 백오프와 별도)
Restart=on-failure
RestartSec=10
StartLimitIntervalSec=3600
StartLimitBurst=5

# 타임아웃
TimeoutStartSec=30
TimeoutStopSec=30

# 로깅
StandardOutput=journal
StandardError=journal
SyslogIdentifier=k-stock-trading

# 리소스 제한
MemoryMax=1G
CPUQuota=80%

# 보안
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/home/ubuntu/K_stock_trading/shared/logs
ReadWritePaths=/home/ubuntu/K_stock_trading/shared/data
PrivateNetwork=false

[Install]
WantedBy=multi-user.target
```

### 2.4 서버 초기 세팅 (setup.sh)

```bash
#!/bin/bash
# 1. 시스템 업데이트
sudo apt update && sudo apt upgrade -y

# 2. Python 3.11 설치
sudo apt install -y software-properties-common
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3.11-dev
sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1

# 3. 필수 패키지
sudo apt install -y git curl wget htop unzip tree

# 4. 타임존 설정
sudo timedatectl set-timezone Asia/Seoul

# 5. 디렉토리 생성
mkdir -p ~/K_stock_trading/{releases,shared/{logs,data},scripts}
```

---

## 3. 배포 파이프라인

### 3.1 배포 흐름 개요

```
로컬 (Windows)                          서버 (Ubuntu)
+-------------------+     SCP/SSH      +-------------------+
| deploy.ps1        | ----------------> | install.sh        |
|  1. 문법 검증     |                   |  1. venv 생성     |
|  2. SSH 테스트    |                   |  2. pip install   |
|  3. 버전 생성     |                   |  3. 심볼릭 링크   |
|  4. SCP 전송      |                   +-------------------+
|  5. install 실행  |                            |
|  6. 심볼릭 스왑   |                   +--------v----------+
+-------------------+                   | systemctl restart |
                                        | k-stock-trading   |
                                        +-------------------+
```

### 3.2 버전 관리 형식

```
v{YYYY}.{MM}.{DD}.{SEQ}

예시:
  v2025.12.14.001  (12월 14일 첫 번째 릴리스)
  v2025.12.14.002  (같은 날 두 번째 릴리스)
```

- 최근 5개 버전 보관, 나머지 자동 삭제
- VERSION 파일에 현재 버전 기록

### 3.3 deploy.ps1 (버전 관리 배포)

6단계 배포 프로세스:

| 단계 | 작업 | 상세 |
|------|------|------|
| 1 | 로컬 검증 | `python -m py_compile src/main.py` |
| 2 | SSH 연결 테스트 | 서버 접근 가능 확인 |
| 3 | 버전 생성 | `v{YYYY.MM.DD}.{SEQ}` 자동 증가 |
| 4 | 파일 전송 | SCP: src/, launcher.py, requirements.txt |
| 5 | 서버 설치 | install.sh 실행 (venv, pip, symlinks) |
| 6 | 서비스 배포 | current 심볼릭 스왑 + systemctl restart |

실패 시 자동 롤백 (이전 버전으로 current 복원).

### 3.4 hotfix.ps1 (빠른 파일 업데이트)

| 항목 | deploy.ps1 | hotfix.ps1 |
|------|-----------|------------|
| 버전 변경 | O | X |
| venv 재생성 | O | X |
| 릴리스 디렉토리 | 새로 생성 | 기존 사용 |
| .env 전송 | X | O |
| 속도 | 느림 | 빠름 |
| 용도 | 정규 배포 | 운영 중 핫픽스 |

### 3.5 install.sh (릴리스 설치)

```bash
# 1. Python 3.11 가상환경 생성
python3.11 -m venv venv

# 2. 의존성 설치
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
deactivate

# 3. 심볼릭 링크 (공유 리소스)
ln -sf $SHARED_DIR/logs  $RELEASE_DIR/logs
ln -sf $SHARED_DIR/data  $RELEASE_DIR/data
ln -sf $SHARED_DIR/.env  $RELEASE_DIR/.env
```

### 3.6 rollback.sh (버전 복원)

```bash
# 이전 버전으로 롤백
./rollback.sh previous

# 특정 버전으로 롤백
./rollback.sh v2025.12.14.001
```

동작: systemctl stop -> current 심볼릭 변경 -> systemctl start

### 3.7 health-check.sh (4-포인트 헬스체크)

| 체크 | 방법 | 실패 조건 |
|------|------|----------|
| 서비스 상태 | `systemctl is-active` | 서비스 비활성 |
| 프로세스 | `pgrep -f launcher.py` | 프로세스 없음 |
| 최근 에러 | journalctl (2분 이내) | error/exception/critical 존재 |
| 버전 파일 | VERSION 파일 존재 | 파일 없음 |

### 3.8 cleanup.sh (주간 유지보수)

- 릴리스: 최근 5개 외 삭제 (current 보호)
- 로그: 7일 이상 된 로테이션 파일 삭제

---

## 4. 키움 REST API 인증 (OAuth2)

### 4.1 TokenManager 구조

```python
@dataclass
class TokenInfo:
    access_token: str
    token_type: str       # "bearer"
    expires_dt: datetime   # 토큰 만료 시각
    issued_at: datetime    # 토큰 발급 시각

    @property
    def is_expired(self) -> bool:
        return datetime.now() >= self.expires_dt

    @property
    def should_refresh(self) -> bool:
        return datetime.now() >= (self.expires_dt - timedelta(minutes=5))
```

### 4.2 토큰 발급

```
POST /oauth2/token
Content-Type: application/json;charset=UTF-8

{
    "grant_type": "client_credentials",
    "appkey": "{KIWOOM_APP_KEY}",
    "secretkey": "{KIWOOM_APP_SECRET}"
}

응답:
{
    "return_code": 0,
    "token": "eyJ...",
    "token_type": "bearer",
    "expires_dt": "20260225093000"    // YYYYMMDDHHMMSS
}
```

### 4.3 토큰 캐싱

| 항목 | 값 |
|------|-----|
| 캐시 파일 | `.token_cache.json` |
| 파일 권한 | chmod 600 |
| 저장 형식 | JSON (ISO 8601 datetime) |
| 수명 | 24시간 |
| 자동 갱신 | 만료 5분 전 |
| 백그라운드 갱신 | 60초 간격 체크 |

### 4.4 모의투자 vs 실거래

```python
# 자동 선택 로직
if settings.is_paper_trading:
    app_key = settings.paper_app_key
    app_secret = settings.paper_app_secret
    base_url = "https://mockapi.kiwoom.com"
else:
    app_key = settings.app_key
    app_secret = settings.app_secret
    base_url = "https://api.kiwoom.com"
```

---

## 5. HTTP 클라이언트 아키텍처

### 5.1 KiwoomAPIClient 구조

```
KiwoomAPIClient
  +-- TokenManager       OAuth2 토큰 관리
  +-- RateLimiter        Token Bucket 속도 제한
  +-- CircuitBreaker     장애 차단기
  +-- httpx.AsyncClient  비동기 HTTP 클라이언트
```

### 5.2 httpx 설정

```python
httpx.AsyncClient(
    base_url=self._base_url,
    timeout=httpx.Timeout(30.0, connect=10.0),
    headers={"Content-Type": "application/json;charset=UTF-8"}
)
```

### 5.3 인증 헤더

```python
headers = {
    "api-id": api_id,                  # 예: "kt00001", "ka10001"
    "authorization": f"Bearer {token}",
}
```

### 5.4 Rate Limiter (Token Bucket)

| 모드 | 속도 | 비고 |
|------|------|------|
| 실거래 | 4.5회/초 | 키움 제한: 5회/초 (여유분 확보) |
| 모의투자 | 0.33회/초 | 429 에러 방지 (3초 간격) |

```python
class RateLimiter:
    def __init__(self, calls_per_second: float):
        self._min_interval = 1.0 / calls_per_second
        self._last_call: float = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self):
        # min_interval 경과 후에만 호출 허용
```

### 5.5 Circuit Breaker

```
상태 전이:
  CLOSED ──(5연속 실패)──> OPEN ──(60초)──> HALF_OPEN
     ^                                         |
     |        (첫 요청 성공)                     |
     +─────────────────────────────────────────+
     |        (첫 요청 실패)                     |
     +──────────── OPEN <──────────────────────+
```

| 파라미터 | 값 |
|---------|-----|
| failure_threshold | 5 (연속 실패 임계) |
| recovery_timeout | 60초 (OPEN -> HALF_OPEN) |

### 5.6 재시도 전략 (tenacity)

```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((
        httpx.RequestError,
        httpx.HTTPStatusError,
        RateLimitError,
    )),
    reraise=True,
)
```

| 파라미터 | 값 |
|---------|-----|
| 최대 시도 | 3회 |
| 백오프 | 지수 (1초~10초) |
| 재시도 대상 | RequestError, HTTPStatusError, RateLimitError |

### 5.7 에러 핸들링

| 에러 | 처리 |
|------|------|
| HTTP 401 | 토큰 강제 무효화 + 갱신 + 재시도 |
| HTTP 429 | Retry-After 헤더 읽기 + sleep + RateLimitError |
| return_code 8005 | 토큰 무효 (401과 동일 처리) |

### 5.8 페이지네이션

```python
# 요청 헤더
headers = {
    "cont-yn": cont_yn,    # "Y" = 다음 페이지 있음
    "next-key": next_key,   # 다음 페이지 커서
}

# 응답 헤더에서 확인
has_next = response.headers.get("cont-yn") == "Y"
next_key = response.headers.get("next-key")

# 자동 페이지네이션
await client.paginate(url, api_id, body, max_pages=10)
```

### 5.9 API 응답 구조

```python
@dataclass
class APIResponse:
    success: bool
    data: Optional[dict] = None
    return_code: int = 0
    return_msg: str = ""
    has_next: bool = False
    next_key: Optional[str] = None
    api_id: str = ""
    raw_response: Optional[dict] = None
```

---

## 6. REST API 엔드포인트

### 6.1 기본 URL

| 구분 | URL |
|------|-----|
| 실거래 REST | `https://api.kiwoom.com` |
| 모의투자 REST | `https://mockapi.kiwoom.com` |

### 6.2 계좌 API

| API ID | 이름 | URL |
|--------|------|-----|
| kt00001 | 예수금상세현황 | `/api/dostk/acnt` |
| kt00004 | 계좌평가현황 | `/api/dostk/acnt` |
| ka10075 | 미체결주문 | `/api/dostk/acnt` |
| ka10076 | 체결정보 | `/api/dostk/acnt` |

**kt00001 - 예수금 조회:**

```python
# 요청
body = {"qry_tp": "3"}  # "3"=추정, "2"=실제

# 응답 -> Balance
Balance(
    deposit=int(data["entr"]),             # 예수금
    available_amount=int(data["ord_alow_amt"]),  # 주문가능금액
    d2_estimated_deposit=int(data["d2_entra"]),  # D+2 추정예수금
    withdrawal_amount=int(data["pymn_alow_amt"]) # 출금가능금액
)
```

**kt00004 - 보유종목 조회:**

```python
# 요청
body = {
    "qry_tp": "1",           # "1"=상장폐지 제외
    "dmst_stex_tp": "KRX",   # "KRX", "NXT", 또는 "" (양쪽 모두)
}

# 응답 배열 -> Position[]
Position(
    stock_code=item["stk_cd"],       # "A" 접두사 제거
    stock_name=item["stk_nm"],
    quantity=int(item["rmnd_qty"]),   # 잔여수량
    average_price=int(item["avg_prc"]),
    current_price=abs(int(item["cur_prc"])),
    eval_amount=int(item["evlt_amt"]),
    profit_loss=int(item["pl_amt"]),
    profit_loss_rate=float(item["pl_rt"]),
    purchase_amount=int(item["pur_amt"]),
)
```

### 6.3 주문 API

| API ID | 이름 | URL |
|--------|------|-----|
| kt10000 | 매수주문 | `/api/dostk/ordr` |
| kt10001 | 매도주문 | `/api/dostk/ordr` |
| kt10002 | 정정주문 | `/api/dostk/ordr` |
| kt10003 | 취소주문 | `/api/dostk/ordr` |

**주문 유형 (OrderType):**

| 값 | 이름 | 설명 |
|----|------|------|
| "0" | LIMIT | 지정가 |
| "3" | MARKET | 시장가 |
| "5" | CONDITIONAL | 조건부지정가 |
| "6" | BEST_LIMIT | 최유리지정가 |
| "7" | FIRST_LIMIT | 최우선지정가 |
| "10" | LIMIT_IOC | 지정가 IOC |
| "13" | MARKET_IOC | 시장가 IOC |
| "20" | LIMIT_FOK | 지정가 FOK |
| "23" | MARKET_FOK | 시장가 FOK |
| "61" | PRE_MARKET | 장시작전시간외 |
| "62" | AFTER_HOURS | 시간외단일가 |
| "81" | POST_MARKET | 장마감후시간외 |

**거래소 (Exchange):**

| 값 | 이름 |
|----|------|
| "KRX" | 한국거래소 |
| "NXT" | 넥스트트레이드 |
| "SOR" | Smart Order Routing |

**매수 요청 (kt10000):**

```python
body = {
    "dmst_stex_tp": "KRX",       # 거래소
    "stk_cd": "005930",           # 종목코드 (6자리)
    "ord_qty": "10",              # 주문수량 (문자열)
    "ord_uv": "",                 # 주문가격 (시장가=빈값)
    "trde_tp": "3",               # 주문유형 (시장가)
    "cond_uv": "",                # 조건가격
    "crd_tp": "00",               # 신용구분 (00=현금)
}

# 응답
OrderResult(
    success=True,
    order_no=response.data["ord_no"],
    exchange=response.data["dmst_stex_tp"],
    message=response.return_msg,
)
```

**체결 대기 (polling):**

```python
await account_api.wait_for_execution(
    order_no="12345",
    max_wait_seconds=5.0,     # 시장가 보통 0.5~2초 체결
    poll_interval=0.5,
)
```

### 6.4 시세 API

| API ID | 이름 | URL |
|--------|------|-----|
| ka10001 | 주식기본정보 | `/api/dostk/stkinfo` |
| ka10004 | 주식호가 | `/api/dostk/stkinfo` |
| ka10005 | 일주월시분 차트 | `/api/dostk/mrkcond` |
| ka10032 | 거래대금상위 | `/api/dostk/mrkcond` |
| ka10080 | 분봉 차트 | `/api/dostk/mrkcond` |
| ka10081 | 일봉 차트 | `/api/dostk/mrkcond` |
| ka20001 | 업종현재가 | `/api/dostk/mrkcond` |

**ka10080 - 분봉 차트:**

```python
body = {
    "stk_cd": "005930",
    "tic_scope": "3",            # 1분, 3분, 5분, 10분, 15분, 30분, 60분
    "upd_stkpc_tp": "0",         # 0=수정주가 미적용
}

# 응답: stk_min_pole_chart_qry 배열
MinuteCandle(
    timestamp=datetime.strptime(item["cntr_tm"], "%Y%m%d%H%M%S"),
    open_price=int(item["open_prc"]),
    high_price=int(item["high_prc"]),
    low_price=int(item["low_prc"]),
    close_price=int(item["cur_prc"]),
    volume=int(item["volume"]),
)

# 페이지네이션으로 최대 ~1000개 캔들 조회
all_data = await client.paginate(url, "ka10080", body, max_pages=10)
```

**ka10081 - 일봉 차트:**

```python
body = {
    "stk_cd": "005930",
    "base_dt": "20260224",       # 기준일자 (YYYYMMDD)
    "upd_stkpc_tp": "0",
}

# 등락률 계산 주의:
# trde_tern_rt 필드는 신규상장 종목에서 신뢰 불가
# pred_pre (전일대비) 사용하여 직접 계산:
prev_close = close_price - pred_pre
change_rate = (pred_pre / prev_close) * 100 if prev_close > 0 else 0
```

### 6.5 종목코드 정규화

```python
# 키움 API는 "A" 접두사 포함 코드 반환 (예: "A005930")
# 정규화: 첫 글자 "A"만 제거 (NXT 종목 중간 A 보존)
stock_code = raw_code[1:] if raw_code.startswith("A") else raw_code
```

### 6.6 가격 부호 처리

```python
# 키움 API가 음수 가격 반환하는 경우 있음
current_price = abs(int(data.get("cur_prc", 0)))
```

---

## 7. WebSocket 실시간 연결

### 7.1 연결 정보

| 항목 | 값 |
|------|-----|
| 실거래 URL | `wss://api.kiwoom.com:10000/api/dostk/websocket` |
| 모의투자 URL | `wss://mockapi.kiwoom.com:10000/api/dostk/websocket` |
| ping_interval | None (키움 자체 PING 사용) |
| ping_timeout | None |

### 7.2 메시지 타입

| trnm | 용도 | 방향 |
|------|------|------|
| LOGIN | 토큰 인증 | Client -> Server |
| PING | 연결 유지 | 양방향 |
| CNSRLST | 조건식 목록 조회 | Client -> Server |
| CNSRREQ | 조건검색 (1회/실시간) | Client -> Server |
| CNSRCLR | 실시간 조건검색 해제 | Client -> Server |
| REAL | 실시간 데이터 (틱, 조건신호) | Server -> Client |
| REG | 실시간 시세 등록 | Client -> Server |
| UNREG | 실시간 시세 해제 | Client -> Server |

### 7.3 인증 흐름

```json
// 1. LOGIN 요청
{"trnm": "LOGIN", "token": "Bearer_token_here"}

// 2. LOGIN 응답
{"trnm": "LOGIN", "return_code": 0, "return_msg": "OK"}
```

### 7.4 실시간 데이터 (REAL)

**틱 데이터:**

```json
{
    "trnm": "REAL",
    "data": [{
        "type": "S3_",
        "values": {
            "9001": "A005930",     // 종목코드
            "9002": "삼성전자",     // 종목명
            "20": "093015",         // 체결시각 (HHMMSS)
            "10": "70000",          // 현재가
            "11": "500",            // 전일대비
            "12": "0.71",           // 등락률
            "15": "1000",           // 체결량
            "13": "5000000",        // 누적거래량
            "14": "350000000000"    // 누적거래대금
        }
    }]
}
```

**조건검색 신호:**

```json
{
    "data": [{
        "trnm": "REAL",
        "type": "0A",
        "values": {
            "9001": "A005930",     // 종목코드
            "302": "삼성전자",      // 종목명
            "843": "I",             // "I"=편입(매수), "D"=이탈(매도)
            "841": "0",             // 조건식 번호
            "20": "093015"          // 시각
        }
    }]
}
```

### 7.5 3계층 Heartbeat 전략

```
계층 1: TCP Keepalive (AWS NAT 350초 대응)
  - TCP_KEEPIDLE = 60초
  - TCP_KEEPINTVL = 10초
  - TCP_KEEPCNT = 6
  - 총 타임아웃: 60 + (10 * 6) = 120초

계층 2: 애플리케이션 Heartbeat (좀비 연결 감지)
  - 간격: 60초
  - 방식: CNSRLST 요청 전송
  - 타임아웃: 30초
  - 실패 임계: 3회 (장 시작 09:00~09:30은 5회)

계층 3: 클라이언트 PING (서버 유휴 방지)
  - 간격: 20초
  - 방식: {"trnm": "PING"} 전송
```

### 7.6 재연결 전략

**Phase 1 - 빠른 재연결 (단기 장애):**

| 시도 | 대기 |
|------|------|
| 1 | 2.0초 |
| 2 | 3.0초 |
| 3 | 4.5초 |
| 4 | 6.75초 |
| 5 | 10.125초 |

(지수 백오프: base 2.0초, multiplier 1.5)

**Phase 2 - 느린 재연결 (서버 점검):**

- 간격: 300초 (5분)
- 시도: 무한
- 종료: 연결 성공 또는 종료 시그널

**재연결 시퀀스:**

```
1. 연결 끊김 감지
2. _active_conditions 초기화 (구독 상태 리셋)
3. _subscribed_stocks는 보존 (틱 재구독용)
4. 10초 대기 (서버 세션 정리)
5. 토큰 강제 갱신 (invalidate_and_refresh)
6. Phase 1 시도 (5회)
7. 실패 시 Phase 2 진입 (무한 반복)
8. 성공 시: 틱 재구독 + on_reconnected 콜백
```

### 7.7 장 시작 시 특별 처리

```python
# 09:00~09:05: 하트비트 건너뜀 (서버 과부하)
# 09:00~09:30: 하트비트 실패 임계 = 5 (평소 3)
```

---

## 8. 조건검색식 구독

### 8.1 SubscriptionManager 상태 머신

```
IDLE (초기)
  |
  v
SUBSCRIBING (구독 시도 중, 재시도 진행)
  +---> SUBSCRIBED (성공, return_code=0)
  |       +---> VERIFYING (재연결 후 좀비 체크)
  |       |       +---> SUBSCRIBED (정상)
  |       |       +---> SUB_FAILED (좀비 감지)
  |       +---> (신호 미수신 10분: 로그만, 재구독 안 함)
  |
  +---> SUB_FAILED (5회 재시도 소진)
          +---> SUB_SUSPENDED (2연속 실패 -> 서킷 브레이커)
          |       +---> (30분 후 복구 시도)
          +---> (AUTO_UNIVERSE만 폴링 폴백 활성화)
```

### 8.2 구독 재시도

| 파라미터 | 값 |
|---------|-----|
| MAX_RETRY_COUNT | 5 |
| BASE_RETRY_DELAY | 1.0초 |
| MAX_RETRY_DELAY | 30.0초 |
| 백오프 | `min(1.0 * 2^(n-1), 30.0) + jitter(+-20%)` |

### 8.3 서킷 브레이커

| 파라미터 | 값 |
|---------|-----|
| CIRCUIT_BREAK_THRESHOLD | 2 (연속 SUB_FAILED) |
| CIRCUIT_BREAK_DURATION | 1800초 (30분) |

### 8.4 조건검색 시작 시퀀스

```
1. WebSocket 연결 확인
2. 사전 해제 (CNSRCLR) + 2초 대기 (서버 캐시 방지)
3. _cnsrreq_lock 획득
4. _expected_cnsrreq_seq 설정 (레이스 컨디션 방지)
5. CNSRREQ 메시지 전송
6. 응답 대기 (타임아웃 30초)
7. return_code == 0 확인
8. _active_conditions에 추가
```

### 8.5 좀비 구독 탐지

재연결 후 30초 대기 -> 폴링으로 조건식 결과 확인:
- 폴링 결과 있는데 실시간 신호 없음 -> 좀비 감지
- 최대 2회 재구독 시도
- 실패 시 SUB_FAILED + 폴링 폴백

### 8.6 폴링 폴백 모드

| 파라미터 | 값 |
|---------|-----|
| POLLING_INTERVAL | 30초 |
| 대상 | AUTO_UNIVERSE만 (ATR_ALERT 제외) |
| 종료 | 실시간 구독 성공 시 자동 종료 |

### 8.7 구독 목적

| 모드 | 설명 | 폴링 폴백 |
|------|------|----------|
| AUTO_UNIVERSE | 자동 종목 탐지 | O |
| ATR_ALERT | ATR 알림 | X |

---

## 9. 애플리케이션 런처

### 9.1 launcher.py 개요

systemd가 실행하는 프로덕션 래퍼. src.main을 감싸며:
- 6단계 사전점검
- 지수 백오프 자동재시작
- 시그널 핸들링
- 텔레그램 알림

### 9.2 사전점검 (6단계)

| 단계 | 체크 | 실패 시 |
|------|------|---------|
| 1 | Python 버전 >= 3.10 | 종료 (exit 1) |
| 2 | 필수 환경변수 4개 | 종료 |
| 3 | 필수 패키지 5개 | 종료 |
| 4 | 디렉토리 구조 (src/, src/main.py) | 종료 |
| 5 | 키움 API 토큰 발급 | 종료 |
| 6 | DB 연결 (PostgreSQL 또는 SQLite) | 종료 |

**필수 환경변수:** KIWOOM_APP_KEY, KIWOOM_APP_SECRET, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

**필수 패키지:** httpx, websockets, pydantic, sqlalchemy, structlog

### 9.3 지수 백오프 자동재시작

```
설정:
  INITIAL_BACKOFF = 5초
  MAX_BACKOFF = 300초 (5분)
  BACKOFF_MULTIPLIER = 2
  MAX_RESTARTS_PER_HOUR = 5
  STABLE_THRESHOLD = 600초 (10분)

흐름:
  시도 1: 실패 -> 5초 대기 -> 재시작
  시도 2: 실패 -> 10초 대기 -> 재시작
  시도 3: 실패 -> 20초 대기 -> 재시작
  ...
  (최대 대기: 5분)

  10분 이상 안정 실행: 백오프 5초로 리셋
  1시간 내 5회 재시작: 완전 종료 (exit 1)
```

### 9.4 시그널 핸들링

```python
# Windows
signal.signal(signal.SIGINT, lambda s, f: signal_handler())

# Linux (서버)
loop.add_signal_handler(signal.SIGTERM, signal_handler)
loop.add_signal_handler(signal.SIGINT, signal_handler)
```

### 9.5 텔레그램 알림

| 이벤트 | 내용 |
|--------|------|
| 시작 성공 | 버전, 점검 결과, 타임스탬프 |
| 정상 종료 | 종료 사유, 총 실행시간 |
| 재시작 시도 | 시도 횟수, 에러 설명, 대기시간 |
| 치명적 실패 | 최근 5개 에러, 수동 개입 필요 |

### 9.6 런처 로깅

| 항목 | 값 |
|------|-----|
| 파일 | launcher.log |
| 로테이션 | 50MB |
| 보관 | 7개 파일 |

### 9.7 JuDoJuSniper (메인 클래스) 초기화 순서

```
launcher.py 사전점검 통과
  |
  v
JuDoJuSniper.initialize()
  1. Database (init_database)
  2. KiwoomAPIClient (async context)
  3. KiwoomWebSocket
  4. TelegramBot (+ 명령어 등록)
  5. TradingEngine (EngineConfig, RiskConfig, UniverseConfig)
  |
  v
JuDoJuSniper.run()
  1. Telegram polling 시작
  2. while _running: sleep(1) 메인루프
  |
  v
JuDoJuSniper.shutdown()
  1. TradingEngine stop
  2. WebSocket disconnect
  3. Telegram stop_polling
  4. API client close
  5. Database close
```

### 9.8 텔레그램 명령어

| 분류 | 명령어 | 설명 |
|------|--------|------|
| 상태 | /status | 시스템 상태 |
| 상태 | /balance | 잔고 & 보유종목 |
| 상태 | /positions | 포지션 동기화 확인 |
| 상태 | /health | 시스템 헬스 리포트 |
| 상태 | /help | 도움말 |
| 제어 | /start | 거래 시작 |
| 제어 | /stop | 거래 정지 |
| 제어 | /pause | 일시 정지 |
| 제어 | /resume | 거래 재개 |
| 매매 | /buy {코드} {금액} | 수동 매수 |
| 매매 | /sell {코드} {수량} | 수동 매도 |
| 설정 | /ratio [%] | 매수 비율 조회/변경 |
| 설정 | /ignore {코드} | 종목 관리 제외 |
| 설정 | /unignore {코드} | 종목 관리 재개 |
| WS | /substatus | 조건검색 구독 상태 |
| WS | /subscribe | 수동 재구독 |
| WS | /wsdiag | WebSocket 진단 |

---

## 10. 데이터베이스 구성

### 10.1 이중 DB 아키텍처

```
DATABASE_URL 설정됨?
  |
  +-- Yes -> Supabase PostgreSQL (async psycopg3)
  |            Pool: 5 + 10 overflow
  |            PgBouncer 호환
  |
  +-- No  -> SQLite (aiosqlite)
               파일: data/k_stock_trading.db
```

### 10.2 PostgreSQL 연결 풀

| 파라미터 | 값 |
|---------|-----|
| pool_size | 5 |
| max_overflow | 10 (최대 15 동시 연결) |
| pool_timeout | 30초 |
| pool_recycle | 1800초 (30분) |
| isolation_level | REPEATABLE READ |
| prepare_threshold | None (PgBouncer 호환) |

### 10.3 SQLAlchemy 2.0+ async ORM

```python
# 비동기 엔진 생성
engine = create_async_engine(
    url,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800,
    isolation_level="REPEATABLE READ",
)

# 세션 팩토리
async_session = async_sessionmaker(engine, expire_on_commit=False)

# 사용
async with db.session() as session:
    result = await session.execute(select(Trade).where(...))
```

### 10.4 데이터 모델

**Trade (거래)**

| 필드 | 타입 | 설명 |
|------|------|------|
| id | Integer PK | 자동 증가 |
| stock_code | String(10) | 종목코드 (인덱스) |
| stock_name | String(100) | 종목명 |
| strategy | String(50) | 전략명 |
| entry_source | VARCHAR | MANUAL, SYSTEM, HTS, RESTORED |
| entry_price | Integer | 진입가 |
| entry_quantity | Integer | 진입수량 |
| entry_amount | BigInteger | 진입금액 |
| entry_time | DateTime | 진입시각 (인덱스) |
| exit_price | Integer (nullable) | 청산가 |
| exit_time | DateTime (nullable) | 청산시각 |
| exit_reason | String(100) | HARD_STOP, TRAILING_STOP, MANUAL |
| profit_loss | Integer | 손익금액 (원) |
| profit_loss_rate | Float | 손익률 (%) |
| status | VARCHAR | OPEN, CLOSED, CANCELLED (인덱스) |
| is_partial_exit | Boolean | 부분 청산 여부 |

**Order (주문)**

| 필드 | 타입 | 설명 |
|------|------|------|
| id | Integer PK | 자동 증가 |
| trade_id | Integer FK | Trade 참조 |
| stock_code | String(10) | 종목코드 |
| side | VARCHAR | BUY, SELL |
| order_type | String(20) | MARKET, LIMIT |
| quantity | Integer | 주문수량 |
| filled_quantity | Integer | 체결수량 |
| filled_price | Integer | 체결가 |
| order_no | String(50) | 주문번호 (인덱스) |
| status | VARCHAR | PENDING -> SUBMITTED -> FILLED |

**DailyStats (일일 통계)**

| 필드 | 타입 | 설명 |
|------|------|------|
| date | Date (unique) | 거래일 |
| trade_count | Integer | 거래 횟수 |
| win_count | Integer | 승리 횟수 |
| net_pnl | BigInteger | 순손익 |
| win_rate | Float | 승률 (%) |

**Signal (신호 기록)**

| 필드 | 타입 | 설명 |
|------|------|------|
| stock_code | String(10) | 종목코드 |
| strategy | String(50) | 전략명 |
| signal_type | String(20) | BUY, SELL |
| price | Integer | 신호 발생 가격 |
| executed | Boolean | 실행 여부 |
| blocked_reason | String(100) | 차단 사유 |

### 10.5 Repository 패턴

```python
# 이중 매수 방지
async def create_trade(stock_code, ...):
    existing = await session.execute(
        select(Trade).where(
            Trade.stock_code == stock_code,
            Trade.status == "OPEN"
        )
    )
    if existing.scalar():
        raise DuplicateTradeError()

# 이중 청산 방지 (SELECT FOR UPDATE)
async def close_trade(trade_id, ...):
    trade = await session.execute(
        select(Trade).where(Trade.id == trade_id).with_for_update()
    )

# 원자적 트랜잭션
async with atomic_session() as session:
    trade = await trade_repo.create(..., session=session)
    order = await order_repo.create(trade_id=trade.id, ..., session=session)
    # 둘 다 성공 또는 둘 다 롤백
```

---

## 11. 환경변수 관리

### 11.1 .env 파일 규칙

**서버 위치:** `/home/ubuntu/K_stock_trading/shared/.env`
**권한:** `chmod 600` (소유자만 읽기/쓰기)

**인라인 주석 금지:**

```bash
# 잘못된 예 (systemd가 주석을 값으로 해석)
SNIPER_TRAP_ENABLED=false  # V6 비활성화

# 올바른 예
# V6 비활성화
SNIPER_TRAP_ENABLED=false
```

### 11.2 Pydantic Settings 로딩 순서

```
1. get_config() (LRU 캐시 싱글톤)
2. 각 Settings 클래스 lazy-load (첫 접근 시)
3. .env 파일 읽기 (SettingsConfigDict)
4. Validator 실행 (예: safety_stop_rate 음수 보장)
```

### 11.3 systemd EnvironmentFile vs python-dotenv

| 항목 | python-dotenv | systemd EnvironmentFile |
|------|--------------|----------------------|
| 인라인 주석 | `#` 이후 무시 | 값의 일부로 해석 |
| 따옴표 | 제거 | 값의 일부로 유지 가능 |
| 빈 줄 | 무시 | 무시 |

두 시스템 모두 호환되려면 **인라인 주석 금지**, **별도 줄 주석** 사용.

### 11.4 필수 환경변수

```bash
# === 투자 모드 ===
ENVIRONMENT=production          # production | development
IS_PAPER_TRADING=false          # false=실전, true=모의

# === 키움증권 API ===
KIWOOM_APP_KEY=PSxxxxxxxx       # 실전 앱키
KIWOOM_APP_SECRET=xxxxxxxx      # 실전 시크릿
KIWOOM_PAPER_APP_KEY=xxx        # 모의 앱키 (모의 시 필수)
KIWOOM_PAPER_APP_SECRET=xxx     # 모의 시크릿

# === 텔레그램 ===
TELEGRAM_BOT_TOKEN=123:ABC...   # BotFather에서 발급
TELEGRAM_CHAT_ID=987654321      # 알림 수신 채팅 ID

# === 데이터베이스 ===
# Supabase (권장)
DATABASE_URL=postgresql://user:pass@db.supabase.co:5432/postgres
# 미설정 시 SQLite 자동 사용

# === 리스크 관리 ===
MAX_POSITIONS=10                # 최대 동시 포지션
BUY_AMOUNT_RATIO=0.15           # 매수 비율 (15%)
SAFETY_STOP_RATE=-4.0           # 고정 손절 (-4%)
DAILY_MAX_LOSS=500000           # 일일 최대 손실 (원)

# === 전략 ===
CONDITION_SEQS=0,1              # 조건검색식 번호
TRADING_MODE=AUTO_UNIVERSE      # MANUAL_ONLY, AUTO_UNIVERSE, SIGNAL_ALERT
V7_PURPLE_ENABLED=true          # V7 Purple-ReAbs 활성화

# === 시간 ===
MARKET_OPEN_TIME=09:00
SIGNAL_START_TIME=09:00
SIGNAL_END_TIME=15:20

# === 로깅 ===
LOG_LEVEL=INFO                  # DEBUG, INFO, WARNING, ERROR
LOG_FORMAT=json                 # json, console
```

### 11.5 API URL 자동 결정

```python
# Settings 클래스 property
@property
def api_host(self) -> str:
    if self.is_paper_trading:
        return "https://mockapi.kiwoom.com"
    return "https://api.kiwoom.com"

@property
def websocket_url(self) -> str:
    if self.is_paper_trading:
        return "wss://mockapi.kiwoom.com:10000"
    return "wss://api.kiwoom.com:10000"
```

---

## 12. 모니터링 & 로깅

### 12.1 structlog 구조화 로깅

**프로세서 파이프라인:**

```
1. merge_contextvars          (비동기 컨텍스트 병합)
2. add_log_level              (레벨 추가)
3. add_logger_name            (로거 이름 추가)
4. PositionalArgumentsFormatter
5. kst_timestamper            (KST 타임스탬프)
6. StackInfoRenderer
7. UnicodeDecoder
8. add_app_context            (environment, is_paper_trading)
9. JSONRenderer               (프로덕션) 또는 ConsoleRenderer (개발)
```

**JSON 로그 형식:**

```json
{
    "timestamp": "2026-02-24 15:30:45 KST",
    "event": "신호 발생",
    "level": "INFO",
    "logger": "src.core.signal_detector",
    "environment": "production",
    "is_paper_trading": false,
    "stock_code": "005930",
    "correlation_id": "005930_20260224_42"
}
```

**서드파티 로그 억제:**

```python
# httpx, httpcore, websockets, asyncio -> WARNING 레벨로 설정
```

### 12.2 로그 로테이션

| 로그 | 크기 | 보관 |
|------|------|------|
| launcher.log | 50MB 로테이션 | 7개 파일 |
| systemd journal | 시스템 설정 | journalctl 접근 |
| shared/logs/ | 일별 로테이션 | 7일 보관 |

### 12.3 텔레그램 알림 (Circuit Breaker)

```
설정:
  CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5    (연속 실패 임계)
  CIRCUIT_BREAKER_TIMEOUT_SECONDS = 300    (5분 차단)

상태 전이:
  CLOSED -> (5연속 실패) -> OPEN -> (5분) -> HALF_OPEN
    ^                                          |
    +---- (성공) <-----------------------------+
    |     (실패) -> OPEN                       |
    +------------------------------------------+

실패 시:
  - 메모리 큐 (최대 50개)
  - 파일 백업 (logs/failed_alerts.log)
  - 복구 후 최대 3개 재전송
```

**메시지 제약:**

| 규칙 | 값 |
|------|-----|
| parse_mode | 사용 금지 (plain text만) |
| 최대 길이 | 4000자 |
| 전송 시도 | 2회 (2초 간격) |
| 전송 타임아웃 | 10초 |

### 12.4 NotificationQueue

| 파라미터 | 값 |
|---------|-----|
| 큐 크기 | 100 (초과 시 가장 오래된 항목 삭제) |
| 재시도 | 3회 (1초 -> 2초 -> 4초 백오프) |
| 종목별 쿨다운 | 300초 (5분) |
| 우선순위 | 0=긴급(선입), 1=일반(FIFO) |
| 처리 간격 | 0.5초 |

**동기화 모델 (C-002 패턴):**

```python
# 2중 Lock으로 deque 보호
async with self._async_lock:       # 비동기 락 (이벤트 루프 보호)
    with self._lock:                # 동기 락 (enqueue 호환)
        item = self._queue.popleft()
```

### 12.5 SystemHealthMonitor

| 파라미터 | 값 |
|---------|-----|
| 체크 간격 | 60초 |
| 일일 리포트 | 15:30 |
| 리포트 리셋 | 09:00 |

**헬스 체크 항목:**

| 체크 | 이상 조건 | 심각도 |
|------|----------|--------|
| 알림 큐 | send_func_none_count > 0 | CRITICAL |
| 알림 큐 | dropped_count > 0 | WARNING |
| 알림 큐 | consecutive_failures >= 3 | WARNING |
| 텔레그램 CB | circuit_breaker.is_open | CRITICAL |
| V7 코디네이터 | dual_pass_task_active == False | CRITICAL |
| V7 코디네이터 | notification_task_active == False | CRITICAL |

**일일 리포트 (15:30) 내용:**

- 알림 큐 통계 (성공, 실패, 삭제)
- 텔레그램 CB 통계 (당일 오픈 횟수)
- 신호 처리기 통계 (처리, 알림, 만료)
- 청산 코디네이터 통계 (총 청산)
- 헬스 모니터 통계 (체크 횟수, 알림 발송)
- 최근 이슈 (마지막 5건)

### 12.6 장 시간 규칙

| 상태 | 시간 | 설명 |
|------|------|------|
| CLOSED | ~08:00 | 장 전 |
| NXT_PRE_MARKET | 08:00~08:50 | NXT 프리마켓 |
| PRE_MARKET | 08:50~09:00 | 동시호가 |
| OPEN | 09:00~15:20 | 정규장 |
| KRX_CLOSING | 15:20~15:30 | KRX 단일가 (NXT 중단) |
| NXT_AFTER | 15:30~20:00 | NXT 애프터마켓 |
| AFTER_HOURS | 20:00~ | 장 후 |

**거래 허용:**

| 구분 | 시간 | 대상 |
|------|------|------|
| 신호 탐지 | 09:05~15:20 | 매수 신호 |
| 정규장 매매 | 09:00~15:20 | 매수/매도 |
| NXT 청산 | 08:00~20:00 | 매도(청산)만 |

---

## 부록: 핵심 상수 요약

| 카테고리 | 상수 | 값 |
|---------|------|-----|
| **API** | 실거래 Rate Limit | 4.5회/초 |
| **API** | 모의투자 Rate Limit | 0.33회/초 |
| **API** | HTTP 타임아웃 | 30초 (connect: 10초) |
| **API** | 재시도 | 3회, 지수 백오프 1~10초 |
| **API** | Circuit Breaker | 5연속 실패 -> 60초 차단 |
| **토큰** | 수명 | 24시간 |
| **토큰** | 갱신 | 만료 5분 전 |
| **토큰** | 캐시 파일 | .token_cache.json |
| **WebSocket** | TCP Keepalive | 60/10/6 (idle/interval/count) |
| **WebSocket** | App Heartbeat | 60초 간격, 30초 타임아웃 |
| **WebSocket** | Client PING | 20초 간격 |
| **WebSocket** | 빠른 재연결 | 5회, 2~10초 백오프 |
| **WebSocket** | 느린 재연결 | 무한, 5분 간격 |
| **구독** | 재시도 | 5회, 1~30초 백오프 |
| **구독** | 서킷 브레이커 | 2연속 실패 -> 30분 차단 |
| **구독** | 폴링 폴백 | 30초 간격 |
| **DB** | Pool | 5 + 10 overflow |
| **DB** | Recycle | 1800초 (30분) |
| **DB** | Isolation | REPEATABLE READ |
| **텔레그램** | CB 임계 | 5연속 실패 |
| **텔레그램** | CB 타임아웃 | 300초 (5분) |
| **알림 큐** | 크기 | 100 |
| **알림 큐** | 재시도 | 3회, 1->2->4초 |
| **알림 큐** | 쿨다운 | 300초 (5분) |
| **런처** | 초기 백오프 | 5초 |
| **런처** | 최대 백오프 | 300초 |
| **런처** | 시간당 최대 재시작 | 5회 |
| **런처** | 안정 판정 | 600초 (10분) |
| **헬스 모니터** | 체크 간격 | 60초 |
| **헬스 모니터** | 일일 리포트 | 15:30 |
