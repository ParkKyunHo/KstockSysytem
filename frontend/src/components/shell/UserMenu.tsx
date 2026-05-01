// UserMenu -- header user avatar + dropdown with Settings / Logout.
//
// Pattern mirrors the YouTube account menu: clicking the avatar opens a
// floating panel with user info on top, navigation items below, and an
// explicit logout button at the bottom. Closing handlers:
//   * outside click (mousedown listener with ref-contains)
//   * Escape key (document keydown)
//   * after a menu item is clicked
//
// Replaces the previous behaviour (avatar click → /settings) so the user
// can log out without having to dig into the settings page.

import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import { useNavigate } from 'react-router-dom';

import { I } from '@/components/icons';
import { useAuth } from '@/contexts/AuthContext';

interface UserMenuProps {
  userInitial: string;
  userName: string;
  userRole?: string | null;
}

export function UserMenu({ userInitial, userName, userRole }: UserMenuProps) {
  const [open, setOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const { logout } = useAuth();
  const navigate = useNavigate();

  // Outside click + Escape close.
  useEffect(() => {
    if (!open) return;
    const handleClick = (e: MouseEvent) => {
      if (
        wrapperRef.current &&
        !wrapperRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', handleClick);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleClick);
      document.removeEventListener('keydown', handleKey);
    };
  }, [open]);

  const handleSettings = useCallback(() => {
    setOpen(false);
    navigate('/settings');
  }, [navigate]);

  const handleLogout = useCallback(async () => {
    if (loggingOut) return;
    setLoggingOut(true);
    try {
      await logout();
    } finally {
      setLoggingOut(false);
      setOpen(false);
      navigate('/login', { replace: true });
    }
  }, [logout, navigate, loggingOut]);

  return (
    <div ref={wrapperRef} style={{ position: 'relative' }}>
      <button
        type="button"
        className="cds-header__user"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="사용자 메뉴"
        style={{
          background: 'transparent',
          border: 0,
          color: 'inherit',
          font: 'inherit',
        }}
      >
        <div className="cds-header__avatar">{userInitial}</div>
        <span className="cds-header__name-text">{userName}</span>
      </button>
      {open ? (
        <div
          role="menu"
          aria-label="사용자 메뉴"
          style={{
            position: 'absolute',
            top: '100%',
            right: 0,
            minWidth: 240,
            background: 'var(--cds-layer-01)',
            color: 'var(--cds-text-primary)',
            boxShadow: '0 2px 8px rgba(0, 0, 0, 0.4)',
            border: '1px solid var(--cds-border-subtle-00)',
            zIndex: 100,
          }}
        >
          {/* User info */}
          <div
            style={{
              padding: '12px 16px',
              borderBottom: '1px solid var(--cds-border-subtle-00)',
              display: 'flex',
              alignItems: 'center',
              gap: 12,
            }}
          >
            <div
              className="cds-header__avatar"
              style={{ width: 32, height: 32, fontSize: 14 }}
            >
              {userInitial}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <span style={{ fontSize: 14, fontWeight: 600 }}>{userName}</span>
              <span
                style={{
                  fontSize: 12,
                  color: 'var(--cds-text-helper)',
                  marginTop: 2,
                }}
              >
                {userRole ?? 'OWNER'}
              </span>
            </div>
          </div>

          {/* Settings */}
          <button
            type="button"
            role="menuitem"
            className="overflow-menu__item"
            onClick={handleSettings}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
            }}
          >
            <I.Settings className="cds-icon" size={16} />
            <span>설정</span>
          </button>

          {/* Divider */}
          <div className="overflow-menu__divider" />

          {/* Logout */}
          <button
            type="button"
            role="menuitem"
            className="overflow-menu__item overflow-menu__item--danger"
            onClick={() => {
              void handleLogout();
            }}
            disabled={loggingOut}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              opacity: loggingOut ? 0.6 : 1,
              cursor: loggingOut ? 'wait' : 'pointer',
            }}
          >
            <I.Logout className="cds-icon" size={16} />
            <span>{loggingOut ? '로그아웃 중...' : '로그아웃'}</span>
          </button>
        </div>
      ) : null}
    </div>
  );
}
