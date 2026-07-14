import { computed } from 'vue';
import { useI18n } from 'vue-i18n';
import type { SettingsNavItemId } from './sections';

export interface SettingsNavItem {
  id: SettingsNavItemId;
  label: string;
  note: string;
}

export function useSettingsNavItems() {
  const { t } = useI18n();

  return computed<SettingsNavItem[]>(() => [
    { id: 'teams', label: t('settings.nav.teams'), note: t('settings.nav.teamsNote') },
    { id: 'roles', label: t('settings.nav.roles'), note: t('settings.nav.rolesNote') },
    { id: 'models', label: t('settings.nav.models'), note: t('settings.nav.modelsNote') },
    { id: 'search', label: t('settings.nav.search'), note: t('settings.nav.searchNote') },
    { id: 'ghost', label: t('settings.nav.ghost'), note: t('settings.nav.ghostNote') },
    { id: 'skills', label: t('settings.nav.skills'), note: t('settings.nav.skillsNote') },
    { id: 'dossiers', label: t('settings.nav.dossiers'), note: t('settings.nav.dossiersNote') },
    { id: 'maintenance', label: t('settings.nav.maintenance'), note: t('settings.nav.maintenanceNote') },
    { id: 'appearance', label: t('settings.nav.appearance'), note: t('settings.nav.appearanceNote') },
    { id: 'advanced', label: t('settings.nav.advanced'), note: t('settings.nav.advancedNote') },
    { id: 'quickInit', label: t('settings.nav.quickInit'), note: t('settings.nav.quickInitNote') },
  ]);
}
