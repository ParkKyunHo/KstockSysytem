import { useCallback, useEffect, useState } from 'react';
import type { ThemeName } from '@/types';

const STORAGE_KEY = 'v71.theme';
const DEFAULT_THEME: ThemeName = 'g100';
// Header icon click cycles through this order (matches the prototype).
const CYCLE: ThemeName[] = ['g100', 'g10', 'g90'];

function readStored(): ThemeName {
  if (typeof window === 'undefined') return DEFAULT_THEME;
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (raw === 'g100' || raw === 'g90' || raw === 'g10' || raw === 'white') {
    return raw;
  }
  return DEFAULT_THEME;
}

/**
 * Theme controller.
 *
 * Sets `data-cds-theme` on <html> and persists to localStorage. The
 * Carbon `<Theme>` component honours this attribute when it sits at
 * the layout root.
 */
export function useTheme(): {
  theme: ThemeName;
  setTheme: (next: ThemeName) => void;
  cycleTheme: () => ThemeName;
} {
  const [theme, setThemeState] = useState<ThemeName>(() => readStored());

  useEffect(() => {
    const html = document.documentElement;
    html.setAttribute('data-cds-theme', theme);
    window.localStorage.setItem(STORAGE_KEY, theme);
  }, [theme]);

  const setTheme = useCallback((next: ThemeName) => setThemeState(next), []);

  const cycleTheme = useCallback(() => {
    let resolved: ThemeName = DEFAULT_THEME;
    setThemeState((current) => {
      const index = CYCLE.indexOf(current);
      const next = CYCLE[(index + 1) % CYCLE.length] ?? DEFAULT_THEME;
      resolved = next;
      return next;
    });
    return resolved;
  }, []);

  return { theme, setTheme, cycleTheme };
}
