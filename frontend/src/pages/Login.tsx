import {
  Button,
  InlineNotification,
  PasswordInput,
  Stack,
  TextInput,
} from '@carbon/react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

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
        <div className="login-tile__overline">V7.1</div>
        <h1>K-Stock Trading</h1>
        <p className="login-tile__sub">관제 대시보드에 로그인</p>
        <Stack gap={5}>
          {error ? (
            <InlineNotification
              kind="error"
              title="인증 실패"
              subtitle={error}
              onClose={() => setError(null)}
              hideCloseButton={false}
              lowContrast
            />
          ) : null}
          <TextInput
            id="login-username"
            labelText="사용자 이름"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="admin"
            size="lg"
            autoComplete="username"
          />
          <PasswordInput
            id="login-password"
            labelText="비밀번호"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="4자리 이상"
            size="lg"
            autoComplete="current-password"
            onKeyDown={(e) => {
              if (e.key === 'Enter' && valid && !loading) submit();
            }}
          />
          <Button
            kind="primary"
            size="lg"
            onClick={submit}
            disabled={!valid || loading}
            style={{ width: '100%' }}
          >
            {loading ? '로그인 중...' : '로그인'}
          </Button>
        </Stack>
      </div>
    </div>
  );
}
