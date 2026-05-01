// V7.1 Login -- wired to /api/v71/auth/login (PRD §1.2 step 1).

import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

import { Btn, Field, InlineNotif, Input } from '@/components/ui';
import { useAuth } from '@/contexts/AuthContext';
import { ApiClientError } from '@/lib/api';

export function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login } = useAuth();

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // backend LoginRequest min_length=5 (PRD §1.2 권장 8자, dev/admin 5자 허용).
  // production rbsgh4는 11자 비번이라 영향 0.
  const valid = username.length >= 3 && password.length >= 5;

  const submit = async () => {
    if (!valid || loading) return;
    setError(null);
    setLoading(true);
    try {
      const result = await login(username, password);
      if (result.totp_required) {
        navigate('/login/totp', {
          state: {
            sessionId: result.session_id,
            from: (location.state as { from?: string } | null)?.from,
          },
        });
        return;
      }
      const redirectTo =
        (location.state as { from?: string } | null)?.from ?? '/dashboard';
      navigate(redirectTo, { replace: true });
    } catch (err) {
      if (err instanceof ApiClientError) {
        if (err.errorCode === 'RATE_LIMIT_EXCEEDED') {
          setError('로그인 시도가 너무 많습니다. 잠시 후 다시 시도하세요.');
        } else {
          setError('로그인 실패: 사용자 이름/비밀번호를 확인하세요.');
        }
      } else {
        setError('네트워크 오류로 로그인할 수 없습니다.');
      }
    } finally {
      setLoading(false);
    }
  };

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
          V7.1
        </div>
        <h1>K-Stock Trading</h1>
        <p className="sub">관제 대시보드에 로그인</p>
        {error ? (
          <InlineNotif
            kind="error"
            title="인증 실패"
            subtitle={error}
            onClose={() => setError(null)}
          />
        ) : null}
        <Field label="사용자 이름">
          <Input
            value={username}
            onChange={setUsername}
            placeholder="3~50자 영숫자_"
            lg
          />
        </Field>
        <Field label="비밀번호">
          <Input
            value={password}
            onChange={setPassword}
            type="password"
            placeholder="8자리 이상"
            lg
            onKeyDown={(e) => {
              if (e.key === 'Enter' && valid && !loading) void submit();
            }}
          />
        </Field>
        <Btn
          kind="primary"
          size="lg"
          full
          onClick={() => void submit()}
          disabled={!valid || loading}
        >
          {loading ? '로그인 중...' : '로그인'}
        </Btn>
      </div>
    </div>
  );
}
