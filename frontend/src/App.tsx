import { useEffect } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';

import { AppShell } from '@/components/shell/AppShell';
import {
  PrivateRoute,
  PublicOnlyRoute,
} from '@/contexts/PrivateRoute';
import { Login } from '@/pages/Login';
import { LoginTotp } from '@/pages/LoginTotp';
import { Dashboard } from '@/pages/Dashboard';
import { TrackedStocks } from '@/pages/TrackedStocks';
import { TrackedStockDetail } from '@/pages/TrackedStockDetail';
import { BoxWizard } from '@/pages/BoxWizard';
import { Positions } from '@/pages/Positions';
import { TradeEvents } from '@/pages/TradeEvents';
import { Reports } from '@/pages/Reports';
import { Notifications } from '@/pages/Notifications';
import { Settings } from '@/pages/Settings';
import { useTheme } from '@/hooks/useTheme';

export default function App() {
  const { theme, cycleTheme } = useTheme();

  // Apply theme class on <html> -- mirrors prototype's setAttribute call.
  useEffect(() => {
    document.documentElement.classList.remove(
      'theme-g10',
      'theme-g90',
      'theme-g100',
      'theme-white',
    );
    document.documentElement.classList.add(`theme-${theme}`);
  }, [theme]);

  return (
    <>
      <Routes>
        {/* Auth pages render without the AppShell. Already-logged-in
            users are redirected to /dashboard. */}
        <Route
          path="/login"
          element={
            <PublicOnlyRoute>
              <Login />
            </PublicOnlyRoute>
          }
        />
        <Route
          path="/login/totp"
          element={
            <PublicOnlyRoute>
              <LoginTotp />
            </PublicOnlyRoute>
          }
        />

        {/* All other routes share AppShell -- protected. */}
        <Route
          element={
            <PrivateRoute>
              <AppShell theme={theme} onCycleTheme={cycleTheme} />
            </PrivateRoute>
          }
        >
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/tracked-stocks" element={<TrackedStocks />} />
          <Route path="/tracked-stocks/:id" element={<TrackedStockDetail />} />
          <Route path="/boxes/new" element={<BoxWizard />} />
          <Route path="/positions" element={<Positions />} />
          <Route path="/trade-events" element={<TradeEvents />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/notifications" element={<Notifications />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Route>
      </Routes>
    </>
  );
}
