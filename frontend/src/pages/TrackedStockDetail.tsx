// V7.1 TrackedStockDetail -- wired to /api/v71/tracked_stocks/{id} (PRD §3.4),
// /api/v71/boxes (PRD §4), /api/v71/positions (PRD §5),
// /api/v71/trade_events (PRD §6).
// PRD Patch #3 applied:
//   - No path tag in the page header (path is per-box).
//   - Boxes table includes a "Path" column.

import { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import type { BoxOut } from '@/api/boxes';
import type { PositionOut } from '@/api/positions';
import type { TrackedStockDetailOut } from '@/api/trackedStocks';
import { I } from '@/components/icons';
import { OrderDialog, type OrderSide } from '@/components/OrderDialog';
import {
  BoxStatusTag,
  Btn,
  ExpandableTile,
  Field,
  InlineNotif,
  Modal,
  NumInput,
  OverflowMenu,
  PnLCell,
  PositionSourceTag,
  Tabs,
  Tag,
  Textarea,
  Tile,
  ToastContainer,
  TrackedStatusTag,
  useToasts,
} from '@/components/ui';
import { useAppShellContext } from '@/hooks/useAppShell';
import {
  useBoxes,
  useDeleteBox,
  usePatchBox,
  usePositions,
  useTrackedStock,
  useTradeEvents,
} from '@/hooks/useApi';
import { ApiClientError } from '@/lib/api';
import { eventLabel } from '@/lib/eventLabel';
import {
  formatDateTime,
  formatKrw,
  formatPct,
  formatRelative,
} from '@/lib/formatters';
import type { StrategyType } from '@/types';

const TOTAL_CAPITAL = 100_000_000;

type DetailTab = 'boxes' | 'positions' | 'events';

interface OrderDialogState {
  side: OrderSide;
  position?: PositionOut;
}

export function TrackedStockDetail() {
  const { id } = useParams<{ id: string }>();
  const { mock } = useAppShellContext();
  const navigate = useNavigate();
  const { toasts, addToast, closeToast } = useToasts();

  const [tab, setTab] = useState<DetailTab>('boxes');
  const [editBox, setEditBox] = useState<BoxOut | null>(null);
  const [delBox, setDelBox] = useState<BoxOut | null>(null);
  const [orderDlg, setOrderDlg] = useState<OrderDialogState | null>(null);

  const { data: stock, isLoading } = useTrackedStock(id ?? null);
  const { data: boxList } = useBoxes(
    { tracked_stock_id: id, limit: 100 },
    { enabled: !!id },
  );
  const { data: positionList } = usePositions(
    { limit: 100 },
    { enabled: !!id },
  );
  const { data: eventList } = useTradeEvents(
    { tracked_stock_id: id, limit: 100 },
    { enabled: !!id },
  );

  const removeBox = useDeleteBox({
    onSuccess: () => {
      addToast({ kind: 'success', title: '박스 처리 완료' });
      setDelBox(null);
    },
    onError: (err) =>
      addToast({
        kind: 'error',
        title: '박스 처리 실패',
        subtitle: err instanceof ApiClientError ? err.message : undefined,
      }),
  });

  // Live price lookup (until WebSocket price channel is wired).
  const livePrice = useMemo(() => {
    if (!stock) return null;
    return (
      mock.trackedStocks.find((s) => s.stock_code === stock.stock_code)
        ?.current_price ?? null
    );
  }, [stock, mock.trackedStocks]);

  if (isLoading) {
    return (
      <div className="cds-tile">
        <p className="text-helper">불러오는 중…</p>
      </div>
    );
  }

  if (!stock) {
    return (
      <div className="cds-tile">
        <p>종목을 찾을 수 없습니다.</p>
      </div>
    );
  }

  const boxes = boxList?.data ?? [];
  const positions = (positionList?.data ?? []).filter(
    (p) => p.tracked_stock_id === stock.id,
  );
  const events = eventList?.data ?? [];

  const change =
    stock.summary.current_position_avg_price && livePrice
      ? ((livePrice - stock.summary.current_position_avg_price) /
          stock.summary.current_position_avg_price) *
        100
      : null;

  return (
    <div>
      {/* Breadcrumbs */}
      <div className="breadcrumbs">
        <a onClick={() => navigate('/tracked-stocks')}>추적 종목</a>
        <span className="sep">/</span>
        <span>{stock.stock_name}</span>
      </div>

      {/* Page header */}
      <div className="page-hd">
        <div>
          <h1 className="page-hd__title">
            {stock.stock_name}{' '}
            <span
              className="mono"
              style={{ fontSize: 16, color: 'var(--cds-text-helper)' }}
            >
              {stock.stock_code}
            </span>
          </h1>
          <div className="page-hd__subtitle">
            <TrackedStatusTag status={stock.status} sm />
            {' · '}
            {stock.market ?? '-'} · 등록 {formatRelative(stock.created_at)} · 출처{' '}
            {stock.source ?? '-'}
          </div>
        </div>
        <div className="page-hd__actions">
          <Btn
            kind="tertiary"
            size="sm"
            icon={I.Document}
            onClick={() => navigate('/reports')}
          >
            리포트 생성
          </Btn>
          <Btn
            kind="tertiary"
            size="sm"
            onClick={() => setOrderDlg({ side: 'BUY' })}
          >
            수동 매수
          </Btn>
          {positions.length > 0 ? (
            <Btn
              kind="tertiary"
              size="sm"
              onClick={() =>
                setOrderDlg({ side: 'SELL', position: positions[0] })
              }
            >
              수동 매도
            </Btn>
          ) : null}
          <Btn
            kind="primary"
            size="sm"
            icon={I.Add}
            onClick={() => navigate(`/boxes/new?stock_id=${id}`)}
          >
            박스 추가
          </Btn>
        </div>
      </div>

      {/* Current price tile */}
      <Tile>
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: 32,
            alignItems: 'flex-end',
          }}
        >
          <div>
            <div className="text-helper">현재가</div>
            <div
              className="mono"
              style={{ fontSize: 32, lineHeight: '40px' }}
            >
              {formatKrw(livePrice)}원
            </div>
          </div>
          {change != null ? (
            <div>
              <div className="text-helper">평단가 대비</div>
              <div
                className={change >= 0 ? 'pnl-profit' : 'pnl-loss'}
                style={{ fontSize: 20, fontFamily: 'var(--font-mono)' }}
              >
                {formatPct(change)}
              </div>
            </div>
          ) : null}
          {stock.user_memo ? (
            <div style={{ flex: 1, minWidth: 200 }}>
              <div className="text-helper">메모</div>
              <div>{stock.user_memo}</div>
            </div>
          ) : null}
        </div>
      </Tile>

      <div style={{ marginTop: 24 }}>
        <Tabs<DetailTab>
          value={tab}
          onChange={setTab}
          tabs={[
            { value: 'boxes', label: '박스', count: boxes.length },
            {
              value: 'positions',
              label: '포지션',
              count: positions.length,
            },
            { value: 'events', label: '거래 이벤트', count: events.length },
          ]}
        />
      </div>

      <div style={{ marginTop: 16 }}>
        {tab === 'boxes' ? (
          boxes.length === 0 ? (
            <EmptyTile
              msg="아직 박스가 없습니다."
              cta="박스 추가"
              onCta={() => navigate(`/boxes/new?stock_id=${id}`)}
            />
          ) : (
            <BoxesTable
              boxes={boxes}
              onEdit={setEditBox}
              onDelete={setDelBox}
              addToast={addToast}
            />
          )
        ) : null}

        {tab === 'positions' ? (
          positions.length === 0 ? (
            <EmptyTile msg="아직 포지션이 없습니다." />
          ) : (
            positions.map((p) => (
              <PositionTile key={p.id} position={p} livePrice={livePrice} />
            ))
          )
        ) : null}

        {tab === 'events' ? (
          events.length === 0 ? (
            <EmptyTile msg="거래 이벤트 없음" />
          ) : (
            <div className="cds-data-table">
              <table className="cds-table cds-table--compact">
                <thead>
                  <tr>
                    <th>시각</th>
                    <th>이벤트</th>
                    <th style={{ textAlign: 'right' }}>수량</th>
                    <th style={{ textAlign: 'right' }}>가격</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((e) => (
                    <tr key={e.id}>
                      <td className="mono">{formatDateTime(e.occurred_at)}</td>
                      <td>{eventLabel(e.event_type)}</td>
                      <td className="price">{e.quantity ?? '-'}</td>
                      <td className="price">{formatKrw(e.price)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        ) : null}
      </div>

      {editBox ? (
        <BoxEditModal
          box={editBox}
          stock={stock}
          livePrice={livePrice}
          siblingBoxes={boxes}
          onClose={() => setEditBox(null)}
          onSaved={() =>
            addToast({
              kind: 'success',
              title: '박스 변경 저장됨',
              subtitle: `${stock.stock_name} ${editBox.box_tier}차`,
            })
          }
          onError={(message) =>
            addToast({
              kind: 'error',
              title: '저장 실패',
              subtitle: message,
            })
          }
        />
      ) : null}

      {orderDlg ? (
        <OrderDialog
          open
          onClose={() => setOrderDlg(null)}
          mock={mock}
          addToast={addToast}
          defaultSide={orderDlg.side}
          defaultStock={
            mock.trackedStocks.find((s) => s.stock_code === stock.stock_code) ??
            undefined
          }
          defaultPosition={
            orderDlg.position
              ? mock.positions.find((p) => p.id === orderDlg.position?.id) ??
                undefined
              : undefined
          }
        />
      ) : null}

      {delBox ? (
        <Modal
          open
          danger
          onClose={() => setDelBox(null)}
          title={delBox.status === 'WAITING' ? '박스 취소' : '박스 비활성화'}
          subtitle={`${stock.stock_name} · ${delBox.box_tier}차 박스`}
          primary={{
            label: delBox.status === 'WAITING' ? '취소' : '비활성화',
            onClick: () => removeBox.mutate(delBox.id),
          }}
          secondary={{ label: '돌아가기', onClick: () => setDelBox(null) }}
        >
          <p>
            {formatKrw(delBox.lower_price)}~{formatKrw(delBox.upper_price)}원 ·{' '}
            {delBox.position_size_pct}% · {delBox.strategy_type}
          </p>
          <p className="text-helper">
            이 박스는 더 이상 진입 트리거를 발동하지 않습니다.
          </p>
        </Modal>
      ) : null}

      <ToastContainer toasts={toasts} onClose={closeToast} />
    </div>
  );
}

// ---------------------------------------------------------------------
// Boxes table
// ---------------------------------------------------------------------

interface BoxesTableProps {
  boxes: BoxOut[];
  onEdit: (b: BoxOut) => void;
  onDelete: (b: BoxOut) => void;
  addToast: ReturnType<typeof useToasts>['addToast'];
}

function BoxesTable({ boxes, onEdit, onDelete, addToast }: BoxesTableProps) {
  return (
    <div className="cds-data-table">
      <table className="cds-table">
        <thead>
          <tr>
            <th>Tier</th>
            <th>경로</th>
            <th style={{ textAlign: 'right' }}>가격대</th>
            <th style={{ textAlign: 'right' }}>비중</th>
            <th style={{ textAlign: 'right' }}>손절</th>
            <th>전략</th>
            <th>상태</th>
            <th style={{ textAlign: 'right' }}>거리</th>
            <th>메모</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {boxes.map((b) => {
            const editable = b.status === 'WAITING';
            return (
              <tr key={b.id}>
                <td>{b.box_tier}차</td>
                <td>
                  <Tag
                    type={b.path_type === 'PATH_A' ? 'blue' : 'purple'}
                    size="sm"
                  >
                    {b.path_type}
                  </Tag>
                </td>
                <td className="price">
                  {formatKrw(b.lower_price)} ~ {formatKrw(b.upper_price)}
                </td>
                <td className="price">{b.position_size_pct}%</td>
                <td className="price pnl-loss">{b.stop_loss_pct}%</td>
                <td>
                  <Tag type="cool-gray" size="sm">
                    {b.strategy_type}
                  </Tag>
                </td>
                <td>
                  <BoxStatusTag status={b.status} />
                </td>
                <td className="price">
                  {b.entry_proximity_pct != null
                    ? formatPct(b.entry_proximity_pct)
                    : '-'}
                </td>
                <td className="text-helper">{b.memo ?? '-'}</td>
                <td>
                  <OverflowMenu
                    items={[
                      {
                        label: '편집',
                        onClick: () => editable && onEdit(b),
                      },
                      {
                        label: '복제',
                        onClick: () =>
                          addToast({
                            kind: 'info',
                            title: '박스 복제 (스텁)',
                            subtitle: `${b.box_tier}차 박스 → 새 박스 생성`,
                          }),
                      },
                      { divider: true },
                      {
                        label: editable ? '취소' : '비활성화',
                        danger: true,
                        onClick: () => onDelete(b),
                      },
                    ]}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------
// Position tile
// ---------------------------------------------------------------------

function PositionTile({
  position: p,
  livePrice,
}: {
  position: PositionOut;
  livePrice: number | null;
}) {
  const pnlAmount =
    livePrice != null
      ? Math.round((livePrice - p.weighted_avg_price) * p.total_quantity)
      : 0;
  const pnlPct =
    livePrice != null && p.weighted_avg_price > 0
      ? ((livePrice - p.weighted_avg_price) / p.weighted_avg_price) * 100
      : 0;

  return (
    <ExpandableTile
      defaultOpen
      head={
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: 16,
          }}
        >
          <div>
            <strong>{p.stock_name}</strong>{' '}
            <PositionSourceTag source={p.source} />{' '}
            <span className="text-helper">
              {p.total_quantity}주 @ {formatKrw(p.weighted_avg_price)}
            </span>
          </div>
          <PnLCell amount={pnlAmount} pct={Number(pnlPct.toFixed(2))} big />
        </div>
      }
    >
      <div className="grid-4">
        <div>
          <div className="text-helper">평단가</div>
          <div className="mono">{formatKrw(p.weighted_avg_price)}</div>
        </div>
        <div>
          <div className="text-helper">손절선</div>
          <div className="mono pnl-loss">{formatKrw(p.fixed_stop_price)}</div>
        </div>
        <div>
          <div className="text-helper">+5% 청산</div>
          <div>{p.profit_5_executed ? '✓ 완료' : '대기'}</div>
        </div>
        <div>
          <div className="text-helper">+10% 청산</div>
          <div>{p.profit_10_executed ? '✓ 완료' : '대기'}</div>
        </div>
      </div>
    </ExpandableTile>
  );
}

// ---------------------------------------------------------------------
// Empty tile
// ---------------------------------------------------------------------

function EmptyTile({
  msg,
  cta,
  onCta,
}: {
  msg: string;
  cta?: string;
  onCta?: () => void;
}) {
  return (
    <div
      className="cds-tile"
      style={{ padding: 32, textAlign: 'center' }}
    >
      <p className="text-helper">{msg}</p>
      {cta && onCta ? (
        <Btn kind="primary" size="sm" onClick={onCta}>
          {cta}
        </Btn>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------
// BoxEditModal
// ---------------------------------------------------------------------

interface BoxEditModalProps {
  box: BoxOut;
  stock: TrackedStockDetailOut;
  livePrice: number | null;
  siblingBoxes: BoxOut[];
  onClose: () => void;
  onSaved: () => void;
  onError: (message: string) => void;
}

function BoxEditModal({
  box,
  stock,
  livePrice,
  siblingBoxes,
  onClose,
  onSaved,
  onError,
}: BoxEditModalProps) {
  const [upper, setUpper] = useState(box.upper_price);
  const [lower, setLower] = useState(box.lower_price);
  const [strategy, setStrategy] = useState<StrategyType>(box.strategy_type);
  const [sizePct, setSizePct] = useState(box.position_size_pct);
  const [stopLoss, setStopLoss] = useState(box.stop_loss_pct);
  const [memo, setMemo] = useState(box.memo ?? '');

  const patch = usePatchBox(box.id, {
    onSuccess: ({ warnings }) => {
      onSaved();
      if (warnings.length > 0) {
        onError(`경고: ${warnings.join(', ')}`);
      }
      onClose();
    },
    onError: (err) =>
      onError(err instanceof ApiClientError ? err.message : '알 수 없는 오류'),
  });

  const investAmount = (TOTAL_CAPITAL * sizePct) / 100;
  const estQty = upper > 0 ? Math.floor(investAmount / upper) : 0;
  const stopPrice = upper * (1 + stopLoss / 100);

  const otherUsedPct = siblingBoxes
    .filter(
      (b) =>
        b.id !== box.id &&
        b.status !== 'INVALIDATED' &&
        b.status !== 'CANCELLED',
    )
    .reduce((s, b) => s + b.position_size_pct, 0);
  const totalIfApplied = otherUsedPct + sizePct;
  const overLimit = totalIfApplied > 30;

  const dirty =
    upper !== box.upper_price ||
    lower !== box.lower_price ||
    strategy !== box.strategy_type ||
    sizePct !== box.position_size_pct ||
    stopLoss !== box.stop_loss_pct ||
    memo !== (box.memo ?? '');

  const valid =
    upper > lower &&
    lower > 0 &&
    sizePct > 0 &&
    sizePct <= 30 &&
    !overLimit &&
    stopLoss < 0 &&
    stopLoss >= -10;

  const submit = () => {
    patch.mutate({
      upper_price: upper,
      lower_price: lower,
      position_size_pct: sizePct,
      stop_loss_pct: stopLoss,
      memo: memo || null,
    });
  };

  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      title={`${stock.stock_name} · ${box.box_tier}차 박스 편집`}
      subtitle={`상태 ${box.status}${
        livePrice != null ? ` · 현재가 ${formatKrw(livePrice)}원` : ''
      }`}
      primary={{
        label: patch.isPending ? '저장 중…' : '변경 저장',
        onClick: submit,
      }}
      primaryDisabled={!valid || !dirty || patch.isPending}
      secondary={{ label: '취소', onClick: onClose }}
    >
      <div className="col gap-16">
        <div className="box-form-grid">
          <Field label="상단 (원)">
            <NumInput
              value={upper}
              onChange={(v) => setUpper(v ?? 0)}
              step={100}
            />
          </Field>
          <Field
            label="하단 (원)"
            error={lower >= upper ? '하단은 상단보다 낮아야 합니다' : undefined}
          >
            <NumInput
              value={lower}
              onChange={(v) => setLower(v ?? 0)}
              step={100}
              invalid={lower >= upper}
            />
          </Field>
        </div>
        <Field label="진입 전략">
          <div className="box-form-row">
            <button
              type="button"
              className={`radio-tile${strategy === 'PULLBACK' ? ' is-selected' : ''}`}
              onClick={() => setStrategy('PULLBACK')}
            >
              <h4>눌림 (PULLBACK)</h4>
              <p className="helper">박스 내 양봉 형성 시 매수</p>
            </button>
            <button
              type="button"
              className={`radio-tile${strategy === 'BREAKOUT' ? ' is-selected' : ''}`}
              onClick={() => setStrategy('BREAKOUT')}
            >
              <h4>돌파 (BREAKOUT)</h4>
              <p className="helper">박스 상단 돌파 매수</p>
            </button>
          </div>
        </Field>
        <div className="box-form-grid">
          <Field
            label="비중 (%)"
            helper={`기타 박스 ${otherUsedPct}% + 신규 = ${totalIfApplied.toFixed(1)}% / 30%`}
          >
            <NumInput
              value={sizePct}
              onChange={(v) => setSizePct(v ?? 0)}
              min={0.1}
              max={30}
              step={0.5}
              invalid={overLimit}
            />
          </Field>
          <Field label="손절폭 (%)">
            <NumInput
              value={stopLoss}
              onChange={(v) => setStopLoss(v ?? 0)}
              min={-10}
              max={-1}
              step={0.5}
            />
          </Field>
        </div>
        {overLimit ? (
          <InlineNotif
            kind="error"
            title="비중 한도 초과"
            subtitle={`누적 ${totalIfApplied.toFixed(1)}% > 30%`}
          />
        ) : null}
        <Tile padding={12}>
          <div
            style={{
              background: 'var(--cds-layer-02)',
              padding: 0,
              margin: 0,
            }}
          >
            <div className="grid-3">
              <div>
                <div className="text-helper">예상 투입</div>
                <div className="mono">{formatKrw(investAmount)}원</div>
              </div>
              <div>
                <div className="text-helper">예상 수량</div>
                <div className="mono">약 {estQty}주</div>
              </div>
              <div>
                <div className="text-helper">손절선</div>
                <div className="mono pnl-loss">
                  {formatKrw(stopPrice)}원
                </div>
              </div>
            </div>
          </div>
        </Tile>
        <Field label="메모">
          <Textarea value={memo} onChange={setMemo} rows={2} />
        </Field>
      </div>
    </Modal>
  );
}
