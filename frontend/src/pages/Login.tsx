// V7.1 Login -- direct port of frontend-prototype/src/pages/login.js LoginPage.

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { Btn, Field, InlineNotif, Input } from '@/components/ui';

export function Login() {
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const valid = username.length > 0 && password.length >= 4;

  const submit = () => {
    setError(null);
    setLoading(true);
    setTimeout(() => {
      setLoading(false);
      if (valid) {
        navigate('/login/totp');
      } else {
        setError('로그인 실패: ID와 비밀번호를 입력하세요');
      }
    }, 400);
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
            placeholder="admin"
            lg
          />
        </Field>
        <Field label="비밀번호">
          <Input
            value={password}
            onChange={setPassword}
            type="password"
            placeholder="4자리 이상"
            lg
            onKeyDown={(e) => {
              if (e.key === 'Enter' && valid && !loading) submit();
            }}
          />
        </Field>
        <Btn
          kind="primary"
          size="lg"
          full
          onClick={submit}
          disabled={!valid || loading}
        >
          {loading ? '로그인 중...' : '로그인'}
        </Btn>
      </div>
    </div>
  );
}
