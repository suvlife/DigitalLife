<script setup lang="ts">
import { onMounted, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import { getLlmServices } from '../../api';
import { showQuickInit } from '../../appUiState';
import type { LlmServiceInfo } from '../../types';
import ModelServiceEditorDialog from './ModelServiceEditorDialog.vue';
import SettingsBreadcrumb from './SettingsBreadcrumb.vue';
import type { SettingsBreadcrumbItem } from './types';

defineProps<{
  breadcrumbItems: SettingsBreadcrumbItem[];
}>();

const emit = defineEmits<{
  navigateBreadcrumb: [key: string];
}>();

const { t } = useI18n();

const services = ref<LlmServiceInfo[]>([]);
const defaultServer = ref<string | null>(null);
const activeIndex = ref<number | null>(null);
const isLoading = ref(false);
const statusText = ref('');
const editorDialogRef = ref<InstanceType<typeof ModelServiceEditorDialog> | null>(null);

function formatServiceType(type: LlmServiceInfo['type']): string {
  switch (type) {
    case 'openai-compatible':
      return 'OpenAI Compatible';
    case 'anthropic':
      return 'Anthropic';
    case 'google':
      return 'Google';
    case 'deepseek':
      return 'DeepSeek';
    default:
      return type;
  }
}

async function loadServices(preferredIndex?: number | null): Promise<void> {
  const data = await getLlmServices();
  services.value = data.llm_services;
  defaultServer.value = data.default_llm_server;

  if (
    preferredIndex !== null
    && preferredIndex !== undefined
    && preferredIndex >= 0
    && preferredIndex < data.llm_services.length
  ) {
    activeIndex.value = preferredIndex;
    return;
  }

  if (activeIndex.value !== null && activeIndex.value < data.llm_services.length) {
    return;
  }

  activeIndex.value = data.llm_services.length ? 0 : null;
}

async function loadAll(preferredIndex?: number | null): Promise<void> {
  isLoading.value = true;
  statusText.value = '';
  try {
    await loadServices(preferredIndex);
  } catch (error) {
    console.error(error);
    statusText.value = t('settings.models.loadFailed');
  } finally {
    isLoading.value = false;
  }
}

function openCreate(): void {
  activeIndex.value = null;
  editorDialogRef.value?.openCreate();
}

function openEdit(index: number): void {
  const service = services.value[index];
  if (!service) {
    return;
  }
  activeIndex.value = index;
  editorDialogRef.value?.openEdit({
    index,
    service,
    defaultServer: defaultServer.value,
  });
}

function handleDialogChanged(payload: { preferredIndex: number | null }): void {
  void loadAll(payload.preferredIndex);
}

onMounted(() => {
  void loadAll();
});

watch(showQuickInit, (value) => {
  if (!value) {
    void loadAll(activeIndex.value);
  }
});
</script>

<template>
  <section id="models" class="config-section">
    <SettingsBreadcrumb :items="breadcrumbItems" @navigate="emit('navigateBreadcrumb', $event)" />

    <div class="section-head section-head--compact">
      <div class="section-actions">
        <span v-if="statusText" class="section-status">{{ statusText }}</span>
        <button type="button" class="secondary-button" @click="openCreate">
          {{ t('settings.models.addService') }}
        </button>
      </div>
    </div>

    <section class="models-table-section">
      <p v-if="isLoading" class="models-empty">{{ t('settings.models.loading') }}</p>

      <div v-else-if="services.length" class="settings-table-wrap">
        <table class="settings-table models-table">
          <thead>
            <tr>
              <th>{{ t('settings.models.nameLabel') }}</th>
              <th>{{ t('settings.models.typeLabel') }}</th>
              <th class="models-table-model-head">{{ t('settings.models.modelLabel') }}</th>
              <th class="models-table-status-head">{{ t('settings.models.table.status') }}</th>
              <th class="models-table-actions-head">{{ t('settings.models.table.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(service, index) in services"
              :key="`${service.name}-${index}`"
              :class="{ active: activeIndex === index }"
              @click="activeIndex = index"
            >
              <td class="models-cell-name">
                <div class="svc-row-name">
                  <strong>{{ service.name }}</strong>
                  <span v-if="service.name === defaultServer" class="svc-chip svc-chip--default">
                    {{ t('settings.models.defaultBadge') }}
                  </span>
                </div>
              </td>
              <td class="models-cell-type">{{ formatServiceType(service.type) }}</td>
              <td class="models-cell-model" :title="service.model">
                <span class="models-cell-model-text">{{ service.model }}</span>
              </td>
              <td class="models-cell-status">
                <span
                  class="svc-chip"
                  :class="service.enable ? 'svc-chip--enabled' : 'svc-chip--disabled'"
                >
                  {{ service.enable ? t('settings.models.enabled') : t('settings.models.disabled') }}
                </span>
              </td>
              <td class="models-cell-actions">
                <button type="button" class="ghost-button" @click.stop="openEdit(index)">
                  {{ t('common.edit') }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <p v-else class="models-empty">{{ t('settings.models.empty') }}</p>
    </section>

    <ModelServiceEditorDialog ref="editorDialogRef" @changed="handleDialogChanged" />
  </section>
</template>

<style scoped>
.config-section {
  padding: 12px 0 0;
}

.section-head,
.section-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.section-head {
  margin-bottom: 8px;
}

.section-head--compact {
  justify-content: flex-end;
}

.section-head h3 {
  margin: 0;
  color: var(--text-strong);
}

.section-status,
.models-empty {
  color: var(--muted);
}

.models-table-section {
  margin-top: 10px;
  padding: 0 10px;
}

.settings-table-wrap {
  margin-top: 10px;
  overflow-x: auto;
  padding: 10px 12px 12px;
  border-radius: 16px;
  background: var(--settings-table-surface);
}

.models-empty {
  margin-top: 10px;
  font-size: 0.86rem;
}

.settings-table {
  width: 100%;
  min-width: 0;
  border-collapse: separate;
  border-spacing: 0;
  table-layout: fixed;
}

.settings-table th,
.settings-table td {
  padding: 12px 14px;
  text-align: left;
  vertical-align: top;
}

.settings-table thead th {
  position: relative;
  padding-top: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid color-mix(in srgb, var(--divider) 86%, transparent);
  background: var(--settings-table-head-bg);
  color: var(--text-strong);
  font-size: 0.84rem;
  font-weight: 700;
  letter-spacing: 0.01em;
  white-space: nowrap;
}

.settings-table thead th:not(:last-child)::after {
  content: '';
  position: absolute;
  top: 14px;
  right: 0;
  width: 1px;
  height: calc(100% - 28px);
  background: color-mix(in srgb, var(--divider) 88%, transparent);
}

.settings-table tbody td {
  border-bottom: 1px solid color-mix(in srgb, var(--divider) 76%, transparent);
  color: var(--text-strong);
  font-size: 0.84rem;
  transition:
    background 140ms ease,
    box-shadow 140ms ease;
}

.settings-table tbody tr:hover td,
.settings-table tbody tr.active td {
  background: var(--settings-table-row-hover);
}

.settings-table tbody tr.active td {
  background: var(--settings-table-row-active);
  box-shadow: none;
}

.settings-table tbody tr:last-child td {
  border-bottom: none;
}

.settings-table tbody tr:first-child td {
  padding-top: 18px;
}

.svc-row-name strong {
  color: var(--text-strong);
  font-size: 0.96rem;
}

.svc-row-name {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex-wrap: wrap;
}

.models-cell-type,
.models-cell-model {
  color: var(--muted);
}

.models-cell-model,
.models-cell-status {
  white-space: nowrap;
}

.models-cell-type {
  width: 150px;
}

.models-cell-model {
  width: 210px;
  overflow: hidden;
}

.models-cell-model-text {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.models-table-status-head,
.models-cell-status {
  width: 108px;
}

.models-cell-actions,
.models-table-actions-head {
  width: 88px;
  text-align: right;
}

.models-cell-actions :deep(.ghost-button) {
  white-space: nowrap;
}

.svc-chip {
  display: inline-flex;
  align-items: center;
  min-height: 20px;
  padding: 0 8px;
  border-radius: 999px;
  border: 1px solid var(--panel-border);
  background: var(--panel-bg);
  color: var(--muted);
  font-size: 0.68rem;
  white-space: nowrap;
}

.svc-chip--default {
  border-color: color-mix(in srgb, var(--good) 38%, var(--panel-border) 62%);
  background: color-mix(in srgb, var(--good) 12%, var(--panel-bg) 88%);
  color: var(--good);
}

.svc-chip--enabled {
  border-color: color-mix(in srgb, var(--good) 38%, var(--panel-border) 62%);
  background: color-mix(in srgb, var(--good) 12%, var(--panel-bg) 88%);
  color: var(--good);
}

.svc-chip--disabled {
  border-color: color-mix(in srgb, var(--warn) 28%, var(--panel-border) 72%);
  background: color-mix(in srgb, var(--warn) 8%, var(--panel-bg) 92%);
  color: var(--warn);
}

@media (max-width: 780px) {
  .section-head,
  .section-actions {
    align-items: flex-start;
    flex-direction: column;
  }

  .section-actions {
    width: 100%;
  }

  .settings-table {
    min-width: 780px;
  }
}
</style>
