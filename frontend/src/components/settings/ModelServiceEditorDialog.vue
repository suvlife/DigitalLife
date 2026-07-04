<script setup lang="ts">
import { computed, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import {
  createLlmService,
  deleteLlmService,
  modifyLlmService,
  setDefaultLlmService,
  testLlmService,
} from '../../api';
import { showGlobalSuccessToast } from '../../appUiState';
import type { LlmServiceInfo, LlmServiceType } from '../../types';
import ConfirmDialog from '../ui/ConfirmDialog.vue';
import ToggleSwitch from '../ui/ToggleSwitch.vue';

type EditorMode = 'create' | 'edit';

type FormSnapshot = {
  name: string;
  base_url: string;
  api_key: string;
  type: string;
  model: string;
  enable: boolean;
  extra_headers: string;
  provider_params: string;
  context_window_tokens: number;
  reserve_output_tokens: number;
  compact_trigger_ratio: number;
  compact_summary_max_tokens: number;
};

type OpenEditPayload = {
  index: number;
  service: LlmServiceInfo;
  defaultServer: string | null;
};

const SERVICE_TYPES: { value: LlmServiceType; label: string }[] = [
  { value: 'openai-compatible', label: 'OpenAI Compatible' },
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'google', label: 'Google (Gemini)' },
  { value: 'deepseek', label: 'DeepSeek' },
];

const PROVIDER_PARAMS_PLACEHOLDER = '{\n  "reasoning_effort": "high"\n}';

const emit = defineEmits<{
  changed: [payload: { preferredIndex: number | null }];
}>();

const { t } = useI18n();

const visible = ref(false);
const mode = ref<EditorMode>('create');
const currentIndex = ref<number | null>(null);
const originalService = ref<LlmServiceInfo | null>(null);
const defaultServer = ref<string | null>(null);
const isSaving = ref(false);
const isDeleting = ref(false);
const isTesting = ref(false);
const isSettingDefault = ref(false);
const advancedOpen = ref(false);
const apiKeyVisible = ref(false);
const deleteConfirmOpen = ref(false);
const statusText = ref('');
const testResult = ref<{ status: string; message: string; detail?: string } | null>(null);

const form = ref({
  name: '',
  base_url: '',
  api_key: '',
  type: 'openai-compatible' as LlmServiceType,
  model: '',
  enable: true,
  extra_headers: '',
  provider_params: '',
  context_window_tokens: 131072,
  reserve_output_tokens: 16384,
  compact_trigger_ratio: 0.85,
  compact_summary_max_tokens: 2048,
});

const isCreating = computed(() => mode.value === 'create');
const isDefault = computed(() => originalService.value?.name === defaultServer.value);
const dialogTitle = computed(() => (
  isCreating.value ? t('settings.models.newTitle') : (form.value.name || t('settings.models.detailFallback'))
));
const dialogEyebrow = computed(() => (isCreating.value ? 'New Service' : 'Service Detail'));
const canDelete = computed(() => !isCreating.value && currentIndex.value !== null && !isDefault.value && !isDeleting.value);
const canSetDefault = computed(() => !isCreating.value && currentIndex.value !== null && !isDefault.value && form.value.enable);

function buildSnapshot(target: typeof form.value): FormSnapshot {
  return {
    name: target.name.trim(),
    base_url: target.base_url.trim(),
    api_key: target.api_key.trim(),
    type: target.type,
    model: target.model.trim(),
    enable: target.enable,
    extra_headers: target.extra_headers.trim(),
    provider_params: target.provider_params.trim(),
    context_window_tokens: target.context_window_tokens,
    reserve_output_tokens: target.reserve_output_tokens,
    compact_trigger_ratio: target.compact_trigger_ratio,
    compact_summary_max_tokens: target.compact_summary_max_tokens,
  };
}

