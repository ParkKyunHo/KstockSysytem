# AWS Lightsail 배포 및 운영 가이드

> **버전**: 1.1
> **작성일**: 2025-12-14
> **최종 수정**: 2025-12-14 (배포 문제 해결 추가)
> **배포 방식**: PowerShell + SCP (Git 미사용)
> **보안**: 전략 코드 비공개

---

## 목차

1. [아키텍처 개요](#1-아키텍처-개요)
2. [사전 준비](#2-사전-준비)
3. [최초 배포](#3-최초-배포)
4. [업데이트 배포](#4-업데이트-배포)
5. [롤백 절차](#5-롤백-절차)
6. [점검 및 유지보수](#6-점검-및-유지보수)
7. [장애 대응](#7-장애-대응)
8. [명령어 레퍼런스](#8-명령어-레퍼런스)

---

## 1. 아키텍처 개요

### 1.1 배포 흐름

```
┌─────────────────────────────────────────────────────────────────────┐
│                        로컬 개발 환경 (Windows)                       │
│  C:\K_stock_trading\                                                │
│  ├── src/                    # 소스 코드                             │
│  ├── scripts/deploy/         # 배포 스크립트                          │
│  └── .env                    # 환경변수 (배포 안함)                    │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ SCP (암호화 전송)
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     AWS Lightsail (Ubuntu 22.04)                     │
│  /home/ubuntu/K_stock_trading/                                       │
│  ├── current/               # 현재 운영 버전 (심볼릭 링크)             │
│  ├── releases/              # 릴리즈 버전 저장                        │
│  │   ├── v2025.12.14.001/                                           │
│  │   ├── v2025.12.14.002/                                           │
│  │   └── ...                                                        │
│  ├── shared/                # 공유 파일 (로그, 데이터)                 │
│  │   ├── logs/                                                      │
│  │   ├── data/                                                      │
│  │   └── .env               # 환경변수 (서버에만 존재)                 │
│  └── scripts/               # 서버 관리 스크립트                       │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 버전 관리 전략

```
릴리즈 버전 형식: v{YYYY}.{MM}.{DD}.{SEQ}
예: v2025.12.14.001, v2025.12.14.002

보관 정책:
- 최근 5개 버전 보관
- 오래된 버전 자동 삭제
```

### 1.3 배포 단계

```
[최초 배포]
1. Lightsail 인스턴스 생성
2. 서버 초기 설정
3. 디렉토리 구조 생성
4. 코드 전송 + 의존성 설치
5. 환경변수 설정
6. systemd 서비스 등록
7. 서비스 시작

[업데이트 배포]
1. 로컬에서 코드 검증
2. 새 릴리즈 버전 생성
3. 코드 전송
4. 의존성 업데이트 (필요시)
5. 심볼릭 링크 전환
6. 서비스 재시작
7. 헬스체크
8. 실패 시 롤백
```

---

## 2. 사전 준비

### 2.1 로컬 환경 (Windows)

#### 필수 소프트웨어

```powershell
# OpenSSH 클라이언트 (Windows 10/11 기본 포함)
ssh -V

# 없으면 설치
Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0
```

#### SSH 키 설정

```powershell
# 1. Lightsail 콘솔에서 키 다운로드
#    Create new → k-stock-trading-key → Download
#    저장 위치: C:\Users\박균호\.ssh\k-stock-trading-key.pem

# 2. 권한 설정 (PowerShell 관리자 권한으로 실행)
icacls "C:\Users\박균호\.ssh\k-stock-trading-key.pem" /inheritance:r
icacls "C:\Users\박균호\.ssh\k-stock-trading-key.pem" /grant:r "$env:USERNAME`:R"
```

#### 환경변수 설정 (로컬)

```powershell
# 시스템 환경변수 (config.bat에 이미 설정됨)
$LIGHTSAIL_HOST = "43.200.235.74"
$LIGHTSAIL_USER = "ubuntu"
$LIGHTSAIL_KEY = "C:\Users\박균호\.ssh\k-stock-trading-key.pem"
```

### 2.2 AWS Lightsail 인스턴스 정보

```
인스턴스 설정 (완료):
- Region: Seoul (ap-northeast-2)
- Platform: Linux/Unix
- Blueprint: Ubuntu 22.04 LTS
- Plan: $5/month (1GB RAM, 1 vCPU)
- Name: k-stock-trading
- SSH Key: k-stock-trading-key
- Network: Dual-stack (IPv4 + IPv6)
- Automatic Snapshots: 활성화 (06:00 UTC)

고정 IP: 43.200.235.74
```

---

## 3. 최초 배포

### 3.1 Step 1: 서버 초기 설정

**PowerShell에서 실행:**

```powershell
# SSH 접속
ssh -i C:\Users\박균호\.ssh\k-stock-trading-key.pem ubuntu@43.200.235.74
```

**서버에서 실행:**

```bash
# 시스템 업데이트
sudo apt update && sudo apt upgrade -y

# Python 3.11 설치
sudo apt install -y software-properties-common
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3.11-dev

# 필수 패키지
sudo apt install -y git curl wget htop unzip

# 타임존 설정
sudo timedatectl set-timezone Asia/Seoul

# 디렉토리 구조 생성
mkdir -p ~/K_stock_trading/{releases,shared/{logs,data},scripts}

# 확인
tree ~/K_stock_trading -L 2
```

### 3.2 Step 2: 로컬에서 배포 스크립트 실행

**PowerShell에서 실행:**

```powershell
cd C:\K_stock_trading
powershell -ExecutionPolicy Bypass -File "scripts\deploy\hotfix.ps1"
```

### 3.3 Step 3: 서버에서 환경변수 설정

```bash
# SSH 접속 후
nano ~/K_stock_trading/shared/.env
```

```bash
# =========================================
# 프로덕션 환경변수
# =========================================
IS_PAPER_TRADING=false
ENVIRONMENT=production

# 키움증권 API
KIWOOM_APP_KEY=PSxxxxxxxx
KIWOOM_APP_SECRET=xxxxxxxx

# 텔레그램
TELEGRAM_BOT_TOKEN=xxxxxxxx
TELEGRAM_CHAT_ID=xxxxxxxx

# 데이터베이스
DATABASE_URL=postgresql://postgres:xxx@db.xxx.supabase.co:5432/postgres

# 리스크 관리
MAX_POSITIONS=3
BUY_AMOUNT_RATIO=0.05

# 로깅
LOG_LEVEL=INFO
```

```bash
# 권한 설정
chmod 600 ~/K_stock_trading/shared/.env
```

### 3.4 Step 4: systemd 서비스 등록

```bash
# 서비스 파일 복사
sudo cp ~/K_stock_trading/current/scripts/server/k-stock-trading.service /etc/systemd/system/

# 서비스 활성화
sudo systemctl daemon-reload
sudo systemctl enable k-stock-trading
sudo systemctl start k-stock-trading

# 상태 확인
sudo systemctl status k-stock-trading
```

---

## 4. 업데이트 배포

### 4.1 배포 전 체크리스트

```
□ 로컬 테스트 완료
□ 문법 오류 없음 (python -m py_compile)
□ 현재 서버 상태 정상
□ 장 마감 후 배포 (권장)
```

### 4.2 배포 실행

**PowerShell에서:**

```powershell
cd C:\K_stock_trading
powershell -ExecutionPolicy Bypass -File "scripts\deploy\deploy.ps1"
```

### 4.3 배포 프로세스 상세

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. 로컬 검증                                                     │
│    - Python 문법 체크                                            │
│    - 필수 파일 존재 확인                                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. 서버 상태 확인                                                 │
│    - SSH 연결 테스트                                              │
│    - 디스크 공간 확인                                             │
│    - 현재 서비스 상태 기록                                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. 새 릴리즈 생성                                                 │
│    - 버전 번호 생성 (v2025.12.14.001)                             │
│    - releases/ 디렉토리에 새 폴더 생성                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. 파일 전송                                                      │
│    - src/ 디렉토리 전송                                           │
│    - requirements.txt 전송                                        │
│    - launcher.py 전송                                             │
│    - 서버 스크립트 전송                                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. 서버에서 설정                                                  │
│    - 가상환경 생성/업데이트                                        │
│    - 의존성 설치                                                  │
│    - shared/ 심볼릭 링크 생성                                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 6. 서비스 전환                                                    │
│    - 서비스 중지                                                  │
│    - current → 새 버전 링크 전환                                  │
│    - 서비스 시작                                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 7. 헬스체크                                                       │
│    - 서비스 상태 확인                                             │
│    - 로그 확인 (에러 없음)                                        │
│    - 텔레그램 알림 확인                                           │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              │                               │
              ▼                               ▼
        [성공]                           [실패]
    배포 완료 알림                      자동 롤백 실행
```

---

## 5. 롤백 절차

### 5.1 자동 롤백

배포 스크립트가 헬스체크 실패 시 자동으로 이전 버전으로 롤백합니다.

### 5.2 수동 롤백

**PowerShell에서:**

```powershell
cd C:\K_stock_trading
# 롤백 스크립트 실행 (서버에서 직접 또는 search_logs.ps1 -cmd 사용)
powershell -ExecutionPolicy Bypass -File "scripts\deploy\search_logs.ps1" -cmd "~/K_stock_trading/scripts/rollback.sh previous"
```

**또는 서버에서 직접:**

```bash
# 가용 버전 확인
ls -la ~/K_stock_trading/releases/

# 특정 버전으로 롤백
~/K_stock_trading/scripts/rollback.sh v2025.12.14.001

# 이전 버전으로 롤백 (가장 최근 이전)
~/K_stock_trading/scripts/rollback.sh previous
```

---

## 6. 점검 및 유지보수

### 6.1 일일 점검 체크리스트

```bash
# 1. 서비스 상태
sudo systemctl status k-stock-trading

# 2. 최근 로그 (에러 확인)
sudo journalctl -u k-stock-trading --since "1 hour ago" | grep -i error

# 3. 리소스 사용량
free -h
df -h

# 4. 프로세스 상태
ps aux | grep python
```

### 6.2 주간 점검

```bash
# 1. 로그 로테이션 확인
ls -la ~/K_stock_trading/shared/logs/

# 2. 디스크 정리
~/K_stock_trading/scripts/cleanup.sh

# 3. 시스템 업데이트 확인
sudo apt update
apt list --upgradable

# 4. 릴리즈 버전 정리 (5개 초과 시)
ls ~/K_stock_trading/releases/ | head -n -5 | xargs -I {} rm -rf ~/K_stock_trading/releases/{}
```

### 6.3 정기 점검 스케줄

| 주기 | 작업 | 명령어 |
|------|------|--------|
| 매일 09:00 전 | 서비스 상태 확인 | `systemctl status` |
| 매일 15:30 후 | 에러 로그 검토 | `journalctl --since today` |
| 주 1회 | 시스템 업데이트 | `apt update && apt upgrade` |
| 월 1회 | Lightsail 스냅샷 | 콘솔에서 수동 생성 |

---

## 7. 장애 대응

### 7.1 장애 유형별 대응

#### 서비스 다운

```bash
ssh -i C:\Users\박균호\.ssh\k-stock-trading-key.pem ubuntu@43.200.235.74

# 1. 상태 확인
sudo systemctl status k-stock-trading

# 2. 로그 확인
sudo journalctl -u k-stock-trading -n 100

# 3. 재시작 시도
sudo systemctl restart k-stock-trading

# 4. 여전히 실패하면 롤백
~/K_stock_trading/scripts/rollback.sh previous

# 서비스 정지
sudo systemctl stop k-stock-trading

# 서비스 시작
sudo systemctl start k-stock-trading
```

#### 메모리 부족

```bash
# 1. 메모리 확인
free -h

# 2. 프로세스 확인
ps aux --sort=-%mem | head -10

# 3. 서비스 재시작 (메모리 해제)
sudo systemctl restart k-stock-trading

# 4. 필요시 Lightsail 플랜 업그레이드 검토
```

#### SSH 접속 불가

```
1. Lightsail 콘솔 → 인스턴스 선택
2. "Connect using SSH" 버튼 (브라우저 기반)
3. 방화벽 규칙 확인 (포트 22)
4. 인스턴스 재부팅 (최후 수단)
```

### 7.2 긴급 연락망

```
1. 텔레그램 봇 알림 확인
2. Lightsail 콘솔 모니터링
3. CloudWatch 알람 (선택 설정)
```

---

## 8. 명령어 레퍼런스

### 8.1 Windows PowerShell 명령어

| 작업 | 명령어 |
|------|--------|
| 배포 (핫픽스) | `powershell -ExecutionPolicy Bypass -File "scripts\deploy\hotfix.ps1"` |
| 업데이트 배포 | `powershell -ExecutionPolicy Bypass -File "scripts\deploy\deploy.ps1"` |
| 로그 확인 | `powershell -ExecutionPolicy Bypass -File "scripts\deploy\check_logs.ps1" 50` |
| 상태 확인 | `powershell -ExecutionPolicy Bypass -File "scripts\deploy\status.ps1"` |
| 로그 검색 | `powershell -ExecutionPolicy Bypass -File "scripts\deploy\search_logs.ps1" -pattern "keyword"` |
| 서버 명령 실행 | `powershell -ExecutionPolicy Bypass -File "scripts\deploy\search_logs.ps1" -cmd "command"` |

### 8.2 서버 명령어

| 작업 | 명령어 |
|------|--------|
| 서비스 시작 | `sudo systemctl start k-stock-trading` |
| 서비스 중지 | `sudo systemctl stop k-stock-trading` |
| 서비스 재시작 | `sudo systemctl restart k-stock-trading` |
| 서비스 상태 | `sudo systemctl status k-stock-trading` |
| 실시간 로그 | `sudo journalctl -u k-stock-trading -f` |
| 오늘 로그 | `sudo journalctl -u k-stock-trading --since today` |
| 버전 확인 | `cat ~/K_stock_trading/current/VERSION` |
| 롤백 | `~/K_stock_trading/scripts/rollback.sh previous` |

### 8.3 문제 해결

| 증상 | 해결 |
|------|------|
| 서비스 시작 안됨 | `journalctl -u k-stock-trading -n 50` 로그 확인 |
| 권한 오류 | `chmod +x` 실행 권한 부여 |
| 모듈 없음 | `source venv/bin/activate && pip install -r requirements.txt` |
| 환경변수 오류 | `cat ~/K_stock_trading/shared/.env` 확인 |
| 메모리 부족 | `free -h` 확인 후 서비스 재시작 |

---

## 부록: 파일 구조

### 로컬 (Windows)

```
C:\K_stock_trading\
├── src/                          # 소스 코드
├── docs/                         # 문서
├── scripts/
│   ├── deploy/                   # 배포 스크립트 (Windows PowerShell)
│   │   ├── hotfix.ps1            # 배포 (핫픽스)
│   │   ├── deploy.ps1            # 업데이트 배포
│   │   ├── status.ps1            # 상태 확인
│   │   ├── check_logs.ps1        # 로그 확인
│   │   ├── search_logs.ps1       # 로그 검색 / 서버 명령 실행
│   │   └── check_db_server.ps1   # DB 확인
│   └── server/                   # 서버 스크립트 (Linux)
│       ├── setup.sh              # 초기 설정
│       ├── install.sh            # 릴리즈 설치
│       ├── health-check.sh       # 헬스체크
│       ├── rollback.sh           # 롤백
│       ├── cleanup.sh            # 정리
│       └── k-stock-trading.service  # systemd
├── launcher.py                   # 프로덕션 런처
├── requirements.txt              # 의존성
└── .env                          # 로컬 환경변수 (배포 안함)
```

### 서버 (Lightsail)

```
/home/ubuntu/K_stock_trading/
├── current -> releases/v2025.12.14.001/  # 현재 버전 (심볼릭 링크)
├── releases/                             # 릴리즈 저장소
│   ├── v2025.12.14.001/
│   │   ├── src/
│   │   ├── venv/
│   │   ├── launcher.py
│   │   ├── requirements.txt
│   │   ├── VERSION
│   │   ├── logs -> ../../shared/logs/
│   │   ├── data -> ../../shared/data/
│   │   └── .env -> ../../shared/.env
│   └── v2025.12.13.002/
├── shared/                               # 공유 데이터
│   ├── logs/
│   ├── data/
│   └── .env
└── scripts/                              # 서버 스크립트
    ├── setup.sh
    ├── install.sh
    ├── rollback.sh
    ├── cleanup.sh
    └── health-check.sh
```

---

## 9. 배포 문제 해결 (Troubleshooting)

### 9.1 알려진 문제 및 해결책

#### 문제 1: `/bin/bash^M: bad interpreter` 에러

**증상:**
```
bash: /home/ubuntu/K_stock_trading/scripts/install.sh: /bin/bash^M: bad interpreter
```

**원인:** Windows에서 편집한 .sh 파일이 CRLF 줄바꿈으로 저장됨

**해결:**
```bash
# 서버에서 실행
sudo apt install -y dos2unix
dos2unix ~/K_stock_trading/scripts/*.sh
```

**예방:** 로컬에서 .sh 파일 편집 시 LF 줄바꿈 사용 (VS Code: 우측 하단 CRLF → LF)

---

#### 문제 2: `python3-venv` 설치 에러

**증상:**
```
The virtual environment was not created successfully because ensurepip is not available.
apt install python3.10-venv
```

**원인:** 서버의 기본 `python3`가 3.10을 가리키지만 `install.sh`가 `python3.11`을 사용해야 함

**해결:**
```bash
# 서버에서 실행
sudo apt install -y python3.11-venv
```

**근본 해결:** `install.sh`에서 `python3.11` 명시 사용 (이미 적용됨)
```bash
# install.sh 라인 43
python3.11 -m venv venv
```

---

#### 문제 3: 버전 형식 오류 `v.2025-12-14..002`

**증상:**
```
현재 버전: v.2025-12-14..001
새 버전: v.2025-12-14..002
```

**원인:** `date /t` 명령이 한국어 로케일에서 다른 형식 출력

**해결:** PowerShell로 로케일 독립적 날짜 파싱 (이미 적용됨)
```batch
:: deploy.bat, first-deploy.bat
for /f %%i in ('powershell -c "Get-Date -Format 'yyyy.MM.dd'"') do set TODAY=%%i
```

---

#### 문제 4: `ssh.bat` 무한 루프

**증상:** `deploy.bat` 실행 시 "K_stock_trading SSH 접속" 무한 반복

**원인:** `scripts/deploy/ssh.bat` 파일이 시스템 `ssh.exe`보다 우선 실행됨

**해결:** `ssh.bat` → `connect.bat`로 이름 변경 (이미 적용됨)

---

### 9.2 배포 실패 시 복구 절차

```powershell
# 1. 서버 접속
ssh -i C:\Users\박균호\.ssh\k-stock-trading-key.pem ubuntu@43.200.235.74

# 2. 잘못된 릴리즈 삭제
rm -rf ~/K_stock_trading/releases/v2025.12.14.xxx

# 3. 심볼릭 링크 정리
rm -f ~/K_stock_trading/current

# 4. 서버 스크립트 줄바꿈 변환
dos2unix ~/K_stock_trading/scripts/*.sh

# 5. 로컬에서 재배포
powershell -ExecutionPolicy Bypass -File "scripts\deploy\deploy.ps1"
```

---

### 9.3 배포 전 체크리스트

```
□ 로컬 테스트 완료
□ Python 문법 체크: python -m py_compile src/main.py
□ 장 마감 후 배포 (권장)
□ 서버 상태 확인: powershell -ExecutionPolicy Bypass -File "scripts\deploy\status.ps1"
□ 백업 확인 (Lightsail 스냅샷)
```

---

### 9.4 최초 배포 시 주의사항

1. **서버 초기 설정**: `setup.sh` 실행으로 Python 3.11 + venv 패키지 설치
2. **환경변수 설정**: `~/K_stock_trading/shared/.env` 파일 생성 필수
3. **권한 설정**: `.env` 파일 권한 `chmod 600`
4. **서비스 등록**: `systemctl enable k-stock-trading`
