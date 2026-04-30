// V7.1 TrackedStocks list -- wired to /api/v71/tracked_stocks (PRD §3).
// PRD Patch #3 applied:
//   - tracked_stocks has no path_type. Path is per-box.
//   - "새 종목 추적" modal does NOT include path RadioButtons.
//   - Path filter / tag derived from summary.path_a_box_count / path_b_box_count.

import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import type {
  StockSearchItem,
  TrackedStockOut,
} from '@/api/trackedStocks';
import { I } from '@/components/icons';
import {
  Btn,
  Dropdown,
  Field,
  InlineNotif,
  Modal,
  OverflowMenu,
  Pagination,
  SearchBox,
  Tag,
  Textarea,
  ToastContainer,
  TrackedStatusTag,
  useToasts,
} from '@/components/ui';
import { useAppShellContext } from '@/hooks/useAppShell';
import {
  useBoxes,
  useCreateTrackedStock,
  useDeleteTrackedStock,
  useStockSearch,
  useTrackedStocks,
} from '@/hooks/useApi';
import { ApiClientError } from '@/lib/api';
import { formatKrw, formatRelative } from '@/lib/formatters';
import type { TrackedStatus } from '@/types';

type StatusFilter = 'all' | TrackedStatus;
type PathFilter = 'all' | 'PATH_A' | 'PATH_B' | 'NONE';

// ---------------------------------------------------------------------
// Column resize (사용자 요청 — 등록일 컬럼이 좁아 줄바꿈되는 결함 fix)
// ---------------------------------------------------------------------

const COL_WIDTH_KEY = 'tracked-stocks/col-widths/v1';
//                      종목  코드   경로  상태  박스  포지션 현재가 등록일  ⋮
const DEFAULT_WIDTHS = [220, 120, 140, 110, 90, 90, 120, 130, 50];
const MIN_WIDTH = 50;

function loadWidths(): number[] {
  try {
    const raw = localStorage.getItem(COL_WIDTH_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (
        Array.isArray(parsed) &&
        parsed.length === DEFAULT_WIDTHS.length &&
        parsed.every((n) => typeof n === 'number' && n >= MIN_WIDTH)
      ) {
        return parsed as number[];
      }
    }
  } catch {
    // localStorage corruption / quota — fall back to defaults
  }
  return [...DEFAULT_WIDTHS];
}

function ColResizer({
  onResize,
}: {
  onResize: (deltaPx: number) => void;
}) {
  const onMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    let lastX = e.clientX;
    const onMove = (ev: MouseEvent) => {
      const delta = ev.clientX - lastX;
      if (delta !== 0) {
        lastX = ev.clientX;
        onResize(delta);
      }
    };
    const onUp = () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  };
  return (
    <span
      onMouseDown={onMouseDown}
      onClick={(e) => e.stopPropagation()}
      style={{
        position: 'absolute',
        right: 0,
        top: 0,
        bottom: 0,
        width: 5,
        cursor: 'col-resize',
        userSelect: 'none',
        zIndex: 1,
      }}
      title="드래그해서 컬럼 너비 조정"
    />
  );
}