function serializeHeaders(headers: Record<string, string> | undefined | null): string {
  if (!headers) {
    return '';
  }
  return Object.entries(headers)
    .filter(([key, value]) => key && value)
    .map(([key, value]) => `${key}: ${value}`)
    .join('\n');
}

function parseHeaders(text: string): Record<string, string> {
  const headers: Record<string, string> = {};
  for (const line of text.split('\n')) {
    const dividerIndex = line.indexOf(':');
    if (dividerIndex <= 0) {
      continue;
    }
    const key = line.slice(0, dividerIndex).trim();
    const value = line.slice(dividerIndex + 1).trim();
    if (key && value) {
      headers[key] = value;
    }
  }
  return headers;
}

function serializeProviderParams(params: Record<string, unknown> | undefined | null): string {
  if (!params || Object.keys(params).length === 0) {
    return '';
  }
  return JSON.stringify(params, null, 2);
}

function parseProviderParams(text: string): Record<string, unknown> {
  const trimmed = text.trim();
  if (!trimmed) {
    return {};
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    throw new Error(t('settings.models.providerParamsInvalid'));
  }

  if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
    throw new Error(t('settings.models.providerParamsObjectOnly'));
  }

  return parsed as Record<string, unknown>;
}

function serviceToFormSnapshot(service: LlmServiceInfo): FormSnapshot {
  return {
    name: service.name.trim(),
    base_url: service.base_url.trim(),
    api_key: service.api_key.trim(),
    type: service.type,
    model: service.model.trim(),
    enable: service.enable,
    extra_headers: serializeHeaders(service.extra_headers),
    provider_params: serializeProviderParams(service.provider_params),
    context_window_tokens: service.context_window_tokens ?? 131072,
    reserve_output_tokens: service.reserve_output_tokens ?? 16384,
    compact_trigger_ratio: service.compact_trigger_ratio ?? 0.85,
    compact_summary_max_tokens: service.compact_summary_max_tokens ?? 2048,
  };
}

const isDirty = computed(() => {
  if (isCreating.value) {
    return true;
  }
  if (!originalService.value) {
    return false;
  }
  return JSON.stringify(buildSnapshot(form.value)) !== JSON.stringify(serviceToFormSnapshot(originalService.value));
});

const canSave = computed(() => {
  if (isSaving.value) {
    return false;
  }
  if (isCreating.value) {
    return form.value.name.trim().length > 0
      && form.value.base_url.trim().length > 0
      && form.value.api_key.trim().length > 0
      && form.value.model.trim().length > 0;
  }
  return isDirty.value;
});

function resetForm(service?: LlmServiceInfo | null): void {
  form.value = {
    name: service?.name ?? '',
    base_url: service?.base_url ?? '',
    api_key: service?.api_key ?? '',
    type: service?.type ?? 'openai-compatible',
    model: service?.model ?? 'qwen-plus',
    enable: service?.enable ?? true,
    extra_headers: service ? serializeHeaders(service.extra_headers) : '',
    provider_params: service ? serializeProviderParams(service.provider_params) : '',
    context_window_tokens: service?.context_window_tokens ?? 131072,
    reserve_output_tokens: service?.reserve_output_tokens ?? 16384,
    compact_trigger_ratio: service?.compact_trigger_ratio ?? 0.85,
    compact_summary_max_tokens: service?.compact_summary_max_tokens ?? 2048,
  };
  advancedOpen.value = false;
  apiKeyVisible.value = false;
  testResult.value = null;
  statusText.value = '';
}

function closeDialog(): void {
  visible.value = false;
  deleteConfirmOpen.value = false;
  mode.value = 'create';
  currentIndex.value = null;
  originalService.value = null;
  defaultServer.value = null;
  resetForm(null);
}

function openCreate(): void {
  mode.value = 'create';
  currentIndex.value = null;
  originalService.value = null;
  defaultServer.value = null;
  resetForm(null);
  visible.value = true;
}

