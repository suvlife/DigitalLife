<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import * as api from '../../api/client';
import GlassPanel from '../GlassPanel.vue';
import HoloCard from '../HoloCard.vue';
import GlowButton from '../GlowButton.vue';
import StatusDot from '../StatusDot.vue';
import FormField from '../form/FormField.vue';
import TextInput from '../form/TextInput.vue';
import FormSelect from '../form/FormSelect.vue';
import FormModal from '../form/FormModal.vue';

interface EditForm {
  index: number | null; // null = 新建
  name: string; base_url: string; api_key: string; type: api.LlmServiceType; model: string;
  max_concurrency: number; requests_per_minute: number;
}

const llmServices = ref<api.LlmServiceInfo[]>([]);
const defaultServer = ref<string | null>(null);
const fallback = ref<string[]>([]);
const catalog = ref<api.LlmProviderCatalogEntry[]>([]);
const loading = ref(false);
const error = ref('');
const notice = ref('');

const editorOpen = ref(false);
const saving = ref(false);
const testing = ref(false);
const testResult = ref<api.LlmServiceTestResult | null>(null);
const deleteTarget = ref<api.LlmServiceInfo | null>(null);
const deleting = ref(false);
const form = ref<EditForm>(emptyForm());

const typeOptions = [
  { value: 'openai-compatible', label: 'OpenAI 兼容' },
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'google', label: 'Google (Gemini)' },
  { value: 'deepseek', label: 'DeepSeek' },
];

const defaultIndex = computed(() => llmServices.value.findIndex(s => s.name === defaultServer.value));

function emptyForm(): EditForm {
  return { index: null, name: '', base_url: '', api_key: '', type: 'openai-compatible', model: '', max_concurrency: 5, requests_per_minute: 0 };
}

async function loadAll() {
  loading.value = true; error.value = '';
  try {
    const d = await api.getLlmServiceConfig();
    llmServices.value = d.llm_services || [];
    defaultServer.value = d.default_llm_server ?? null;
    try { const fb = await api.getLlmFallback(); fallback.value = fb.fallback_llm_servers || []; } catch { fallback.value = []; }
  } catch (e: any) { error.value = e?.message || '加载失败'; }
  finally { loading.value = false; }
}

async function loadCatalog() { try { catalog.value = await api.getLlmProviderCatalog(); } catch {} }

function openCreate() { form.value = emptyForm(); testResult.value = null; editorOpen.value = true; }
function openEdit(svc: api.LlmServiceInfo, index: number) {
  form.value = {
    index, name: svc.name, base_url: svc.base_url, api_key: '', // 密钥不回填，留空表示不修改
    type: svc.type, model: svc.model,
    max_concurrency: svc.max_concurrency ?? 5, requests_per_minute: svc.requests_per_minute ?? 0,
  };
  testResult.value = null; editorOpen.value = true;
}

function applyProvider(providerId: string) {
  const p = catalog.value.find(x => x.id === providerId);
  if (!p) return;
  form.value.base_url = p.base_url;
  form.value.type = (p.type as api.LlmServiceType) || 'openai-compatible';
  form.value.model = p.default_model || '';
  if (!form.value.name) form.value.name = p.id;
}

async function save() {
  if (!form.value.name.trim() || !form.value.base_url.trim()) { error.value = '名称与接入地址必填'; return; }
  saving.value = true; error.value = '';
  try {
    if (form.value.index === null) {
      await api.createLlmService({
        name: form.value.name.trim(), base_url: form.value.base_url.trim(), api_key: form.value.api_key,
        type: form.value.type, model: form.value.model,
        max_concurrency: form.value.max_concurrency, requests_per_minute: form.value.requests_per_minute,
      });
      notice.value = '已创建 LLM 服务';
    } else {
      const body: api.LlmServiceModifyPayload = {
        base_url: form.value.base_url.trim(), type: form.value.type, model: form.value.model,
        max_concurrency: form.value.max_concurrency, requests_per_minute: form.value.requests_per_minute,
      };
      if (form.value.api_key) body.api_key = form.value.api_key; // 仅在填写时更新密钥
      await api.modifyLlmService(form.value.index, body);
      notice.value = '已保存修改';
    }
    editorOpen.value = false;
    await loadAll();
  } catch (e: any) { error.value = e?.message || '保存失败'; }
  finally { saving.value = false; }
}

async function testConnection() {
  testing.value = true; testResult.value = null; error.value = '';
  try {
    const payload: api.LlmServiceTestPayload = form.value.index === null
      ? { mode: 'temp', base_url: form.value.base_url, api_key: form.value.api_key, type: form.value.type, model: form.value.model }
      : { mode: 'saved', index: form.value.index };
    testResult.value = await api.testLlmService(payload);
  } catch (e: any) { testResult.value = { status: 'error', message: e?.message || '测试失败' }; }
  finally { testing.value = false; }
}

async function setDefault(index: number) {
  error.value = ''; notice.value = '';
  try { await api.setDefaultLlmService(index); notice.value = '已设为默认服务'; await loadAll(); }
  catch (e: any) { error.value = e?.message || '设置失败'; }
}

