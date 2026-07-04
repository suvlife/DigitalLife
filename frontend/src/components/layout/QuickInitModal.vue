<script setup lang="ts">
import { computed, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { testLlmService, quickInit } from '../../api';
import type { LlmServiceTestResult, LlmServiceType } from '../../types';

const SERVICE_TYPES: { value: LlmServiceType; label: string }[] = [
  { value: 'openai-compatible', label: 'OpenAI Compatible' },
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'google', label: 'Google (Gemini)' },
  { value: 'deepseek', label: 'DeepSeek' },
];

const PROVIDER_PARAMS_PLACEHOLDER = '{\n  "reasoning_effort": "high"\n}';

const emit = defineEmits<{
  skip: [];
  done: [];
}>();

const { t } = useI18n();

const baseUrl = ref('');
const apiKey = ref('');
const model = ref('');
const providerParams = ref('');
const serviceType = ref<LlmServiceType>('openai-compatible');
const apiKeyVisible = ref(false);
const advancedOpen = ref(false);
const isTesting = ref(false);
const isSaving = ref(false);
const testResult = ref<{ status: string; message: string; detail?: string } | null>(null);
const saveError = ref('');

const canTest = computed(() => {
  return baseUrl.value.trim() !== ''
    && apiKey.value.trim() !== ''
    && model.value.trim() !== ''
    && !isTesting.value
    && !isSaving.value;
});

const canSave = computed(() => {
  return canTest.value && !isSaving.value;
});

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

