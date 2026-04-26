# AWS Lightsail 런처 구현 계획

> **작성일**: 2025-12-13
> **상태**: 계획 완료, 구현 대기
> **목적**: K_stock_trading 시스템을 AWS Lightsail에서 24시간 안정적으로 운영

---

## 개요

**목표**: K_stock_trading 시스템을 AWS Lightsail에서 24시간 안정적으로 운영하기 위한 Production-ready 런처

**핵심 요구사항**:
1. 실행 전 검증 절차 (Pre-flight Checks)
2. 크래시 시 자동 재시작 (지수 백오프)
3. Graceful Shutdown (SIGTERM/SIGINT 처리)
4. 로그 관리 및 텔레그램 알림
5. systemd 서비스 통합

---

## 생성할 파일 (3개)

| 파일 | 설명 |
|------|------|
| `launcher.py` | Python 메인 런처 (Pre-flight + Process Manager) |
| `scripts/start.sh` | Linux Bash 스크립트 (start/stop/restart/status) |
| `scripts/systemd/k-stock-trading.service` | systemd 서비스 파일 |

---

## 1. launcher.py 설계

### 클래스 구조

```
launcher.py
├── PreflightChecker        # 6가지 사전 검증
├── ProcessManager          # 프로세스 실행 및 재시작
├── LauncherLogger          # 로그 관리
└── LauncherNotifier        # 텔레그램 알림
```

### 1.1 PreflightChecker (사전 검증)

| # | 검증 항목 | 방법 | 실패 시 |
|---|----------|------|---------|
| 1 | Python 버전 | `sys.version_info >= (3, 10)` | 종료 |
| 2 | 필수 환경변수 | `os.getenv()` 체크 | 종료 |
| 3 | 의존성 패키지 | `importlib.import_module()` | 종료 |
| 4 | 키움 API 토큰 | `TokenManager.get_token()` | 종료 |
| 5 | DB 연결 | `DatabaseManager.initialize()` | 경고 (SQLite 폴백) |
| 6 | 텔레그램 연결 | `TelegramNotifier.send_message()` | 경고 (계속 진행) |

```python
class PreflightChecker:
    async def run_all_checks(self) -> tuple[bool, list[str]]:
        """모든 검증 실행, (성공여부, 에러목록) 반환"""

    def check_python_version(self) -> bool
    def check_environment_variables(self) -> tuple[bool, list[str]]
    def check_dependencies(self) -> tuple[bool, list[str]]
    async def check_kiwoom_api(self) -> bool
    async def check_database(self) -> bool
    async def check_telegram(self) -> bool
```

**필수 환경변수**:
- `KIWOOM_APP_KEY`
- `KIWOOM_APP_SECRET`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `DATABASE_URL` (Optional - SQLite 폴백)

### 1.2 ProcessManager (프로세스 관리)

**재시작 정책**:
- 지수 백오프: 5초 → 10초 → 20초 → 40초 → ... → 300초 (최대)
- 성공적 실행 10분 후 백오프 리셋
- 1시간 내 5회 초과 재시작 시 중단 (무한루프 방지)

```python
class ProcessManager:
    INITIAL_BACKOFF = 5       # 초기 대기 시간
    MAX_BACKOFF = 300         # 최대 대기 시간 (5분)
    BACKOFF_MULTIPLIER = 2    # 지수 배수
    MAX_RESTARTS_PER_HOUR = 5 # 시간당 최대 재시작 횟수
    STABLE_THRESHOLD = 600    # 안정 판정 시간 (10분)

    async def run(self):
        """메인 실행 루프"""
        while not self._shutdown_requested:
            start_time = time.time()
            exit_code = await self._run_process()
            runtime = time.time() - start_time

            if runtime > STABLE_THRESHOLD:
                self._reset_backoff()

            if self._should_stop_restarting():
                break

            await asyncio.sleep(self._current_backoff)
            self._increase_backoff()
```

### 1.3 Signal Handler

```python
def setup_signal_handlers(process_manager: ProcessManager):
    """SIGTERM, SIGINT 처리"""
    def handler(signum, frame):
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        process_manager.request_shutdown()

    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)
```

### 1.4 LauncherLogger

