<script setup lang="ts">
import { computed } from 'vue';
import { useI18n } from 'vue-i18n';
import SettingsBreadcrumb from './SettingsBreadcrumb.vue';
import type { SettingsBreadcrumbItem } from './types';
import { setThemePreference, themePreference, type ThemePreference } from '../../theme/themeStore';

defineProps<{
  breadcrumbItems: SettingsBreadcrumbItem[];
}>();

const emit = defineEmits<{
  navigateBreadcrumb: [key: string];
}>();

const { t } = useI18n();

interface ThemeOption {
  id: ThemePreference;
  label: string;
  note: string;
  icon: 'light' | 'dark' | 'system';
}

const themeOptions = computed<ThemeOption[]>(() => [
  {
    id: 'light',
    label: t('settings.appearance.light'),
    note: t('settings.appearance.lightNote'),
    icon: 'light',
  },
  {
    id: 'dark',
    label: t('settings.appearance.dark'),
    note: t('settings.appearance.darkNote'),
    icon: 'dark',
  },
  {
    id: 'system',
    label: t('settings.appearance.system'),
    note: t('settings.appearance.systemNote'),
    icon: 'system',
  },
]);

const effectiveModeLabel = computed<string>(() => {
  switch (themePreference.value) {
    case 'light':
      return t('settings.appearance.light');
    case 'dark':
      return t('settings.appearance.dark');
    case 'system':
      return t('settings.appearance.system');
    default:
      return '';
  }
});

function selectTheme(preference: ThemePreference): void {
  setThemePreference(preference);
}
</script>

<template>
  <section id="appearance" class="config-section appearance-section">
    <SettingsBreadcrumb :items="breadcrumbItems" @navigate="emit('navigateBreadcrumb', $event)" />

    <section class="appearance-panel panel">
      <div class="appearance-head">
        <h3>{{ t('settings.appearance.title') }}</h3>
        <p class="appearance-description">{{ t('settings.appearance.description') }}</p>
      </div>

      <div class="appearance-body">
        <div class="appearance-row">
          <div class="appearance-row-info">
            <span class="appearance-row-label">{{ t('settings.appearance.themeMode') }}</span>
            <span class="appearance-row-note">
              {{ t('settings.appearance.currentEffective', { mode: effectiveModeLabel }) }}
            </span>
          </div>
        </div>

        <div class="appearance-options" role="radiogroup" :aria-label="t('settings.appearance.themeMode')">
          <button
            v-for="option in themeOptions"
            :key="option.id"
            type="button"
            class="appearance-option"
            :class="{ 'is-active': themePreference === option.id }"
            role="radio"
            :aria-checked="themePreference === option.id"
            @click="selectTheme(option.id)"
          >
            <span class="appearance-option__icon" :data-icon="option.icon" aria-hidden="true">
              <svg v-if="option.icon === 'light'" viewBox="0 0 24 24">
                <circle cx="12" cy="12" r="4" />
                <path d="M12 2.75v2.5" />
                <path d="M12 18.75v2.5" />
                <path d="M4.93 4.93l1.77 1.77" />
                <path d="M17.3 17.3l1.77 1.77" />
                <path d="M2.75 12h2.5" />
                <path d="M18.75 12h2.5" />
                <path d="M4.93 19.07l1.77-1.77" />
                <path d="M17.3 6.7l1.77-1.77" />
              </svg>
              <svg v-else-if="option.icon === 'dark'" viewBox="0 0 24 24">
                <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a7.8 7.8 0 1 0 10.5 10.5Z" />
              </svg>
              <svg v-else viewBox="0 0 24 24">
                <rect x="3" y="5" width="18" height="14" rx="2" />
                <path d="M3 9h18" />
                <path d="M8 5v4" />
              </svg>
            </span>
            <span class="appearance-option__text">
              <span class="appearance-option__label">{{ option.label }}</span>
              <span class="appearance-option__note">{{ option.note }}</span>
            </span>
            <span
              v-if="themePreference === option.id"
              class="appearance-option__check"
              aria-hidden="true"
            >✓</span>
          </button>
        </div>
      </div>
    </section>
  </section>
</template>

<style scoped>
.appearance-section {
  padding: 12px 0 0;
}

.appearance-panel {
  border: 1px solid var(--panel-border);
  border-radius: 14px;
  background: var(--surface-soft);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.appearance-head h3 {
  margin: 0;
  color: var(--text-strong);
  font-size: 0.92rem;
}

.appearance-description {
  margin: 4px 0 0;
  color: var(--text-secondary);
  font-size: 0.74rem;
  line-height: 1.4;
}

.appearance-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.appearance-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.appearance-row-info {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.appearance-row-label {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--text-strong);
}

.appearance-row-note {
  font-size: 0.72rem;
  color: var(--text-secondary);
  line-height: 1.4;
}

.appearance-options {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.appearance-option {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--panel-border);
  border-radius: 12px;
  background: var(--panel-bg);
  color: var(--text-strong);
  text-align: left;
  cursor: pointer;
  outline: none;
  position: relative;
  transition:
    border-color 140ms ease,
    background 140ms ease,
    box-shadow 140ms ease,
    transform 140ms ease;
}

.appearance-option:hover {
  border-color: color-mix(in srgb, var(--focus-border) 42%, var(--panel-border) 58%);
  background: color-mix(in srgb, var(--selected) 22%, var(--panel-bg) 78%);
  transform: translateY(-1px);
}

.appearance-option:focus-visible {
  border-color: var(--focus-border);
  box-shadow: 0 0 0 2px var(--focus-glow);
}

.appearance-option.is-active {
  border-color: var(--focus-border);
  background: var(--backend-selected-active, color-mix(in srgb, var(--selected) 44%, var(--panel-bg) 56%));
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--focus-border) 32%, transparent);
}

.appearance-option__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: color-mix(in srgb, var(--surface-panel) 70%, var(--surface-page) 30%);
  color: var(--text-secondary);
}

.appearance-option.is-active .appearance-option__icon {
  color: var(--theme-switch-icon-active);
  background: color-mix(in srgb, var(--interactive-selected) 42%, var(--surface-panel) 58%);
}

.appearance-option__icon svg {
  width: 16px;
  height: 16px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.9;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.appearance-option[data-icon='system'] svg {
  fill: none;
  stroke: currentColor;
  stroke-width: 1.7;
}

.appearance-option__text {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.appearance-option__label {
  font-size: 0.84rem;
  font-weight: 600;
  color: var(--text-strong);
}

.appearance-option__note {
  font-size: 0.68rem;
  color: var(--text-secondary);
  line-height: 1.35;
}

.appearance-option__check {
  position: absolute;
  top: 8px;
  right: 10px;
  color: color-mix(in srgb, var(--state-success) 82%, var(--text-primary) 18%);
  font-size: 0.84rem;
  font-weight: 700;
}

@media (max-width: 780px) {
  .appearance-options {
    grid-template-columns: 1fr;
  }
}
</style>