async function toggleEnable(svc: api.LlmServiceInfo, index: number) {
  error.value = ''; notice.value = '';
  try { await api.modifyLlmService(index, { enable: !svc.enable }); await loadAll(); }
  catch (e: any) { error.value = e?.message || '操作失败'; }
}

async function confirmDelete() {
  if (deleteTarget.value === null) return;
  deleting.value = true; error.value = '';
  try {
    const idx = llmServices.value.indexOf(deleteTarget.value);
    await api.deleteLlmService(idx);
    notice.value = `已删除服务 ${deleteTarget.value.name}`;
    deleteTarget.value = null;
    await loadAll();
  } catch (e: any) { error.value = e?.message || '删除失败'; }
  finally { deleting.value = false; }
}

async function saveFallback() {
  error.value = ''; notice.value = '';
  try { await api.setLlmFallback(fallback.value); notice.value = '兜底链已保存'; }
  catch (e: any) { error.value = e?.message || '保存失败'; }
}
function toggleFallback(name: string) {
  if (name === defaultServer.value) return; // 默认服务不进兜底链
  const i = fallback.value.indexOf(name);
  if (i >= 0) fallback.value.splice(i, 1); else fallback.value.push(name);
}
function moveFallback(i: number, dir: -1 | 1) {
  const j = i + dir; if (j < 0 || j >= fallback.value.length) return;
  const [x] = fallback.value.splice(i, 1); fallback.value.splice(j, 0, x);
}

onMounted(() => { loadAll(); loadCatalog(); });
</script>

<template>
  <div class="llm-section">
    <div class="section-actions">
      <GlowButton variant="primary" size="sm" @click="openCreate">+ 添加服务</GlowButton>
      <GlowButton variant="secondary" size="sm" :loading="loading" @click="loadAll">刷新</GlowButton>
    </div>
    <p v-if="error" class="msg-error">{{ error }}</p>
    <p v-if="notice" class="msg-ok">{{ notice }}</p>

    <div class="service-list">
      <HoloCard v-for="(svc, i) in llmServices" :key="svc.name" :status="svc.enable ? 'discussing' : 'idle'">
        <template #header>
          <div class="svc-header">
            <StatusDot :status="svc.enable ? 'online' : 'waiting'" />
            <span class="svc-name">{{ svc.name }}</span>
            <span v-if="svc.is_builtin" class="badge">内置</span>
            <span v-if="svc.name === defaultServer" class="badge badge-default">默认</span>
            <span v-else-if="fallback.includes(svc.name)" class="badge badge-fallback">兜底 #{{ fallback.indexOf(svc.name) + 1 }}</span>
          </div>
        </template>
        <p class="svc-info">{{ svc.model || '未指定模型' }} · {{ svc.type }}</p>
        <p class="svc-url">{{ svc.base_url }}</p>
        <template #footer>
          <div class="svc-actions">
            <GlowButton variant="secondary" size="sm" @click="openEdit(svc, i)">编辑</GlowButton>
            <GlowButton v-if="svc.name !== defaultServer" variant="secondary" size="sm" @click="setDefault(i)">设默认</GlowButton>
            <GlowButton variant="secondary" size="sm" @click="toggleEnable(svc, i)">{{ svc.enable ? '停用' : '启用' }}</GlowButton>
            <GlowButton v-if="!svc.is_builtin" variant="danger" size="sm" @click="deleteTarget = svc">删除</GlowButton>
          </div>
        </template>
      </HoloCard>
      <GlassPanel v-if="!llmServices.length && !loading" padding="md">
        <p class="empty-text">暂未配置大模型服务，点击「添加服务」开始。</p>
      </GlassPanel>
    </div>

    <!-- 兜底链配置 -->
    <GlassPanel v-if="llmServices.length" padding="md" class="fallback-panel">
      <div class="fallback-header">
        <span class="fallback-title">兜底链（首选不可用时按序切换）</span>
        <GlowButton variant="secondary" size="sm" @click="saveFallback">保存兜底链</GlowButton>
      </div>
      <p class="fallback-hint">默认服务：{{ defaultServer || '未设置' }}。勾选其他服务加入兜底链，用箭头调整顺序。</p>
      <div class="fallback-list">
        <div v-for="svc in llmServices.filter(s => s.name !== defaultServer)" :key="svc.name" class="fallback-item">
          <label class="fb-check">
            <input type="checkbox" :checked="fallback.includes(svc.name)" @change="toggleFallback(svc.name)" />
            <span>{{ svc.name }}</span>
          </label>
          <div v-if="fallback.includes(svc.name)" class="fb-order">
            <button class="fb-btn" @click="moveFallback(fallback.indexOf(svc.name), -1)">↑</button>
            <button class="fb-btn" @click="moveFallback(fallback.indexOf(svc.name), 1)">↓</button>
          </div>
        </div>
      </div>
    </GlassPanel>

    <!-- 编辑/新建 模态框 -->
    <FormModal :open="editorOpen" :title="form.index === null ? '添加 LLM 服务' : `编辑 ${form.name}`"
      confirm-text="保存" :loading="saving" @close="editorOpen = false" @confirm="save">
      <FormField v-if="catalog.length && form.index === null" label="从厂商预设快速填充" hint="选择厂商自动填入接入地址与模型">
        <FormSelect :model-value="''" :options="[{ value: '', label: '手动配置' }, ...catalog.map(p => ({ value: p.id, label: api.providerDisplayName(p) }))]"
          placeholder="手动配置" @update:model-value="applyProvider" />
      </FormField>
      <FormField label="服务名称" required>
        <TextInput v-model="form.name" placeholder="如 qwen、deepseek" :disabled="form.index !== null" />
      </FormField>
      <FormField label="服务类型" required>
        <FormSelect v-model="form.type" :options="typeOptions" />
      </FormField>
      <FormField label="接入地址 (base_url)" required hint="支持本地服务如 http://127.0.0.1:11434/v1">
        <TextInput v-model="form.base_url" placeholder="https://api.example.com/v1" mono />
      </FormField>
      <FormField label="API Key" :hint="form.index !== null ? '留空表示不修改现有密钥' : ''">
        <TextInput v-model="form.api_key" password placeholder="sk-..." mono />
      </FormField>
      <FormField label="模型">
        <TextInput v-model="form.model" placeholder="如 qwen-plus" mono />
      </FormField>
      <div class="form-row">
        <FormField label="最大并发">
          <TextInput v-model="form.max_concurrency" type="number" />
        </FormField>
        <FormField label="每分钟请求上限(0=不限)">
          <TextInput v-model="form.requests_per_minute" type="number" />
        </FormField>
      </div>
      <div class="editor-test">
        <GlowButton variant="secondary" size="sm" :loading="testing" @click="testConnection">测试连接</GlowButton>
        <span v-if="testResult" class="test-result" :class="testResult.status === 'ok' ? 'test-ok' : 'test-fail'">
          {{ testResult.status === 'ok' ? '✓ ' : '✗ ' }}{{ testResult.message }}
        </span>
      </div>
    </FormModal>

    <!-- 删除确认 -->
    <FormModal :open="deleteTarget !== null" title="删除 LLM 服务" confirm-text="删除" confirm-danger
      :loading="deleting" @close="deleteTarget = null" @confirm="confirmDelete">
      <p class="confirm-text">确定删除服务 <strong>{{ deleteTarget?.name }}</strong> 吗？此操作不可撤销。</p>
    </FormModal>
  </div>
