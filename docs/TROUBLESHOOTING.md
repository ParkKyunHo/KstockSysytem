# TROUBLESHOOTING

> K_stock_trading 장애 대응 가이드

---

## 장애 유형별 대응

| 장애 유형 | 감지 | 대응 |
|----------|------|------|
| 네트워크 오류 | HTTP 타임아웃 | 지수 백오프 재시도 (3회) |
| 토큰 만료 | 401 응답 | 즉시 재발급 |
| Rate Limit | 429 응답 | 큐잉 + 대기 |
| DB 장애 | 연결 오류 | SQLite 폴백 |
| 서버 크래시 | systemd | 자동 재시작 + 상태 복구 |
| 손실 한도 | RiskManager | 당일 거래 중단 + 알림 |
| WebSocket 끊김 | ConnectionClosed | 자동 재연결 (최대 5회) |

---

## 리스크 관리 이벤트

| 이벤트 | 조건 | 대응 |
|--------|------|------|
| Floor Line 이탈 | `current_price < stop_loss_price` | 기술적 손절 청산 |
| Safety Net | `-3.5%` 손실 | 강제 청산 |
| 분할 익절 | `+3%` 수익 | 50% 매도 + 본전컷 |
| VI 발동 | 키움 VI 신호 | 60초 쿨다운 |
| VI 타임아웃 | 5분 경과 | 자동 해제 |
| 시장 급락 | KOSDAQ 3분 -0.8% | Global_Lock 5분 |
| 장전 데이터 | 08:30~09:00 | 예상 체결가 무시 |
| 장 시작 갭 | 09:00 | 갭 손절/익절 즉시 처리 |

---

## VI 발동 시 매도 로직

| 매도 로직 | VI 발동 시 | 비고 |
|----------|-----------|------|
| 분할 익절 | **작동** | 이미 익절 구간 |
| Safety Lock | 정지 | VI 해제 후 재평가 |
| Crash Guard | 정지 | VI 해제 후 재평가 |
| 3분봉 EMA20 이탈 | 정지 | VI 해제 후 재평가 |
| 기술적 손절 | 정지 | VI 해제 후 재평가 |
| Safety Net (-3.5%) | **작동** | 최후의 보루 |
| 수동 청산 | **작동** | 사용자 의지 존중 |

---

## 과거 버그 및 수정

### 2025-12-17: 텔레그램 409 Conflict / 명령어 중복 응답

**증상:**
- `/help`, `/status` 등 명령어가 두 번 응답됨
- 서버 로그에 `409 Conflict` 에러 반복

**원인:**
- `test_server.ps1` 스크립트가 SSH로 서버에서 `python -m src.main` 실행
- 로컬 Claude 백그라운드 태스크를 종료해도 **서버의 Python 프로세스는 살아있음**
- systemd 서비스 + 고아 프로세스 = 2개가 동시에 텔레그램 폴링 → 409 Conflict

**진단:**
```powershell
# 서버 Python 프로세스 확인
powershell -ExecutionPolicy Bypass -File "scripts\deploy\check_processes.ps1"

# systemd 서비스 외에 아래와 같은 프로세스가 있으면 고아 프로세스
# ubuntu  32232  python -m src.main
```

**해결:**
```powershell
# 1. 서비스 중지
powershell -ExecutionPolicy Bypass -File "scripts\deploy\stop_service.ps1"

# 2. 고아 프로세스 확인 및 종료
powershell -ExecutionPolicy Bypass -File "scripts\deploy\check_processes.ps1"
powershell -ExecutionPolicy Bypass -File "scripts\deploy\kill_orphan.ps1"

# 3. 서비스 재시작
powershell -ExecutionPolicy Bypass -File "scripts\deploy\start_service.ps1"
```

**예방:**
- `test_server.ps1` 실행 후 반드시 서버 프로세스 확인
- Claude 백그라운드 태스크 종료 시 서버도 확인
- SSH로 실행한 프로세스는 로컬 종료와 무관하게 서버에서 계속 실행됨

---

