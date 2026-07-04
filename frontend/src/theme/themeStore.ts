import { ref, type Ref } from 'vue';

/**
 * Module-level singleton store for the user's theme preference.
 *
 * The actual DOM application of the resolved theme happens in App.vue (which
 * owns the prefers-color-scheme media query listener and the resolvedThemeMode
 * computed). This store exists purely so other components — such as the
 * Appearance settings section — can read and update the user's preference
 * without going through prop drilling or events.
 */
export type ThemePreference = 'dark' | 'light' | 'system';

export const THEME_PREFERENCE_STORAGE_KEY = 'theme-mode';
export const SYSTEM_PREFERS_DARK_QUERY = '(prefers-color-scheme: dark)';

export function readStoredThemePreference(): ThemePreference {
  try {
    const stored = localStorage.getItem(THEME_PREFERENCE_STORAGE_KEY);
    if (stored === 'dark' || stored === 'light' || stored === 'system') {
      return stored;
    }
  } catch {
    // localStorage may be unavailable (private mode, etc.) — fall back to dark.
  }
  return 'dark';
}

export const themePreference: Ref<ThemePreference> = ref<ThemePreference>(readStoredThemePreference());

export function setThemePreference(preference: ThemePreference): void {
  themePreference.value = preference;
  try {
    localStorage.setItem(THEME_PREFERENCE_STORAGE_KEY, preference);
  } catch {
    // Ignore storage write failures.
  }
}

export function readSystemPrefersDark(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return true;
  }
  return window.matchMedia(SYSTEM_PREFERS_DARK_QUERY).matches;
}
