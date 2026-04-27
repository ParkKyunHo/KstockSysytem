// V7.1 TOTP -- wired to /api/v71/auth/totp/verify (PRD §1.2 step 2).

import { useEffect, useRef, useState } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';

import { Btn, Field, InlineNotif, Input, ProgressBar } from '@/components/ui';
import { useAuth } from '@/contexts/AuthContext';
import { ApiClientError } from '@/lib/api';

interface LoginTotpState {
  sessionId: string;
  from?: string;
}

export function LoginTotp() {
  const navigate = useNavigate();
  const location = useLocation();
  const { verifyTotp } = useAuth();

  const state = (location.state as LoginTotpState | null) ?? null;
  const sessionId = state?.sessionId;

  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [seconds, setSeconds] = useState(30);
  const [submitting, setSubmitting] = useState(false);
  const submittedFor = useRef<string | null>(null);

  useEffect(() => {
    const id = window.setInterval(
      () => setSeconds((s) => (s <= 0 ? 30 : s - 1)),
      1000,
    );
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    if (
      code.length === 6 &&
      !submitting &&
      submittedFor.current !== code &&
      sessionId
    ) {
      submittedFor.current = code;
      void (async () => {
        setSubmitting(true);
        setError(null);
        try {
          await verifyTotp(sessionId, code);
          navigate(state?.from ?? '/dashboard', { replace: true });
        } catch (err) {
          if (err instanceof ApiClientError) {
            if (err.errorCode === 'INVALID_TOTP') {
              setError('잘못된 코드입니다.');
            } else if (err.errorCode === 'SESSION_EXPIRED') {
              setError('세션이 만료되었습니다. 다시 로그인하세요.');
            } else {
              setError('인증 실패: ' + err.message);
            }
          } else {
            setError('네트워크 오류');
          }
          setCode('');
        } finally {
          setSubmitting(false);
        }
      })();
    }
  }, [code, submitting, verifyTotp, sessionId, navigate, state]);

  if (!sessionId) {
    // Reload-after-totp scenario: kick the user back to /login.
    return <Navigate to="/login" replace />;
  }

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
          Google Authenticator의 6자리 코드를 입력하세요.
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
            disabled={submitting}
          />
        </Field>
        <div style={{ marginBottom: 16 }}>
          <ProgressBar
            value={30 - seconds}
            max={30}
            helper={`다음 코드까지 ${seconds}초`}
          />
        </div>
        <Btn
          kind="ghost"
          size="sm"
          onClick={() => navigate('/login', { replace: true })}
        >
          로그인 화면으로
        </Btn>
      </div>
    </div>
  );
}
