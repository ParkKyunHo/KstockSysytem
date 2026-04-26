import { Tag } from '@carbon/react';
import type {
  BoxStatus,
  PositionSource,
  PositionStatus,
  Severity,
  TrackedStatus,
} from '@/types';

type CarbonTagType =
  | 'red'
  | 'magenta'
  | 'purple'
  | 'blue'
  | 'cyan'
  | 'teal'
  | 'green'
  | 'gray'
  | 'cool-gray'
  | 'warm-gray'
  | 'high-contrast'
  | 'outline';

// ---------------------------------------------------------------------
// Tracked status
// ---------------------------------------------------------------------

const TRACKED_TAG: Record<TrackedStatus, { type: CarbonTagType; label: string }> = {
  TRACKING: { type: 'gray', label: '추적' },
  BOX_SET: { type: 'blue', label: '박스 설정' },
  POSITION_OPEN: { type: 'green', label: '포지션 보유' },
  POSITION_PARTIAL: { type: 'cyan', label: '부분 청산' },
  EXITED: { type: 'cool-gray', label: '추적 종료' },
};

export function TrackedStatusTag({ status }: { status: TrackedStatus }) {
  const { type, label } = TRACKED_TAG[status];
  return <Tag type={type}>{label}</Tag>;
}

// ---------------------------------------------------------------------
// Box status
// ---------------------------------------------------------------------

const BOX_TAG: Record<BoxStatus, { type: CarbonTagType; label: string }> = {
  WAITING: { type: 'blue', label: '대기' },
  TRIGGERED: { type: 'green', label: '체결' },
  INVALIDATED: { type: 'cool-gray', label: '무효' },
  CANCELLED: { type: 'gray', label: '취소' },
};

export function BoxStatusTag({ status }: { status: BoxStatus }) {
  const { type, label } = BOX_TAG[status];
  return <Tag type={type}>{label}</Tag>;
}

// ---------------------------------------------------------------------
// Position source / status
// ---------------------------------------------------------------------

const POSITION_SOURCE_TAG: Record<
  PositionSource,
  { type: CarbonTagType; label: string }
> = {
  SYSTEM_A: { type: 'blue', label: 'PATH_A' },
  SYSTEM_B: { type: 'purple', label: 'PATH_B' },
  MANUAL: { type: 'magenta', label: 'MANUAL' },
};

export function PositionSourceTag({ source }: { source: PositionSource }) {
  const { type, label } = POSITION_SOURCE_TAG[source];
  return <Tag type={type}>{label}</Tag>;
}

const POSITION_STATUS_TAG: Record<
  PositionStatus,
  { type: CarbonTagType; label: string }
> = {
  OPEN: { type: 'green', label: 'OPEN' },
  PARTIAL_CLOSED: { type: 'cyan', label: '부분 청산' },
  CLOSED: { type: 'cool-gray', label: 'CLOSED' },
};

export function PositionStatusTag({ status }: { status: PositionStatus }) {
  const { type, label } = POSITION_STATUS_TAG[status];
  return <Tag type={type}>{label}</Tag>;
}

// ---------------------------------------------------------------------
// Notification severity
// ---------------------------------------------------------------------

const SEVERITY_TAG: Record<Severity, { type: CarbonTagType; label: string }> = {
  CRITICAL: { type: 'red', label: 'CRITICAL' },
  HIGH: { type: 'magenta', label: 'HIGH' },
  MEDIUM: { type: 'blue', label: 'MEDIUM' },
  LOW: { type: 'cool-gray', label: 'LOW' },
};

export function SeverityTag({ severity }: { severity: Severity }) {
  const { type, label } = SEVERITY_TAG[severity];
  return (
    <Tag type={type} size="sm">
      {label}
    </Tag>
  );
}