function openEdit(payload: OpenEditPayload): void {
  mode.value = 'edit';
  currentIndex.value = payload.index;
  originalService.value = payload.service;
  defaultServer.value = payload.defaultServer;
  resetForm(payload.service);
  visible.value = true;
}

async function saveService(): Promise<void> {
  if (!canSave.value) {
    return;
  }

  isSaving.value = true;
  statusText.value = '';

  try {
    const headers = parseHeaders(form.value.extra_headers);
    const providerParams = parseProviderParams(form.value.provider_params);

    if (isCreating.value) {
      const payload: Record<string, unknown> = {
        name: form.value.name.trim(),
        base_url: form.value.base_url.trim(),
        api_key: form.value.api_key.trim(),
        type: form.value.type,
        model: form.value.model.trim(),
        enable: form.value.enable,
        context_window_tokens: form.value.context_window_tokens,
        reserve_output_tokens: form.value.reserve_output_tokens,
        compact_trigger_ratio: form.value.compact_trigger_ratio,
        compact_summary_max_tokens: form.value.compact_summary_max_tokens,
      };

      if (Object.keys(headers).length) {
        payload.extra_headers = headers;
      }
      if (Object.keys(providerParams).length) {
        payload.provider_params = providerParams;
      }

      const result = await createLlmService(payload);
      showGlobalSuccessToast(t('settings.models.createSuccess'));
      emit('changed', { preferredIndex: result.index });
      closeDialog();
      return;
    }

    if (currentIndex.value === null || !originalService.value) {
      return;
    }

    const updates: Record<string, unknown> = {};
    const current = originalService.value;

    if (form.value.base_url.trim() !== current.base_url) updates.base_url = form.value.base_url.trim();
    if (form.value.api_key.trim() !== current.api_key) updates.api_key = form.value.api_key.trim();
    if (form.value.type !== current.type) updates.type = form.value.type;
    if (form.value.model.trim() !== current.model) updates.model = form.value.model.trim();
    if (form.value.enable !== current.enable) updates.enable = form.value.enable;
    if (form.value.context_window_tokens !== current.context_window_tokens) {
      updates.context_window_tokens = form.value.context_window_tokens;
    }
    if (form.value.reserve_output_tokens !== current.reserve_output_tokens) {
      updates.reserve_output_tokens = form.value.reserve_output_tokens;
    }
    if (form.value.compact_trigger_ratio !== current.compact_trigger_ratio) {
      updates.compact_trigger_ratio = form.value.compact_trigger_ratio;
    }
    if (form.value.compact_summary_max_tokens !== current.compact_summary_max_tokens) {
      updates.compact_summary_max_tokens = form.value.compact_summary_max_tokens;
    }

    const newHeaders = parseHeaders(form.value.extra_headers);
    if (JSON.stringify(newHeaders) !== JSON.stringify(current.extra_headers)) {
      updates.extra_headers = newHeaders;
    }
    if (JSON.stringify(providerParams) !== JSON.stringify(current.provider_params ?? {})) {
      updates.provider_params = providerParams;
    }

    if (Object.keys(updates).length > 0) {
      await modifyLlmService(currentIndex.value, updates);
      showGlobalSuccessToast(t('settings.models.saveSuccess'));
    }

    emit('changed', { preferredIndex: currentIndex.value });
    closeDialog();
  } catch (error) {
    console.error(error);
    statusText.value = error instanceof Error ? error.message : t('settings.models.saveFailed');
  } finally {
    isSaving.value = false;
  }
}

function requestDelete(): void {
  if (!canDelete.value) {
    return;
  }
  deleteConfirmOpen.value = true;
}

async function confirmDelete(): Promise<void> {
  if (currentIndex.value === null) {
    deleteConfirmOpen.value = false;
    return;
  }

  isDeleting.value = true;
  statusText.value = '';

  try {
    await deleteLlmService(currentIndex.value);
    showGlobalSuccessToast(t('settings.models.deleteSuccess'));
    emit('changed', { preferredIndex: null });
    closeDialog();
  } catch (error) {
    console.error(error);
    statusText.value = t('settings.models.deleteFailed');
  } finally {
    isDeleting.value = false;
  }
}

