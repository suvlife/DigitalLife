<script setup lang="ts">
import { ref, onMounted } from 'vue';
import * as api from '../../api/client';
import GlassPanel from '../GlassPanel.vue';
import HoloCard from '../HoloCard.vue';
import GlowButton from '../GlowButton.vue';
import StatusDot from '../StatusDot.vue';
import FormField from '../form/FormField.vue';
import TextInput from '../form/TextInput.vue';
import FormSelect from '../form/FormSelect.vue';
import FormToggle from '../form/FormToggle.vue';
import FormModal from '../form/FormModal.vue';

const config = ref<api.SearchToolsConfig | null>(null);
const loading = ref(false);
const saving = ref(false);
const error = ref(''); const notice = ref('');

const editorOpen = ref(false);
const editingIndex = ref<number | null>(null);
const providerForm = ref({ provider: 'tavily', apiKeysText: '', enable: true });
const deleteTarget = ref<number | null>(null);
const deleting = ref(false);

const providerOptions = [
  { value: 'tavily', label: 'Tavily' },
  { value: 'brave', label: 'Brave' },
  { value: 'bing', label: 'Bing' },
];

async function load() {
  loading.value = true; error.value = '';
  try { config.value = await api.getSearchConfig(); }
  catch (e: any) { error.value = e?.message || '加载失败'; }
  finally { loading.value = false; }
}

async function toggleEnabled(v: boolean) {
  saving.value = true; error.value = ''; notice.value = '';
  try { await api.updateSearchSettings({ enabled: v }); notice.value = v ? '搜索已启用' : '搜索已停用'; await load(); }
  catch (e: any) { error.value = e?.message || '操作失败'; }
  finally { saving.value = false; }
}

function openCreate() { editingIndex.value = null; providerForm.value = { provider: 'tavily', apiKeysText: '', enable: true }; editorOpen.value = true; }
function openEdit(i: number) {
  const p = config.value?.providers[i]; if (!p) return;
  editingIndex.value = i;
  providerForm.value = { provider: p.provider, apiKeysText: '', enable: p.enable };
  editorOpen.value = true;
}

async function saveProvider() {
  saving.value = true; error.value = ''; notice.value = '';
  const keys = providerForm.value.apiKeysText.split('\n').map(s => s.trim()).filter(Boolean);
  try {
    if (editingIndex.value === null) {
      await api.createSearchProvider({ provider: providerForm.value.provider, api_keys: keys, enable: providerForm.value.enable });
      notice.value = '已添加搜索引擎';
    } else {
      const body: api.SearchProviderModifyPayload = { enable: providerForm.value.enable };
      if (keys.length) body.api_keys = keys;
      await api.modifySearchProvider(editingIndex.value, body);
      notice.value = '已保存';
    }
    editorOpen.value = false;
    await load();
  } catch (e: any) { error.value = e?.message || '保存失败'; }
  finally { saving.value = false; }
}

async function confirmDelete() {
  if (deleteTarget.value === null) return;
  deleting.value = true; error.value = '';
  try { await api.deleteSearchProvider(deleteTarget.value); notice.value = '已删除'; deleteTarget.value = null; await load(); }
  catch (e: any) { error.value = e?.message || '删除失败'; }
  finally { deleting.value = false; }
}

onMounted(load);
</script>

