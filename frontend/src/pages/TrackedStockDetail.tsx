import { useParams } from 'react-router-dom';

export function TrackedStockDetail() {
  const { id } = useParams<{ id: string }>();
  return (
    <div>
      <div className="page-hd">
        <div>
          <h1 className="page-hd__title">추적 종목 상세 ({id ?? '-'})</h1>
          <div className="page-hd__subtitle">
            P5.3 다음 단계에서 본 화면이 구현됩니다.
          </div>
        </div>
      </div>
    </div>
  );
}
