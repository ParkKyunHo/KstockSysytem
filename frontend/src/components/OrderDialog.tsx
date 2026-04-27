// V7.1 OrderDialog -- direct port of frontend-prototype/src/components/order-dialog.js.
// Manual buy / sell with safety checks (validations, warnings, confirm step).

import { useEffect, useState } from 'react';

import {
  Btn,
  Dropdown,
  Field,
  InlineNotif,
  Modal,
  NumInput,
  Textarea,
} from '@/components/ui';
import { formatKrw, formatKrwSigned } from '@/lib/formatters';
import type { Position } from '@/types';
import type { TrackedStockWithPrice, MockState } from '@/mocks';

const TOTAL_CAPITAL = 100_000_000;

export type OrderSide = 'BUY' | 'SELL';
export type OrderType = 'LIMIT' | 'MARKET';

export interface OrderToast {
  kind: 'success' | 'info' | 'warning' | 'error';
  title: string;
  subtitle?: string;
  caption?: string;
}

interface OrderDialogProps {
  open: boolean;
  onClose: () => void;
  mock: MockState;
  addToast: (t: OrderToast) => void;
  defaultStock?: TrackedStockWithPrice;
  defaultSide?: OrderSide;
  defaultPosition?: Position;
}

export function OrderDialog({
  open,
  onClose,
  mock,
  addToast,
  defaultStock,
  defaultSide,
  defaultPosition,
}: OrderDialogProps) {
  const initialStockId =
    defaultStock?.id ??
    defaultPosition?.tracked_stock_id ??
    mock.trackedStocks[0]?.id ??
    '';
  const [side, setSide] = useState<OrderSide>(defaultSide ?? 'BUY');
  const [stockId, setStockId] = useState<string>(initialStockId);
  const [orderType, setOrderType] = useState<OrderType>('LIMIT');
  const [quantity, setQuantity] = useState<number>(1);
  const [price, setPrice] = useState<number>(0);
  const [reason, setReason] = useState<string>('');
  const [confirmStep, setConfirmStep] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const stock =
    mock.trackedStocks.find((s) => s.id === stockId) ?? mock.trackedStocks[0];
  const position =
    side === 'SELL'
      ? defaultPosition ??
        mock.positions.find(
          (p) => p.tracked_stock_id === stock?.id && p.status !== 'CLOSED',
        )
      : null;

  // Initialize price from stock current_price.
  useEffect(() => {
    if (stock) setPrice(stock.current_price);
  }, [stock]);

  // Reset state every time the dialog opens.
  useEffect(() => {
    if (open) {
      setConfirmStep(false);
      setSubmitting(false);
      setSide(defaultSide ?? 'BUY');
      setStockId(
        defaultStock?.id ??
          defaultPosition?.tracked_stock_id ??
          mock.trackedStocks[0]?.id ??
          '',
      );
      setOrderType('LIMIT');
      setQuantity(1);
      setReason('');
    }
  }, [open, defaultSide, defaultStock, defaultPosition, mock.trackedStocks]);

  if (!open || !stock) return null;

  const orderPrice = orderType === 'MARKET' ? stock.current_price : price;
  const totalAmount = orderPrice * quantity;
  const totalPct = (totalAmount / TOTAL_CAPITAL) * 100;
  const fees = Math.round(
    totalAmount * 0.00015 + (side === 'SELL' ? totalAmount * 0.0023 : 0),
  );

  // Validations -- block submit when present.
  const errors: string[] = [];
  if (!stockId) errors.push('종목을 선택하세요');
  if (quantity <= 0) errors.push('수량은 1주 이상');
  if (orderType === 'LIMIT' && price <= 0)
    errors.push('지정가는 0보다 커야 합니다');
  if (side === 'SELL' && position && quantity > position.total_quantity)
    errors.push(`보유 수량(${position.total_quantity}주) 초과`);
  if (side === 'BUY' && totalPct > 30)
    errors.push(`단일 종목 30% 한도 초과 (${totalPct.toFixed(1)}%)`);

  // Warnings -- allow but caution.
  const warnings: string[] = [];
  if (
    orderType === 'LIMIT' &&
    side === 'BUY' &&
    price > stock.current_price * 1.03
  )
    warnings.push('지정가가 현재가 대비 +3% 초과 — 즉시 체결 가능성');
  if (
    orderType === 'LIMIT' &&
    side === 'SELL' &&
    price < stock.current_price * 0.97
  )
    warnings.push('지정가가 현재가 대비 -3% 초과 — 즉시 체결 가능성');
  if (orderType === 'MARKET')
    warnings.push('시장가 — 체결 가격이 현재가와 다를 수 있습니다');
  if (side === 'BUY' && totalPct > 15)
    warnings.push(
      `단일 종목 비중 ${totalPct.toFixed(1)}% — 권장 한도 15% 초과`,
    );

  const valid = errors.length === 0;

  const submit = () => {
    setSubmitting(true);
    window.setTimeout(() => {
      addToast({
        kind: 'success',
        title: `${side === 'BUY' ? '매수' : '매도'} 주문 접수`,
        subtitle: `${stock.stock_name} · ${quantity}주 · ${
          orderType === 'MARKET' ? '시장가' : `${formatKrw(price)}원`
        }`,
        caption: `order_id: ord-${Math.random().toString(36).slice(2, 10)}`,
      });
      setSubmitting(false);
      onClose();
    }, 800);
  };

  return (
    <Modal
      open
      onClose={onClose}
      size="md"
      title={confirmStep ? '주문 확인' : '수동 주문'}
      subtitle={
        confirmStep
          ? '아래 내용을 확인하고 전송하세요'
          : '신중하게 입력하세요 — 즉시 키움 API로 전송됩니다'
      }
      danger={side === 'SELL'}
      primary={
        confirmStep
          ? {
              label: submitting
                ? '전송 중...'
                : side === 'BUY'
                  ? '매수 주문 전송'
                  : '매도 주문 전송',
              onClick: submit,
            }
          : { label: '주문 검토', onClick: () => setConfirmStep(true) }
      }
      primaryDisabled={!valid || submitting}
      primaryLoading={submitting}
      secondary={
        confirmStep
          ? { label: '돌아가기', onClick: () => setConfirmStep(false) }
          : { label: '취소', onClick: onClose }
      }
    >
      {confirmStep ? (
        <OrderConfirmView
          side={side}
          stock={stock}
          quantity={quantity}
          orderType={orderType}
          orderPrice={orderPrice}
          totalAmount={totalAmount}
          totalPct={totalPct}
          fees={fees}
          reason={reason}
          position={position ?? null}
        />
      ) : (
        <OrderFormView
          side={side}
          setSide={setSide}
          mock={mock}
          stock={stock}
          stockId={stockId}
          setStockId={setStockId}
          orderType={orderType}
          setOrderType={setOrderType}
          quantity={quantity}
          setQuantity={setQuantity}
          price={price}
          setPrice={setPrice}
          reason={reason}
          setReason={setReason}
          position={position ?? null}
          errors={errors}
          warnings={warnings}
          totalAmount={totalAmount}
          totalPct={totalPct}
          fees={fees}
          fixedSide={!!defaultSide}
          fixedStock={!!defaultStock || !!defaultPosition}
        />
      )}
    </Modal>
  );
}

