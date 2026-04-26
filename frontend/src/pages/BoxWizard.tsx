import { PlaceholderPage } from '@/components/shell/PlaceholderPage';

/**
 * PRD Patch #3 적용: 7-step (Step 1 경로 선택 추가).
 *
 * 1. 경로 선택 (PATH_A 단타 / PATH_B 중기) -- ★ Patch #3 신규
 * 2. 진입 전략 (PULLBACK / BREAKOUT)
 * 3. 가격 범위 (상단/하단)
 * 4. 비중 (%)
 * 5. 손절폭 (%)
 * 6. 확인
 * 7. 저장
 */
export function BoxWizard() {
  return (
    <PlaceholderPage
      title="박스 설정"
      phase="P5.3"
      description="7-step ProgressIndicator (Patch #3) -- 경로 → 전략 → 가격 → 비중 → 손절 → 확인 → 저장"
    />
  );
}
