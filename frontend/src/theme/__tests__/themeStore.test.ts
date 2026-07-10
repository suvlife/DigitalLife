import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  readStoredThemePreference,
  setThemePreference,
  themePreference,
  THEME_PREFERENCE_STORAGE_KEY,
} from '../themeStore';

/**
 * The test environment does not provide a real localStorage, so we install a
 * minimal in-memory mock before each test. This mirrors the approach the
 * existing test files would need if the environment had localStorage.
 */
function createMemoryStorage(): Storage {
  const store = new Map<string, string>();
  return {
    get length() {
      return store.size;
    },
    clear() {
      store.clear();
    },
    getItem(key: string) {
      return store.has(key) ? (store.get(key) as string) : null;
    },
    key(index: number) {
      return Array.from(store.keys())[index] ?? null;
    },
    removeItem(key: string) {
      store.delete(key);
    },
    setItem(key: string, value: string) {
      store.set(key, String(value));
    },
  };
}

describe('themeStore', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', createMemoryStorage());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('readStoredThemePreference returns stored value when valid', () => {
    localStorage.setItem(THEME_PREFERENCE_STORAGE_KEY, 'light');
    expect(readStoredThemePreference()).toBe('light');
  });

  it('readStoredThemePreference returns "light" fallback for invalid value', () => {
    localStorage.setItem(THEME_PREFERENCE_STORAGE_KEY, 'neon');
    expect(readStoredThemePreference()).toBe('light');
  });

  it('readStoredThemePreference returns "light" fallback when unset', () => {
    expect(readStoredThemePreference()).toBe('light');
  });

  it('readStoredThemePreference falls back to light when localStorage throws', () => {
    vi.stubGlobal('localStorage', {
      getItem: () => {
        throw new Error('denied');
      },
      setItem: () => {},
      removeItem: () => {},
      clear: () => {},
    });

    expect(readStoredThemePreference()).toBe('light');
  });

  it('setThemePreference updates the ref and persists to localStorage', () => {
    setThemePreference('system');
    expect(themePreference.value).toBe('system');
    expect(localStorage.getItem(THEME_PREFERENCE_STORAGE_KEY)).toBe('system');
  });

  it('setThemePreference ignores storage write failures', () => {
    vi.stubGlobal('localStorage', {
      getItem: () => null,
      setItem: () => {
        throw new Error('denied');
      },
      removeItem: () => {},
      clear: () => {},
    });

    expect(() => setThemePreference('light')).not.toThrow();
    expect(themePreference.value).toBe('light');
  });
});