// ---------------------------------------------------------------------
// Form view
// ---------------------------------------------------------------------

interface FormProps {
  side: OrderSide;
  setSide: (v: OrderSide) => void;
  mock: MockState;
  stock: TrackedStockWithPrice;
  stockId: string;
  setStockId: (v: string) => void;
  orderType: OrderType;
  setOrderType: (v: OrderType) => void;
  quantity: number;
  setQuantity: (v: number) => void;
  price: number;
  setPrice: (v: number) => void;
  reason: string;
  setReason: (v: string) => void;
  position: Position | null;
  errors: string[];
  warnings: string[];
  totalAmount: number;
  totalPct: number;
  fees: number;
  fixedSide: boolean;
  fixedStock: boolean;
}

function OrderFormView({
  side,
  setSide,
  mock,
  stock,
  stockId,
  setStockId,
  orderType,
  setOrderType,
  quantity,
  setQuantity,
  price,
  setPrice,
  reason,
  setReason,
  position,
  errors,
  warnings,
  totalAmount,
  totalPct,
  fees,
  fixedSide,
  fixedStock,
}: FormProps) {
  const stockOptions = mock.trackedStocks
    .filter((s) =>
      side === 'SELL'
        ? mock.positions.some(
            (p) => p.tracked_stock_id === s.id && p.status !== 'CLOSED',
          )
        : true,
    )
    .map((s) => ({
      value: s.id,
      label: `${s.stock_name} (${s.stock_code}) · ${formatKrw(s.current_price)}원`,
    }));

  const livePctVsCurrent =
    price > 0
      ? (((price - stock.current_price) / stock.current_price) * 100).toFixed(2)
      : '0';

  return (
    <div className="col gap-16">
      {/* Side toggle */}
      {!fixedSide ? (
        <div className="order-side-toggle">
          <button
            type="button"
            className={`is-buy${side === 'BUY' ? ' is-active' : ''}`}
            onClick={() => setSide('BUY')}
          >
            매수
          </button>
          <button
            type="button"
            className={`is-sell${side === 'SELL' ? ' is-active' : ''}`}
            onClick={() => setSide('SELL')}
          >
            매도
          </button>
        </div>
      ) : null}

      {/* Stock picker */}
      <Field label="종목">
        {fixedStock ? (
          <div
            className="cds-tile"
            style={{ padding: 12, background: 'var(--cds-layer-02)' }}
          >
            <strong>{stock.stock_name}</strong>{' '}
            <span className="mono text-helper">{stock.stock_code}</span> ·{' '}
            <span className="mono">{formatKrw(stock.current_price)}원</span>
          </div>
        ) : (
          <Dropdown
            value={stockId}
            onChange={setStockId}
            options={stockOptions}
          />
        )}
      </Field>

      {/* Position info if SELL */}
      {side === 'SELL' && position ? (
        <div
          className="cds-tile"
          style={{ background: 'var(--cds-layer-02)', padding: 12 }}
        >
          <div className="grid-3">
            <div>
              <div className="text-helper">보유</div>
              <div className="mono">{position.total_quantity}주</div>
            </div>
            <div>
              <div className="text-helper">평단가</div>
              <div className="mono">
                {formatKrw(position.weighted_avg_price)}원
              </div>
            </div>
            <div>
              <div className="text-helper">평가손익</div>
              <div
                className={`mono ${position.pnl_amount >= 0 ? 'pnl-profit' : 'pnl-loss'}`}
              >
                {formatKrwSigned(position.pnl_amount)}원
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {/* Order type + quantity */}
      <div className="box-form-grid">
        <Field label="주문 유형">
          <Dropdown
            value={orderType}
            onChange={setOrderType}
            options={[
              { value: 'LIMIT', label: '지정가' },
              { value: 'MARKET', label: '시장가' },
            ]}
          />
        </Field>
        <Field label="수량 (주)">
          <NumInput
            value={quantity}
            onChange={(v) => setQuantity(v ?? 1)}
            min={1}
            step={1}
          />
        </Field>
      </div>

      {orderType === 'LIMIT' ? (
        <Field
          label="지정가 (원)"
          helper={`현재가 ${formatKrw(stock.current_price)}원 (${livePctVsCurrent}%)`}
        >
          <NumInput
            value={price}
            onChange={(v) => setPrice(v ?? 0)}
            step={100}
          />
        </Field>
      ) : null}

      {/* Quick qty buttons (for SELL) */}
      {side === 'SELL' && position ? (
        <div className="row-12">
          {[25, 50, 75, 100].map((p) => (
            <Btn
              key={p}
              kind="tertiary"
              size="sm"
              onClick={() =>
                setQuantity(Math.max(1, Math.floor((position.total_quantity * p) / 100)))
              }
            >
              {p}%
            </Btn>
          ))}
        </div>
      ) : null}

      {/* Summary */}
      <div className="order-summary">
        <div>주문 금액</div>
        <div>{formatKrw(totalAmount)}원</div>
        <div>비중</div>
        <div>{totalPct.toFixed(2)}%</div>
        <div>예상 수수료/세금</div>
        <div>{formatKrw(fees)}원</div>
        <div>{side === 'BUY' ? '총 매수가' : '실수령액'}</div>
        <div style={{ fontWeight: 600 }}>
          {formatKrw(side === 'BUY' ? totalAmount + fees : totalAmount - fees)}원
        </div>
      </div>

      {/* Errors / warnings */}
      {errors.length > 0 ? (
        <InlineNotif
          kind="error"
          title="주문 불가"
          subtitle={errors.join(' · ')}
        />
      ) : warnings.length > 0 ? (
        <InlineNotif
          kind="warning"
          title="주의"
          subtitle={warnings.join(' · ')}
          lowContrast
        />
      ) : null}

      {/* Reason */}
      <Field label="사유 (선택, 추후 분석용)">
        <Textarea
          value={reason}
          onChange={setReason}
          rows={2}
          placeholder="예: 시장 급변동, 손절 지연 등"
        />
      </Field>
    </div>
  );
}

// ---------------------------------------------------------------------
// Confirm view
// ---------------------------------------------------------------------

interface ConfirmProps {
  side: OrderSide;
  stock: TrackedStockWithPrice;
  quantity: number;
  orderType: OrderType;
  orderPrice: number;
  totalAmount: number;
  totalPct: number;
  fees: number;
  reason: string;
  position: Position | null;
}

function OrderConfirmView({
  side,
  stock,
  quantity,
  orderType,
  orderPrice,
  totalAmount,
  totalPct,
  fees,
  reason,
  position,
}: ConfirmProps) {
  const rows: Array<[string, string]> = [
    ['종류', side === 'BUY' ? '매수' : '매도'],
    ['종목', `${stock.stock_name} (${stock.stock_code})`],
    ['주문 유형', orderType === 'LIMIT' ? '지정가' : '시장가'],
    ['수량', `${quantity}주`],
    [
      '가격',
      orderType === 'MARKET'
        ? `시장가 (현재 ${formatKrw(stock.current_price)}원)`
        : `${formatKrw(orderPrice)}원`,
    ],
    ['주문 금액', `${formatKrw(totalAmount)}원`],
    ['비중', `${totalPct.toFixed(2)}%`],
    ['수수료/세금', `${formatKrw(fees)}원`],
  ];
  if (side === 'SELL' && position) {
    rows.push(['청산 후 잔량', `${position.total_quantity - quantity}주`]);
  }
  if (reason) {
    rows.push(['사유', reason]);
  }

  return (
    <div className="col gap-16">
      <InlineNotif
        kind={side === 'BUY' ? 'info' : 'warning'}
        title="실거래 주문 — 키움 API로 전송됩니다"
        subtitle="취소는 미체결 상태에서만 가능. 시장가는 즉시 체결."
        lowContrast
      />
      <div className="cds-slist">
        {rows.map(([k, v]) => (
          <div key={k} className="cds-slist__row">
            <div className="cds-slist__cell">{k}</div>
            <div
              className="cds-slist__cell mono"
              style={{ fontWeight: 600 }}
            >
              {v}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
