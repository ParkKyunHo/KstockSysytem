import {
  Button,
  InlineNotification,
  ProgressBar,
  Stack,
  TextInput,
} from '@carbon/react';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

export function LoginTotp() {
  const navigate = useNavigate();
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [seconds, setSeconds] = useState(28);

  // 30s rolling countdown.
  useEffect(() => {
    const id = window.setInterval(
      () => setSeconds((s) => (s <= 0 ? 30 : s - 1)),
      1000,
    );
    return () => window.clearInterval(id);
  }, []);

  // Auto-verify when 6 digits typed.
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
        <div className="login-tile__overline">2단계 인증</div>
        <h1>TOTP 코드 입력</h1>
        <p className="login-tile__sub">
          Google Authenticator의 6자리 코드를 입력하세요. (테스트: 123456)
        </p>
        <Stack gap={5}>
          {error ? (
            <InlineNotification
              kind="error"
              title={error}
              onClose={() => setError(null)}
              lowContrast
            />
          ) : null}
          <TextInput
            id="totp-code"
            labelText="인증 코드"
            value={code}
            onChange={(e) =>
              setCode(e.target.value.replace(/\D/g, '').slice(0, 6))
            }
            placeholder="000000"
            maxLength={6}
            size="lg"
            autoFocus
            inputMode="numeric"
            style={{ fontFamily: 'IBM Plex Mono, monospace' }}
          />
          <ProgressBar
            label="다음 코드까지"
            helperText={`${seconds}초`}
            value={30 - seconds}
            max={30}
          />
          <Button
            kind="ghost"
            size="sm"
            onClick={() => {
              /* P5.4: 백업 코드 화면 */
            }}
          >
            백업 코드 사용
          </Button>
        </Stack>
      </div>
    </div>
  );
}
