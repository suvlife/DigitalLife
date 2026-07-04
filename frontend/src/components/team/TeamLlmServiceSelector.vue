<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import { getLlmServices, updateTeam } from '../../api';
import { showGlobalSuccessToast } from '../../appUiState';
import CustomSelect from '../ui/CustomSelect.vue';
import type { LlmServiceInfo } from '../../types';

const props = defineProps<{
  teamId: number;
  currentServiceName: string | null;
  disabled?: boolean;
}>();

const emit = defineEmits<{
  saved: [serviceName: string];
}>();

const { t } = useI18n();

const loading = ref(false);
const saving = ref(false);
const services = ref<LlmServiceInfo[]>([]);
const selected = ref<string>('');

const enabledServices = computed(() => services.value.filter((service) => service.enable));

const serviceOptions = computed(() => {
  const options = enabledServices.value.map((service) => ({
    value: service.name,
    label: service.name,
  }));

  if (!options.some((option) => option.value === selected.value) && selected.value) {
    options.push({ value: selected.value, label: `${selected.value} (${t('team.llmServiceDisabled')})` });
  }

  return options;
});

const currentDisplayName = computed(() => {
  if (!selected.value) {
    return t('team.llmServiceDefault');
  }
  return selected.value;
});

const hasChanges = computed(() => {
  const initial = props.currentServiceName ?? '';
  return (selected.value || '') !== (initial || '');
});

async function loadServices(): Promise<void> {
  loading.value = true;
  try {
    const data = await getLlmServices();
    services.value = data.llm_services ?? [];
  } catch (error) {
    console.error('Failed to load LLM services', error);
  } finally {
    loading.value = false;
  }
}

watch(
  () => props.currentServiceName,
  (name) => {
    selected.value = name ?? '';
  },
  { immediate: true },
);

onMounted(() => {
  void loadServices();
});

async function handleSave(): Promise<void> {
  if (saving.value || !hasChanges.value) {
    return;
  }

  saving.value = true;
  try {
    await updateTeam(props.teamId, {
      config_updates: { llm_service_name: selected.value || null },
    });
    showGlobalSuccessToast(t('team.llmServiceSaved'));
    emit('saved', selected.value);
  } catch (error) {
    console.error('Failed to update team LLM service', error);
  } finally {
    saving.value = false;
  }
}

function handleReset(): void {
  selected.value = props.currentServiceName ?? '';
}
</script>

<template>
  <section class="llm-service-panel">
    <div class="panel-head">
      <span class="panel-title">{{ t('team.llmService') }}</span>
      <span v-if="loading" class="panel-hint">{{ t('common.loading') }}</span>
    </div>

    <div class="llm-service-row">
      <span class="row-label">{{ t('team.llmServiceLabel') }}</span>
      <div class="llm-service-select">
        <CustomSelect
          v-model="selected"
          :options="serviceOptions"
          :placeholder="t('team.llmServiceDefault')"
          :disabled="disabled || saving"
        />
      </div>
    </div>

    <div class="llm-service-current">
      <span class="row-label">{{ t('team.llmServiceCurrent') }}</span>
      <span class="current-value">{{ currentDisplayName }}</span>
    </div>

    <div v-if="hasChanges" class="llm-service-actions">
      <button
        type="button"
        class="secondary-button llm-service-action-button llm-service-action-button--compact"
        :disabled="saving"
        @click="handleReset"
      >
        {{ t('settings.teams.reset') }}
      </button>
      <button
        type="button"
        class="secondary-button llm-service-action-button"
        :disabled="saving"
        @click="handleSave"
      >
        {{ saving ? t('settings.teams.saving') : t('settings.teams.saveBtn') }}
      </button>
    </div>
  </section>
</template>

<style scoped>
.llm-service-panel {
  display: grid;
  gap: 8px;
  border: 1px solid var(--team-create-panel-border);
  border-radius: 20px;
  background: var(--panel-bg);
  box-shadow: var(--panel-shadow);
  padding: 10px 12px;
  align-content: start;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.panel-title {
  color: var(--text-strong);
  font-size: 0.96rem;
  font-weight: 700;
  letter-spacing: 0.01em;
}

.panel-hint {
  color: var(--muted);
  font-size: 0.74rem;
}

.llm-service-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 2px;
}

.llm-service-select {
  flex: 1;
  min-width: 0;
}

.row-label {
  color: var(--muted);
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  white-space: nowrap;
}

.llm-service-current {
  display: flex;
  align-items: center;
  gap: 12px;
}

.current-value {
  color: var(--text-strong);
  font-size: 0.86rem;
  word-break: break-word;
}

.llm-service-actions {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 4px;
}

.llm-service-action-button {
  min-width: 132px;
}

.llm-service-action-button--compact {
  min-width: 88px;
}

@media (max-width: 780px) {
  .llm-service-row,
  .llm-service-current {
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;
  }
}
</style>