</template>

<style scoped>
.llm-section { display: flex; flex-direction: column; gap: var(--space-4); }
.section-actions { display: flex; gap: var(--space-3); }
.msg-error { font-size: var(--fs-sm); color: var(--holo-red); margin: 0; }
.msg-ok { font-size: var(--fs-sm); color: var(--holo-teal); margin: 0; }
.service-list { display: flex; flex-direction: column; gap: var(--space-3); }
.svc-header { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.svc-name { font-size: var(--fs-base); font-weight: 500; color: var(--text-primary); }
.badge { font-size: 10px; padding: 1px 6px; border-radius: 4px; background: rgba(0,217,255,0.1); color: var(--holo-cyan); border: 1px solid var(--glass-border); }
.badge-default { background: rgba(0,230,180,0.12); color: var(--holo-teal); border-color: rgba(0,230,180,0.3); }
.badge-fallback { background: rgba(180,120,255,0.12); color: var(--holo-purple); border-color: rgba(180,120,255,0.3); }
.svc-info { font-size: var(--fs-sm); color: var(--text-secondary); }
.svc-url { font-size: var(--fs-xs); color: var(--text-muted); font-family: var(--font-mono); word-break: break-all; }
.svc-actions { display: flex; gap: var(--space-2); flex-wrap: wrap; }
.empty-text { color: var(--text-muted); text-align: center; }
.fallback-panel { display: flex; flex-direction: column; gap: var(--space-3); }
.fallback-header { display: flex; justify-content: space-between; align-items: center; }
.fallback-title { font-size: var(--fs-sm); font-weight: 600; color: var(--text-primary); }
.fallback-hint { font-size: var(--fs-xs); color: var(--text-muted); margin: 0; }
.fallback-list { display: flex; flex-direction: column; gap: var(--space-2); }
.fallback-item { display: flex; justify-content: space-between; align-items: center; }
.fb-check { display: flex; align-items: center; gap: 8px; font-size: var(--fs-sm); color: var(--text-secondary); cursor: pointer; }
.fb-order { display: flex; gap: 4px; }
.fb-btn { background: rgba(255,255,255,0.04); border: 1px solid var(--glass-border); color: var(--text-secondary); border-radius: 4px; width: 24px; height: 24px; cursor: pointer; }
.fb-btn:hover { border-color: var(--glass-border-active); color: var(--holo-cyan); }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-3); }
.editor-test { display: flex; align-items: center; gap: var(--space-3); }
.test-result { font-size: var(--fs-xs); }
.test-ok { color: var(--holo-teal); }
.test-fail { color: var(--holo-red); }
.confirm-text { font-size: var(--fs-sm); color: var(--text-secondary); }
</style>
