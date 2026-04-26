(function(){
/* Reports — list + detail (AI-generated stock research) */
const { useState, useMemo } = React;
const U = window.UI;
const I = window.Icons;

// Status mapping
const STATUS_TAG = {
  COMPLETED:  { type: 'green',     label: '완료' },
  GENERATING: { type: 'blue',      label: '생성 중' },
  PENDING:    { type: 'cool-gray', label: '대기' },
  FAILED:     { type: 'red',       label: '실패' },
};

function Reports({ mock, onNav, addToast, openId }) {
  const [search, setSearch] = useState('');
  const [tab, setTab] = useState('all');
  const [openReport, setOpenReport] = useState(null);
  const [confirmRegen, setConfirmRegen] = useState(null);
  const [confirmDel, setConfirmDel] = useState(null);

  // Auto-open if openId passed in
  React.useEffect(() => {
    if (openId) {
      const r = mock.reports.find(x => x.id === openId);
      if (r) setOpenReport(r);
    }
  }, [openId]);

  const list = useMemo(() => mock.reports.filter(r => {
    if (search && !r.stock_name.includes(search) && !r.stock_code.includes(search)) return false;
    if (tab !== 'all' && r.status !== tab) return false;
    return true;
  }), [search, tab, mock.reports]);

  return React.createElement('div', null,
    React.createElement('div', { className: 'page-hd' },
      React.createElement('div', null,
        React.createElement('h1', { className: 'page-hd__title' }, '리서치 리포트'),
        React.createElement('div', { className: 'page-hd__subtitle' }, 'Claude가 생성하는 종목별 분석 리포트 · 총 ', mock.reports.length, '개')),
      React.createElement('div', { className: 'page-hd__actions' },
        React.createElement(U.Btn, { kind: 'primary', size: 'sm', icon: I.Add, onClick: () => addToast({ kind: 'info', title: '리포트 생성 — 추적 종목 페이지에서 시작' }) }, '리포트 생성'))),

    React.createElement(U.Tabs, { value: tab, onChange: setTab, tabs: [
      { value: 'all', label: '전체', count: mock.reports.length },
      { value: 'COMPLETED', label: '완료', count: mock.reports.filter(r=>r.status==='COMPLETED').length },
      { value: 'GENERATING', label: '생성 중', count: mock.reports.filter(r=>r.status==='GENERATING').length },
      { value: 'PENDING', label: '대기', count: mock.reports.filter(r=>r.status==='PENDING').length },
      { value: 'FAILED', label: '실패', count: mock.reports.filter(r=>r.status==='FAILED').length },
    ]}),

    React.createElement('div', { className: 'cds-data-table', style: { marginTop: 16 } },
      React.createElement('div', { className: 'table-toolbar' },
        React.createElement(U.SearchBox, { value: search, onChange: setSearch, placeholder: '종목명 또는 코드' })),
      React.createElement('div', { className: 'table-wrap' },
        React.createElement('table', { className: 'cds-table' },
          React.createElement('thead', null,
            React.createElement('tr', null,
              React.createElement('th', null, '종목'),
              React.createElement('th', null, '상태'),
              React.createElement('th', null, '모델'),
              React.createElement('th', { style: { textAlign: 'right' } }, '토큰'),
              React.createElement('th', { style: { textAlign: 'right' } }, '소요'),
              React.createElement('th', null, '생성일'),
              React.createElement('th', null, ''))),
          React.createElement('tbody', null,
            list.map(r => {
              const tag = STATUS_TAG[r.status] || STATUS_TAG.PENDING;
              const totalTokens = (r.prompt_tokens || 0) + (r.completion_tokens || 0);
              return React.createElement('tr', { key: r.id, style: { cursor: r.status === 'COMPLETED' ? 'pointer' : 'default' },
                  onClick: () => r.status === 'COMPLETED' && setOpenReport(r) },
                React.createElement('td', null,
                  React.createElement('strong', null, r.stock_name), ' ',
                  React.createElement('span', { className: 'mono text-helper' }, r.stock_code)),
                React.createElement('td', null,
                  React.createElement(U.Tag, { type: tag.type, size: 'sm' }, tag.label),
                  r.status === 'GENERATING' && r.progress != null &&
                    React.createElement('div', { style: { width: 80, marginTop: 4 } },
                      React.createElement(U.ProgressBar, { value: r.progress, max: 100, helper: r.progress + '%' }))),
                React.createElement('td', { className: 'mono', style: { fontSize: 12 } }, r.model_version || '-'),
                React.createElement('td', { className: 'price' }, totalTokens ? totalTokens.toLocaleString() : '-'),
                React.createElement('td', { className: 'price' }, r.generation_duration_seconds ? r.generation_duration_seconds + '초' : '-'),
                React.createElement('td', { className: 'mono', style: { fontSize: 12 } }, window.fmt.relative(r.created_at)),
                React.createElement('td', { onClick: e => e.stopPropagation() },
                  React.createElement(U.OverflowMenu, { items: [
                    r.status === 'COMPLETED' && { label: '열기', onClick: () => setOpenReport(r) },
                    r.status === 'COMPLETED' && r.pdf_path && { label: 'PDF 다운로드', onClick: () => addToast({ kind: 'info', title: 'PDF 다운로드 (스텁)', subtitle: r.pdf_path }) },
                    r.status === 'COMPLETED' && r.excel_path && { label: 'Excel 다운로드', onClick: () => addToast({ kind: 'info', title: 'Excel 다운로드 (스텁)', subtitle: r.excel_path }) },
                    r.status !== 'GENERATING' && { label: '재생성', onClick: () => setConfirmRegen(r) },
                    { divider: true },
                    { label: '삭제', danger: true, onClick: () => setConfirmDel(r) },
                  ].filter(Boolean) })));
            }))))),

    openReport && React.createElement(ReportDetailModal, { report: openReport, mock, onClose: () => setOpenReport(null), addToast }),
    confirmRegen && React.createElement(U.Modal, {
      open: true, onClose: () => setConfirmRegen(null),
      title: '리포트 재생성', subtitle: confirmRegen.stock_name + ' (' + confirmRegen.stock_code + ')',
      primary: { label: '재생성', onClick: () => { addToast({ kind: 'success', title: '재생성 시작', subtitle: '예상 소요: 5분' }); setConfirmRegen(null); }},
      secondary: { label: '취소', onClick: () => setConfirmRegen(null) },
    },
      React.createElement('p', null, '기존 리포트는 보존되며 새 버전이 생성됩니다.'),
      React.createElement('p', { className: 'text-helper' }, '예상 토큰 사용: ~20,000 / 비용: ~$0.30')),

    confirmDel && React.createElement(U.Modal, {
      open: true, danger: true, onClose: () => setConfirmDel(null),
      title: '리포트 삭제', subtitle: confirmDel.stock_name,
      primary: { label: '삭제', onClick: () => { addToast({ kind: 'success', title: '리포트 삭제됨' }); setConfirmDel(null); }},
      secondary: { label: '취소', onClick: () => setConfirmDel(null) },
    },
      React.createElement('p', null, '이 작업은 되돌릴 수 없습니다.'))
  );
}

// ----- Markdown-lite renderer (h2/h3/li/strong/table) -----
function renderMD(text) {
  if (!text) return null;
  const lines = text.split('\n');
  const out = [];
  let listBuf = [];
  let tableBuf = [];
  const flushList = () => {
    if (listBuf.length) {
      out.push(React.createElement('ul', { key: 'ul-' + out.length, className: 'md-ul' },
        listBuf.map((t, i) => React.createElement('li', { key: i }, parseInline(t)))));
      listBuf = [];
    }
  };
  const flushTable = () => {
    if (tableBuf.length >= 2) {
      const headers = tableBuf[0].split('|').map(s => s.trim()).filter(Boolean);
      const rows = tableBuf.slice(2).map(r => r.split('|').map(s => s.trim()).filter(Boolean));
      out.push(React.createElement('table', { key: 'tb-' + out.length, className: 'cds-table cds-table--compact', style: { marginBottom: 12 } },
        React.createElement('thead', null, React.createElement('tr', null, headers.map((h, i) => React.createElement('th', { key: i }, h)))),
        React.createElement('tbody', null, rows.map((r, i) =>
          React.createElement('tr', { key: i }, r.map((c, j) =>
            React.createElement('td', { key: j }, parseInline(c))))))));
    }
    tableBuf = [];
  };
  lines.forEach((ln, idx) => {
    const t = ln.trim();
    if (t.startsWith('|')) { tableBuf.push(t); return; }
    if (tableBuf.length) flushTable();
    if (t.startsWith('### ')) { flushList(); out.push(React.createElement('h4', { key: 'h-'+idx, className: 'md-h3' }, t.slice(4))); return; }
    if (t.startsWith('## '))  { flushList(); out.push(React.createElement('h3', { key: 'h-'+idx, className: 'md-h2' }, t.slice(3))); return; }
    if (t.startsWith('- '))   { listBuf.push(t.slice(2)); return; }
    flushList();
    if (t === '') return;
    out.push(React.createElement('p', { key: 'p-'+idx, className: 'md-p' }, parseInline(t)));
  });
  flushList(); flushTable();
  return out;
}

function parseInline(text) {
  // **bold**
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((p, i) => {
    if (p.startsWith('**') && p.endsWith('**')) return React.createElement('strong', { key: i }, p.slice(2, -2));
    return p;
  });
}

function ReportDetailModal({ report, mock, onClose, addToast }) {
  const [tab, setTab] = useState('narrative');
  const [notes, setNotes] = useState(report.user_notes || '');
  const [editingNotes, setEditingNotes] = useState(false);
  const stock = mock.trackedStocks.find(s => s.stock_code === report.stock_code);

  return React.createElement(U.Modal, {
    open: true, onClose, size: 'xl', title: report.stock_name + ' 리포트',
    subtitle: report.stock_code + ' · ' + (report.model_version || '') + ' · ' + window.fmt.dateTime(report.created_at),
    secondary: { label: '닫기', onClick: onClose },
  },
    // Meta strip
    React.createElement('div', { className: 'report-meta' },
      React.createElement('div', null,
        React.createElement('div', { className: 'text-helper' }, '소요'),
        React.createElement('div', { className: 'mono' }, report.generation_duration_seconds ? report.generation_duration_seconds + '초' : '-')),
      React.createElement('div', null,
        React.createElement('div', { className: 'text-helper' }, '입력 토큰'),
        React.createElement('div', { className: 'mono' }, report.prompt_tokens ? report.prompt_tokens.toLocaleString() : '-')),
      React.createElement('div', null,
        React.createElement('div', { className: 'text-helper' }, '출력 토큰'),
        React.createElement('div', { className: 'mono' }, report.completion_tokens ? report.completion_tokens.toLocaleString() : '-')),
      stock && React.createElement('div', null,
        React.createElement('div', { className: 'text-helper' }, '현재가'),
        React.createElement('div', { className: 'mono' }, window.fmt.krw(stock.current_price), '원')),
      React.createElement('div', { style: { marginLeft: 'auto', display: 'flex', gap: 8 } },
        report.pdf_path && React.createElement(U.Btn, { kind: 'tertiary', size: 'sm', icon: I.Download,
          onClick: () => addToast({ kind: 'info', title: 'PDF 다운로드 (스텁)' }) }, 'PDF'),
        report.excel_path && React.createElement(U.Btn, { kind: 'tertiary', size: 'sm', icon: I.Download,
          onClick: () => addToast({ kind: 'info', title: 'Excel 다운로드 (스텁)' }) }, 'Excel'))),

    // Tabs
    React.createElement(U.Tabs, { value: tab, onChange: setTab, tabs: [
      { value: 'narrative', label: '내러티브' },
      { value: 'facts', label: '객관 팩트' },
      { value: 'notes', label: '내 메모' },
    ]}),

    // Body
    React.createElement('div', { className: 'report-body' },
      tab === 'narrative' && React.createElement('div', { className: 'md-doc' }, renderMD(report.narrative_part)),
      tab === 'facts' && React.createElement('div', { className: 'md-doc' }, renderMD(report.facts_part)),
      tab === 'notes' && React.createElement('div', null,
        editingNotes
          ? React.createElement('div', null,
              React.createElement(U.Textarea, { value: notes, onChange: setNotes, rows: 8, placeholder: '이 리포트에 대한 개인 메모...' }),
              React.createElement('div', { style: { marginTop: 12, display: 'flex', gap: 8 } },
                React.createElement(U.Btn, { kind: 'primary', size: 'sm', onClick: () => { setEditingNotes(false); addToast({ kind: 'success', title: '메모 저장됨' }); }}, '저장'),
                React.createElement(U.Btn, { kind: 'ghost', size: 'sm', onClick: () => { setNotes(report.user_notes || ''); setEditingNotes(false); }}, '취소')))
          : React.createElement('div', null,
              notes
                ? React.createElement('div', { className: 'md-doc', style: { whiteSpace: 'pre-wrap' } }, notes)
                : React.createElement('p', { className: 'text-helper' }, '아직 메모가 없습니다.'),
              React.createElement('div', { style: { marginTop: 12 } },
                React.createElement(U.Btn, { kind: 'tertiary', size: 'sm', icon: I.Edit, onClick: () => setEditingNotes(true) }, notes ? '메모 수정' : '메모 작성')))))
  );
}

window.Pages = window.Pages || {};
window.Pages.Reports = Reports;

})();