```python
class LauncherLogger:
    LOG_DIR = "logs"
    MAX_SIZE = 100 * 1024 * 1024  # 100MB
    BACKUP_COUNT = 7              # 7일 보관

    def setup(self) -> logging.Logger:
        """RotatingFileHandler + StreamHandler 설정"""
```

### 1.5 LauncherNotifier

```python
class LauncherNotifier:
    async def send_startup_notification(self, checks_passed: list[str])
    async def send_shutdown_notification(self, reason: str)
    async def send_restart_notification(self, attempt: int, error: str)
    async def send_critical_failure(self, errors: list[str])
```

---

## 2. start.sh 설계

```bash
#!/bin/bash
# K-Stock Trading System Launcher

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PID_FILE="$PROJECT_DIR/k-stock-trading.pid"
LOG_FILE="$PROJECT_DIR/logs/launcher.log"

case "$1" in
    start)
        # 중복 실행 방지, nohup으로 백그라운드 실행
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE")
            if ps -p "$PID" > /dev/null 2>&1; then
                echo "Already running (PID: $PID)"
                exit 1
            fi
        fi

        cd "$PROJECT_DIR"
        nohup python3 launcher.py >> "$LOG_FILE" 2>&1 &
        echo $! > "$PID_FILE"
        echo "Started (PID: $!)"
        ;;
    stop)
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE")
            if ps -p "$PID" > /dev/null 2>&1; then
                echo "Stopping (PID: $PID)..."
                kill -TERM "$PID"

                # 30초 대기
                for i in {1..30}; do
                    if ! ps -p "$PID" > /dev/null 2>&1; then
                        break
                    fi
                    sleep 1
                done

                # 여전히 실행 중이면 SIGKILL
                if ps -p "$PID" > /dev/null 2>&1; then
                    echo "Force killing..."
                    kill -KILL "$PID"
                fi

                rm -f "$PID_FILE"
                echo "Stopped"
            else
                echo "Not running (stale PID file)"
                rm -f "$PID_FILE"
            fi
        else
            echo "Not running"
        fi
        ;;
    restart)
        $0 stop
        sleep 2
        $0 start
        ;;
    status)
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE")
            if ps -p "$PID" > /dev/null 2>&1; then
                echo "Running (PID: $PID)"
                ps -p "$PID" -o pid,etime,rss,cmd
                exit 0
            else
                echo "Not running (stale PID file)"
                exit 1
            fi
        else
            echo "Not running"
            exit 1
        fi
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
```

---

## 3. systemd 서비스 설계

```ini
[Unit]
Description=K-Stock Trading System
Documentation=https://github.com/your-repo/K_stock_trading
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/K_stock_trading
Environment=PYTHONPATH=/home/ubuntu/K_stock_trading
EnvironmentFile=/home/ubuntu/K_stock_trading/.env

ExecStart=/usr/bin/python3 /home/ubuntu/K_stock_trading/launcher.py
ExecStop=/bin/kill -TERM $MAINPID

# 재시작 정책 (launcher.py 자체가 재시작 로직 포함)
Restart=on-failure
RestartSec=10
StartLimitIntervalSec=3600
StartLimitBurst=5

# 로그
StandardOutput=journal
StandardError=journal
SyslogIdentifier=k-stock-trading

# 리소스 제한
MemoryMax=2G
CPUQuota=80%

# 보안 강화
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/home/ubuntu/K_stock_trading/logs
ReadWritePaths=/home/ubuntu/K_stock_trading/data

[Install]
WantedBy=multi-user.target
```

---

## 실행 흐름도

