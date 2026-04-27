// V7.1 Reports -- wired to /api/v71/reports (PRD §8).
// AI-generated stock research with list + detail modal + markdown viewer.

import { Fragment, useMemo, useState } from 'react';

import type { ReportOut, ReportStatusLit } from '@/api/reports';
import { I } from '@/components/icons';
import {
  Btn,
  Modal,
  OverflowMenu,
  ProgressBar,
  SearchBox,
  Tabs,
  Tag,
  type TagType,
  Textarea,
  ToastContainer,
  useToasts,
} from '@/components/ui';
import { useAppShellContext } from '@/hooks/useAppShell';
import {
  useDeleteReport,
  usePatchReport,
  useReports,
  useRestoreReport,
} from '@/hooks/useApi';
import { ApiClientError } from '@/lib/api';
import { formatDateTime, formatKrw, formatRelative } from '@/lib/formatters';

// ---------------------------------------------------------------------
// Status mapping
// ---------------------------------------------------------------------

const STATUS_TAG: Record<ReportStatusLit, { type: TagType; label: string }> = {
  COMPLETED: { type: 'green', label: '완료' },
  GENERATING: { type: 'blue', label: '생성 중' },
  PENDING: { type: 'cool-gray', label: '대기' },
  FAILED: { type: 'red', label: '실패' },
};

type StatusTab = 'all' | ReportStatusLit;

// ---------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------

