<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import {
  createSearchProvider,
  deleteSearchProvider,
  getSearchConfig,
  modifySearchProvider,
  updateSearchSettings,
} from '../../api';
import { showGlobalSuccessToast } from '../../appUiState';
import type { SearchConfig, SearchProviderInfo } from '../../types';
import ConfirmDialog from '../ui/ConfirmDialog.vue';
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

const config = ref<SearchConfig | null>(null);
const isLoading = ref(false);
const statusText = ref('');

// 全局设置草稿
const globalEnabled = ref(true);
const maxContentLength = ref(8000);
const maxFetchBytes = ref(5 * 1024 * 1024);
const isSavingSettings = ref(false);

// 引擎编辑弹窗
const dialogOpen = ref(false);
const dialogMode = ref<'create' | 'edit'>('create');
const editingIndex = ref<number | null>(null);
const editingOriginal = ref<SearchProviderInfo | null>(null);
const formProvider = ref('');
const formEnable = ref(true);
const formKeysText = ref('');
const clearKeys = ref(false);
const isSavingProvider = ref(false);
const dialogError = ref('');

const deleteConfirmOpen = ref(false);
const deletingIndex = ref<number | null>(null);
const isDeleting = ref(false);

const providers = computed(() => config.value?.providers ?? []);

const dialogTitle = computed(() => (
  dialogMode.value === 'create' ? t('settings.search.newTitle') : t('settings.search.editTitle')
));

function syncGlobalDraft(source: SearchConfig): void {
  globalEnabled.value = source.enabled;
  maxContentLength.value = source.max_content_length;
  maxFetchBytes.value = source.max_fetch_bytes;
}

async function loadConfig(): Promise<void> {
  isLoading.value = true;
  statusText.value = '';
  try {
    const data = await getSearchConfig();
    config.value = data;
    syncGlobalDraft(data);
  } catch (error) {
    console.error(error);
    statusText.value = t('settings.search.loadFailed');
  } finally {
    isLoading.value = false;
  }
}

async function saveGlobalSettings(): Promise<void> {
  if (isSavingSettings.value) {
    return;
  }
  isSavingSettings.value = true;
  try {
    await updateSearchSettings({
      enabled: globalEnabled.value,
      max_content_length: maxContentLength.value,
      max_fetch_bytes: maxFetchBytes.value,
    });
    showGlobalSuccessToast(t('settings.search.settingsSaved'));
    await loadConfig();
  } catch (error) {
    console.error(error);
  } finally {
    isSavingSettings.value = false;
  }
}

function openCreate(): void {
  dialogMode.value = 'create';
  editingIndex.value = null;
  editingOriginal.value = null;
  formProvider.value = '';
  formEnable.value = true;
  formKeysText.value = '';
  clearKeys.value = false;
  dialogError.value = '';
  dialogOpen.value = true;
}

function openEdit(index: number): void {
  const provider = providers.value[index];
  if (!provider) {
    return;
  }
  dialogMode.value = 'edit';
  editingIndex.value = index;
  editingOriginal.value = provider;
  formProvider.value = provider.provider;
  formEnable.value = provider.enable;
  // 已保存 key 为脱敏值，编辑时留空，避免误将掩码写回覆盖真实 key。
  formKeysText.value = '';
  clearKeys.value = false;
  dialogError.value = '';
  dialogOpen.value = true;
}

function closeDialog(): void {
  dialogOpen.value = false;
}