<template>
  <div class="search-section">
    <div class="section-actions">
      <FormToggle :model-value="config?.enabled ?? false" label="启用联网搜索" @update:model-value="toggleEnabled" />
      <GlowButton variant="primary" size="sm" @click="openCreate">+ 添加引擎</GlowButton>
      <GlowButton variant="secondary" size="sm" :loading="loading" @click="load">刷新</GlowButton>
    </div>
    <p v-if="error" class="msg-error">{{ error }}</p>
    <p v-if="notice" class="msg-ok">{{ notice }}</p>

    <div class="provider-list" v-if="config">
      <HoloCard v-for="(p, i) in config.providers" :key="p.provider" :status="p.enable ? 'discussing' : 'idle'">
        <template #header>
          <div class="svc-header">
            <StatusDot :status="p.enable ? 'online' : 'waiting'" />
            <span class="svc-name">{{ p.provider }}</span>
            <span v-if="p.has_api_key" class="badge">{{ p.api_keys_count }} Key</span>
            <span v-else class="badge badge-missing">无 Key</span>
          </div>
        </template>
        <p class="svc-info">{{ p.enable ? '已启用' : '已停用' }}</p>
        <template #footer>
          <div class="svc-actions">
            <GlowButton variant="secondary" size="sm" @click="openEdit(i)">编辑</GlowButton>
            <GlowButton variant="danger" size="sm" @click="deleteTarget = i">删除</GlowButton>
          </div>
        </template>
      </HoloCard>
      <GlassPanel v-if="!config.providers.length" padding="md"><p class="empty-text">暂未配置搜索引擎</p></GlassPanel>
    </div>

    <FormModal :open="editorOpen" :title="editingIndex === null ? '添加搜索引擎' : '编辑搜索引擎'"
      confirm-text="保存" :loading="saving" @close="editorOpen = false" @confirm="saveProvider">
      <FormField label="引擎" required>
        <FormSelect v-model="providerForm.provider" :options="providerOptions" :disabled="editingIndex !== null" />
      </FormField>
      <FormField label="API Keys（每行一个，支持多 Key 轮询）" :hint="editingIndex !== null ? '留空表示不修改现有 Key' : ''">
        <textarea v-model="providerForm.apiKeysText" class="keys-input" rows="4" placeholder="tvly-...&#10;第二把 Key（可选）"></textarea>
      </FormField>
      <FormToggle v-model="providerForm.enable" label="启用该引擎" />
    </FormModal>

    <FormModal :open="deleteTarget !== null" title="删除搜索引擎" confirm-text="删除" confirm-danger
      :loading="deleting" @close="deleteTarget = null" @confirm="confirmDelete">
      <p class="confirm-text">确定删除该搜索引擎吗？</p>
    </FormModal>
  </div>
</template>

<style scoped>
.search-section { display: flex; flex-direction: column; gap: var(--space-4); }
.section-actions { display: flex; align-items: center; gap: var(--space-4); }
.msg-error { font-size: var(--fs-sm); color: var(--holo-red); margin: 0; }
.msg-ok { font-size: var(--fs-sm); color: var(--holo-teal); margin: 0; }
.provider-list { display: flex; flex-direction: column; gap: var(--space-3); }
.svc-header { display: flex; align-items: center; gap: 8px; }
.svc-name { font-size: var(--fs-base); font-weight: 500; color: var(--text-primary); text-transform: capitalize; }
.badge { font-size: 10px; padding: 1px 6px; border-radius: 4px; background: rgba(0,217,255,0.1); color: var(--holo-cyan); border: 1px solid var(--glass-border); }
.badge-missing { background: rgba(255,82,82,0.08); color: var(--holo-red); border-color: rgba(255,82,82,0.3); }
.svc-info { font-size: var(--fs-sm); color: var(--text-secondary); }
.svc-actions { display: flex; gap: var(--space-2); }
.empty-text { color: var(--text-muted); text-align: center; }
.keys-input { width: 100%; background: rgba(0,0,0,0.25); border: 1px solid var(--glass-border); border-radius: var(--glass-radius-sm); padding: 8px 12px; color: var(--text-primary); font-family: var(--font-mono); font-size: var(--fs-xs); resize: vertical; box-sizing: border-box; }
.keys-input:focus { border-color: var(--glass-border-active); box-shadow: var(--glow-cyan); outline: none; }
.confirm-text { font-size: var(--fs-sm); color: var(--text-secondary); }
</style>
