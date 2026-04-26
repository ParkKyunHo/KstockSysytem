import { useParams } from 'react-router-dom';
import { PlaceholderPage } from '@/components/shell/PlaceholderPage';

export function TrackedStockDetail() {
  const { id } = useParams<{ id: string }>();
  return (
    <PlaceholderPage
      title={`추적 종목 상세 (${id ?? '-'})`}
      phase="P5.3"
      description="Breadcrumb + Tile + Tabs (박스 / 포지션 / 거래 이벤트)"
    />
  );
}
