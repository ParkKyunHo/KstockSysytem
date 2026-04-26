import { Stack, Tile } from '@carbon/react';

/**
 * P5.3에서 본 화면이 구현됩니다 (10_UI_GUIDE_CARBON.md §3 + 12_SECURITY.md §3).
 */
export function Login() {
  return (
    <div
      style={{
        display: 'flex',
        minHeight: '100vh',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '1.5rem',
        background: 'var(--cds-background)',
      }}
    >
      <Tile style={{ maxWidth: '24rem', width: '100%', padding: '1.5rem' }}>
        <Stack gap={5}>
          <div>
            <h1 style={{ margin: 0, fontSize: '1.5rem' }}>V7.1</h1>
            <p style={{ color: 'var(--cds-text-secondary)' }}>K-Stock Trading</p>
          </div>
          <p>P5.3 -- 로그인 화면 (ID/PW + InlineNotification + InlineLoading)</p>
        </Stack>
      </Tile>
    </div>
  );
}