```
[systemd start]
       │
       ▼
[launcher.py 시작]
       │
       ▼
┌─────────────────────────────────────┐
│ PreflightChecker.run_all_checks()   │
│  ├─ Python 버전 확인                 │
│  ├─ 환경변수 확인                    │
│  ├─ 의존성 확인                      │
│  ├─ 키움 API 토큰 확인               │
│  ├─ DB 연결 확인                     │
│  └─ 텔레그램 연결 확인               │
└─────────────────────────────────────┘
       │
       ├── 실패 → 텔레그램 알림 + 종료
       │
       ▼ 성공
┌─────────────────────────────────────┐
│ 텔레그램 시작 알림                    │
│ "시스템 시작됨, Pre-flight 완료"     │
└─────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────┐
│ ProcessManager.run()                 │
│  └─ subprocess: python -m src.main   │
└─────────────────────────────────────┘
       │
       ├── 정상 종료 (exit 0) → 종료
       │
       ├── 비정상 종료 (exit != 0)
       │         │
       │         ▼
       │   ┌─────────────────────────┐
       │   │ 재시작 카운터 체크        │
       │   │ (1시간 내 5회 초과?)     │
       │   └─────────────────────────┘
       │         │
       │         ├── 초과 → Critical 알림 + 종료
       │         │
       │         ▼ 미초과
       │   ┌─────────────────────────┐
       │   │ 지수 백오프 대기          │
       │   │ 재시작 알림              │
       │   └─────────────────────────┘
       │         │
       │         └── ProcessManager.run() 재실행
       │
       ▼
[SIGTERM 수신]
       │
       ▼
┌─────────────────────────────────────┐
│ Graceful Shutdown                    │
│  ├─ 자식 프로세스에 SIGTERM 전달      │
│  ├─ 30초 대기 후 SIGKILL             │
│  └─ 종료 알림                        │
└─────────────────────────────────────┘
```

---

## AWS Lightsail 배포 절차

### 사전 준비

1. **Lightsail 인스턴스 생성**
   - OS: Ubuntu 22.04 LTS
   - 최소 사양: 1GB RAM, 1 vCPU (권장: 2GB RAM)
   - 고정 IP 할당

2. **필수 패키지 설치**
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.11 python3.11-venv python3-pip git
```

3. **프로젝트 클론 및 의존성 설치**
```bash
cd /home/ubuntu
git clone https://github.com/your-repo/K_stock_trading.git
cd K_stock_trading
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

4. **환경변수 설정**
```bash
cp .env.example .env
nano .env  # 키움 API 키, 텔레그램 토큰 등 설정
```

### 파일 전송 (로컬에서 개발 후)
```bash
scp launcher.py ubuntu@<LIGHTSAIL_IP>:/home/ubuntu/K_stock_trading/
scp scripts/start.sh ubuntu@<LIGHTSAIL_IP>:/home/ubuntu/K_stock_trading/scripts/
scp scripts/systemd/k-stock-trading.service ubuntu@<LIGHTSAIL_IP>:/tmp/
```

### 서비스 설치
```bash
# 실행 권한 부여
chmod +x /home/ubuntu/K_stock_trading/scripts/start.sh

# systemd 서비스 설치
sudo mv /tmp/k-stock-trading.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable k-stock-trading
sudo systemctl start k-stock-trading
```

### 상태 확인
```bash
# 서비스 상태
sudo systemctl status k-stock-trading

# 실시간 로그
journalctl -u k-stock-trading -f

# 애플리케이션 로그
tail -f /home/ubuntu/K_stock_trading/logs/launcher.log
```

### 유용한 명령어
```bash
# 서비스 재시작
sudo systemctl restart k-stock-trading

# 서비스 중지
sudo systemctl stop k-stock-trading

# 부팅 시 자동 시작 비활성화
sudo systemctl disable k-stock-trading

# 최근 100줄 로그
journalctl -u k-stock-trading -n 100

# 오늘 로그만
journalctl -u k-stock-trading --since today
```

---

## 수정/생성 대상 파일

| 파일 | 작업 | 위치 |
|------|------|------|
| `launcher.py` | 신규 생성 | 프로젝트 루트 |
| `scripts/start.sh` | 신규 생성 | scripts/ |
| `scripts/systemd/k-stock-trading.service` | 신규 생성 | scripts/systemd/ |

---

## 핵심 코드 참조

| 모듈 | 파일 | 사용 목적 |
|------|------|----------|
| 진입점 | `src/main.py` | JuDoJuSniper 클래스 |
| 설정 | `src/utils/config.py` | AppConfig, 환경변수 |
| 토큰 | `src/api/auth.py` | TokenManager |
| DB | `src/database/connection.py` | DatabaseManager |
| 텔레그램 | `src/notification/telegram.py` | TelegramNotifier |

---

## TODO (구현 시)

- [ ] `launcher.py` 전체 코드 작성
- [ ] `scripts/start.sh` 생성
- [ ] `scripts/systemd/` 디렉토리 생성
- [ ] `scripts/systemd/k-stock-trading.service` 생성
- [ ] 로컬 테스트
- [ ] Lightsail 배포 테스트
