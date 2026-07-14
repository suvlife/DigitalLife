<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { getGhostConfig, testGhostConnection, updateGhostConfig } from '../../api';
import { showGlobalSuccessToast } from '../../appUiState';
import type { GhostConfig } from '../../types';
import ToggleSwitch from '../ui/ToggleSwitch.vue';
import SettingsBreadcrumb from './SettingsBreadcrumb.vue';
import type { SettingsBreadcrumbItem } from './types';

defineProps<{
  breadcrumbItems: SettingsBreadcrumbItem[];
}>();

const emit = defineEmits<{
  navigateBreadcrumb: [key: string];
}>();

const { t } = useI18n();

const original = ref<GhostConfig | null>(null);
const isLoading = ref(false);
const statusText = ref('');
const isSaving = ref(false);
const isTesting = ref(false);
const adminKeyVisible = ref(false);
const contentKeyVisible = ref(false);
const clearAdminKey = ref(false);
const clearContentKey = ref(false);
const testResult = ref<{ ok: boolean; message: string } | null>(null);

const form = ref({
  enabled: false,
  api_url: '',
  admin_api_key: '',
  content_api_key: '',
  auto_publish: true,
  publish_status: 'published',
  skip_ssl_verify: false,
});

const hasAdminKey = computed(() => original.value?.has_admin_key ?? false);
const hasContentKey = computed(() => original.value?.has_content_key ?? false);

async function loadConfig(): Promise<void> {
  isLoading.value = true;
  statusText.value = '';
  try {
    const data = await getGhostConfig();
    original.value = data;
    form.value = {
      enabled: data.enabled,
      api_url: data.api_url,
      admin_api_key: '',
      content_api_key: '',
      auto_publish: data.auto_publish,
      publish_status: data.publish_status || 'published',
      skip_ssl_verify: data.skip_ssl_verify,
    };
    clearAdminKey.value = false;
    clearContentKey.value = false;
    testResult.value = null;
  } catch (error) {
    console.error(error);
    statusText.value = t('settings.ghost.loadFailed');
  } finally {
    isLoading.value = false;
  }
}

async function saveConfig(): Promise<void> {
  if (isSaving.value) {
    return;
  }
  isSaving.value = true;
  statusText.value = '';
  try {
    const payload: Record<string, unknown> = {
      enabled: form.value.enabled,
      api_url: form.value.api_url.trim(),
      auto_publish: form.value.auto_publish,
      publish_status: form.value.publish_status,
      skip_ssl_verify: form.value.skip_ssl_verify,
    };
    // 空 key 表示保留原值；仅在填写或显式清除时提交。
    if (clearAdminKey.value) {
      payload.clear_admin_api_key = true;
    } else if (form.value.admin_api_key.trim()) {
      payload.admin_api_key = form.value.admin_api_key.trim();
    }
    if (clearContentKey.value) {
      payload.clear_content_api_key = true;
    } else if (form.value.content_api_key.trim()) {
      payload.content_api_key = form.value.content_api_key.trim();
    }

    await updateGhostConfig(payload);
    showGlobalSuccessToast(t('settings.ghost.saveSuccess'));
    await loadConfig();
  } catch (error) {
    console.error(error);
    statusText.value = error instanceof Error ? error.message : t('settings.ghost.saveFailed');
  } finally {
    isSaving.value = false;
  }
}

async function testConnection(): Promise<void> {
  if (isTesting.value) {
    return;
  }
  const apiUrl = form.value.api_url.trim();
  if (!apiUrl && !hasAdminKey.value) {
    testResult.value = { ok: false, message: t('settings.ghost.apiUrlRequired') };
    return;
  }
  isTesting.value = true;
  testResult.value = null;
  try {
    const result = await testGhostConnection({
      api_url: apiUrl,
      admin_api_key: form.value.admin_api_key.trim(),
      skip_ssl_verify: form.value.skip_ssl_verify,
    });
    const ok = result.success === true || result.status === 'ok' || result.status === 'success';
    testResult.value = {
      ok,
      message: String(
        result.message
        ?? result.detail
        ?? (ok ? t('settings.ghost.testSuccess') : t('settings.ghost.testFailed')),
      ),
    };
  } catch (error) {
    testResult.value = {
      ok: false,
      message: error instanceof Error ? error.message : t('settings.ghost.testFailed'),
    };
  } finally {
    isTesting.value = false;
  }
}

