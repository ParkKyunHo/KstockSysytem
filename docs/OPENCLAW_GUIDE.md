# OpenClaw 키움 REST API 연동 가이드

> OpenClaw 텔레그램 봇을 통해 키움증권 시장 데이터를 자연어로 조회하는 시스템

---

## 1. 시스템 아키텍처

```
[사용자 Telegram DM] ←→ [OpenClaw Gateway :19000] ←→ [Gemini 2.5 Pro]
                                    │
                           exec tool (bash)
                                    │
                    [kiwoom_ranking.sh] → [키움 REST API]
                                              │
                                    POST /oauth2/token (인증)
                                    POST /api/dostk/rkinfo (거래대금)
```

### 핵심 구성

| 구성요소 | 버전/경로 | 설명 |
|----------|-----------|------|
| OpenClaw | v2026.2.23 | 로컬 AI 에이전트 프레임워크 |
| Gateway | `localhost:19000` | WebSocket 기반 에이전트 서버 |
| 모델 | `google/gemini-2.5-pro` | LLM 백엔드 |
| Telegram Bot | `@stock_Albra_bot` | 사용자 인터페이스 |
| 키움 API | `api.kiwoom.com` | 실전 REST API |

---

## 2. 파일 구조

```
~/.openclaw/
├── openclaw.json              # 메인 설정 (env, gateway, channels)
├── gateway.cmd                # Windows Scheduled Task 시작 스크립트
├── workspace/
│   ├── AGENTS.md              # 에이전트 행동 규칙
│   ├── TOOLS.md               # 도구 사용 가이드 (키움 API 포함)
│   ├── SOUL.md                # 에이전트 페르소나
│   ├── USER.md                # 사용자 프로필
│   ├── IDENTITY.md            # 봇 정체성
│   ├── HEARTBEAT.md           # 주기적 체크 설정
│   └── BOOTSTRAP.md           # 초기 설정
└── skills/
    └── kiwoom-market-ranking/
        ├── SKILL.md            # 스킬 정의 (YAML frontmatter + 가이드)
        └── scripts/
            └── kiwoom_ranking.sh  # 거래대금 조회 헬퍼 스크립트
```

---

## 3. 스킬 상세: kiwoom-market-ranking

### 3.1 동작 흐름

1. 사용자가 텔레그램에서 "거래대금 상위 종목" 질문
2. OpenClaw(Gemini)이 TOOLS.md를 참조하여 exec 도구로 스크립트 실행
3. `kiwoom_ranking.sh`가 키움 API 토큰 발급 → 거래대금 조회
4. 결과를 파싱하여 텔레그램으로 전송

### 3.2 키움 API 엔드포인트

#### 인증 (토큰 발급)

```
POST https://api.kiwoom.com/oauth2/token
Content-Type: application/json;charset=UTF-8

{
  "grant_type": "client_credentials",
  "appkey": "$KIWOOM_APP_KEY",
  "secretkey": "$KIWOOM_APP_SECRET"
}

응답: { "token": "...", "token_type": "Bearer", "expires_dt": "..." }
```

#### 거래대금 상위 조회 (ka10032)

```
POST https://api.kiwoom.com/api/dostk/rkinfo
Content-Type: application/json;charset=UTF-8
Authorization: Bearer $TOKEN
api-id: ka10032

{
  "stex_tp": "K",            # 거래소 (K: KRX)
  "mrkt_tp": "0",            # 0=전체, 1=코스피, 2=코스닥
  "sort_tp": "0",            # 거래대금 기준
  "cnt": "30",               # 조회 개수
  "mang_stk_incls": "0"      # 관리종목 제외
}

응답: { "trde_prica_upper": [ { "now_rank", "stk_cd", "stk_nm", "cur_prc", "flu_rt", "trde_prica" }, ... ] }
```

### 3.3 응답 필드

| 필드 | 설명 | 비고 |
|------|------|------|
| `now_rank` | 순위 | |
| `stk_cd` | 종목코드 | A접두사 없음 (실제 확인) |
| `stk_nm` | 종목명 | |
| `cur_prc` | 현재가 | +/- 부호 포함 |
| `flu_rt` | 등락률(%) | +/- 부호 포함 |
| `trde_prica` | 거래대금 | 백만원 단위 |
| `now_trde_qty` | 거래량 | |

### 3.4 스크립트 사용법

```bash
# 전체 시장 상위 30종목 (기본)
bash ~/.openclaw/skills/kiwoom-market-ranking/scripts/kiwoom_ranking.sh

# 코스피 상위 10종목
bash ~/.openclaw/skills/kiwoom-market-ranking/scripts/kiwoom_ranking.sh --market kospi --count 10

# 코스닥 상위 20종목
bash ~/.openclaw/skills/kiwoom-market-ranking/scripts/kiwoom_ranking.sh --market kosdaq --count 20
```

필수 환경변수: `KIWOOM_APP_KEY`, `KIWOOM_APP_SECRET`
필수 바이너리: `curl`, `jq`

---

## 4. 새 스킬 추가 가이드

### 4.1 디렉토리 생성

```bash
mkdir -p ~/.openclaw/skills/{skill-name}/scripts/
```

### 4.2 SKILL.md 작성