export function Reports() {
  const { toasts, addToast, closeToast } = useToasts();

  const [search, setSearch] = useState('');
  const [tab, setTab] = useState<StatusTab>('all');
  const [showHidden, setShowHidden] = useState(false); // ★ PRD Patch #5
  const [openReport, setOpenReport] = useState<ReportOut | null>(null);
  const [confirmRegen, setConfirmRegen] = useState<ReportOut | null>(null);
  const [confirmDel, setConfirmDel] = useState<ReportOut | null>(null);

  const { data: list } = useReports({
    limit: 200,
    include_hidden: showHidden,
  });
  const reports = list?.data ?? [];

  const removeReport = useDeleteReport({
    onSuccess: () =>
      addToast({
        kind: 'success',
        title: '리포트 숨김 처리됨',
        subtitle: '영구 보존되며 "숨긴 리포트 보기"로 다시 표시 가능',
      }),
    onError: () =>
      addToast({ kind: 'error', title: '숨김 처리 실패' }),
  });

  const restoreReport = useRestoreReport({
    onSuccess: () =>
      addToast({ kind: 'success', title: '리포트 복구됨' }),
    onError: () =>
      addToast({ kind: 'error', title: '복구 실패' }),
  });

  const filtered = useMemo(
    () =>
      reports.filter((r) => {
        if (
          search &&
          !r.stock_name.includes(search) &&
          !r.stock_code.includes(search)
        )
          return false;
        if (tab !== 'all' && r.status !== tab) return false;
        return true;
      }),
    [reports, search, tab],
  );

  const counts = {
    all: reports.length,
    COMPLETED: reports.filter((r) => r.status === 'COMPLETED').length,
    GENERATING: reports.filter((r) => r.status === 'GENERATING').length,
    PENDING: reports.filter((r) => r.status === 'PENDING').length,
    FAILED: reports.filter((r) => r.status === 'FAILED').length,
  };

  return (
    <div>
      <div className="page-hd">
        <div>
          <h1 className="page-hd__title">리서치 리포트</h1>
          <div className="page-hd__subtitle">
            Claude가 생성하는 종목별 분석 리포트 · 총 {reports.length}개
          </div>
        </div>
        <div className="page-hd__actions">
          <Btn
            kind="tertiary"
            size="sm"
            onClick={() => setShowHidden((v) => !v)}
          >
            {showHidden ? '숨긴 리포트 숨김' : '숨긴 리포트 보기'}
          </Btn>
          <Btn
            kind="primary"
            size="sm"
            icon={I.Add}
            onClick={() =>
              addToast({
                kind: 'info',
                title: '리포트 생성 — 추적 종목 페이지에서 시작',
              })
            }
          >
            리포트 생성
          </Btn>
        </div>
      </div>

      <Tabs<StatusTab>
        value={tab}
        onChange={setTab}
        tabs={[
          { value: 'all', label: '전체', count: counts.all },
          { value: 'COMPLETED', label: '완료', count: counts.COMPLETED },
          { value: 'GENERATING', label: '생성 중', count: counts.GENERATING },
          { value: 'PENDING', label: '대기', count: counts.PENDING },
          { value: 'FAILED', label: '실패', count: counts.FAILED },
        ]}
      />

      <div className="cds-data-table" style={{ marginTop: 16 }}>
        <div className="table-toolbar">
          <SearchBox
            value={search}
            onChange={setSearch}
            placeholder="종목명 또는 코드"
          />
        </div>
        <div className="table-wrap">
          <table className="cds-table">
            <thead>
              <tr>
                <th>종목</th>
                <th>상태</th>
                <th>모델</th>
                <th style={{ textAlign: 'right' }}>토큰</th>
                <th style={{ textAlign: 'right' }}>소요</th>
                <th>생성일</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => {
                const tag = STATUS_TAG[r.status];
                const totalTokens =
                  (r.prompt_tokens ?? 0) + (r.completion_tokens ?? 0);
                const clickable = r.status === 'COMPLETED';
                return (
                  <tr
                    key={r.id}
                    style={{ cursor: clickable ? 'pointer' : 'default' }}
                    onClick={() => clickable && setOpenReport(r)}
                  >
                    <td>
                      <strong>{r.stock_name}</strong>{' '}
                      <span className="mono text-helper">{r.stock_code}</span>
                    </td>
                    <td>
                      <Tag type={tag.type} size="sm">
                        {tag.label}
                      </Tag>
                      {r.status === 'GENERATING' && r.progress != null ? (
                        <div style={{ width: 80, marginTop: 4 }}>
                          <ProgressBar
                            value={r.progress}
                            max={100}
                            helper={`${r.progress}%`}
                          />
                        </div>
                      ) : null}
                    </td>
                    <td className="mono" style={{ fontSize: 12 }}>
                      {r.model_version || '-'}
                    </td>
                    <td className="price">
                      {totalTokens ? totalTokens.toLocaleString() : '-'}
                    </td>
                    <td className="price">
                      {r.generation_duration_seconds
                        ? `${r.generation_duration_seconds}초`
                        : '-'}
                    </td>
                    <td className="mono" style={{ fontSize: 12 }}>
                      {formatRelative(r.created_at)}
                    </td>
                    <td onClick={(e) => e.stopPropagation()}>
                      <OverflowMenu
                        items={[
                          ...(r.status === 'COMPLETED'
                            ? [
                                {
                                  label: '열기',
                                  onClick: () => setOpenReport(r),
                                },
                              ]
                            : []),
                          ...(r.status === 'COMPLETED' && r.pdf_path
                            ? [
                                {
                                  label: 'PDF 다운로드',
                                  onClick: () =>
                                    addToast({
                                      kind: 'info',
                                      title: 'PDF 다운로드 (스텁)',
                                      subtitle: r.pdf_path ?? undefined,
                                    }),
                                },
                              ]
                            : []),
                          ...(r.status === 'COMPLETED' && r.excel_path
                            ? [
                                {
                                  label: 'Excel 다운로드',
                                  onClick: () =>
                                    addToast({
                                      kind: 'info',
                                      title: 'Excel 다운로드 (스텁)',
                                      subtitle: r.excel_path ?? undefined,
                                    }),
                                },
                              ]
                            : []),
                          ...(r.status !== 'GENERATING'
                            ? [
                                {
                                  label: '재생성',
                                  onClick: () => setConfirmRegen(r),
                                },
                              ]
                            : []),
                          { divider: true },
                          // ★ PRD Patch #5: is_hidden 상태별 액션 분기
                          ...(r.is_hidden
                            ? [
                                {
                                  label: '복구',
                                  onClick: () => restoreReport.mutate(r.id),
                                },
                              ]
                            : [
                                {
                                  label: '숨기기',
                                  danger: true,
                                  onClick: () => setConfirmDel(r),
                                },
                              ]),
                        ]}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {openReport ? (
        <ReportDetailModal
          report={openReport}
          onClose={() => setOpenReport(null)}
          addToast={addToast}
        />
      ) : null}

      {confirmRegen ? (
        <Modal
          open
          onClose={() => setConfirmRegen(null)}
          title="리포트 재생성"
          subtitle={`${confirmRegen.stock_name} (${confirmRegen.stock_code})`}
          primary={{
            label: '재생성',
            onClick: () => {
              addToast({
                kind: 'info',
                title: '재생성은 추적 종목 페이지에서 다시 요청하세요',
              });
              setConfirmRegen(null);
            },
          }}
          secondary={{
            label: '취소',
            onClick: () => setConfirmRegen(null),
          }}
        >
          <p>기존 리포트는 보존되며 새 버전이 생성됩니다.</p>
          <p className="text-helper">예상 토큰 사용: ~20,000 / 비용: ~$0.30</p>
        </Modal>
      ) : null}

      {confirmDel ? (
        <Modal
          open
          danger
          onClose={() => setConfirmDel(null)}
          title="리포트 숨기기"
          subtitle={confirmDel.stock_name}
          primary={{
            label: removeReport.isPending ? '처리 중…' : '숨기기',
            onClick: () => {
              // PRD Patch #5: 백엔드 DELETE /api/v71/reports/{id} soft delete
              removeReport.mutate(confirmDel.id);
              setConfirmDel(null);
            },
          }}
          primaryDisabled={removeReport.isPending}
          secondary={{ label: '취소', onClick: () => setConfirmDel(null) }}
        >
          <p>리포트는 영구 보존되며 목록에서만 숨겨집니다.</p>
          <p className="text-helper">
            "숨긴 리포트 보기" 토글로 다시 표시 가능.
          </p>
        </Modal>
      ) : null}

      <ToastContainer toasts={toasts} onClose={closeToast} />
    </div>
  );
}

// ---------------------------------------------------------------------
// Markdown-lite renderer (h2/h3/li/strong/table)
// ---------------------------------------------------------------------

function parseInline(text: string): React.ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((p, i) =>
    p.startsWith('**') && p.endsWith('**') ? (
      <strong key={i}>{p.slice(2, -2)}</strong>
    ) : (
      <Fragment key={i}>{p}</Fragment>
    ),
  );
}

function renderMD(text: string | null): React.ReactNode {
  if (!text) return null;
  const lines = text.split('\n');
  const out: React.ReactNode[] = [];
  let listBuf: string[] = [];
  let tableBuf: string[] = [];

  const flushList = () => {
    if (listBuf.length) {
      out.push(
        <ul key={`ul-${out.length}`} className="md-ul">
          {listBuf.map((t, i) => (
            <li key={i}>{parseInline(t)}</li>
          ))}
        </ul>,
      );
      listBuf = [];
    }
  };

  const flushTable = () => {
    if (tableBuf.length >= 2) {
      const headers = tableBuf[0]
        .split('|')
        .map((s) => s.trim())
        .filter(Boolean);
      const rows = tableBuf
        .slice(2)
        .map((r) => r.split('|').map((s) => s.trim()).filter(Boolean));
      out.push(
        <table
          key={`tb-${out.length}`}
          className="cds-table cds-table--compact"
          style={{ marginBottom: 12 }}
        >
          <thead>
            <tr>
              {headers.map((h, i) => (
                <th key={i}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                {r.map((c, j) => (
                  <td key={j}>{parseInline(c)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>,
      );
    }
    tableBuf = [];
  };

  lines.forEach((ln, idx) => {
    const t = ln.trim();
    if (t.startsWith('|')) {
      tableBuf.push(t);
      return;
    }
    if (tableBuf.length) flushTable();
    if (t.startsWith('### ')) {
      flushList();
      out.push(
        <h4 key={`h-${idx}`} className="md-h3">
          {t.slice(4)}
        </h4>,
      );
      return;
    }
    if (t.startsWith('## ')) {
      flushList();
      out.push(
        <h3 key={`h-${idx}`} className="md-h2">
          {t.slice(3)}
        </h3>,
      );
      return;
    }
    if (t.startsWith('- ')) {
      listBuf.push(t.slice(2));
      return;
    }
    flushList();
    if (t === '') return;
    out.push(
      <p key={`p-${idx}`} className="md-p">
        {parseInline(t)}
      </p>,
    );
  });
  flushList();
  flushTable();
  return out;
}

// ---------------------------------------------------------------------
// ReportDetailModal
// ---------------------------------------------------------------------

type DetailTab = 'narrative' | 'facts' | 'notes';

interface ReportDetailModalProps {
  report: ReportOut;
  onClose: () => void;
  addToast: ReturnType<typeof useToasts>['addToast'];
}

function ReportDetailModal({
  report,
  onClose,
  addToast,
}: ReportDetailModalProps) {
  const { mock } = useAppShellContext();
  const [tab, setTab] = useState<DetailTab>('narrative');
  const [notes, setNotes] = useState(report.user_notes ?? '');
  const [editingNotes, setEditingNotes] = useState(false);
  const stock = mock.trackedStocks.find(
    (s) => s.stock_code === report.stock_code,
  );

  const patch = usePatchReport(report.id, {
    onSuccess: () => {
      addToast({ kind: 'success', title: '메모 저장됨' });
      setEditingNotes(false);
    },
    onError: (err) => {
      addToast({
        kind: 'error',
        title: '저장 실패',
        subtitle: err instanceof ApiClientError ? err.message : undefined,
      });
    },
  });

  return (
    <Modal
      open
      onClose={onClose}
      size="xl"
      title={`${report.stock_name} 리포트`}
      subtitle={`${report.stock_code} · ${report.model_version ?? ''} · ${formatDateTime(report.created_at)}`}
      secondary={{ label: '닫기', onClick: onClose }}
    >
      {/* Meta strip */}
      <div className="report-meta">
        <div>
          <div className="text-helper">소요</div>
          <div className="mono">
            {report.generation_duration_seconds
              ? `${report.generation_duration_seconds}초`
              : '-'}
          </div>
        </div>
        <div>
          <div className="text-helper">입력 토큰</div>
          <div className="mono">
            {report.prompt_tokens
              ? report.prompt_tokens.toLocaleString()
              : '-'}
          </div>
        </div>
        <div>
          <div className="text-helper">출력 토큰</div>
          <div className="mono">
            {report.completion_tokens
              ? report.completion_tokens.toLocaleString()
              : '-'}
          </div>
        </div>
        {stock ? (
          <div>
            <div className="text-helper">현재가</div>
            <div className="mono">{formatKrw(stock.current_price)}원</div>
          </div>
        ) : null}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          {report.pdf_path ? (
            <Btn
              kind="tertiary"
              size="sm"
              icon={I.Download}
              onClick={() =>
                addToast({ kind: 'info', title: 'PDF 다운로드 (스텁)' })
              }
            >
              PDF
            </Btn>
          ) : null}
          {report.excel_path ? (
            <Btn
              kind="tertiary"
              size="sm"
              icon={I.Download}
              onClick={() =>
                addToast({ kind: 'info', title: 'Excel 다운로드 (스텁)' })
              }
            >
              Excel
            </Btn>
          ) : null}
        </div>
      </div>

      {/* Tabs */}
      <Tabs<DetailTab>
        value={tab}
        onChange={setTab}
        tabs={[
          { value: 'narrative', label: '내러티브' },
          { value: 'facts', label: '객관 팩트' },
          { value: 'notes', label: '내 메모' },
        ]}
      />

      {/* Body */}
      <div className="report-body">
        {tab === 'narrative' ? (
          <div className="md-doc">{renderMD(report.narrative_part)}</div>
        ) : null}
        {tab === 'facts' ? (
          <div className="md-doc">{renderMD(report.facts_part)}</div>
        ) : null}
        {tab === 'notes' ? (
          <div>
            {editingNotes ? (
              <div>
                <Textarea
                  value={notes}
                  onChange={setNotes}
                  rows={8}
                  placeholder="이 리포트에 대한 개인 메모..."
                />
                <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
                  <Btn
                    kind="primary"
                    size="sm"
                    onClick={() =>
                      patch.mutate({ user_notes: notes || null })
                    }
                    disabled={patch.isPending}
                  >
                    {patch.isPending ? '저장 중…' : '저장'}
                  </Btn>
                  <Btn
                    kind="ghost"
                    size="sm"
                    onClick={() => {
                      setNotes(report.user_notes ?? '');
                      setEditingNotes(false);
                    }}
                  >
                    취소
                  </Btn>
                </div>
              </div>
            ) : (
              <div>
                {notes ? (
                  <div
                    className="md-doc"
                    style={{ whiteSpace: 'pre-wrap' }}
                  >
                    {notes}
                  </div>
                ) : (
                  <p className="text-helper">아직 메모가 없습니다.</p>
                )}
                <div style={{ marginTop: 12 }}>
                  <Btn
                    kind="tertiary"
                    size="sm"
                    icon={I.Edit}
                    onClick={() => setEditingNotes(true)}
                  >
                    {notes ? '메모 수정' : '메모 작성'}
                  </Btn>
                </div>
              </div>
            )}
          </div>
        ) : null}
      </div>
    </Modal>
  );
}
