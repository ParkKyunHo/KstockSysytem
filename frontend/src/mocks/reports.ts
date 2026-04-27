// V7.1 Reports mock -- mirrors frontend-prototype/src/mocks/index.js (8 reports).

import type { Report } from '@/types';
import { isoMinusDay, isoMinusHour, isoMinusMin } from '@/lib/time';

const samsungNarrative = `## 삼성전자의 이야기

**메모리 반도체의 대장.** 2025년 한 해 HBM3E 양산 캐파를 두 배로 늘리며 SK하이닉스에 빼앗겼던 AI 메모리 시장 점유율을 빠르게 되찾았다.

### 사업 구조

- **DS 부문 (반도체)**: 매출의 60% 이상
- **DX 부문 (스마트폰/가전)**: 30%
- **하만 (전장)**: 10%

### 최근 분기 핵심 변화

2026 1Q 영업이익 7.1조 원 — 컨센서스 6.4조 원 상회. 메모리 가격 상승 + HBM 비중 확대가 견인했다.

### 전략 의미

PATH_A 단타로 박스 잡기에 적합한 종목. 거래대금 3조 원대로 유동성 충분.`;

const samsungFacts = `## 객관 팩트

| 항목 | 값 |
|------|-----|
| 시가총액 | 432조 원 |
| 1년 최고 / 최저 | 78,500 / 65,200원 |
| PER (TTM) | 14.2 |
| PBR | 1.4 |
| 배당수익률 | 1.9% |

### 최근 공시 (60일)
- 2026-04-12: 자사주 매입 1조 원 결의
- 2026-03-28: 1Q 잠정실적 발표
- 2026-03-15: HBM4 첫 샘플 출하

### 외인/기관 수급 (5일)
- 외인: +2,850억 원
- 기관: +1,420억 원`;

export const mockReports: Report[] = [
  {
    id: 'r-001',
    stock_code: '005930',
    stock_name: '삼성전자',
    status: 'COMPLETED',
    model_version: 'claude-opus-4.5',
    prompt_tokens: 12450,
    completion_tokens: 8230,
    narrative_part: samsungNarrative,
    facts_part: samsungFacts,
    pdf_path: '/reports/r-001.pdf',
    excel_path: '/reports/r-001.xlsx',
    user_notes: 'HBM 수혜 지속 — 1차 박스 진입 시 비중 10%로 포지션 시작',
    generation_started_at: isoMinusDay(1),
    generation_completed_at: isoMinusHour(23),
    generation_duration_seconds: 312,
    created_at: isoMinusDay(1),
  },
  {
    id: 'r-002',
    stock_code: '000660',
    stock_name: 'SK하이닉스',
    status: 'COMPLETED',
    model_version: 'claude-opus-4.5',
    prompt_tokens: 11200,
    completion_tokens: 7950,
    narrative_part: '## SK하이닉스 이야기\n\nHBM 시장의 압도적 1등.',
    facts_part: '## 객관 팩트\n시가총액 162조 원.',
    pdf_path: '/reports/r-002.pdf',
    excel_path: '/reports/r-002.xlsx',
    user_notes: null,
    generation_started_at: isoMinusDay(2),
    generation_completed_at: isoMinusDay(2),
    generation_duration_seconds: 285,
    created_at: isoMinusDay(2),
  },
  {
    id: 'r-003',
    stock_code: '247540',
    stock_name: '에코프로비엠',
    status: 'GENERATING',
    model_version: 'claude-opus-4.5',
    prompt_tokens: null,
    completion_tokens: null,
    narrative_part: null,
    facts_part: null,
    pdf_path: null,
    excel_path: null,
    user_notes: null,
    progress: 64,
    generation_started_at: isoMinusMin(3),
    generation_completed_at: null,
    generation_duration_seconds: null,
    created_at: isoMinusMin(3),
  },
  {
    id: 'r-004',
    stock_code: '042660',
    stock_name: '한화오션',
    status: 'COMPLETED',
    model_version: 'claude-sonnet-4.5',
    prompt_tokens: 8800,
    completion_tokens: 5600,
    narrative_part: '## 한화오션',
    facts_part: '## 팩트',
    pdf_path: '/reports/r-004.pdf',
    excel_path: '/reports/r-004.xlsx',
    user_notes: null,
    generation_started_at: isoMinusDay(3),
    generation_completed_at: isoMinusDay(3),
    generation_duration_seconds: 198,
    created_at: isoMinusDay(3),
  },
  {
    id: 'r-005',
    stock_code: '267260',
    stock_name: 'HD현대일렉트릭',
    status: 'PENDING',
    model_version: 'claude-opus-4.5',
    prompt_tokens: null,
    completion_tokens: null,
    narrative_part: null,
    facts_part: null,
    pdf_path: null,
    excel_path: null,
    user_notes: null,
    generation_started_at: null,
    generation_completed_at: null,
    generation_duration_seconds: null,
    created_at: isoMinusMin(8),
  },
  {
    id: 'r-006',
    stock_code: '293490',
    stock_name: '카카오게임즈',
    status: 'FAILED',
    model_version: 'claude-opus-4.5',
    prompt_tokens: 4200,
    completion_tokens: null,
    narrative_part: null,
    facts_part: null,
    pdf_path: null,
    excel_path: null,
    user_notes: null,
    error_message: 'Anthropic API 일시적 503',
    generation_started_at: isoMinusHour(4),
    generation_completed_at: null,
    generation_duration_seconds: null,
    created_at: isoMinusHour(4),
  },
  {
    id: 'r-007',
    stock_code: '012450',
    stock_name: '한화에어로스페이스',
    status: 'COMPLETED',
    model_version: 'claude-opus-4.5',
    prompt_tokens: 13500,
    completion_tokens: 9100,
    narrative_part: '## 한화에어로스페이스',
    facts_part: '## 팩트',
    pdf_path: '/reports/r-007.pdf',
    excel_path: '/reports/r-007.xlsx',
    user_notes: null,
    generation_started_at: isoMinusDay(4),
    generation_completed_at: isoMinusDay(4),
    generation_duration_seconds: 340,
    created_at: isoMinusDay(4),
  },
  {
    id: 'r-008',
    stock_code: '034020',
    stock_name: '두산에너빌리티',
    status: 'COMPLETED',
    model_version: 'claude-sonnet-4.5',
    prompt_tokens: 7800,
    completion_tokens: 5200,
    narrative_part: '## 두산에너빌리티',
    facts_part: '## 팩트',
    pdf_path: '/reports/r-008.pdf',
    excel_path: '/reports/r-008.xlsx',
    user_notes: null,
    generation_started_at: isoMinusDay(5),
    generation_completed_at: isoMinusDay(5),
    generation_duration_seconds: 167,
    created_at: isoMinusDay(5),
  },
];