async function handleSetDefault(): Promise<void> {
  if (!canSetDefault.value || currentIndex.value === null || isSettingDefault.value) {
    return;
  }

  isSettingDefault.value = true;

  try {
    await setDefaultLlmService(currentIndex.value);
    showGlobalSuccessToast(t('settings.models.defaultSuccess'));
    emit('changed', { preferredIndex: currentIndex.value });
    closeDialog();
  } catch (error) {
    console.error(error);
  } finally {
    isSettingDefault.value = false;
  }
}

function handleDefaultToggle(nextChecked: boolean): void {
  if (!nextChecked || isDefault.value) {
    return;
  }

  void handleSetDefault();
}

async function handleTest(): Promise<void> {
  isTesting.value = true;
  testResult.value = null;

  try {
    const providerParams = parseProviderParams(form.value.provider_params);
    const result = await testLlmService({
      mode: 'temp',
      base_url: form.value.base_url.trim(),
      api_key: form.value.api_key.trim(),
      type: form.value.type,
      model: form.value.model.trim(),
      extra_headers: parseHeaders(form.value.extra_headers),
      provider_params: providerParams,
    });

    const detailParts: string[] = [];
    if (result.detail?.duration_ms !== undefined) detailParts.push(`${result.detail.duration_ms}ms`);
    if (result.detail?.response_text) detailParts.push(result.detail.response_text.slice(0, 80));
    if (result.detail?.raw_error) detailParts.push(result.detail.raw_error.slice(0, 120));
    testResult.value = {
      status: result.status,
      message: result.message,
      detail: detailParts.join(' · ') || undefined,
    };
  } catch (error) {
    testResult.value = {
      status: 'error',
      message: error instanceof Error ? error.message : t('settings.models.testError'),
      detail: error instanceof Error ? undefined : String(error),
    };
  } finally {
    isTesting.value = false;
  }
}

