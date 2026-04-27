// V7.1 BoxWizard -- wired to /api/v71/tracked_stocks/{id} + /api/v71/boxes (PRD §3.4, §4.2).
// PRD Patch #3: 7-step wizard (Step 0 "경로 선택" added before strategy).
// Step labels: ['경로', '전략', '가격', '비중', '손절', '확인', '저장'].

import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { I } from '@/components/icons';
import {
  Btn,
  Field,
  InlineNotif,
  NumInput,
  ProgressBar,
  ProgressIndicator,
  SliderInput,
  Textarea,
  ToastContainer,
  useToasts,
} from '@/components/ui';
import { useAppShellContext } from '@/hooks/useAppShell';
import {
  useBoxes,
  useCreateBox,
  useTrackedStock,
  useTrackedStocks,
} from '@/hooks/useApi';
import { ApiClientError } from '@/lib/api';
import { formatKrw } from '@/lib/formatters';
import type { PathType, StrategyType } from '@/types';

const TOTAL_CAPITAL = 100_000_000;

const STEP_LABELS = [
  '경로',
  '전략',
  '가격',
  '비중',
  '손절',
  '확인',
  '저장',
] as const;

export function BoxWizard() {
  const { mock } = useAppShellContext();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { toasts, addToast, closeToast } = useToasts();

  const stockIdParam = params.get('stock_id');

  // Resolve the actual tracked_stock id. The query param can be either
  // an UUID (preferred, from TrackedStocks list) or a stock_code (legacy).
  const isUuidLike = stockIdParam ? /^[0-9a-f-]{8,}$/i.test(stockIdParam) : false;
  const { data: trackedListForCode } = useTrackedStocks(
    { stock_code: stockIdParam ?? undefined, limit: 1 },
    { enabled: !!stockIdParam && !isUuidLike },
  );
  const fallbackId =
    !isUuidLike && trackedListForCode?.data[0]?.id
      ? trackedListForCode.data[0].id
      : null;
  const stockId = isUuidLike ? stockIdParam : fallbackId;

  const { data: stock, isLoading } = useTrackedStock(stockId);
  const { data: boxList } = useBoxes(
    { tracked_stock_id: stockId ?? undefined, limit: 100 },
    { enabled: !!stockId },
  );

  const livePrice = useMemo(() => {
    if (!stock) return 0;
    return (
      mock.trackedStocks.find((s) => s.stock_code === stock.stock_code)
        ?.current_price ?? 0
    );
  }, [stock, mock.trackedStocks]);

  const existingBoxes = (boxList?.data ?? []).filter(
    (b) => b.status !== 'INVALIDATED' && b.status !== 'CANCELLED',
  );
  const usedPct = existingBoxes.reduce((s, b) => s + b.position_size_pct, 0);

  const [step, setStep] = useState(0);
  const [path, setPath] = useState<PathType>('PATH_A');
  const [upper, setUpper] = useState(0);
  const [lower, setLower] = useState(0);
  const [strategy, setStrategy] = useState<StrategyType>('PULLBACK');
  const [sizePct, setSizePct] = useState(10);
  const [stopLoss, setStopLoss] = useState(-5);
  const [memo, setMemo] = useState('');

  // Initialize the price band once livePrice is available.
  useEffect(() => {
    if (livePrice > 0 && upper === 0 && lower === 0) {
      setUpper(Math.round(livePrice * 1.01));
      setLower(Math.round(livePrice * 0.99));
    }
  }, [livePrice, upper, lower]);

  const create = useCreateBox({
    onSuccess: (created) => {
      addToast({
        kind: 'success',
        title: '박스 저장 완료',
        subtitle: `${stock?.stock_name ?? ''} ${created.box_tier}차 박스 · ${created.path_type}`,
      });
      navigate(`/tracked-stocks/${stockId}`);
    },
    onError: (err) => {
      addToast({
        kind: 'error',
        title: '박스 저장 실패',
        subtitle: err instanceof ApiClientError ? err.message : '알 수 없는 오류',
      });
      setStep(5);
    },
  });

  if (isLoading) {
    return (
      <div className="cds-tile">
        <p className="text-helper">불러오는 중…</p>
      </div>
    );
  }

  if (!stock || !stockId) {
    return (
      <div className="cds-tile">
        <p>종목을 찾을 수 없습니다.</p>
      </div>
    );
  }

  const investAmount = (TOTAL_CAPITAL * sizePct) / 100;
  const estQty = upper > 0 ? Math.floor(investAmount / upper) : 0;
  const stopPrice = upper * (1 + stopLoss / 100);
  const boxWidth = upper - lower;
  const boxWidthPct = lower > 0 ? (boxWidth / lower) * 100 : 0;
  const totalPctIfAdded = usedPct + sizePct;
  const overLimit = totalPctIfAdded > 30;

  const valid = (() => {
    if (step === 0) return path === 'PATH_A' || path === 'PATH_B';
    if (step === 1) return !!strategy;
    if (step === 2) return upper > 0 && lower > 0 && upper > lower;
    if (step === 3) return sizePct > 0 && sizePct <= 30 && !overLimit;
    if (step === 4) return stopLoss < 0 && stopLoss >= -10;
    return true;
  })();

  const next = () => {
    if (step < 5) {
      setStep(step + 1);
    } else if (step === 5) {
      setStep(6);
      create.mutate({
        tracked_stock_id: stockId,
        path_type: path,
        upper_price: upper,
        lower_price: lower,
        position_size_pct: sizePct,
        stop_loss_pct: stopLoss,
        strategy_type: strategy,
        memo: memo || null,
      });
    }
  };
  const prev = () => step > 0 && setStep(step - 1);
  const cancel = () => navigate(`/tracked-stocks/${stockId}`);

  return (
    <div>
      <div className="breadcrumbs">
        <a onClick={() => navigate('/tracked-stocks')}>추적 종목</a>
        <span className="sep">/</span>
        <a onClick={() => navigate(`/tracked-stocks/${stockId}`)}>
          {stock.stock_name}
        </a>
        <span className="sep">/</span>
        <span>박스 추가</span>
      </div>

      <div className="page-hd">
        <div>
          <h1 className="page-hd__title">
            박스 설정 — {stock.stock_name}
          </h1>
          <div className="page-hd__subtitle">
            현재가 {formatKrw(livePrice)}원 · 기존 박스{' '}
            {existingBoxes.length}개 (사용 비중 {usedPct}%)
          </div>
        </div>
      </div>

      <ProgressIndicator current={step} steps={[...STEP_LABELS]} />

      <div className="cds-tile" style={{ padding: 24 }}>
        {/* Step 0 -- 경로 (PRD Patch #3) */}
        {step === 0 ? (
          <div className="col gap-16">
            <h3 style={{ margin: 0 }}>박스 진입 경로 선택</h3>
            <p className="text-helper" style={{ margin: 0 }}>
              같은 종목 안에서도 박스마다 다른 경로를 지정할 수 있습니다.
            </p>
            <div className="radio-tile-group">
              <button
                type="button"
                className={`radio-tile${path === 'PATH_A' ? ' is-selected' : ''}`}
                onClick={() => setPath('PATH_A')}
              >
                <h4>PATH_A — 단타 (3분봉)</h4>
                <p>며칠~몇 주 단위 매매. 박스 진입 → 빠른 청산.</p>
                <p className="helper">진입: 3분봉 완성 즉시 매수</p>
                <p className="helper">이용: 주도주, 테마주, 단기 모멘텀</p>
              </button>
              <button
                type="button"
                className={`radio-tile${path === 'PATH_B' ? ' is-selected' : ''}`}
                onClick={() => setPath('PATH_B')}
              >
                <h4>PATH_B — 중기 (일봉)</h4>
                <p>월 단위 추세 추종. 분할 매수 + 트레일링 스탑.</p>
                <p className="helper">
                  진입: 일봉 완성 후 익일 09:01 매수
                </p>
                <p className="helper">이용: 가치주, 증권주, 장기 테마</p>
              </button>
            </div>
            {path === 'PATH_B' ? (
              <InlineNotif
                kind="warning"
                lowContrast
                title="갭업 5% 이상 시 매수 포기"
                subtitle="PATH_B는 일봉 완성 후 익일 09:01 매수. 시초가 갭업이 5% 이상이면 진입을 포기합니다."
              />
            ) : null}
          </div>
        ) : null}

        {/* Step 1 -- 전략 */}
        {step === 1 ? (
          <div className="col gap-16">
            <h3 style={{ margin: 0 }}>진입 전략 선택</h3>
            <div className="radio-tile-group">
              <button
                type="button"
                className={`radio-tile${strategy === 'PULLBACK' ? ' is-selected' : ''}`}
                onClick={() => setStrategy('PULLBACK')}
              >
                <h4>눌림 (PULLBACK)</h4>
                <p>박스 안에서 양봉 형성 시 매수</p>
                <p className="helper">
                  직전봉 + 현재봉 모두 양봉 + 박스 내 종가 · 봉 완성 직후 즉시
                  매수
                </p>
              </button>
              <button
                type="button"
                className={`radio-tile${strategy === 'BREAKOUT' ? ' is-selected' : ''}`}
                onClick={() => setStrategy('BREAKOUT')}
              >
                <h4>돌파 (BREAKOUT)</h4>
                <p>박스 상단 돌파 시 매수</p>
                <p className="helper">
                  종가 &gt; 박스 상단 + 양봉 + 정상 시가 (갭업 제외)
                </p>
              </button>
            </div>
          </div>
        ) : null}

        {/* Step 2 -- 가격 */}
        {step === 2 ? (
          <div className="col gap-16">
            <h3 style={{ margin: 0 }}>가격 범위 설정</h3>
            <div
              className="tile-row"
              style={{ background: 'var(--cds-layer-02)' }}
            >
              <div>
                <div className="text-helper">현재가</div>
                <div className="mono">{formatKrw(livePrice)}원</div>
              </div>
              <div>
                <div className="text-helper">52주 최고</div>
                <div className="mono">
                  {formatKrw(Math.round(livePrice * 1.15))}원
                </div>
              </div>
              <div>
                <div className="text-helper">52주 최저</div>
                <div className="mono">
                  {formatKrw(Math.round(livePrice * 0.72))}원
                </div>
              </div>
            </div>
            {existingBoxes.length > 0 ? (
              <InlineNotif
                kind="warning"
                lowContrast
                title="기존 박스 존재"
                subtitle={`이 종목에 ${existingBoxes.length}개의 활성 박스가 있습니다. 가격대 겹침 주의.`}
              />
            ) : null}
            <Field label="박스 상단 (원)">
              <NumInput
                value={upper}
                onChange={(v) => setUpper(v ?? 0)}
                step={100}
              />
            </Field>
            <Field
              label="박스 하단 (원)"
              error={
                lower >= upper ? '하단은 상단보다 낮아야 합니다' : undefined
              }
            >
              <NumInput
                value={lower}
                onChange={(v) => setLower(v ?? 0)}
                step={100}
                invalid={lower >= upper}
              />
            </Field>
            <div
              className="cds-tile"
              style={{ background: 'var(--cds-layer-02)' }}
            >
              <div className="text-helper">박스 폭</div>
              <div className="mono" style={{ fontSize: 18 }}>
                {formatKrw(boxWidth)}원 ({boxWidthPct.toFixed(2)}%)
              </div>
            </div>
          </div>
        ) : null}

        {/* Step 3 -- 비중 */}
        {step === 3 ? (
          <div className="col gap-16">
            <h3 style={{ margin: 0 }}>비중 설정</h3>
            <Field
              label={`비중 (%) — 단계별 한도 30%, 현재 사용 ${usedPct}%`}
            >
              <div className="row-12" style={{ alignItems: 'center' }}>
                <NumInput
                  value={sizePct}
                  onChange={(v) => setSizePct(v ?? 0)}
                  min={0.1}
                  max={30}
                  step={0.5}
                />
                <SliderInput
                  value={sizePct}
                  onChange={setSizePct}
                  min={0.1}
                  max={30}
                  step={0.5}
                  fmt={(v) => `${v}%`}
                />
              </div>
            </Field>
            <div
              className="cds-tile"
              style={{ background: 'var(--cds-layer-02)' }}
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
                  <div className="text-helper">추가 후 누적</div>
                  <div className="mono">
                    {totalPctIfAdded.toFixed(1)}% / 30%
                  </div>
                </div>
              </div>
            </div>
            {overLimit ? (
              <InlineNotif
                kind="error"
                title="한도 초과"
                subtitle={`현재 ${usedPct}% + 신규 ${sizePct}% = ${totalPctIfAdded.toFixed(1)}%. 30% 한도를 초과합니다.`}
              />
            ) : (
              <InlineNotif
                kind="success"
                lowContrast
                title="한도 내"
                subtitle={`누적 ${totalPctIfAdded.toFixed(1)}% / 30%`}
              />
            )}
          </div>
        ) : null}

        {/* Step 4 -- 손절 */}
        {step === 4 ? (
          <div className="col gap-16">
            <h3 style={{ margin: 0 }}>손절폭 설정</h3>
            <Field label="손절폭 (%) — 매수 후 ~ +5% 미만 구간에 적용">
              <div className="row-12" style={{ alignItems: 'center' }}>
                <NumInput
                  value={-stopLoss}
                  onChange={(v) => setStopLoss(-Math.abs(v ?? 0))}
                  min={1}
                  max={10}
                  step={0.5}
                />
                <SliderInput
                  value={-stopLoss}
                  onChange={(v) => setStopLoss(-Math.abs(v))}
                  min={1}
                  max={10}
                  step={0.5}
                  fmt={(v) => `-${v}%`}
                />
              </div>
            </Field>
            <div
              className="cds-tile"
              style={{ background: 'var(--cds-layer-02)' }}
            >
              <div className="text-helper">
                예상 손절선 (박스 상단 {formatKrw(upper)}원 기준)
              </div>
              <div
                className="mono pnl-loss"
                style={{ fontSize: 20 }}
              >
                {formatKrw(stopPrice)}원
              </div>
            </div>
            <InlineNotif
              kind="info"
              lowContrast
              title="단계별 손절 자동 전환"
              subtitle="매수 ~ +5% 미만: 사용자 설정 / +5% 청산 후: -2% / +10% 청산 후: +4% (본전)"
            />
          </div>
        ) : null}

        {/* Step 5 -- 확인 */}
        {step === 5 ? (
          <div className="col gap-16">
            <h3 style={{ margin: 0 }}>저장 전 확인</h3>
            <div className="cds-slist">
              {(
                [
                  ['종목', `${stock.stock_name} (${stock.stock_code})`],
                  [
                    '경로',
                    path === 'PATH_A'
                      ? 'PATH_A — 단타 (3분봉)'
                      : 'PATH_B — 중기 (일봉)',
                  ],
                  ['Tier', `${existingBoxes.length + 1}차 박스`],
                  [
                    '가격',
                    `${formatKrw(lower)} ~ ${formatKrw(upper)}원 (폭 ${boxWidthPct.toFixed(2)}%)`,
                  ],
                  ['전략', strategy],
                  [
                    '비중',
                    `${sizePct}% (예상 ${formatKrw(investAmount)}원, 약 ${estQty}주)`,
                  ],
                  ['손절폭', `${stopLoss}% → ${formatKrw(stopPrice)}원`],
                ] as Array<[string, string]>
              ).map(([k, v]) => (
                <div key={k} className="cds-slist__row">
                  <div className="cds-slist__cell">{k}</div>
                  <div className="cds-slist__cell mono">{v}</div>
                </div>
              ))}
            </div>
            <Field label="메모 (선택)">
              <Textarea value={memo} onChange={setMemo} rows={2} />
            </Field>
          </div>
        ) : null}

        {/* Step 6 -- 저장 */}
        {step === 6 ? (
          <div
            className="col gap-16"
            style={{ alignItems: 'center', textAlign: 'center', padding: 32 }}
          >
            <I.Success
              size={48}
              style={{ fill: 'var(--cds-support-success)' }}
            />
            <h3>박스 저장 중...</h3>
            <ProgressBar
              value={create.isPending ? 60 : 100}
              helper={create.isPending ? '서버에 저장하는 중' : '저장 완료'}
            />
          </div>
        ) : null}
      </div>

      {step < 6 ? (
        <div
          style={{
            display: 'flex',
            gap: 12,
            marginTop: 16,
            justifyContent: 'flex-end',
          }}
        >
          <Btn kind="secondary" onClick={step === 0 ? cancel : prev}>
            {step === 0 ? '취소' : '이전'}
          </Btn>
          <Btn kind="primary" onClick={next} disabled={!valid}>
            {step === 5 ? '저장' : '다음'}
          </Btn>
        </div>
      ) : null}

      <ToastContainer toasts={toasts} onClose={closeToast} />
    </div>
  );
}
