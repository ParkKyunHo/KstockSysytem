import { Theme } from '@carbon/react';
import { Navigate, Route, Routes } from 'react-router-dom';

import { AppShell } from '@/components/shell/AppShell';
import { Login } from '@/pages/Login';
import { LoginTotp } from '@/pages/LoginTotp';
import { Dashboard } from '@/pages/Dashboard';
import { TrackedStocks } from '@/pages/TrackedStocks';
import { TrackedStockDetail } from '@/pages/TrackedStockDetail';
import { BoxWizard } from '@/pages/BoxWizard';
import { Positions } from '@/pages/Positions';
import { Reports } from '@/pages/Reports';
import { Notifications } from '@/pages/Notifications';
import { Settings } from '@/pages/Settings';
import { useTheme } from '@/hooks/useTheme';

export default function App() {
  const { theme, cycleTheme } = useTheme();

  return (
    <Theme theme={theme}>
      <Routes>
        {/* Auth pages render without the AppShell. */}
        <Route path="/login" element={<Login />} />
        <Route path="/login/totp" element={<LoginTotp />} />

        {/* All other routes share AppShell. */}
        <Route element={<AppShell theme={theme} onCycleTheme={cycleTheme} />}>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/tracked-stocks" element={<TrackedStocks />} />
          <Route path="/tracked-stocks/:id" element={<TrackedStockDetail />} />
          <Route path="/boxes/new" element={<BoxWizard />} />
          <Route path="/positions" element={<Positions />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/notifications" element={<Notifications />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Route>
      </Routes>
    </Theme>
  );
}