async function handleTest(): Promise<void> {
  isTesting.value = true;
  testResult.value = null;
  saveError.value = '';
  try {
    const parsedProviderParams = parseProviderParams(providerParams.value);
    const result: LlmServiceTestResult = await testLlmService({
      mode: 'temp',
      base_url: baseUrl.value.trim(),
      api_key: apiKey.value.trim(),
      type: serviceType.value,
      model: model.value.trim(),
      provider_params: parsedProviderParams,
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
      message: error instanceof Error ? error.message : t('quickInit.testError'),
    };
  } finally {
    isTesting.value = false;
  }
}

async function handleSave(): Promise<void> {
  isSaving.value = true;
  saveError.value = '';
  try {
    const parsedProviderParams = parseProviderParams(providerParams.value);
    const data = await quickInit({
      base_url: baseUrl.value.trim(),
      api_key: apiKey.value.trim(),
      model: model.value.trim(),
      type: serviceType.value,
      provider_params: parsedProviderParams,
    });
    if (data.status !== 'ok') {
      saveError.value = data.message || t('quickInit.saveFailed');
      return;
    }
    emit('done');
  } catch (error) {
    saveError.value = error instanceof Error ? error.message : t('quickInit.saveFailedRetry');
  } finally {
    isSaving.value = false;
  }
}
</script>

<template>
  <Teleport to="body">
    <div class="quick-init-overlay">
      <section class="quick-init-dialog panel">
        <div class="quick-init-head">
          <p class="quick-init-eyebrow">{{ t('quickInit.eyebrow') }}</p>
          <h3>{{ t('quickInit.title') }}</h3>
          <p class="quick-init-desc">
            {{ t('quickInit.description') }}
          </p>
        </div>

        <div class="quick-init-form">
          <label class="form-label">
            <span class="label-text">{{ t('quickInit.apiUrl') }}</span>
            <input
              v-model="baseUrl"
              type="text"
              class="form-input"
              placeholder="https://api.openai.com/v1"
              :disabled="isSaving"
            />
            <span class="form-hint">{{ t('quickInit.apiUrlHint') }}</span>
          </label>

          <label class="form-label">
            <span class="label-text">{{ t('quickInit.serviceType') }}</span>
            <select v-model="serviceType" class="form-input form-select" :disabled="isSaving">
              <option v-for="t in SERVICE_TYPES" :key="t.value" :value="t.value">{{ t.label }}</option>
            </select>
          </label>

          <label class="form-label">
            <span class="label-text">{{ t('quickInit.apiKey') }}</span>
            <div class="input-with-toggle">
              <input
                v-model="apiKey"
                :type="apiKeyVisible ? 'text' : 'password'"
                class="form-input"
                placeholder="sk-..."
                :disabled="isSaving"
              />
              <button
                type="button"
                class="toggle-visibility"
                :title="apiKeyVisible ? t('quickInit.apiKeyHide') : t('quickInit.apiKeyShow')"
                @click="apiKeyVisible = !apiKeyVisible"
              >
                {{ apiKeyVisible ? '🙈' : '👁' }}
              </button>
            </div>
          </label>

          <label class="form-label">
            <span class="label-text">{{ t('quickInit.modelName') }}</span>
            <input
              v-model="model"
              type="text"
              class="form-input"
              :placeholder="t('quickInit.modelPlaceholder')"
              :disabled="isSaving"
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
              <p class="quick-init-eyebrow">{{ t('settings.models.advanced') }}</p>
              <strong>{{ t('settings.models.advanced') }}</strong>
            </div>
            <span class="advanced-toggle__state">{{ advancedOpen ? t('common.collapse') : t('common.expand') }}</span>
          </button>

          <div v-if="advancedOpen" class="advanced-body">
            <label class="form-label">
              <span class="label-text">{{ t('settings.models.providerParams') }}</span>
              <textarea
                v-model="providerParams"
                class="form-input form-textarea form-textarea--code"
                rows="7"
                :placeholder="PROVIDER_PARAMS_PLACEHOLDER"
                :disabled="isSaving"
              ></textarea>
              <span class="form-hint">{{ t('settings.models.providerParamsHint') }}</span>
            </label>
          </div>
        </section>

        <!-- test connection -->
        <div class="quick-init-test">
          <button
            type="button"
            class="secondary-button test-button"
            :disabled="!canTest"
            @click="handleTest"
          >
            {{ isTesting ? t('quickInit.testing') : t('quickInit.testButton') }}
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

        <!-- save error -->
        <div v-if="saveError" class="save-error">{{ saveError }}</div>

        <!-- actions -->
        <div class="quick-init-actions">
          <button type="button" class="ghost-button" :disabled="isSaving" @click="emit('skip')">
            {{ t('quickInit.skip') }}
          </button>
          <button
            type="button"
            class="secondary-button save-button"
            :disabled="!canSave"
            @click="handleSave"
          >
            {{ isSaving ? t('quickInit.completing') : t('quickInit.complete') }}
          </button>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.quick-init-overlay {
  position: fixed;
  inset: 0;
  z-index: 70;
  display: grid;
  place-items: center;
  padding: 28px;
  background: rgba(6, 10, 16, 0.62);
  backdrop-filter: blur(10px);
}

.quick-init-dialog {
  width: min(560px, 100%);
  max-height: calc(100vh - 56px);
  padding: 24px;
  display: grid;
  gap: 18px;
  overflow-y: auto;
  border-radius: 18px;
  border: 1px solid color-mix(in srgb, var(--interactive-focus-border) 32%, var(--border-default) 68%);
  background:
    linear-gradient(
      180deg,
      color-mix(in srgb, var(--surface-panel) 95%, transparent) 0%,
      color-mix(in srgb, var(--surface-panel-muted) 92%, transparent) 100%
    );
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.40);
}

.quick-init-head {
  display: grid;
  gap: 6px;
}

.quick-init-eyebrow {
  margin: 0;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.14em;
  font-size: 0.68rem;
}

.quick-init-head h3 {
  margin: 0;
  color: var(--text-primary);
  font-size: 1.18rem;
}

.quick-init-desc {
  margin: 0;
  color: var(--text-secondary);
  font-size: 0.86rem;
  line-height: 1.55;
}

.quick-init-form {
  display: grid;
  gap: 14px;
}

.advanced-card {
  border: 1px solid color-mix(in srgb, var(--interactive-focus-border) 18%, var(--border-default) 82%);
  border-radius: 14px;
  background: color-mix(in srgb, var(--surface-panel-muted) 82%, var(--surface-panel) 18%);
  overflow: hidden;
}

