import { Btn } from '@/components/ui';

export function TrackedStocks() {
  return (
    <div>
      <div className="page-hd">
        <div>
          <h1 className="page-hd__title">추적 종목</h1>
          <div className="page-hd__subtitle">
            P5.3 다음 단계에서 본 화면이 구현됩니다 (PRD Patch #3 -- 경로 선택 UI 없음).
          </div>
        </div>
        <div className="page-hd__actions">
          <Btn kind="primary" size="sm">새 종목 추적</Btn>
        </div>
      </div>
    </div>
  );
}
