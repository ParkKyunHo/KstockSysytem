# V7.1 리포트 시스템 (Reporting System)

> 이 문서는 V7.1의 **On-Demand 종목 리포트 시스템**을 정의합니다.
> 
> Claude Opus 4.7을 활용하여 종목별 깊이 있는 리포트를 생성합니다.
> 
> **사용자 요청 시에만 생성** (자동 생성 안 함, 비용 + 노이즈 회피).

---

## 목차

- [§0. 리포트 시스템 철학](#0-리포트-시스템-철학)
- [§1. 리포트 구조](#1-리포트-구조)
- [§2. PART 1: 이야기 (Narrative)](#2-part-1-이야기-narrative)
- [§3. PART 2: 객관 팩트 (Facts)](#3-part-2-객관-팩트-facts)
- [§4. 데이터 수집](#4-데이터-수집)
- [§5. Claude API 활용](#5-claude-api-활용)
- [§6. 프롬프트 엔지니어링](#6-프롬프트-엔지니어링)
- [§7. 생성 워크플로우](#7-생성-워크플로우)
- [§8. PDF / Excel 생성](#8-pdf--excel-생성)
- [§9. DB 저장 및 조회](#9-db-저장-및-조회)
- [§10. 비용 관리](#10-비용-관리)

---

## §0. 리포트 시스템 철학

### 0.1 5대 원칙

```yaml
원칙 1: On-Demand만 (자동 생성 안 함)
  사용자가 명시적으로 요청한 종목만
  비용 절감
  노이즈 회피
  사용자 의도 존중

원칙 2: 깊이 우선 (Depth over Breadth)
  "칩·재료까지" 깊이 분석
  표면적 정보 X
  HTS/뉴스 한 번에 안 보이는 정보

원칙 3: 이중 구조 (Story + Facts)
  PART 1: 이야기 (서사) - 직관적 이해
  PART 2: 객관 팩트 - 검증 가능한 데이터
  둘 다 중요, 분리

원칙 4: 영구 보존
  생성된 리포트는 DB 영구 저장
  과거 리포트 비교 가능
  사용자 메모 추가 가능
  PDF/Excel 다운로드 (외부 보관)

원칙 5: 인간 검증 가능
  모든 팩트 출처 명시
  데이터 소스 추적
  AI 환각 가능성 인지
  사용자가 최종 판단
```

### 0.2 리포트 사용 시나리오

```yaml
시나리오 1: 신규 종목 평가
  발견 → 추적 등록 직후 → 리포트 생성
  → 종목 깊이 있게 이해 후 박스 설정

시나리오 2: 보유 중 점검
  포지션 보유 중 의문 발생
  → 리포트 생성 → 객관적 재평가
  → 청산 또는 추가 매수 결정

시나리오 3: 월간 리뷰
  monthly_review 알림에서 60일+ 정체 종목
  → 리포트 생성 → 추적 지속/종료 결정

시나리오 4: 외부 공유
  PDF 다운로드 → 지인과 토론 (개인 보관용)

NOT 시나리오:
  자동 매일 모든 종목 리포트 ❌
  대량 일괄 생성 ❌
```

### 0.3 사용 빈도 가정

```yaml
예상 사용:
  주 2~3건
  월 10~15건

비용 가정 (Claude Opus 4.7):
  리포트 1건당:
    Input: ~10,000 토큰
    Output: ~5,000 토큰
    비용: 약 0.5~1 USD
  
  월 15건: 약 7~15 USD
  연 180건: 약 90~180 USD

→ 부담스럽지 않은 수준
→ 사용자 요청 시에만 생성하므로 폭주 위험 낮음
```

---

## §1. 리포트 구조

### 1.1 전체 구조

```yaml
리포트 = 메타데이터 + PART 1 + PART 2 + 사용자 메모

메타데이터:
  - 종목 코드, 이름
  - 생성 시각
  - 모델 버전 (claude-opus-4-7)
  - 토큰 사용량
  - 데이터 소스 목록
  - 생성 소요 시간

PART 1: 이야기 (Markdown)
  - 출발 (회사 시작)
  - 성장 (현재까지)
  - 현재 (현 상황)
  - 미래 (향후 방향)

PART 2: 객관 팩트 (Markdown)
  - 회사 개요
  - 사업 부문
  - 공급망 (칩·재료 핵심)
  - 재무 요약
  - 최근 공시
  - 최근 뉴스 (2주)
  - 동종업계 비교

사용자 메모 (사후 추가)
  - 자유 텍스트
  - 사용자가 리포트 본 후 작성
```

### 1.2 분량 가이드

```yaml
PART 1 (이야기):
  분량: A4 1~1.5페이지 (약 800~1,500자)
  톤: 서사적, 흥미로운
  목적: 종목을 친구에게 설명하듯

PART 2 (객관 팩트):
  분량: A4 1~1.5페이지 (약 1,000~1,800자)
  톤: 정보 중심, 간결
  목적: 검증 가능한 사실 제공

총 분량: A4 2~3페이지
PDF: 깔끔한 레이아웃
Excel: 데이터 위주 시트별 분리
```

---

## §2. PART 1: 이야기 (Narrative)

### 2.1 구조 (4-Phase Story Arc)

```yaml
구조:
  ## 출발 (Origin)
    - 언제, 누가, 왜 시작했는가
    - 초기 비즈니스 모델
    - 핵심 인물 (창업자, 초기 투자자)
    - 어떤 문제를 풀려 했는가

  ## 성장 (Growth)
    - 핵심 변곡점들
    - 주요 인수합병
    - 사업 영역 확장
    - 시장 점유율 변화
    - 위기와 극복

  ## 현재 (Now)
    - 현재 시장 위치
    - 핵심 사업 부문
    - 최근 1~2년 핵심 이슈
    - 현재 가장 뜨거운 모멘텀
    - 시장이 주목하는 이유

  ## 미래 (Future)
    - 향후 1~3년 전망
    - 핵심 모멘텀 (긍정/부정)
    - 시장 컨센서스
    - 리스크 요인
    - 다음 변곡점 후보
```

### 2.2 톤 가이드

```yaml
톤:
  - 서사적 (드라마틱 X, 차분히)
  - 명료한 (어려운 용어 풀어서)
  - 균형 (긍정/부정 모두)
  - 사실 기반 (추측 X)

문체:
  - 평서문 위주
  - 한국어 자연스럽게
  - 일관된 시제 (현재형 + 과거형 적절히)
  - 전문 용어는 최소화 또는 풀이

피해야 할 것:
  ❌ "엄청난", "충격적인", "놀라운" 등 과장
  ❌ 투자 추천 (매수/매도 의견)
  ❌ 가격 예측 (목표가)
  ❌ 환각 정보 (불확실한 사실)
  
권장:
  ✅ "주목할 점은", "흥미롭게도", "한편"
  ✅ 출처 암시 ("최근 발표에 따르면")
  ✅ 균형 잡힌 시각
```

### 2.3 예시 (삼성전자)

```markdown
# 삼성전자 - 반도체 거인의 새로운 도약

## 출발

삼성전자는 1969년 이병철 회장이 설립했습니다. 처음에는 흑백 TV와 라디오를 만드는 작은 가전 회사였습니다. 일본의 산요와 NEC로부터 기술을 빌려와 시작했습니다.

1974년, 운명적 결정이 있었습니다. 한국반도체 인수입니다. 당시 반도체는 검증되지 않은 사업이었지만, 이병철 회장은 미래를 내다봤습니다. 이 결정이 오늘날 삼성전자를 만들었습니다.

## 성장

1980년대 후반 메모리 반도체로 진출했습니다. 1992년 세계 최초 64Mb DRAM 개발, 1993년 메모리 1위 등극. 이후 25년 이상 메모리 1위를 지켰습니다.

2000년대는 휴대폰 시장 진입. 갤럭시 시리즈로 애플의 아이폰과 경쟁하는 글로벌 브랜드가 됐습니다.

위기도 있었습니다. 2014년 갤럭시 노트7 발화 사건, 2017년 이재용 부회장 구속. 그러나 회복했습니다.

## 현재

삼성전자는 세 가지 핵심 사업을 가지고 있습니다.

첫째, 메모리 반도체. DRAM과 NAND 분야 1위입니다. 최근 HBM3E (고대역폭 메모리)에서 SK하이닉스에 밀렸으나, 2025년 들어 엔비디아 공급 인증을 받으며 따라잡고 있습니다.

둘째, 파운드리. TSMC에 한참 밀려있지만 3나노 공정에서 게이트올어라운드(GAA) 기술로 추격합니다.

셋째, 모바일과 가전. 갤럭시 S 시리즈와 폴더블 폰이 주력입니다.

## 미래

향후 1~2년 핵심은 AI 반도체입니다. HBM3E 양산 안정화와 엔비디아 공급 비중 확대가 주가의 핵심 모멘텀입니다.

리스크는 메모리 사이클입니다. 메모리 반도체는 호황과 불황이 반복됩니다. 현재 호황 사이클이 어디쯤인지가 관건입니다.

장기적으로는 파운드리 추격이 관건입니다. TSMC와의 격차가 좁혀질지가 향후 5년 운명을 결정할 것입니다.
```

### 2.4 종목별 차별화

```yaml
대형주 (삼성전자, SK하이닉스 등):
  위와 같이 4-Phase 구조 충실히
  
중소형주:
  '출발'과 '성장' 압축
  '현재'와 '미래'에 집중
  최근 모멘텀 중심

테마주 (예: AI 관련):
  '출발'은 짧게
  '현재'와 '미래'에 시장 컨텍스트 강조
  기술 혁신과 회사 위치

신규 상장:
  '출발' 자세히 (대부분 모름)
  '성장'은 간략 (역사 짧음)
  '미래' 강조 (왜 상장했는지)
```

---

## §3. PART 2: 객관 팩트 (Facts)

### 3.1 구조 (7개 섹션)

```yaml
## 1. 회사 개요 (Company Overview)
  - 정식 명칭, 영문명
  - 설립일, 본사 위치
  - 대표이사
  - 직원 수
  - 시가총액
  - 상장 시장 (KOSPI/KOSDAQ)
  - 업종, 섹터
  - 주요 주주 구조 (5% 이상)

## 2. 사업 부문 (Business Segments)
  - 부문별 매출 비중 (직전 분기)
  - 각 부문의 주요 제품/서비스
  - 핵심 기술/특허

## 3. 공급망 (Supply Chain) ★ 핵심
  - 주요 고객 (B2B의 경우)
  - 주요 공급사
  - 핵심 원재료
  - 지정학적 리스크 (중국, 미국 등)
  - "칩·재료" 깊이

## 4. 재무 요약 (Financial Summary)
  - 최근 4분기 실적 (매출, 영업이익, 순이익)
  - YoY 변화율
  - 주요 재무 비율 (PER, PBR, ROE, 부채비율)
  - 현금흐름

## 5. 최근 공시 (Recent Disclosures)
  - DART 최근 1개월 공시
  - 주요 공시 요약 (주식 분할, 자사주 매입, 신규 사업 등)

## 6. 최근 뉴스 (Recent News, 2주)
  - 주요 언론 보도
  - 기관 리포트 발표
  - 핵심 이벤트

## 7. 동종업계 비교 (Peer Comparison)
  - 같은 섹터 주요 회사 3~5개
  - 시가총액, 매출, PER 비교
  - 상대적 강점/약점
```

### 3.2 "칩·재료" 깊이 (특별 강조)

```yaml
의미:
  표면적 정보가 아닌 깊이 있는 분석
  특히 다음을 포함:
    - 어떤 칩(반도체 부품)이 사용되는가?
    - 어떤 원재료가 핵심인가?
    - 공급사가 누구인가?
    - 가격 변동에 어떻게 영향받는가?

예시 (삼성전자 HBM3E):
  ❌ "삼성전자는 HBM을 만든다"
  ✅ "삼성전자 HBM3E는 1b DRAM 다이를 적층해 만들고, 
      이를 위해 ASML EUV 노광기, AMAT/LAM 식각 장비를 사용.
      엔비디아 H200, B200에 공급 (2024년 말부터),
      비메모리 분야에서는 TSMC 5나노 공정에 일부 의존."

예시 (LG에너지솔루션):
  ❌ "LG에너지솔루션은 배터리를 만든다"
  ✅ "LG에너지솔루션은 NCM 양극재 사용 (LG화학 자회사 GLG 공급),
      음극재는 포스코퓨처엠과 BTR 신소재에서 조달.
      전구체는 중국 의존도 70%+ (CNGR 등),
      미국 IRA 대응 위해 캐나다 광산 (LiVista) 투자."

이런 깊이는:
  - HTS에 안 나옴
  - 일반 뉴스에도 표면적
  - 리포트에서만 가치 있음
  - Claude의 강점 (깊이 있는 통합)
```

### 3.3 출처 명시

```yaml
모든 팩트는 출처 명시:
  - DART 공시: "[DART, 2026-02-01 분기보고서]"
  - 뉴스: "[연합뉴스, 2026-04-20]"
  - 회사 IR: "[삼성전자 IR, 2026 Q1 실적 발표]"
  - 기타: 가능한 한 구체적

불확실한 정보:
  "~로 알려져 있다", "보도에 따르면"
  
숫자는 정확:
  ❌ "약 1조원대"
  ✅ "1조 245억 원 (2025년 매출, 분기보고서)"

날짜 명시:
  ❌ "최근"
  ✅ "2026년 4월 20일 발표"
```

---

## §4. 데이터 수집

### 4.1 데이터 소스

```yaml
1. 키움 REST API (시세, 재무):
   - 종목 기본 정보 (이름, 시가총액, 업종)
   - 1년 / 5년 가격 차트 데이터
   - 분기/연간 재무제표
   - 거래량
   
2. DART API (공시):
   - 사업보고서, 분기/반기 보고서
   - 주요 공시 (주식 분할, 자사주, M&A, 신규 사업)
   - 최근 1개월 공시 목록
   
3. 네이버 뉴스 API (뉴스):
   - 종목명 검색
   - 최근 2주 뉴스
   - 상위 10~20건
   
4. Claude의 사전 학습 지식:
   - 회사 역사 (출발, 성장)
   - 산업 컨텍스트
   - 글로벌 비교
   - "칩·재료" 깊이
   
   ※ 단, 최근 1년 정보는 DART/뉴스로 보완
```

### 4.2 데이터 수집 우선순위

```yaml
필수 (없으면 리포트 실패):
  - 종목 기본 정보 (키움)
  - 최근 분기 재무 (DART 또는 키움)
  
권장 (있으면 풍부):
  - 최근 1개월 공시 (DART)
  - 최근 2주 뉴스 (네이버)
  - 5년 가격 추이 (키움)
  
선택 (있으면 깊이):
  - 동종업계 데이터
  - 외국인 보유율
  - 기관 매수/매도 추이
```

### 4.3 데이터 수집 코드 구조

```python
# src/core/v71/report/data_collector.py

"""
종목 리포트용 데이터 수집.

필수 데이터 + 권장 데이터 + 선택 데이터.
실패 시 graceful degradation.
"""

from dataclasses import dataclass
from typing import Optional, List
from datetime import datetime, timedelta

@dataclass
class CollectedData:
    """수집된 모든 데이터."""
    # 필수
    basic_info: dict  # 종목 기본
    financial_summary: dict  # 재무 요약
    
    # 권장
    recent_disclosures: Optional[List[dict]]
    recent_news: Optional[List[dict]]
    price_history: Optional[dict]
    
    # 선택
    peer_data: Optional[List[dict]]
    foreign_ownership: Optional[dict]
    
    # 메타
    collection_started_at: datetime
    collection_completed_at: datetime
    sources_used: List[str]
    sources_failed: List[str]


class V71DataCollector:
    """리포트용 데이터 수집자."""
    
    def __init__(
        self,
        kiwoom_client,
        dart_client,
        news_client,
    ):
        self._kiwoom = kiwoom_client
        self._dart = dart_client
        self._news = news_client
    
    async def collect(self, stock_code: str) -> CollectedData:
        """
        종목 리포트용 데이터 일괄 수집.
        
        Args:
            stock_code: 종목 코드
        
        Returns:
            CollectedData
        
        Raises:
            DataCollectionError: 필수 데이터 수집 실패
        """
        started = datetime.utcnow()
        sources_used = []
        sources_failed = []
        
        # 1. 필수 데이터
        try:
            basic_info = await self._kiwoom.get_stock_info(stock_code)
            sources_used.append("kiwoom_basic")
        except Exception as e:
            raise DataCollectionError(f"Failed to get basic info: {e}")
        
        try:
            financial_summary = await self._collect_financial(stock_code)
            sources_used.append("kiwoom_financial")
        except Exception as e:
            raise DataCollectionError(f"Failed to get financial: {e}")
        
        # 2. 권장 데이터 (실패 시 None)
        recent_disclosures = None
        try:
            recent_disclosures = await self._dart.get_recent_disclosures(
                stock_code,
                from_date=datetime.utcnow() - timedelta(days=30),
            )
            sources_used.append("dart")
        except Exception as e:
            sources_failed.append(f"dart: {e}")
        
        recent_news = None
        try:
            recent_news = await self._news.search_news(
                query=basic_info["stock_name"],
                from_date=datetime.utcnow() - timedelta(days=14),
                limit=20,
            )
            sources_used.append("naver_news")
        except Exception as e:
            sources_failed.append(f"naver_news: {e}")
        
        price_history = None
        try:
            price_history = await self._kiwoom.get_price_history(
                stock_code, period="5y"
            )
            sources_used.append("kiwoom_history")
        except Exception as e:
            sources_failed.append(f"kiwoom_history: {e}")
        
        # 3. 선택 데이터 (실패 무시)
        peer_data = None
        foreign_ownership = None
        try:
            peer_data = await self._collect_peers(stock_code)
            sources_used.append("peer_data")
        except Exception:
            pass
        
        try:
            foreign_ownership = await self._kiwoom.get_foreign_ownership(stock_code)
            sources_used.append("foreign_ownership")
        except Exception:
            pass
        
        return CollectedData(
            basic_info=basic_info,
            financial_summary=financial_summary,
            recent_disclosures=recent_disclosures,
            recent_news=recent_news,
            price_history=price_history,
            peer_data=peer_data,
            foreign_ownership=foreign_ownership,
            collection_started_at=started,
            collection_completed_at=datetime.utcnow(),
            sources_used=sources_used,
            sources_failed=sources_failed,
        )
    
    async def _collect_financial(self, stock_code: str) -> dict:
        """최근 4분기 재무 수집."""
        # 키움 또는 DART에서 분기별 재무
        # YoY 계산
        ...
    
    async def _collect_peers(self, stock_code: str) -> List[dict]:
        """동종업계 비교 데이터."""
        # 같은 섹터 회사 3~5개
        # 시가총액, PER, PBR 등
        ...
```

### 4.4 캐싱 전략

```yaml
캐싱 (선택, 비용 절감):
  - 종목 기본 정보: 1일 캐시
  - 재무 데이터: 1일 캐시
  - 뉴스: 캐시 안 함 (실시간)
  - 공시: 1시간 캐시

저장:
  Redis (선택) 또는 PostgreSQL JSONB

최초 구현:
  캐시 없이 단순하게
  사용 빈도 낮으므로 비용 부담 적음
```

---

## §5. Claude API 활용

### 5.1 모델 선택

```yaml
모델: claude-opus-4-7 (또는 최신 Opus)
이유:
  - 가장 깊이 있는 분석
  - 한국어 우수
  - 추론 능력 (사실 통합)
  - 글쓰기 품질

대안 (선택):
  - claude-sonnet-4-7: 비용 절감 시
    - PART 1만 sonnet
    - PART 2는 opus (정확성 중요)
```

### 5.2 API 호출 클라이언트

```python
# src/core/v71/report/claude_api_client.py

"""
Claude API 클라이언트 (리포트 생성용).
"""

import anthropic
from dataclasses import dataclass
from typing import Optional

@dataclass
class ClaudeAPIResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    duration_seconds: float


class V71ClaudeAPIClient:
    """Anthropic Claude API 클라이언트."""
    
    def __init__(self, api_key: str):
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = "claude-opus-4-7"
    
    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 8000,
        temperature: float = 0.7,
    ) -> ClaudeAPIResponse:
        """
        Claude API 호출.
        
        Args:
            system_prompt: 시스템 프롬프트
            user_prompt: 사용자 프롬프트
            max_tokens: 최대 출력 토큰
            temperature: 0.0 (정확) ~ 1.0 (창의)
        
        Returns:
            ClaudeAPIResponse
        """
        import time
        start = time.perf_counter()
        
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_prompt},
            ],
        )
        
        duration = time.perf_counter() - start
        
        # 응답 추출
        text = ""
        for block in response.content:
            if block.type == "text":
                text += block.text
        
        return ClaudeAPIResponse(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
            duration_seconds=duration,
        )
```

### 5.3 두 번 호출 vs 한 번 호출

```yaml
옵션 1: PART 1과 PART 2 별도 호출 (권장)
  장점:
    - 각 PART 최적화된 프롬프트
    - 더 깊이 있는 결과
    - 토큰 한도 여유 (PART 1, 2 각 8000)
    - 실패 시 부분 복구 가능
  단점:
    - 비용 2배
    - 시간 2배

옵션 2: 한 번에 호출
  장점:
    - 비용/시간 절감
    - 일관성
  단점:
    - 토큰 한도 빠듯 (16000)
    - 깊이 부족 가능

선택: 옵션 1 (별도 호출)
  사용 빈도 낮아 비용 부담 적음
  품질 우선
```

---

## §6. 프롬프트 엔지니어링

### 6.1 PART 1 프롬프트

```yaml
시스템 프롬프트:
"""
당신은 한국 주식 시장 전문 분석가입니다.

역할:
사용자에게 종목을 친구에게 설명하듯이 이야기 형태로 풀어주세요.
4단계 구조: 출발(Origin) → 성장(Growth) → 현재(Now) → 미래(Future)

원칙:
1. 사실 기반 (추측 금지, 환각 금지)
2. 균형 잡힌 시각 (긍정/부정 모두)
3. 명료한 한국어 (전문 용어 풀어서)
4. 차분한 톤 (과장 X)
5. 매수/매도 추천 절대 금지
6. 가격 예측 절대 금지
7. 분량: A4 1~1.5페이지 (800~1500자)

형식:
Markdown 형태로 작성.
H1, H2 헤딩 사용.
적절히 단락 구분.

출처:
가능하면 데이터 출처 암시 ("최근 발표에 따르면", "분기보고서에 의하면")
불확실한 정보는 "알려져 있다", "보도에 따르면" 사용

이야기 톤:
- "주목할 점은..."
- "흥미롭게도..."
- "한편..."
- "역사를 보면..."
"""

사용자 프롬프트:
f"""
다음 종목에 대한 PART 1 (이야기) 리포트를 작성해주세요.

종목: {stock_name} ({stock_code})

수집된 데이터:
[basic_info JSON]
[recent_disclosures JSON]
[recent_news JSON]
[price_history summary]

위 데이터와 당신의 사전 지식을 결합하여
4단계 구조 (출발/성장/현재/미래) 이야기를 작성해주세요.

특히 강조:
- 회사가 풀려는 핵심 문제
- 핵심 변곡점들
- 현재 시장 위치와 모멘텀
- 향후 1~3년 전망과 리스크
"""
```

### 6.2 PART 2 프롬프트

```yaml
시스템 프롬프트:
"""
당신은 한국 주식 시장 전문 분석가입니다.

역할:
종목에 대한 객관적이고 검증 가능한 팩트만 정리하세요.

7개 섹션:
1. 회사 개요
2. 사업 부문
3. 공급망 (★ 깊이 있게: 칩, 재료, 공급사)
4. 재무 요약
5. 최근 공시 (1개월)
6. 최근 뉴스 (2주)
7. 동종업계 비교

원칙:
1. 모든 사실에 출처 명시 ([DART, 2026-02-01], [연합뉴스, 2026-04-20])
2. 숫자는 정확히 (단위, 시점 명시)
3. "약", "대략" 회피 (정확한 숫자)
4. 불확실하면 "보도에 따르면", "알려진 바로는"
5. 매수/매도 의견 절대 금지
6. 분량: A4 1~1.5페이지 (1000~1800자)

특별 강조 - 공급망 (3번):
다른 리포트에서 안 다루는 깊이 있는 분석을 해주세요:
- 어떤 핵심 부품/원재료를 사용하는가?
- 공급사는 누구인가?
- 지정학적 리스크 (중국, 미국)
- 가격 변동성에 어떤 영향을 받는가?
- 핵심 고객은 누구인가? (B2B의 경우)

형식:
Markdown.
각 섹션 H2 헤딩.
표 활용 가능 (재무, 동종업계).
출처 명시 (괄호로).
"""

사용자 프롬프트:
f"""
다음 종목의 PART 2 (객관 팩트) 리포트를 작성해주세요.

종목: {stock_name} ({stock_code})

수집된 데이터:
[basic_info JSON]
[financial_summary JSON]
[recent_disclosures JSON]  # 1개월
[recent_news JSON]  # 2주
[peer_data JSON]
[foreign_ownership]

특히 공급망 섹션은 다음을 포함:
- 핵심 칩/부품/원재료
- 주요 공급사 (가능하면 회사명)
- 주요 고객 (B2B의 경우)
- 지정학적 리스크
- 비용 구조

당신의 사전 지식 + 위 데이터로 정확한 팩트만 작성.
숫자는 출처와 시점 명시.
"""
```

### 6.3 프롬프트 개선 (반복)

```yaml
초기 운영:
  몇 건 생성 후 사용자 피드백
  프롬프트 조정

피드백 수집:
  사용자 메모 (생성 후 추가)에서
  "이런 정보가 부족했다"
  "이건 너무 길다"

개선 루프:
  프롬프트 v1 → 사용자 피드백 → v2 → ...

버전 관리:
  src/core/v71/report/prompts/v1.yaml
  src/core/v71/report/prompts/v2.yaml
  사용 모델: 최신 버전
```

---

## §7. 생성 워크플로우

### 7.1 전체 플로우

```
사용자 요청 (POST /api/v71/reports/request)
    ↓
1. 리포트 레코드 생성 (status=PENDING)
    ↓
2. 비동기 작업 큐에 추가
    ↓
3. 응답 반환 (report_id, 예상 시간)

------ 비동기 ------

4. 데이터 수집 (V71DataCollector)
    - 키움 API
    - DART API
    - 네이버 뉴스
    - 30~60초 소요
    ↓
5. 상태 업데이트: status=GENERATING
    ↓
6. PART 1 생성 (Claude API)
    - 60~120초 소요
    ↓
7. PART 2 생성 (Claude API)
    - 60~120초 소요
    ↓
8. PDF 생성
    ↓
9. Excel 생성
    ↓
10. DB 저장 (status=COMPLETED)
    ↓
11. 사용자 알림 (텔레그램 LOW)
    "삼성전자 리포트 생성 완료. 웹에서 확인."
```

### 7.2 비동기 실행

```python
# src/core/v71/report/report_generator.py

"""
리포트 생성 메인 워크플로우.
"""

import asyncio
from datetime import datetime

class V71ReportGenerator:
    """리포트 생성기."""
    
    def __init__(
        self,
        data_collector,
        claude_client,
        report_storage,
        pdf_exporter,
        excel_exporter,
        notification_skill,
    ):
        self._collector = data_collector
        self._claude = claude_client
        self._storage = report_storage
        self._pdf = pdf_exporter
        self._excel = excel_exporter
        self._notify = notification_skill
    
    async def generate(
        self,
        report_id: UUID,
        stock_code: str,
        requested_by: UUID,
    ):
        """
        리포트 생성 전체 워크플로우.
        
        비동기 백그라운드 실행.
        실패 시 status=FAILED + 에러 메시지.
        """
        try:
            # 1. 상태: GENERATING
            await self._storage.update_status(
                report_id, "GENERATING", started_at=datetime.utcnow()
            )
            
            # 2. 데이터 수집
            data = await self._collector.collect(stock_code)
            
            # 3. PART 1 생성
            part1_response = await self._generate_part1(stock_code, data)
            
            # 4. PART 2 생성
            part2_response = await self._generate_part2(stock_code, data)
            
            # 5. 합치기
            report_content = {
                "narrative_part": part1_response.text,
                "facts_part": part2_response.text,
                "data_sources": data.sources_used,
                "input_tokens": part1_response.input_tokens + part2_response.input_tokens,
                "output_tokens": part1_response.output_tokens + part2_response.output_tokens,
            }
            
            # 6. PDF 생성
            pdf_path = await self._pdf.generate(report_id, report_content, data)
            
            # 7. Excel 생성
            excel_path = await self._excel.generate(report_id, report_content, data)
            
            # 8. DB 저장 완료
            await self._storage.complete(
                report_id=report_id,
                content=report_content,
                pdf_path=pdf_path,
                excel_path=excel_path,
                completed_at=datetime.utcnow(),
            )
            
            # 9. 알림
            await self._notify.send_low_priority(
                event_type="REPORT_COMPLETED",
                stock_code=stock_code,
                payload={"report_id": str(report_id)},
            )
        
        except Exception as e:
            # 실패 처리
            await self._storage.fail(
                report_id=report_id,
                error_message=str(e),
            )
            
            await self._notify.send_high_priority(
                event_type="REPORT_FAILED",
                stock_code=stock_code,
                payload={"report_id": str(report_id), "error": str(e)},
            )
            
            raise
    
    async def _generate_part1(self, stock_code, data):
        """PART 1: 이야기."""
        from src.core.v71.report.prompts import get_part1_prompt
        
        system, user = get_part1_prompt(stock_code, data)
        return await self._claude.generate(
            system_prompt=system,
            user_prompt=user,
            max_tokens=4000,
            temperature=0.7,
        )
    
    async def _generate_part2(self, stock_code, data):
        """PART 2: 객관 팩트."""
        from src.core.v71.report.prompts import get_part2_prompt
        
        system, user = get_part2_prompt(stock_code, data)
        return await self._claude.generate(
            system_prompt=system,
            user_prompt=user,
            max_tokens=4000,
            temperature=0.4,  # 사실 위주, 낮은 온도
        )
```

### 7.3 진행 상황 표시

```yaml
사용자 경험:
  요청 후: "리포트 생성 중... 예상 5분"
  
  진행 단계 (선택):
    [▓▓░░░░░░░░] 20% - 데이터 수집 중
    [▓▓▓▓▓░░░░░] 50% - PART 1 작성 중
    [▓▓▓▓▓▓▓▓░░] 80% - PART 2 작성 중
    [▓▓▓▓▓▓▓▓▓▓] 100% - 완료

기술:
  WebSocket으로 진행률 push
  또는 폴링 (GET /api/v71/reports/{id})
```

---

## §8. PDF / Excel 생성

### 8.1 PDF 생성

```yaml
라이브러리: reportlab 또는 weasyprint
권장: weasyprint (HTML/CSS 기반, 디자인 자유)

레이아웃:
  표지:
    - 종목명 + 코드
    - 생성일
    - V7.1 로고
  
  목차 (자동)
  
  PART 1: 이야기 (1~1.5 페이지)
  PART 2: 객관 팩트 (1~1.5 페이지)
  
  부록:
    - 데이터 소스
    - 면책 조항
    - 메타정보

폰트:
  본문: 나눔명조 또는 Pretendard
  제목: 굵게
  숫자: 모노스페이스

스타일:
  - 깔끔한 레이아웃
  - 충분한 여백
  - A4 사이즈
  - 한국어 최적화
```

### 8.2 PDF 코드 예시

```python
# src/core/v71/report/exporters.py

"""
PDF / Excel 생성기.
"""

from weasyprint import HTML, CSS
from datetime import datetime
from pathlib import Path
import jinja2


class V71PDFExporter:
    """PDF 생성기 (WeasyPrint 기반)."""
    
    def __init__(self, output_dir: Path):
        self._output_dir = output_dir
        self._jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader("src/core/v71/report/templates"),
            autoescape=True,
        )
    
    async def generate(
        self,
        report_id: UUID,
        report_content: dict,
        data: CollectedData,
    ) -> str:
        """PDF 생성."""
        # 1. HTML 템플릿 렌더링
        template = self._jinja_env.get_template("report.html")
        html = template.render(
            stock_code=data.basic_info["stock_code"],
            stock_name=data.basic_info["stock_name"],
            generated_at=datetime.utcnow(),
            narrative_part=report_content["narrative_part"],
            facts_part=report_content["facts_part"],
            data_sources=report_content["data_sources"],
            metadata={
                "model": "claude-opus-4-7",
                "input_tokens": report_content["input_tokens"],
                "output_tokens": report_content["output_tokens"],
            },
        )
        
        # 2. CSS
        css = CSS(filename="src/core/v71/report/templates/report.css")
        
        # 3. PDF 생성
        output_path = self._output_dir / f"report_{report_id}.pdf"
        HTML(string=html).write_pdf(str(output_path), stylesheets=[css])
        
        return str(output_path)
```

### 8.3 HTML 템플릿

```html
<!-- src/core/v71/report/templates/report.html -->
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>{{ stock_name }} 리포트</title>
</head>
<body>
    <!-- 표지 -->
    <section class="cover">
        <h1>{{ stock_name }}</h1>
        <p class="code">{{ stock_code }}</p>
        <p class="date">생성일: {{ generated_at.strftime('%Y-%m-%d') }}</p>
        <p class="logo">K-Stock Trading V7.1</p>
    </section>
    
    <!-- PART 1 -->
    <section class="part1">
        <h1>PART 1: 이야기</h1>
        <div class="markdown-content">
            {{ narrative_part | markdown_to_html | safe }}
        </div>
    </section>
    
    <!-- PART 2 -->
    <section class="part2">
        <h1>PART 2: 객관 팩트</h1>
        <div class="markdown-content">
            {{ facts_part | markdown_to_html | safe }}
        </div>
    </section>
    
    <!-- 부록 -->
    <section class="appendix">
        <h2>데이터 소스</h2>
        <ul>
            {% for source in data_sources %}
            <li>{{ source }}</li>
            {% endfor %}
        </ul>
        
        <h2>면책 조항</h2>
        <p>
            본 리포트는 AI(Claude Opus 4.7)가 작성한 자료이며,
            투자 판단의 참고 자료일 뿐입니다.
            매수/매도 추천이 아니며, 투자 결과에 책임지지 않습니다.
            데이터의 정확성은 사용자가 검증해야 합니다.
        </p>
        
        <h2>메타정보</h2>
        <table>
            <tr><th>모델</th><td>{{ metadata.model }}</td></tr>
            <tr><th>입력 토큰</th><td>{{ metadata.input_tokens }}</td></tr>
            <tr><th>출력 토큰</th><td>{{ metadata.output_tokens }}</td></tr>
        </table>
    </section>
</body>
</html>
```

### 8.4 Excel 생성

```yaml
라이브러리: openpyxl

시트 구성:
  - Sheet 1: 요약 (Summary)
  - Sheet 2: 재무 (Financials) - 표 위주
  - Sheet 3: 공시 (Disclosures)
  - Sheet 4: 뉴스 (News)
  - Sheet 5: 동종업계 (Peers)
  - Sheet 6: PART 1 (Narrative) - 텍스트
  - Sheet 7: PART 2 (Facts) - 텍스트

용도:
  데이터 분석가용
  엑셀에서 추가 가공 가능
  스크리닝, 비교 분석
```

---

## §9. DB 저장 및 조회

### 9.1 저장 (V71ReportStorage)

```python
# src/core/v71/report/report_storage.py

class V71ReportStorage:
    """리포트 DB 저장/조회."""
    
    async def create_pending(
        self,
        stock_code: str,
        stock_name: str,
        tracked_stock_id: Optional[UUID],
        requested_by: UUID,
    ) -> UUID:
        """리포트 레코드 생성 (PENDING 상태)."""
        report_id = uuid4()
        await self._db.execute(
            """
            INSERT INTO daily_reports (
                id, stock_code, stock_name, tracked_stock_id, 
                requested_by, requested_at, status, model_version
            ) VALUES ($1, $2, $3, $4, $5, NOW(), 'PENDING', 'claude-opus-4-7')
            """,
            report_id, stock_code, stock_name, tracked_stock_id, requested_by,
        )
        return report_id
    
    async def update_status(self, report_id, status, **kwargs):
        """상태 업데이트."""
        ...
    
    async def complete(
        self,
        report_id: UUID,
        content: dict,
        pdf_path: str,
        excel_path: str,
        completed_at: datetime,
    ):
        """완료 처리."""
        await self._db.execute(
            """
            UPDATE daily_reports SET
                status = 'COMPLETED',
                narrative_part = $2,
                facts_part = $3,
                data_sources = $4,
                prompt_tokens = $5,
                completion_tokens = $6,
                pdf_path = $7,
                excel_path = $8,
                generation_completed_at = $9,
                generation_duration_seconds = EXTRACT(EPOCH FROM ($9 - generation_started_at))
            WHERE id = $1
            """,
            report_id,
            content["narrative_part"],
            content["facts_part"],
            content["data_sources"],
            content["input_tokens"],
            content["output_tokens"],
            pdf_path,
            excel_path,
            completed_at,
        )
    
    async def fail(self, report_id, error_message):
        """실패 처리."""
        ...
    
    async def get_by_id(self, report_id) -> Optional[Report]:
        """단일 조회."""
        ...
    
    async def list_by_stock(
        self,
        stock_code: str,
        limit: int = 20,
    ) -> List[Report]:
        """종목별 리포트 이력."""
        ...
```

### 9.2 조회 패턴

```yaml
사용자 시나리오:

1. 종목 상세 페이지에서:
   GET /api/v71/reports?stock_code=005930
   → 해당 종목 리포트 이력 (시간순)

2. 전체 리포트 리스트:
   GET /api/v71/reports
   → 최근 생성된 리포트들

3. 단일 리포트 읽기:
   GET /api/v71/reports/{id}
   → 전체 내용 (PART 1 + PART 2)

4. 비교 (선택):
   같은 종목 6개월 전 vs 현재
   "어떻게 변했나" 자동 비교 (선택 기능)

영구 보존:
  daily_reports 테이블 (03_DATA_MODEL.md §4.1)
  PDF/Excel 파일 별도 저장
```

---

## §10. 비용 관리

### 10.1 비용 추정

```yaml
Claude Opus 4.7 가격 (가정):
  Input: $15 / 1M tokens
  Output: $75 / 1M tokens

리포트 1건당:
  PART 1: Input ~6000, Output ~2500
    비용: 0.09 + 0.19 = $0.28
  PART 2: Input ~7000, Output ~2500
    비용: 0.105 + 0.19 = $0.30
  
  합계: ~$0.58/건

월 사용량 (예상):
  10건: $5.8
  20건: $11.6
  30건: $17.4

연 200건: ~$120

→ 부담 적음
```

### 10.2 비용 한도

```yaml
선택 기능: 월간 한도

설정:
  user_settings.report_monthly_limit: 30 (기본)
  
한도 도달 시:
  - 새 리포트 요청 거부
  - 텔레그램 알림: "월 한도 도달"
  - 다음 달 1일 리셋

표시:
  설정 페이지에서 사용량 확인
  대시보드에 "월 사용: 5/30"
```

### 10.3 토큰 절감 전략

```yaml
1. 데이터 압축:
   - 필수 데이터만 프롬프트에 포함
   - 긴 뉴스는 요약 후 입력
   - 중복 정보 제거

2. 모델 차등 (선택):
   - PART 1: claude-sonnet-4-7 (더 저렴)
   - PART 2: claude-opus-4-7 (정확성)
   - 비용 ~50% 절감

3. 캐싱:
   - 같은 종목 24시간 내 재요청 시 기존 사용
   - 또는 사용자에게 "최근 리포트 있음" 안내
   - 강제 재생성 옵션

4. 분량 조정:
   - 현재: 2~3페이지
   - 짧은 버전: 1~1.5페이지 (선택)
```

### 10.4 사용량 추적

```yaml
DB 추적 (daily_reports.prompt_tokens, completion_tokens):
  매월 집계
  사용자 알림

쿼리 예시:
  SELECT 
    DATE_TRUNC('month', created_at) AS month,
    COUNT(*) AS count,
    SUM(prompt_tokens) AS total_input,
    SUM(completion_tokens) AS total_output,
    SUM(prompt_tokens) * 0.000015 + SUM(completion_tokens) * 0.000075 AS cost_usd
  FROM daily_reports
  WHERE status = 'COMPLETED'
  GROUP BY month
  ORDER BY month DESC;

대시보드 표시:
  "이번 달 리포트: 5건, 약 $3.20 사용"
```

---

## 부록 A: 리포트 품질 검증

### A.1 자동 검증

```yaml
생성 후 자동 체크:
  1. 분량: 각 PART 800~3000자 (너무 짧거나 길지 않음)
  2. 구조: H1 1개 (제목), H2 4개 (PART 1) 또는 7개 (PART 2)
  3. 출처 명시: PART 2에 출처 표기 N개 이상
  4. 금지 단어: "매수 추천", "강력 추천", "확실히 오를"
  5. 숫자 형식: 천 단위 콤마 또는 정확한 단위

위반 시:
  자동 재생성 or 사용자에게 경고
```

### A.2 사용자 피드백

```yaml
리포트 읽기 화면에 평가:
  ⭐⭐⭐⭐⭐ (5점)
  
  좋았던 점 (선택):
    ☐ PART 1 이야기가 흥미로움
    ☐ PART 2 깊이 있는 정보
    ☐ 공급망 분석 유용
    ☐ 출처 명확
  
  부족한 점 (선택):
    ☐ 너무 일반적 (구체성 부족)
    ☐ 정보 부정확
    ☐ 분량 적당하지 않음
    ☐ 환각/오류 발견
  
  자유 코멘트

피드백 활용:
  프롬프트 개선
  품질 추적
  주기적 리뷰
```

---

## 부록 B: 미정 사항

```yaml
B.1 Claude API 정확한 모델명/가격:
  실제 사용 시 최신 가격 적용
  Anthropic 공식 사이트 확인

B.2 DART API 정확한 사용법:
  공식 OpenDART API 활용
  https://opendart.fss.or.kr/

B.3 네이버 뉴스 API:
  검색 API 사용
  Rate Limit 확인

B.4 PDF/Excel 디자인:
  초안 후 사용자 피드백
  반복 개선

B.5 리포트 비교 기능:
  같은 종목 시간 차이 비교
  자동 변경점 추출
  Phase 2 기능 (초기 미포함)

B.6 다국어 지원:
  한국어 우선
  영어 옵션 (선택)
```

---

*이 문서는 V7.1 리포트 시스템의 단일 진실 원천입니다.*  
*Claude Opus 4.7 활용으로 깊이 있는 종목 분석을 제공합니다.*  
*사용자 요청 시에만 생성 (On-Demand).*

*최종 업데이트: 2026-04-25*