defineExpose({
  openCreate,
  openEdit,
});
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="editor-overlay" @click.self="closeDialog">
      <section class="editor-dialog panel scrollbar-thin">
        <header class="editor-head">
          <div class="editor-head-copy">
            <p class="editor-eyebrow">{{ dialogEyebrow }}</p>
            <h3>{{ dialogTitle }}</h3>
          </div>
          <div class="editor-head-actions">
            <ToggleSwitch
              v-if="!isCreating"
              variant="inline"
              :checked="isDefault"
              :disabled="isSettingDefault || (!isDefault && !canSetDefault)"
              :label="isDefault ? t('settings.models.defaultServiceBadge') : t('settings.models.setDefault')"
              @toggle="handleDefaultToggle"
            />
            <button type="button" class="ghost-button editor-close" :aria-label="t('common.close')" @click="closeDialog">
              ×
            </button>
          </div>
        </header>

        <div class="editor-badges">
          <span v-if="isCreating" class="svc-chip svc-chip--draft">
            {{ t('settings.models.unsavedBadge') }}
          </span>
          <span v-if="!form.enable" class="svc-chip svc-chip--disabled">
            {{ t('settings.models.disabledBadge') }}
          </span>
        </div>

        <div class="svc-form-grid">
          <label class="svc-field">
            <span>{{ t('settings.models.nameLabel') }}</span>
            <input
              v-model="form.name"
              type="text"
              class="svc-input"
              :class="{ 'svc-input--readonly': !isCreating }"
              :placeholder="t('settings.models.namePlaceholder')"
              :readonly="!isCreating"
            />
          </label>

          <label class="svc-field">
            <span>{{ t('settings.models.enableLabel') }}</span>
            <div class="svc-toggle-box">
              <ToggleSwitch
                variant="inline"
                :checked="form.enable"
                :label="form.enable ? t('settings.models.enabled') : t('settings.models.disabled')"
                @toggle="form.enable = $event"
              />
            </div>
          </label>

          <label class="svc-field svc-field--wide">
            <span>Base URL</span>
            <input
              v-model="form.base_url"
              type="text"
              class="svc-input"
              placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1"
            />
          </label>

          <label class="svc-field svc-field--wide">
            <span>API Key</span>
            <div class="svc-input-group">
              <input
                v-model="form.api_key"
                :type="apiKeyVisible ? 'text' : 'password'"
                class="svc-input svc-input--flex"
                placeholder="sk-..."
              />
              <button type="button" class="ghost-button" @click="apiKeyVisible = !apiKeyVisible">
                {{ apiKeyVisible ? t('settings.models.apiKeyHide') : t('settings.models.apiKeyShow') }}
              </button>
            </div>
          </label>

          <label class="svc-field">
            <span>{{ t('settings.models.typeLabel') }}</span>
            <select v-model="form.type" class="svc-input svc-select">
              <option v-for="serviceType in SERVICE_TYPES" :key="serviceType.value" :value="serviceType.value">
                {{ serviceType.label }}
              </option>
            </select>
          </label>

          <label class="svc-field">
            <span>{{ t('settings.models.modelLabel') }}</span>
            <input
              v-model="form.model"
              type="text"
              class="svc-input"
              :placeholder="t('settings.models.modelPlaceholder')"
            />
          </label>
        </div>

        <section class="advanced-card">
          <button
            type="button"
            class="advanced-toggle"
            :aria-expanded="advancedOpen"
            @click="advancedOpen = !advancedOpen"
          >
            <div>
              <p class="editor-eyebrow">Advanced</p>
              <strong>{{ t('settings.models.advanced') }}</strong>
            </div>
            <span class="advanced-toggle__state">{{ advancedOpen ? t('common.collapse') : t('common.expand') }}</span>
          </button>

          <div v-if="advancedOpen" class="advanced-grid">
            <label class="svc-field">
              <span>{{ t('settings.models.contextWindow') }}</span>
              <input v-model.number="form.context_window_tokens" type="number" class="svc-input" min="1024" />
            </label>

            <label class="svc-field">
              <span>{{ t('settings.models.outputReserved') }}</span>
              <input v-model.number="form.reserve_output_tokens" type="number" class="svc-input" min="256" />
            </label>

            <label class="svc-field">
              <span>{{ t('settings.models.compactRatio') }}</span>
              <input
                v-model.number="form.compact_trigger_ratio"
                type="number"
                class="svc-input"
                min="0"
                max="1"
                step="0.01"
              />
            </label>

            <label class="svc-field">
              <span>{{ t('settings.models.summaryMax') }}</span>
              <input v-model.number="form.compact_summary_max_tokens" type="number" class="svc-input" min="256" />
            </label>

            <label class="svc-field svc-field--wide">
              <span>{{ t('settings.models.extraHeaders') }}</span>
              <textarea
                v-model="form.extra_headers"
                class="svc-textarea"
                rows="4"
                placeholder="X-Custom-Header: value"
              ></textarea>
            </label>

            <label class="svc-field svc-field--wide">
              <span>{{ t('settings.models.providerParams') }}</span>
              <textarea
                v-model="form.provider_params"
                class="svc-textarea svc-textarea--code"
                rows="8"
                :placeholder="PROVIDER_PARAMS_PLACEHOLDER"
              ></textarea>
              <small class="svc-hint">{{ t('settings.models.providerParamsHint') }}</small>
            </label>
          </div>
        </section>

        <p v-if="statusText" class="editor-status">{{ statusText }}</p>

        <footer class="editor-actions">
          <div class="editor-actions-leading">
            <div class="test-section">
              <button
                type="button"
                class="secondary-button"
                :disabled="isTesting || (!isCreating && currentIndex === null)"
                @click="handleTest"
              >
                {{ isTesting ? t('settings.models.testing') : t('settings.models.testBtn') }}
              </button>
              <div
                v-if="testResult"
                class="test-result"
                :class="testResult.status === 'ok' ? 'test-result--ok' : 'test-result--error'"
              >
                <strong>{{ testResult.message }}</strong>
                <p v-if="testResult.detail">{{ testResult.detail }}</p>
              </div>
            </div>
          </div>

          <div class="editor-actions-trailing">
            <button
              v-if="canDelete"
              type="button"
              class="secondary-button secondary-button--danger"
              :disabled="isDeleting"
              @click="requestDelete"
            >
              {{ isDeleting ? t('settings.models.deleting') : t('settings.models.deleteBtn') }}
            </button>
            <button type="button" class="secondary-button" @click="closeDialog">
              {{ t('common.cancel') }}
            </button>
            <button type="button" class="secondary-button" :disabled="!canSave" @click="saveService">
              {{ isSaving ? t('settings.models.saving') : (isCreating ? t('settings.models.createBtn') : t('settings.models.saveBtn')) }}
            </button>
          </div>
        </footer>
      </section>

      <ConfirmDialog
        :open="deleteConfirmOpen"
        :title="t('settings.models.deleteConfirmTitle')"
        :message="t('settings.models.deleteConfirmMsg', { name: originalService?.name || '' })"
        :confirm-label="t('settings.models.deleteConfirmBtn')"
        danger
        @close="deleteConfirmOpen = false"
        @confirm="confirmDelete"
      />
    </div>
  </Teleport>