.advanced-toggle {
  width: 100%;
  min-height: 56px;
  padding: 12px 14px;
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
  color: var(--text-primary);
  font-size: 0.96rem;
}

.advanced-toggle__state {
  color: var(--text-secondary);
  font-size: 0.8rem;
}

.advanced-body {
  padding: 0 14px 14px;
}

.form-label {
  display: grid;
  gap: 4px;
}

.label-text {
  font-size: 0.78rem;
  color: var(--text-primary);
  font-weight: 500;
}

.form-input {
  width: 100%;
  height: 36px;
  padding: 0 12px;
  border: 1px solid var(--border-default);
  border-radius: 8px;
  background: var(--surface-panel-muted);
  color: var(--text-primary);
  font-size: 0.88rem;
  outline: none;
  transition: border-color 0.18s ease;
  box-sizing: border-box;
}

.form-input:focus {
  border-color: var(--interactive-focus-border);
  box-shadow: 0 0 0 2px var(--interactive-focus-ring);
}

.form-input:disabled {
  opacity: 0.56;
}

.form-textarea {
  min-height: 120px;
  height: auto;
  padding: 10px 12px;
  resize: vertical;
}

.form-textarea--code {
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  line-height: 1.5;
}

.form-hint {
  font-size: 0.72rem;
  color: var(--text-tertiary);
}

.form-select {
  appearance: none;
  cursor: pointer;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%237f91a4' viewBox='0 0 16 16'%3E%3Cpath d='M8 11L3 6h10z'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 12px center;
  padding-right: 32px;
}

.input-with-toggle {
  position: relative;
  display: flex;
  align-items: center;
}

.input-with-toggle .form-input {
  padding-right: 40px;
}

.toggle-visibility {
  position: absolute;
  right: 6px;
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 0.88rem;
  padding: 4px;
  line-height: 1;
  opacity: 0.7;
  transition: opacity 0.18s ease;
}

.toggle-visibility:hover {
  opacity: 1;
}

.quick-init-test {
  display: grid;
  gap: 8px;
}

.test-button {
  width: 100%;
  height: 36px;
  font-size: 0.88rem;
}

.test-result {
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 0.82rem;
  line-height: 1.5;
}

.test-result strong {
  display: block;
}

.test-result p {
  margin: 4px 0 0;
  opacity: 0.8;
  word-break: break-word;
}

.test-result--ok {
  border: 1px solid color-mix(in srgb, var(--state-success) 38%, var(--border-default) 62%);
  background: color-mix(in srgb, var(--state-success) 10%, var(--surface-panel) 90%);
  color: var(--state-success);
}

.test-result--error {
  border: 1px solid color-mix(in srgb, var(--state-danger) 34%, var(--border-default) 66%);
  background: color-mix(in srgb, var(--state-danger) 10%, var(--surface-panel) 90%);
  color: var(--state-danger);
}

.save-error {
  padding: 10px 14px;
  border-radius: 8px;
  border: 1px solid color-mix(in srgb, var(--state-danger) 34%, var(--border-default) 66%);
  background: color-mix(in srgb, var(--state-danger) 10%, var(--surface-panel) 90%);
  color: var(--state-danger);
  font-size: 0.82rem;
}

.quick-init-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.quick-init-actions > .ghost-button {
  min-width: 72px;
  height: 36px;
  padding: 0 16px;
  font-size: 0.84rem;
}

.save-button {
  min-width: 88px;
  height: 36px;
  padding: 0 20px;
  font-size: 0.84rem;
  border-color: color-mix(in srgb, var(--state-success) 38%, var(--border-default) 62%);
  background: color-mix(in srgb, var(--state-success) 14%, var(--surface-panel) 86%);
}

.save-button:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--state-success) 58%, var(--interactive-focus-border) 42%);
  background: color-mix(in srgb, var(--state-success) 24%, var(--surface-panel) 76%);
}

@media (max-width: 640px) {
  .quick-init-overlay {
    padding: 12px;
  }

  .quick-init-dialog {
    width: min(100%, calc(100vw - 24px));
    max-height: calc(100vh - 24px);
    padding: 16px;
  }
}
</style>
