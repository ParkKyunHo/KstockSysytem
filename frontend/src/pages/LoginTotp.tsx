// V7.1 TOTP -- direct port of frontend-prototype/src/pages/login.js TotpPage.

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { Btn, Field, InlineNotif, Input, ProgressBar } from '@/components/ui';

export function LoginTotp() {
  const navigate = useNavigate();
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [seconds, setSeconds] = useState(28);

  useEffect(() => {
    const id = window.setInterval(
      () => setSeconds((s) => (s <= 0 ? 30 : s - 1)),
      1000,
    );
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    if (code.length === 6) {
      if (code === '123456') {
        navigate('/dashboard');
      } else {
        setError('잘못된 코드');
        setCode('');
      }
    }
  }, [code, navigate]);

  return (
    <div className="login-shell">
      <div className="login-tile">
        <div
          style={{
            fontSize: 12,
            color: 'var(--cds-text-helper)',
            letterSpacing: 0.32,
            textTransform: 'uppercase',
            marginBottom: 4,
          }}
        >
          2단계 인증
        </div>
        <h1>TOTP 코드 입력</h1>
        <p className="sub">
          Google Authenticator의 6자리 코드를 입력하세요. (테스트: 123456)
        </p>
        {error ? (
          <InlineNotif
            kind="error"
            title={error}
            onClose={() => setError(null)}
          />
        ) : null}
        <Field label="인증 코드">
          <Input
            value={code}
            onChange={(v) => setCode(v.replace(/\D/g, '').slice(0, 6))}
            placeholder="000000"
            maxLength={6}
            lg
            mono
            autoFocus
          />
        </Field>
        <div style={{ marginBottom: 16 }}>
          <ProgressBar
            value={30 - seconds}
            max={30}
            helper={`다음 코드까지 ${seconds}초`}
          />
        </div>
        <Btn kind="ghost" size="sm">
          백업 코드 사용
        </Btn>
      </div>
    </div>
  );
}
