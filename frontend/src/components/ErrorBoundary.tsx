// React ErrorBoundary -- production build 에서 어떤 컴포넌트 에러도
// entire tree unmount (검은 화면) 로 흐르지 않게 안전망 제공.
//
// trigger 예시:
//   * API 응답 schema 미스매치 (number 기대인데 string)
//   * 라이브러리 chunk load 실패
//   * 네트워크 단절 중 컴포넌트 mount
//
// fallback 정책:
//   1. "새로고침" -- window.location.reload(). 단순 일시 에러 복구.
//   2. "데이터 지우고 재시작" -- localStorage/sessionStorage 비운 뒤
//      reload. 토큰 만료 / Query cache 손상 등 누적 상태가 원인일 때.
//
// 디자인은 Carbon CDS 변수에 정렬해서 g100 dark theme 와 자연스럽게 어울림.
// CSS variable 미정의 시 fallback 색을 inline 으로 지정해 ErrorBoundary
// 자체가 다시 렌더 실패하지 않도록 한다.

import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null, errorInfo: null };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    // production 에서도 console 에 남아 DevTools 로 진단 가능.
    // eslint-disable-next-line no-console
    console.error('[ErrorBoundary]', error, errorInfo);
    this.setState({ errorInfo });
  }

  private handleReload = (): void => {
    window.location.reload();
  };

  private handleClearAndReload = (): void => {
    try {
      window.localStorage.clear();
      window.sessionStorage.clear();
    } catch {
      // 일부 브라우저 (private mode) 가 storage access 거부 -- 무시.
    }
    window.location.reload();
  };

  render(): ReactNode {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return (
      <div
        style={{
          position: 'fixed',
          inset: 0,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '2rem',
          background: 'var(--cds-background, #161616)',
          color: 'var(--cds-text-primary, #f4f4f4)',
          fontFamily: '"IBM Plex Sans", system-ui, sans-serif',
          gap: '1rem',
          textAlign: 'center',
        }}
      >
        <div
          style={{
            fontSize: '1.5rem',
            fontWeight: 400,
            color: 'var(--cds-support-error, #fa4d56)',
          }}
        >
          예기치 못한 오류가 발생했습니다
        </div>
        <p
          style={{
            color: 'var(--cds-text-helper, #a8a8a8)',
            maxWidth: '36rem',
            lineHeight: 1.5,
            margin: 0,
          }}
        >
          화면을 새로고침하거나, 로컬 데이터를 지우고 다시 로그인하면
          대부분 복구됩니다. 반복되면 콘솔의 상세 정보를 캡처해 주세요.
        </p>
        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <button
            type="button"
            onClick={this.handleReload}
            style={{
              padding: '0.5rem 1.25rem',
              fontSize: '0.875rem',
              cursor: 'pointer',
              background: 'var(--cds-button-primary, #0f62fe)',
              color: '#ffffff',
              border: 'none',
              fontFamily: 'inherit',
            }}
          >
            새로고침
          </button>
          <button
            type="button"
            onClick={this.handleClearAndReload}
            style={{
              padding: '0.5rem 1.25rem',
              fontSize: '0.875rem',
              cursor: 'pointer',
              background: 'transparent',
              color: 'var(--cds-text-primary, #f4f4f4)',
              border: '1px solid var(--cds-border-strong, #6f6f6f)',
              fontFamily: 'inherit',
            }}
          >
            데이터 지우고 재시작
          </button>
        </div>
        <details
          style={{
            marginTop: '1.5rem',
            maxWidth: '60rem',
            width: '100%',
            textAlign: 'left',
          }}
        >
          <summary
            style={{
              cursor: 'pointer',
              color: 'var(--cds-text-helper, #a8a8a8)',
              fontSize: '0.875rem',
            }}
          >
            상세 정보
          </summary>
          <pre
            style={{
              marginTop: '0.5rem',
              padding: '1rem',
              background: 'var(--cds-layer, #262626)',
              color: 'var(--cds-text-secondary, #c6c6c6)',
              fontFamily: '"IBM Plex Mono", monospace',
              fontSize: '0.75rem',
              overflow: 'auto',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              maxHeight: '20rem',
            }}
          >
            {this.state.error ? this.state.error.toString() : 'Unknown error'}
            {this.state.errorInfo?.componentStack
              ? `\n\nComponent stack:${this.state.errorInfo.componentStack}`
              : ''}
          </pre>
        </details>
      </div>
    );
  }
}