onMounted(() => {
  void loadConfig();
});
</script>

<template>
  <section id="ghost" class="config-section">
    <SettingsBreadcrumb :items="breadcrumbItems" @navigate="emit('navigateBreadcrumb', $event)" />

    <div class="section-intro">
      <p class="section-eyebrow">{{ t('settings.ghost.eyebrow') }}</p>
      <h3>{{ t('settings.ghost.title') }}</h3>
      <p class="section-desc">{{ t('settings.ghost.description') }}</p>
    </div>

    <p v-if="statusText" class="section-status section-status--error">{{ statusText }}</p>
    <p v-if="isLoading" class="section-status">{{ t('settings.ghost.loading') }}</p>

    <div v-else class="cfg-card">
      <div class="cfg-row cfg-row--switch">
        <div class="cfg-row-label">
          <strong>{{ t('settings.ghost.enableLabel') }}</strong>
          <span>{{ t('settings.ghost.enableNote') }}</span>
        </div>
        <ToggleSwitch
          variant="inline"
          :checked="form.enabled"
          :label="form.enabled ? t('common.on') : t('common.off')"
          @toggle="form.enabled = $event"
        />
      </div>

      <label class="cfg-field">
        <span>{{ t('settings.ghost.apiUrl') }}</span>
        <input
          v-model="form.api_url"
          type="text"
          class="cfg-input"
          :placeholder="t('settings.ghost.apiUrlPlaceholder')"
        />
      </label>

      <label class="cfg-field">
        <span>{{ t('settings.ghost.adminApiKey') }}</span>
        <div class="cfg-input-group">
          <input
            v-model="form.admin_api_key"
            :type="adminKeyVisible ? 'text' : 'password'"
            class="cfg-input cfg-input--flex"
            :placeholder="t('settings.ghost.adminApiKeyPlaceholder')"
            :disabled="clearAdminKey"
          />
          <button type="button" class="ghost-button" @click="adminKeyVisible = !adminKeyVisible">
            {{ adminKeyVisible ? t('settings.models.apiKeyHide') : t('settings.models.apiKeyShow') }}
          </button>
        </div>
        <div class="cfg-key-meta">
          <small v-if="hasAdminKey" class="cfg-hint">{{ t('settings.ghost.keySavedHint') }}</small>
          <label v-if="hasAdminKey" class="cfg-checkbox">
            <input v-model="clearAdminKey" type="checkbox" />
            <span>{{ t('settings.ghost.clearKey') }}</span>
          </label>
        </div>
      </label>

      <label class="cfg-field">
        <span>{{ t('settings.ghost.contentApiKey') }}</span>
        <div class="cfg-input-group">
          <input
            v-model="form.content_api_key"
            :type="contentKeyVisible ? 'text' : 'password'"
            class="cfg-input cfg-input--flex"
            :placeholder="t('settings.ghost.contentApiKeyPlaceholder')"
            :disabled="clearContentKey"
          />
          <button type="button" class="ghost-button" @click="contentKeyVisible = !contentKeyVisible">
            {{ contentKeyVisible ? t('settings.models.apiKeyHide') : t('settings.models.apiKeyShow') }}
          </button>
        </div>
        <div class="cfg-key-meta">
          <small v-if="hasContentKey" class="cfg-hint">{{ t('settings.ghost.keySavedHint') }}</small>
          <label v-if="hasContentKey" class="cfg-checkbox">
            <input v-model="clearContentKey" type="checkbox" />
            <span>{{ t('settings.ghost.clearKey') }}</span>
          </label>
        </div>
      </label>

      <div class="cfg-row cfg-row--switch">
        <div class="cfg-row-label">
          <strong>{{ t('settings.ghost.autoPublish') }}</strong>
          <span>{{ t('settings.ghost.autoPublishNote') }}</span>
        </div>
        <ToggleSwitch
          variant="inline"
          :checked="form.auto_publish"
          :label="form.auto_publish ? t('common.on') : t('common.off')"
          @toggle="form.auto_publish = $event"
        />
      </div>

      <label class="cfg-field">
        <span>{{ t('settings.ghost.publishStatus') }}</span>
        <select v-model="form.publish_status" class="cfg-input cfg-select">
          <option value="published">{{ t('settings.ghost.publishStatusPublished') }}</option>
          <option value="draft">{{ t('settings.ghost.publishStatusDraft') }}</option>
        </select>
      </label>

      <div class="cfg-row cfg-row--switch">
        <div class="cfg-row-label">
          <strong>{{ t('settings.ghost.skipSslVerify') }}</strong>
          <span>{{ t('settings.ghost.skipSslVerifyNote') }}</span>
        </div>
        <ToggleSwitch
          variant="inline"
          :checked="form.skip_ssl_verify"
          :label="form.skip_ssl_verify ? t('common.on') : t('common.off')"
          @toggle="form.skip_ssl_verify = $event"
        />
      </div>

      <div
        v-if="testResult"
        class="test-result"
        :class="testResult.ok ? 'test-result--ok' : 'test-result--error'"
      >
        {{ testResult.message }}
      </div>

      <div class="cfg-actions">
        <button type="button" class="secondary-button" :disabled="isTesting" @click="testConnection">
          {{ isTesting ? t('settings.ghost.testing') : t('settings.ghost.testBtn') }}
        </button>
        <button type="button" class="secondary-button" :disabled="isSaving" @click="saveConfig">
          {{ isSaving ? t('settings.ghost.saving') : t('settings.ghost.saveBtn') }}
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.config-section {
  padding: 12px 0 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.section-intro h3 {
  margin: 2px 0 0;
  color: var(--text-strong);
}

.section-eyebrow {
  margin: 0;
  color: var(--accent);
  text-transform: uppercase;
  letter-spacing: 0.14em;
  font-size: 0.68rem;
}

.section-desc {
  margin: 6px 0 0;
  color: var(--muted);
  font-size: 0.82rem;
  line-height: 1.5;
}

.section-status {
  color: var(--muted);
  font-size: 0.86rem;
}

.section-status--error {
  color: var(--danger);
}

.cfg-card {
  border: 1px solid var(--panel-border);
  border-radius: 14px;
  background: var(--surface-soft);
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.cfg-row--switch {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.cfg-row-label {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.cfg-row-label strong {
  color: var(--text-strong);
}

.cfg-row-label span {
  color: var(--muted);
  font-size: 0.76rem;
}

.cfg-field {
  display: grid;
  gap: 6px;
}

.cfg-field > span {
  color: var(--muted);
  font-size: 0.78rem;
}

.cfg-input,
.cfg-select {
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

.cfg-input:focus,
.cfg-select:focus {
  border-color: var(--focus-border);
  box-shadow: 0 0 0 2px var(--focus-glow);
  outline: none;
}

.cfg-input-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.cfg-input--flex {
  flex: 1;
  min-width: 0;
}

.cfg-key-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.cfg-hint {
  color: var(--muted);
  font-size: 0.74rem;
  line-height: 1.4;
}

.cfg-checkbox {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--muted);
  font-size: 0.78rem;
  white-space: nowrap;
}

.cfg-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.test-result {
  padding: 8px 12px;
  border-radius: 10px;
  font-size: 0.84rem;
  line-height: 1.5;
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
</style>