</template>

<style scoped>
.editor-overlay {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgba(6, 10, 16, 0.56);
  backdrop-filter: blur(10px);
}

.editor-dialog {
  width: min(760px, calc(100vw - 40px));
  max-height: calc(100vh - 40px);
  padding: 18px;
  display: grid;
  gap: 14px;
  overflow: auto;
}

.editor-head,
.editor-actions,
.editor-badges {
  display: flex;
  align-items: center;
  gap: 10px;
}

.editor-head,
.editor-actions {
  justify-content: space-between;
}

.editor-head-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
}

.editor-head-copy {
  min-width: 0;
}

.editor-close {
  min-width: 32px;
  height: 32px;
  padding: 0;
  font-size: 1rem;
}

.editor-eyebrow {
  margin: 0;
  color: var(--accent);
  text-transform: uppercase;
  letter-spacing: 0.14em;
  font-size: 0.68rem;
}

.editor-head h3 {
  margin: 0;
  color: var(--text-strong);
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

.svc-chip--disabled {
  border-color: color-mix(in srgb, var(--warn) 28%, var(--panel-border) 72%);
  background: color-mix(in srgb, var(--warn) 8%, var(--panel-bg) 92%);
  color: var(--warn);
}

.svc-chip--draft {
  border-color: color-mix(in srgb, var(--panel-border) 88%, var(--focus-border) 12%);
  background: color-mix(in srgb, var(--surface-soft) 82%, var(--panel-bg) 18%);
  color: var(--muted);
}

.svc-form-grid,
.advanced-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.svc-field {
  display: grid;
  gap: 6px;
}

.svc-field--wide {
  grid-column: 1 / -1;
}

.svc-field > span,
.editor-status {
  color: var(--muted);
  font-size: 0.76rem;
}

.svc-toggle-box {
  min-height: 44px;
  display: flex;
  align-items: center;
}

.svc-input,
.svc-textarea,
.svc-select {
  width: 100%;
  border: 1px solid var(--panel-border);
  border-radius: 12px;
  background: var(--panel-bg);
  color: var(--text-strong);
  padding: 10px 12px;
  font: inherit;
  font-size: 0.88rem;
  box-sizing: border-box;
}

.svc-input--readonly {
  border: 1px dashed color-mix(in srgb, var(--focus-border) 18%, var(--panel-border) 82%);
  background: color-mix(in srgb, var(--surface-soft) 86%, var(--panel-bg) 14%);
  color: color-mix(in srgb, var(--muted) 84%, var(--text-strong) 16%);
  -webkit-text-fill-color: color-mix(in srgb, var(--muted) 84%, var(--text-strong) 16%);
}

.svc-input[readonly] {
  cursor: default;
}

.svc-input--flex {
  flex: 1;
  min-width: 0;
}

.svc-input-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.svc-textarea {
  resize: vertical;
  min-height: 72px;
}

.svc-textarea--code {
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
}

.svc-hint {
  color: var(--muted);
  font-size: 0.78rem;
  line-height: 1.5;
}

.advanced-card {
  border: 1px solid var(--panel-border);
  border-radius: 14px;
  background: color-mix(in srgb, var(--surface-soft) 84%, var(--panel-bg) 16%);
  overflow: hidden;
}

.advanced-toggle {
  width: 100%;
  min-height: 56px;
  padding: 10px 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: none;
  background: transparent;
  color: inherit;
  cursor: pointer;
  text-align: left;
}

.advanced-toggle strong {
  color: var(--text-strong);
  font-size: 0.96rem;
}

.advanced-toggle__state {
  color: var(--muted);
  font-size: 0.8rem;
}

.advanced-grid {
  padding: 0 14px 14px;
}

.test-section {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
}

.test-result {
  flex: 1;
  min-width: 180px;
  padding: 8px 12px;
  border-radius: 10px;
  font-size: 0.84rem;
  line-height: 1.5;
}

.test-result strong {
  display: block;
}

.test-result p {
  margin: 2px 0 0;
  word-break: break-word;
}

.test-result--ok {
  border: 1px solid color-mix(in srgb, var(--good) 32%, var(--panel-border) 68%);
  background: color-mix(in srgb, var(--good) 8%, var(--panel-bg) 92%);
  color: var(--good);
}

.test-result--error {
  border: 1px solid color-mix(in srgb, var(--danger) 32%, var(--panel-border) 68%);
  background: color-mix(in srgb, var(--danger) 8%, var(--panel-bg) 92%);
  color: var(--danger);
}

.editor-actions {
  justify-content: space-between;
  flex-wrap: wrap;
}

.editor-actions-leading,
.editor-actions-trailing {
  display: flex;
  align-items: center;
  gap: 10px;
}

.editor-actions-leading {
  min-height: 32px;
  flex: 1;
  min-width: 220px;
}

.editor-actions-trailing {
  justify-content: flex-end;
  flex-wrap: wrap;
}

.secondary-button--danger {
  border-color: color-mix(in srgb, var(--danger) 38%, var(--panel-border) 62%);
  background: color-mix(in srgb, var(--danger) 10%, var(--panel-bg) 90%);
  color: color-mix(in srgb, var(--danger) 88%, var(--text-strong) 12%);
}

.secondary-button--danger:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--danger) 62%, var(--focus-border) 38%);
  background: color-mix(in srgb, var(--danger) 18%, var(--surface-soft) 82%);
  color: color-mix(in srgb, var(--danger) 92%, var(--text-strong) 8%);
  transform: translateY(-1px);
}

@media (max-width: 780px) {
  .editor-overlay {
    padding: 12px;
  }

  .editor-dialog {
    width: min(100%, calc(100vw - 24px));
    max-height: calc(100vh - 24px);
    padding: 14px;
  }

  .svc-form-grid,
  .advanced-grid {
    grid-template-columns: 1fr;
  }

  .editor-head-actions {
    width: 100%;
    justify-content: space-between;
  }

  .editor-actions,
  .editor-actions-leading,
  .editor-actions-trailing {
    width: 100%;
  }

  .editor-actions-leading,
  .editor-actions-trailing {
    justify-content: flex-start;
  }
}
</style>
