import { useOutletContext } from 'react-router-dom';
import type { AppShellOutletContext } from '@/components/shell/AppShell';

/**
 * Read live mock + system status from the AppShell layout route.
 * Use this in any page that sits under <AppShell />.
 */
export function useAppShellContext(): AppShellOutletContext {
  return useOutletContext<AppShellOutletContext>();
}
