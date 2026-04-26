(function(){
/* Login + TOTP */
const { useState } = React;
const { Btn, Field, Input, InlineNotif, ProgressBar } = window.UI;

function LoginPage({ onSuccess, onForgotTotp }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const valid = username.length > 0 && password.length >= 4;
  const submit = () => {
    setError(null);
    setLoading(true);
    setTimeout(() => {
      setLoading(false);
      // 프로토타입: 사용자명만 있으면 통과 (admin / 1234 권장)
      if (username.length > 0 && password.length >= 4) onSuccess('totp');
      else setError('로그인 실패: ID와 비밀번호를 입력하세요');
    }, 400);
  };
  return React.createElement('div', { className: 'login-shell' },
    React.createElement('div', { className: 'login-tile' },
      React.createElement('div', { style: { fontSize: 12, color: 'var(--cds-text-helper)', letterSpacing: 0.32, textTransform: 'uppercase', marginBottom: 4 } }, 'V7.1'),
      React.createElement('h1', null, 'K-Stock Trading'),
      React.createElement('p', { className: 'sub' }, '관제 대시보드에 로그인'),
      error && React.createElement(InlineNotif, { kind: 'error', title: '인증 실패', subtitle: error, onClose: () => setError(null) }),
      React.createElement(Field, { label: '사용자 이름' },
        React.createElement(Input, { value: username, onChange: setUsername, placeholder: 'admin', lg: true })),
      React.createElement(Field, { label: '비밀번호' },
        React.createElement(Input, { value: password, onChange: setPassword, type: 'password', placeholder: '4자리 이상', lg: true })),
      React.createElement(Btn, { kind: 'primary', size: 'lg', full: true, onClick: submit, disabled: !valid || loading },
        loading ? '로그인 중...' : '로그인')
    )
  );
}

function TotpPage({ onSuccess, onCancel }) {
  const [code, setCode] = useState('');
  const [error, setError] = useState(null);
  const [seconds, setSeconds] = useState(28);
  React.useEffect(() => {
    const t = setInterval(() => setSeconds(s => s <= 0 ? 30 : s - 1), 1000);
    return () => clearInterval(t);
  }, []);
  React.useEffect(() => {
    if (code.length === 6) {
      if (code === '123456') onSuccess();
      else { setError('잘못된 코드'); setCode(''); }
    }
  }, [code]);
  return React.createElement('div', { className: 'login-shell' },
    React.createElement('div', { className: 'login-tile' },
      React.createElement('div', { style: { fontSize: 12, color: 'var(--cds-text-helper)', letterSpacing: 0.32, textTransform: 'uppercase', marginBottom: 4 } }, '2단계 인증'),
      React.createElement('h1', null, 'TOTP 코드 입력'),
      React.createElement('p', { className: 'sub' }, 'Google Authenticator의 6자리 코드를 입력하세요. (테스트: 123456)'),
      error && React.createElement(InlineNotif, { kind: 'error', title: error, onClose: () => setError(null) }),
      React.createElement(Field, { label: '인증 코드' },
        React.createElement(Input, { value: code, onChange: v => setCode(v.replace(/\D/g, '').slice(0, 6)), placeholder: '000000', maxLength: 6, lg: true, mono: true, autoFocus: true })),
      React.createElement('div', { style: { marginBottom: 16 } },
        React.createElement(ProgressBar, { value: 30 - seconds, max: 30, helper: `다음 코드까지 ${seconds}초` })),
      React.createElement(Btn, { kind: 'ghost', size: 'sm', onClick: onCancel }, '백업 코드 사용')
    )
  );
}

window.Pages = window.Pages || {};
window.Pages.Login = LoginPage;
window.Pages.Totp = TotpPage;

})();