function parseKeys(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

async function saveProvider(): Promise<void> {
  const provider = formProvider.value.trim();
  if (!provider) {
    dialogError.value = t('settings.search.providerRequired');
    return;
  }
  if (isSavingProvider.value) {
    return;
  }
  isSavingProvider.value = true;
  dialogError.value = '';
  try {
    if (dialogMode.value === 'create') {
      await createSearchProvider({
        provider,
        api_keys: parseKeys(formKeysText.value),
        enable: formEnable.value,
      });
      showGlobalSuccessToast(t('settings.search.createSuccess'));
    } else if (editingIndex.value !== null) {
      const payload: {
        provider?: string;
        enable?: boolean;
        api_keys?: string[];
        clear_api_keys?: boolean;
      } = {
        provider,
        enable: formEnable.value,
      };
      if (clearKeys.value) {
        payload.clear_api_keys = true;
      } else {
        const keys = parseKeys(formKeysText.value);
        // 仅在用户填写了新 key 时才提交，避免脱敏留空覆盖真实值。
        if (keys.length > 0) {
          payload.api_keys = keys;
        }
      }
      await modifySearchProvider(editingIndex.value, payload);
      showGlobalSuccessToast(t('settings.search.saveSuccess'));
    }
    closeDialog();
    await loadConfig();
  } catch (error) {
    console.error(error);
    dialogError.value = error instanceof Error ? error.message : t('settings.search.saveFailed');
  } finally {
    isSavingProvider.value = false;
  }
}

function requestDelete(index: number): void {
  deletingIndex.value = index;
  deleteConfirmOpen.value = true;
}

async function confirmDelete(): Promise<void> {
  if (deletingIndex.value === null) {
    deleteConfirmOpen.value = false;
    return;
  }
  isDeleting.value = true;
  try {
    await deleteSearchProvider(deletingIndex.value);
    showGlobalSuccessToast(t('settings.search.deleteSuccess'));
    deleteConfirmOpen.value = false;
    deletingIndex.value = null;
    await loadConfig();
  } catch (error) {
    console.error(error);
  } finally {
    isDeleting.value = false;
  }
}

onMounted(() => {
  void loadConfig();
});
</script>

<template>
  <section id="search" class="config-section">
    <SettingsBreadcrumb :items="breadcrumbItems" @navigate="emit('navigateBreadcrumb', $event)" />

    <div class="section-intro">
      <p class="section-eyebrow">{{ t('settings.search.eyebrow') }}</p>
      <h3>{{ t('settings.search.title') }}</h3>
      <p class="section-desc">{{ t('settings.search.description') }}</p>
    </div>

    <p v-if="statusText" class="section-status">{{ statusText }}</p>
    <p v-if="isLoading" class="section-status">{{ t('settings.search.loading') }}</p>

    <template v-else>
      <!-- 全局设置 -->
      <div class="cfg-card">
        <div class="cfg-row cfg-row--switch">
          <div class="cfg-row-label">
            <strong>{{ t('settings.search.globalEnable') }}</strong>
            <span>{{ t('settings.search.globalEnableNote') }}</span>
          </div>
          <ToggleSwitch
            variant="inline"
            :checked="globalEnabled"
            :label="globalEnabled ? t('settings.search.enabled') : t('settings.search.disabled')"
            @toggle="globalEnabled = $event"
          />
        </div>

        <div class="cfg-grid">
          <label class="cfg-field">
            <span>{{ t('settings.search.maxContentLength') }}</span>
            <input v-model.number="maxContentLength" type="number" class="cfg-input" min="1000" />
          </label>
          <label class="cfg-field">
            <span>{{ t('settings.search.maxFetchBytes') }}</span>
            <input v-model.number="maxFetchBytes" type="number" class="cfg-input" min="65536" />
          </label>
        </div>

        <div class="cfg-actions">
          <button type="button" class="secondary-button" :disabled="isSavingSettings" @click="saveGlobalSettings">
            {{ isSavingSettings ? t('settings.search.saving') : t('settings.search.saveSettings') }}
          </button>
        </div>
      </div>

      <!-- 引擎列表 -->
      <div class="section-head">
        <div class="section-head-copy">
          <strong>{{ t('settings.search.providersTitle') }}</strong>
          <span class="section-count">{{ t('settings.search.providersCount', { count: providers.length }) }}</span>
        </div>
        <button type="button" class="secondary-button" @click="openCreate">
          {{ t('settings.search.addProvider') }}
        </button>
      </div>

      <p class="rotation-hint">{{ t('settings.search.rotationHint') }}</p>

      <div v-if="providers.length" class="provider-list">
        <div v-for="(provider, index) in providers" :key="`${provider.provider}-${index}`" class="provider-card">
          <div class="provider-main">
            <div class="provider-title">
              <strong>{{ provider.provider }}</strong>
              <span
                class="svc-chip"
                :class="provider.enable ? 'svc-chip--enabled' : 'svc-chip--disabled'"
              >
                {{ provider.enable ? t('settings.search.enabled') : t('settings.search.disabled') }}
              </span>
            </div>
            <div class="provider-keys">
              <span v-if="provider.api_keys_count" class="key-chip">
                {{ t('settings.search.keysCount', { count: provider.api_keys_count }) }}
              </span>
              <span v-else class="key-chip key-chip--empty">{{ t('settings.search.noKey') }}</span>
              <code v-for="(masked, keyIndex) in provider.api_keys" :key="keyIndex" class="key-masked">
                {{ masked }}
              </code>
            </div>
          </div>
          <div class="provider-actions">
            <button type="button" class="ghost-button" @click="openEdit(index)">{{ t('common.edit') }}</button>
            <button type="button" class="ghost-button ghost-button--danger" @click="requestDelete(index)">
              {{ t('common.delete') }}
            </button>
          </div>
        </div>
      </div>

      <p v-else class="section-status">{{ t('settings.search.empty') }}</p>
    </template>

    <!-- 引擎编辑弹窗 -->
    <Teleport to="body">
      <div v-if="dialogOpen" class="editor-overlay" @click.self="closeDialog">
        <section class="editor-dialog panel scrollbar-thin">
          <header class="editor-head">
            <h3>{{ dialogTitle }}</h3>
            <button type="button" class="ghost-button editor-close" :aria-label="t('common.close')" @click="closeDialog">×</button>
          </header>

          <label class="cfg-field">
            <span>{{ t('settings.search.providerLabel') }}</span>
            <input
              v-model="formProvider"
              type="text"
              class="cfg-input"
              :placeholder="t('settings.search.providerPlaceholder')"
            />
            <small class="cfg-hint">{{ t('settings.search.providerHint') }}</small>
          </label>

          <label class="cfg-field">
            <span>{{ t('settings.search.enableLabel') }}</span>
            <div class="cfg-toggle-box">
              <ToggleSwitch
                variant="inline"
                :checked="formEnable"
                :label="formEnable ? t('settings.search.enabled') : t('settings.search.disabled')"
                @toggle="formEnable = $event"
              />
            </div>
          </label>

          <label class="cfg-field">
            <span>{{ t('settings.search.keysLabel') }}</span>
            <textarea
              v-model="formKeysText"
              class="cfg-textarea"
              rows="5"
              :placeholder="t('settings.search.keysPlaceholder')"
              :disabled="clearKeys"
            ></textarea>
            <small v-if="dialogMode === 'edit' && editingOriginal?.api_keys_count" class="cfg-hint">
              {{ t('settings.search.keysMaskedHint', { count: editingOriginal.api_keys_count }) }}
            </small>
          </label>

          <label v-if="dialogMode === 'edit'" class="cfg-checkbox">
            <input v-model="clearKeys" type="checkbox" />
            <span>{{ t('settings.search.clearKeys') }}</span>
          </label>

          <p v-if="dialogError" class="editor-status">{{ dialogError }}</p>

          <footer class="editor-actions">
            <button type="button" class="secondary-button" @click="closeDialog">{{ t('common.cancel') }}</button>
            <button type="button" class="secondary-button" :disabled="isSavingProvider" @click="saveProvider">
              {{ isSavingProvider
                ? t('settings.search.saving')
                : (dialogMode === 'create' ? t('settings.search.createBtn') : t('settings.search.saveBtn')) }}
            </button>
          </footer>
        </section>
      </div>
    </Teleport>

    <ConfirmDialog
      :open="deleteConfirmOpen"
      :title="t('settings.search.deleteConfirmTitle')"
      :message="t('settings.search.deleteConfirmMsg', {
        name: deletingIndex !== null ? (providers[deletingIndex]?.provider || '') : '',
      })"
      :confirm-label="t('settings.search.deleteConfirmBtn')"
      danger
      @close="deleteConfirmOpen = false"
      @confirm="confirmDelete"
    />
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