```yaml
---
name: skill-name
description: "스킬 설명. 트리거 키워드 포함."
metadata:
  openclaw:
    emoji: "📈"
    requires:
      env: ["KIWOOM_APP_KEY", "KIWOOM_APP_SECRET"]
      bins: ["curl", "jq"]
---

# 스킬 제목

## When to Use
- 트리거 조건 나열

## When NOT to Use
- 제외 조건 나열

## 사용법
(스크립트 실행 방법)
```

### 4.3 TOOLS.md에 등록 (필수!)

> managed 스킬은 에이전트 시스템 프롬프트에 자동 주입되지 않음.
> 반드시 `~/.openclaw/workspace/TOOLS.md`에 사용법을 추가해야 에이전트가 인식함.

### 4.4 openclaw.json에 환경변수 등록

새로운 API 키가 필요한 경우 `env` 섹션에 추가:
```json
{
  "env": {
    "NEW_API_KEY": "value"
  }
}
```

### 4.5 스킬 확인

```bash
openclaw skills list          # ready/missing 상태 확인
openclaw skills info {name}   # 상세 정보 + requires 충족 여부
openclaw skills check         # 전체 스킬 상태 점검
```

### 4.6 Gateway 재시작

스킬 추가/수정 후 gateway 재시작 필요:
```bash
openclaw gateway restart
```

**주의**: gateway.cmd는 cmd.exe 한글 경로 깨짐 문제가 있어 Scheduled Task가 실패할 수 있음.
bash에서 직접 실행하거나, 아래 방법 사용:

```powershell
# PowerShell에서 시작
Start-Process -FilePath "$env:USERPROFILE\.openclaw\gateway.cmd" -WindowStyle Hidden
```

---

## 5. 트러블슈팅

### 5.1 gateway.cmd 한글 경로 오류

**증상**: Scheduled Task가 "Ready" 상태로 즉시 종료
**원인**: cmd.exe가 UTF-8 한글 경로(`박균호`)를 `諛뺢???`로 읽음
**해결**:
```bash
# bash에서 직접 실행 (한글 경로 정상 처리)
export HOME="/c/Users/박균호"
export OPENCLAW_GATEWAY_PORT=19000
export OPENCLAW_GATEWAY_TOKEN="<token>"
export KIWOOM_APP_KEY="<key>"
export KIWOOM_APP_SECRET="<secret>"
"C:\Program Files\nodejs\node.exe" "C:\Users\박균호\AppData\Roaming\npm\node_modules\openclaw\dist\index.js" gateway --port 19000
```

### 5.2 managed 스킬이 에이전트에 안 보임

**증상**: `openclaw skills list`에서 "ready"이지만 에이전트가 스킬 못 찾음
**원인**: OpenClaw은 bundled 스킬만 시스템 프롬프트에 자동 주입
**해결**: `~/.openclaw/workspace/TOOLS.md`에 스크립트 경로와 사용법 수동 추가

### 5.3 jq 없음 오류

**증상**: 스킬 상태 "missing (bins: jq)"
**해결**: `choco install jq -y`

### 5.4 API 토큰 만료

키움 API 토큰은 약 24시간 유효. 스크립트가 매 호출마다 새 토큰을 발급하므로 문제없음.
토큰 발급이 실패하면 `KIWOOM_APP_KEY`, `KIWOOM_APP_SECRET` 값 확인.

### 5.5 세션 캐싱 문제

**증상**: TOOLS.md 수정 후에도 에이전트가 이전 버전 참조
**원인**: Gateway가 워크스페이스 파일을 기동 시 캐시
**해결**: Gateway 프로세스를 완전히 종료 후 재시작

---

## 6. 향후 스킬 구현 참고 API

| 스킬 | API ID | 엔드포인트 | 설명 |
|------|--------|-----------|------|
| 개별 종목 현재가 | ka10001 | `/api/dostk/stkinfo` | 종목코드로 현재가 조회 |
| 일봉 차트 | ka10081 | `/api/dostk/chart` | 일봉 데이터 |
| 보유 종목 | ka10072 | `/api/dostk/acntinfo` | 계좌 잔고 |
| 체결 내역 | ka10073 | `/api/dostk/ordinfo` | 주문/체결 조회 |
| 시장 지수 | ka80003 | `/api/dostk/mktinfo` | 코스피/코스닥 지수 |
| 업종 순위 | ka10031 | `/api/dostk/rkinfo` | sort_tp 변경으로 업종별 조회 |

> 각 API의 정확한 파라미터는 `src/api/endpoints/market.py` 참조

---

## 7. 설정 파일 위치 요약

| 파일 | 경로 | 용도 |
|------|------|------|
| OpenClaw 설정 | `~/.openclaw/openclaw.json` | gateway, env, channels |
| Gateway 시작 | `~/.openclaw/gateway.cmd` | Scheduled Task용 |
| 에이전트 도구 | `~/.openclaw/workspace/TOOLS.md` | 스킬 사용법 등록 |
| 스킬 정의 | `~/.openclaw/skills/{name}/SKILL.md` | 스킬 메타 + 가이드 |
| 스킬 스크립트 | `~/.openclaw/skills/{name}/scripts/` | 실행 스크립트 |
| Gateway 로그 | `/tmp/openclaw/openclaw-YYYY-MM-DD.log` | 런타임 로그 |