### 2025-12-15: Safety Lock/Crash Guard `_indicator` 에러
- **파일**: `src/core/trading_engine.py:1737,2048,2104,2195`
- **에러**: `'SignalDetector' object has no attribute '_indicator'`
- **원인**: `Indicator` 클래스는 정적 메서드만 가진 유틸리티 클래스인데, 인스턴스 속성처럼 접근 시도
- **수정**: `Indicator.ema()` 정적 메서드로 직접 호출
```python
# Before (잘못됨):
ema20 = self._signal_detector._indicator.ema(closes, period)

# After (올바름):
ema20 = Indicator.ema(candles['close'], period).iloc[-1]
```

### 2025-12-15: DB entry_source 컬럼 누락
- **에러**: `column trades.entry_source does not exist`
- **원인**: SQLAlchemy `create_all()`은 기존 테이블에 새 컬럼을 추가하지 않음
- **수정**: 서버에서 직접 `ALTER TABLE` 실행
```bash
# 서버에서 마이그레이션 스크립트 실행
powershell -ExecutionPolicy Bypass -File "scripts\deploy\check_db_server.ps1"
```
**주의**: MCP와 서버가 다른 DB 연결을 사용할 수 있음. MCP 마이그레이션이 적용 안 될 경우 서버에서 직접 실행 필요.

### 2025-12-15: 토큰 캐시 Read-only 에러
- **파일**: `src/api/auth.py`
- **에러**: `[Errno 30] Read-only file system` 또는 `[Errno 21] Is a directory`
- **원인**: `/tmp` 또는 프로젝트 루트가 읽기 전용이거나 디렉토리 경로
- **수정**: 홈 디렉토리 우선, `.resolve()` 사용, 디렉토리 체크 추가

### 2025-12-14: /start 핸들러 블로킹
- **파일**: `src/main.py:128-135`
- **원인**: `await engine.start()`가 휴장일에 1시간 대기 → 폴링 블로킹
- **수정**: `asyncio.create_task(self._engine.start())`

### 2025-12-11: 매도 체결 타임아웃
- **파일**: `trading_engine.py:1000-1107`
- **원인**: 체결 대기 타임아웃 → 중복 매도 주문
- **수정**: `_pending_sell_orders` 추적 + `_check_pending_sell_order()`

### 2025-12-10: highest_price 저장 실패
- **파일**: `trading_engine.py:2226,2229`
- **원인**: `position.metadata` → `position.signal_metadata` 오타
- **수정**: 올바른 속성명 사용

### 2025-12-08: 분할 익절 중복 실행
- **파일**: `trading_engine.py:1546`
- **원인**: `on_partial_exit()` 호출 시 2개 인자만 전달 (4개 필요)
- **수정**: 올바른 4개 인자 전달

---

## 배포 문제 해결

### CRLF 줄바꿈 에러
```
bash: /home/ubuntu/K_stock_trading/scripts/install.sh: /bin/bash^M: bad interpreter
```

**해결:** 서버에서 `dos2unix ~/K_stock_trading/scripts/*.sh`

### python3-venv 에러
```
The virtual environment was not created successfully because ensurepip is not available.
```

**해결:** `sudo apt install -y python3.11-venv`

### 버전 형식 오류
```
현재 버전: v.2025-12-14..001
```

**해결:** `deploy.bat`에서 PowerShell 날짜 파싱 사용 (이미 수정됨)

### ssh.bat 무한 루프

**증상:** deploy.bat 실행 시 "K_stock_trading SSH 접속" 무한 반복

**해결:** `ssh.bat` → `connect.bat`로 이름 변경 (이미 수정됨)

> **상세 가이드**: `docs/DEPLOYMENT_GUIDE.md` → 9. 배포 문제 해결 참조

---

## 서버 명령어

```bash
# 서비스 상태
sudo systemctl status k-stock-trading

# 로그 확인
sudo journalctl -u k-stock-trading -f

# 재시작
sudo systemctl restart k-stock-trading

# 중지
sudo systemctl stop k-stock-trading

# 버전 확인
cat ~/K_stock_trading/current/VERSION
```

---

## 디버깅 명령어

```bash
# 분할 익절 관련
grep -n "partial_exit" src/core/risk_manager.py

# 손절 로직
grep -n "check_exit" src/core/risk_manager.py

# 트레일링 스탑
grep -n "highest_price" src/core/trading_engine.py

# VI 관련
grep -n "vi_" src/core/trading_engine.py
```