.cfg-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
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
.cfg-textarea {
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

.cfg-textarea {
  resize: vertical;
  min-height: 96px;
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
}

.cfg-input:focus,
.cfg-textarea:focus {
  border-color: var(--focus-border);
  box-shadow: 0 0 0 2px var(--focus-glow);
  outline: none;
}

.cfg-hint {
  color: var(--muted);
  font-size: 0.74rem;
  line-height: 1.4;
}

.cfg-toggle-box {
  min-height: 40px;
  display: flex;
  align-items: center;
}

.cfg-actions {
  display: flex;
  justify-content: flex-end;
}

.cfg-checkbox {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--muted);
  font-size: 0.82rem;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.section-head-copy {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.section-head-copy strong {
  color: var(--text-strong);
}

.section-count {
  color: var(--muted);
  font-size: 0.76rem;
}

.rotation-hint {
  margin: -4px 0 0;
  color: var(--muted);
  font-size: 0.76rem;
  line-height: 1.4;
}

.provider-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.provider-card {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--panel-border);
  border-radius: 14px;
  background: var(--surface-soft);
}

.provider-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.provider-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.provider-title strong {
  color: var(--text-strong);
  font-size: 0.96rem;
  text-transform: uppercase;
  letter-spacing: 0.02em;
}

.provider-keys {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.key-chip {
  font-size: 0.7rem;
  color: var(--good);
  border: 1px solid color-mix(in srgb, var(--good) 32%, var(--panel-border) 68%);
  background: color-mix(in srgb, var(--good) 10%, var(--panel-bg) 90%);
  border-radius: 999px;
  padding: 1px 8px;
}

.key-chip--empty {
  color: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 28%, var(--panel-border) 72%);
  background: color-mix(in srgb, var(--warn) 8%, var(--panel-bg) 92%);
}

.key-masked {
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  font-size: 0.72rem;
  color: var(--muted);
  background: var(--panel-bg);
  border: 1px solid var(--panel-border);
  border-radius: 6px;
  padding: 1px 6px;
}

.provider-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.ghost-button--danger {
  color: var(--danger);
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
  width: min(560px, calc(100vw - 40px));
  max-height: calc(100vh - 40px);
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  overflow: auto;
}

.editor-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.editor-head h3 {
  margin: 0;
  color: var(--text-strong);
}

.editor-close {
  min-width: 32px;
  height: 32px;
  padding: 0;
  font-size: 1rem;
}

.editor-status {
  color: var(--danger);
  font-size: 0.8rem;
}

.editor-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

@media (max-width: 780px) {
  .cfg-grid {
    grid-template-columns: 1fr;
  }

  .provider-card {
    flex-direction: column;
  }
}
</style>
