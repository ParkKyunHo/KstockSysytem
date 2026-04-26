import { Stack, Tile } from '@carbon/react';

export function LoginTotp() {
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
            <h2 style={{ margin: 0 }}>2단계 인증</h2>
          </div>
          <p>P5.3 -- TOTP 6자리 입력 + ProgressBar 30초</p>
        </Stack>
      </Tile>
    </div>
  );
}