export function TrackedStocks() {
  const { mock } = useAppShellContext();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { toasts, addToast, closeToast } = useToasts();

  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [pathFilter, setPathFilter] = useState<PathFilter>('all');
  const [page, setPage] = useState(1);
  const [showNew, setShowNew] = useState(params.get('new') === '1');
  const [confirmDel, setConfirmDel] = useState<{
    stock: TrackedStockOut;
    mode: 'stop' | 'delete';
  } | null>(null);
  const perPage = 10;

  const { data: list } = useTrackedStocks({ limit: 200 });
  const { data: boxList } = useBoxes({ limit: 200 });

  // Column widths — persisted per-user in localStorage. 9 columns
  // matching the <thead> below (종목/코드/경로/상태/박스/포지션/현재가/등록일/⋮).
  const [colWidths, setColWidths] = useState<number[]>(() => loadWidths());
  useEffect(() => {
    try {
      localStorage.setItem(COL_WIDTH_KEY, JSON.stringify(colWidths));
    } catch {
      // quota / disabled — silently ignore (UX preference is best-effort)
    }
  }, [colWidths]);
  const resizeCol = (idx: number, delta: number) =>
    setColWidths((prev) => {
      const next = [...prev];
      next[idx] = Math.max(MIN_WIDTH, next[idx] + delta);
      return next;
    });
  const removeTracked = useDeleteTrackedStock({
    onSuccess: () => {
      const wasDelete = confirmDel?.mode === 'delete';
      addToast({
        kind: 'success',
        title: wasDelete ? '종목 영구 삭제 완료' : '추적 종료됨',
      });
      setConfirmDel(null);
    },
    onError: (err) => {
      const wasDelete = confirmDel?.mode === 'delete';
      addToast({
        kind: 'error',
        title: wasDelete ? '삭제 실패' : '추적 종료 실패',
        subtitle: err instanceof ApiClientError ? err.message : undefined,
      });
    },
  });

  // Live price lookup by stock_code -- via cached mock prices.
  const priceByCode = useMemo(() => {
    const m = new Map<string, number>();
    for (const ms of mock.trackedStocks) m.set(ms.stock_code, ms.current_price);
    return m;
  }, [mock.trackedStocks]);

  const items = list?.data ?? [];
  const boxes = boxList?.data ?? [];

  const filtered = useMemo(
    () =>
      items.filter((s) => {
        if (
          search &&
          !(s.stock_name.includes(search) || s.stock_code.includes(search))
        )
          return false;
        if (statusFilter !== 'all' && s.status !== statusFilter) return false;
        if (pathFilter === 'PATH_A' && s.summary.path_a_box_count === 0)
          return false;
        if (pathFilter === 'PATH_B' && s.summary.path_b_box_count === 0)
          return false;
        if (
          pathFilter === 'NONE' &&
          (s.summary.path_a_box_count > 0 || s.summary.path_b_box_count > 0)
        )
          return false;
        return true;
      }),
    [items, search, statusFilter, pathFilter],
  );

  const paged = filtered.slice((page - 1) * perPage, page * perPage);
  const boxesWaiting = boxes.filter((b) => b.status === 'WAITING').length;

  return (
    <div>
      <div className="page-hd">
        <div>
          <h1 className="page-hd__title">추적 종목</h1>
          <div className="page-hd__subtitle">
            총 {filtered.length}개 / 박스 대기 {boxesWaiting}
          </div>
        </div>
        <div className="page-hd__actions">
          <Btn
            kind="primary"
            size="sm"
            icon={I.Add}
            onClick={() => setShowNew(true)}
          >
            새 종목 추적
          </Btn>
        </div>
      </div>

      {/* toolbar + table */}
      <div className="cds-data-table">
        <div className="table-toolbar">
          <SearchBox
            value={search}
            onChange={setSearch}
            placeholder="종목명 또는 코드 검색"
          />
          <div className="table-toolbar__tools">
            <Dropdown<StatusFilter>
              value={statusFilter}
              onChange={setStatusFilter}
              options={[
                { value: 'all', label: '상태: 전체' },
                { value: 'TRACKING', label: '추적 중' },
                { value: 'BOX_SET', label: '박스 설정' },
                { value: 'POSITION_OPEN', label: '포지션 보유' },
                { value: 'POSITION_PARTIAL', label: '부분 청산' },
                { value: 'EXITED', label: '종료' },
              ]}
            />
            <Dropdown<PathFilter>
              value={pathFilter}
              onChange={setPathFilter}
              options={[
                { value: 'all', label: '경로: 전체' },
                { value: 'PATH_A', label: 'PATH_A 박스 보유' },
                { value: 'PATH_B', label: 'PATH_B 박스 보유' },
                { value: 'NONE', label: '박스 없음' },
              ]}
            />
          </div>
        </div>
        <div className="table-wrap">
          <table
            className="cds-table"
            style={{ tableLayout: 'fixed', width: 'max-content', minWidth: '100%' }}
          >
            <colgroup>
              {colWidths.map((w, i) => (
                <col key={i} style={{ width: w }} />
              ))}
            </colgroup>
            <thead>
              <tr>
                <th style={{ position: 'relative' }}>
                  종목명
                  <ColResizer onResize={(d) => resizeCol(0, d)} />
                </th>
                <th style={{ position: 'relative' }}>
                  코드
                  <ColResizer onResize={(d) => resizeCol(1, d)} />
                </th>
                <th style={{ position: 'relative' }}>
                  경로 분포
                  <ColResizer onResize={(d) => resizeCol(2, d)} />
                </th>
                <th style={{ position: 'relative' }}>
                  상태
                  <ColResizer onResize={(d) => resizeCol(3, d)} />
                </th>
                <th style={{ textAlign: 'right', position: 'relative' }}>
                  박스
                  <ColResizer onResize={(d) => resizeCol(4, d)} />
                </th>
                <th style={{ textAlign: 'right', position: 'relative' }}>
                  포지션
                  <ColResizer onResize={(d) => resizeCol(5, d)} />
                </th>
                <th style={{ textAlign: 'right', position: 'relative' }}>
                  현재가
                  <ColResizer onResize={(d) => resizeCol(6, d)} />
                </th>
                <th style={{ position: 'relative' }}>
                  등록일
                  <ColResizer onResize={(d) => resizeCol(7, d)} />
                </th>
                <th />
              </tr>
            </thead>
            <tbody>
              {paged.map((s) => {
                const livePrice = priceByCode.get(s.stock_code);
                return (
                  <tr
                    key={s.id}
                    style={{ cursor: 'pointer' }}
                    onClick={() => navigate(`/tracked-stocks/${s.id}`)}
                  >
                    <td>
                      <strong>{s.stock_name}</strong>
                      {s.user_memo ? (
                        <div
                          className="text-helper"
                          style={{ marginTop: 2 }}
                        >
                          {s.user_memo}
                        </div>
                      ) : null}
                    </td>
                    <td className="mono">
                      {s.stock_code}{' '}
                      <span className="text-helper">{s.market ?? ''}</span>
                    </td>
                    <td>
                      <PathDistribution
                        a={s.summary.path_a_box_count}
                        b={s.summary.path_b_box_count}
                      />
                    </td>
                    <td>
                      <TrackedStatusTag status={s.status} sm />
                    </td>
                    <td className="price">
                      {s.summary.active_box_count} /{' '}
                      {s.summary.triggered_box_count}
                    </td>
                    <td className="price">
                      {s.summary.current_position_qty || '-'}
                    </td>
                    <td className="price">{formatKrw(livePrice ?? null)}</td>
                    <td className="mono" style={{ fontSize: 12 }}>
                      {formatRelative(s.created_at)}
                    </td>
                    <td onClick={(e) => e.stopPropagation()}>
                      <OverflowMenu
                        items={
                          s.status === 'EXITED'
                            ? [
                                {
                                  label: '리포트 생성',
                                  onClick: () => {
                                    navigate('/reports');
                                    addToast({
                                      kind: 'info',
                                      title: `${s.stock_name} 리포트 생성 시작`,
                                    });
                                  },
                                },
                                { divider: true },
                                {
                                  label: '삭제',
                                  danger: true,
                                  onClick: () =>
                                    setConfirmDel({
                                      stock: s,
                                      mode: 'delete',
                                    }),
                                },
                              ]
                            : [
                                {
                                  label: '박스 추가',
                                  onClick: () =>
                                    navigate(`/boxes/new?stock_id=${s.id}`),
                                },
                                {
                                  label: '메모 수정',
                                  onClick: () =>
                                    addToast({
                                      kind: 'info',
                                      title: '메모 수정 (스텁)',
                                    }),
                                },
                                {
                                  label: '리포트 생성',
                                  onClick: () => {
                                    navigate('/reports');
                                    addToast({
                                      kind: 'info',
                                      title: `${s.stock_name} 리포트 생성 시작`,
                                    });
                                  },
                                },
                                { divider: true },
                                {
                                  label: '추적 종료',
                                  danger: true,
                                  onClick: () =>
                                    setConfirmDel({ stock: s, mode: 'stop' }),
                                },
                              ]
                        }
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <Pagination
          total={filtered.length}
          page={page}
          perPage={perPage}
          onPage={setPage}
        />
      </div>

      {showNew ? (
        <NewTrackedStockModal
          onClose={() => setShowNew(false)}
          onSubmitted={(created) => {
            setShowNew(false);
            addToast({
              kind: 'success',
              title: '종목 추적 시작',
              subtitle: `${created.stock_name} (${created.stock_code}) · 박스 설정으로 이동`,
            });
            navigate(`/boxes/new?stock_id=${created.id}`);
          }}
          onError={(message) =>
            addToast({ kind: 'error', title: '추적 시작 실패', subtitle: message })
          }
        />
      ) : null}

      {confirmDel ? (
        <Modal
          open
          danger
          onClose={() => setConfirmDel(null)}
          title={
            confirmDel.mode === 'delete'
              ? `${confirmDel.stock.stock_name} 영구 삭제`
              : `${confirmDel.stock.stock_name} 추적 종료`
          }
          subtitle="확인 필요"
          primary={{
            label: confirmDel.mode === 'delete' ? '영구 삭제' : '추적 종료',
            onClick: () => removeTracked.mutate(confirmDel.stock.id),
          }}
          secondary={{ label: '취소', onClick: () => setConfirmDel(null) }}
        >
          {confirmDel.mode === 'delete' ? (
            <>
              <p>
                {confirmDel.stock.stock_name} ({confirmDel.stock.stock_code})를
                목록에서 영구 삭제할까요?
              </p>
              <ul style={{ paddingLeft: 20, fontSize: 14 }}>
                <li>이미 종료된(EXITED) 추적 종목 정리용</li>
                <li>관련 박스(취소 상태)는 함께 제거됩니다</li>
                <li>
                  과거 매매 기록(거래 이벤트, 종료된 포지션)은 audit을 위해
                  보존됩니다 — 종목 연결만 끊어집니다
                </li>
                <li>이 작업은 되돌릴 수 없습니다</li>
              </ul>
            </>
          ) : (
            <>
              <p>
                {confirmDel.stock.stock_name} ({confirmDel.stock.stock_code})
                추적을 종료할까요?
              </p>
              <ul style={{ paddingLeft: 20, fontSize: 14 }}>
                <li>
                  활성 박스 {confirmDel.stock.summary.active_box_count}개 모두
                  취소됩니다
                </li>
                <li>시세 모니터링 중지</li>
                <li>상태가 EXITED 로 변경됩니다 (목록 유지)</li>
              </ul>
            </>
          )}
        </Modal>
      ) : null}

      <ToastContainer toasts={toasts} onClose={closeToast} />
    </div>
  );
}

// ---------------------------------------------------------------------
// PathDistribution -- one or two tags depending on box counts.
// ---------------------------------------------------------------------

function PathDistribution({ a, b }: { a: number; b: number }) {
  if (a === 0 && b === 0) {
    return <span className="text-helper">-</span>;
  }
  return (
    <span style={{ display: 'inline-flex', gap: 4 }}>
      {a > 0 ? (
        <Tag type="blue" size="sm">
          PATH_A {a}
        </Tag>
      ) : null}
      {b > 0 ? (
        <Tag type="purple" size="sm">
          PATH_B {b}
        </Tag>
      ) : null}
    </span>
  );
}

// ---------------------------------------------------------------------
// NewTrackedStockModal -- PRD Patch #3: NO path_type RadioButtons.
// ---------------------------------------------------------------------

interface NewTrackedStockModalProps {
  onClose: () => void;
  onSubmitted: (created: TrackedStockOut) => void;
  onError: (message: string) => void;
}

function NewTrackedStockModal({
  onClose,
  onSubmitted,
  onError,
}: NewTrackedStockModalProps) {
  const [q, setQ] = useState('');
  const [selected, setSelected] = useState<StockSearchItem | null>(null);
  const [memo, setMemo] = useState('');
  const [source, setSource] = useState('HTS');

  const { data: results = [], isFetching } = useStockSearch(q);
  const create = useCreateTrackedStock({
    onSuccess: (created) => onSubmitted(created),
    onError: (err) => {
      onError(err instanceof ApiClientError ? err.message : '알 수 없는 오류');
    },
  });

  const submit = () => {
    if (!selected) return;
    create.mutate({
      stock_code: selected.stock_code,
      user_memo: memo || null,
      source,
    });
  };

  return (
    <Modal
      open
      onClose={onClose}
      title="새 종목 추적"
      subtitle="종목을 검색해 추적 시작 — 경로는 박스 설정에서 선택"
      size="md"
      primary={{
        label: create.isPending ? '추적 시작 중…' : '추적 시작',
        onClick: submit,
      }}
      secondary={{ label: '취소', onClick: onClose }}
      primaryDisabled={!selected || create.isPending}
    >
      <SearchBox value={q} onChange={setQ} placeholder="종목명 또는 코드" />
      <div
        className="cds-slist cds-slist--simple"
        style={{ maxHeight: 200, overflowY: 'auto', marginTop: 12 }}
      >
        {q.length === 0 ? (
          <div className="cds-slist__row">
            <div className="cds-slist__cell text-helper">
              검색어를 입력하세요.
            </div>
          </div>
        ) : isFetching ? (
          <div className="cds-slist__row">
            <div className="cds-slist__cell text-helper">검색 중…</div>
          </div>
        ) : results.length === 0 ? (
          <div className="cds-slist__row">
            <div className="cds-slist__cell text-helper">
              검색 결과가 없습니다.
            </div>
          </div>
        ) : (
          results.map((r) => (
            <div key={r.stock_code} className="cds-slist__row">
              <div
                className={`cds-slist__cell${selected?.stock_code === r.stock_code ? ' is-selected' : ''}`}
                onClick={() => setSelected(r)}
              >
                <div
                  style={{ display: 'flex', justifyContent: 'space-between' }}
                >
                  <div>
                    <strong>{r.stock_name}</strong>{' '}
                    <span className="text-helper mono">
                      {r.stock_code}
                      {r.market ? ` · ${r.market}` : ''}
                    </span>
                  </div>
                  <span className="mono">
                    {r.current_price != null
                      ? `${formatKrw(r.current_price)}원`
                      : '-'}
                  </span>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
      <div style={{ marginTop: 12 }}>
        <InlineNotif
          kind="info"
          lowContrast
          title="경로 선택은 박스 설정에서"
          subtitle="종목 등록 후 박스 설정 마법사에서 PATH_A(단타) / PATH_B(중기)를 박스 단위로 지정합니다."
        />
      </div>
      <div
        style={{
          marginTop: 16,
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 16,
        }}
      >
        <Field label="출처">
          <Dropdown<string>
            value={source}
            onChange={setSource}
            options={[
              { value: 'HTS', label: 'HTS' },
              { value: '뉴스', label: '뉴스' },
              { value: '리포트', label: '리포트' },
              { value: '직접 분석', label: '직접 분석' },
            ]}
          />
        </Field>
        <Field label="메모 (선택)">
          <Textarea
            value={memo}
            onChange={setMemo}
            rows={2}
            placeholder="예: 반도체 사이클 회복"
          />
        </Field>
      </div>
    </Modal>
  );
}
