<script setup lang="ts">
import { ref, onMounted } from 'vue';
import * as api from '../../api/client';
import GlassPanel from '../GlassPanel.vue';
import GlowButton from '../GlowButton.vue';
import StatusDot from '../StatusDot.vue';
import FormField from '../form/FormField.vue';
import TextInput from '../form/TextInput.vue';
import FormSelect from '../form/FormSelect.vue';
import FormToggle from '../form/FormToggle.vue';

const config = ref<api.GhostConfig | null>(null);
const form = ref({ enabled: false, api_url: '', admin_api_key: '', content_api_key: '', auto_publish: false, publish_status: 'draft' as 'published' | 'draft' });
const loading = ref(false);
const saving = ref(false);
const testing = ref(false);
const testResult = ref<api.GhostTestResult | null>(null);
const error = ref(''); const notice = ref('');

const statusOptions = [
  { value: 'draft', label: '草稿 (draft)' },
  { value: 'published', label: '直接发布 (published)' },
];

async function load() {
  loading.value = true; error.value = '';
  try {
    const c = await api.getGhostConfig();
    config.value = c;
    form.value = {
      enabled: c.enabled, api_url: c.api_url || '', admin_api_key: '', content_api_key: '',
      auto_publish: c.auto_publish, publish_status: c.publish_status,
    };
  } catch (e: any) { error.value = e?.message || '加载失败'; }
  finally { loading.value = false; }
}

async function save() {
  saving.value = true; error.value = ''; notice.value = '';
  try {
    const body: api.GhostConfigPatch = {
      enabled: form.value.enabled, api_url: form.value.api_url.trim(),
      auto_publish: form.value.auto_publish, publish_status: form.value.publish_status,
    };
    if (form.value.admin_api_key) body.admin_api_key = form.value.admin_api_key;
    if (form.value.content_api_key) body.content_api_key = form.value.content_api_key;
    await api.saveGhostConfig(body);
    notice.value = 'Ghost 配置已保存';
    await load();
  } catch (e: any) { error.value = e?.message || '保存失败'; }
  finally { saving.value = false; }
}

async function test() {
  testing.value = true; testResult.value = null; error.value = '';
  try {
    const body: api.GhostTestPayload = {};
    if (form.value.api_url) body.api_url = form.value.api_url;
    if (form.value.admin_api_key) body.admin_api_key = form.value.admin_api_key;
    testResult.value = await api.testGhostConfig(body);
  } catch (e: any) { testResult.value = { success: false, message: e?.message || '测试失败' }; }
  finally { testing.value = false; }
}

onMounted(load);
</script>

<template>
  <div class="ghost-section">
    <div class="status-row" v-if="config">
      <StatusDot :status="config.enabled ? 'online' : 'waiting'" :label="config.enabled ? '自动发布已启用' : '未启用'" />
      <span v-if="config.has_admin_key" class="key-badge">Admin Key 已配置</span>
      <span v-else class="key-badge key-missing">Admin Key 未配置</span>
    </div>
    <p v-if="error" class="msg-error">{{ error }}</p>
    <p v-if="notice" class="msg-ok">{{ notice }}</p>

    <GlassPanel padding="md" class="form-panel">
      <FormToggle v-model="form.enabled" label="启用 Ghost 自动发布" />
      <FormField label="博客地址 (api_url)" hint="Ghost 站点地址，需公网可访问，如 https://blog.example.com">
        <TextInput v-model="form.api_url" placeholder="https://blog.example.com" mono />
      </FormField>
      <FormField label="Admin API Key" hint="用于发布文章。留空表示不修改现有密钥">
        <TextInput v-model="form.admin_api_key" password placeholder="xxxx:yyyy..." mono />
      </FormField>
      <FormField label="Content API Key" hint="可选，用于读取内容（不用于发布）">
        <TextInput v-model="form.content_api_key" password placeholder="留空表示不修改" mono />
      </FormField>
      <div class="form-row">
        <FormField label="发布状态">
          <FormSelect v-model="form.publish_status" :options="statusOptions" />
        </FormField>
        <FormField label=" "><FormToggle v-model="form.auto_publish" label="讨论完成自动发布" /></FormField>
      </div>
      <div class="actions">
        <GlowButton variant="primary" size="sm" :loading="saving" @click="save">保存配置</GlowButton>
        <GlowButton variant="secondary" size="sm" :loading="testing" @click="test">测试连接</GlowButton>
        <span v-if="testResult" class="test-result" :class="testResult.success ? 'test-ok' : 'test-fail'">
          {{ testResult.success ? '✓ ' : '✗ ' }}{{ testResult.message }}
        </span>
      </div>
    </GlassPanel>
  </div>
</template>

<style scoped>
.ghost-section { display: flex; flex-direction: column; gap: var(--space-4); }
.status-row { display: flex; align-items: center; gap: var(--space-3); }
.key-badge { font-size: 10px; padding: 1px 8px; border-radius: 4px; background: rgba(0,230,180,0.1); color: var(--holo-teal); border: 1px solid rgba(0,230,180,0.3); }
.key-missing { background: rgba(255,82,82,0.08); color: var(--holo-red); border-color: rgba(255,82,82,0.3); }
.msg-error { font-size: var(--fs-sm); color: var(--holo-red); margin: 0; }
.msg-ok { font-size: var(--fs-sm); color: var(--holo-teal); margin: 0; }
.form-panel { display: flex; flex-direction: column; gap: var(--space-4); }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-3); align-items: end; }
.actions { display: flex; align-items: center; gap: var(--space-3); }
.test-result { font-size: var(--fs-xs); }
.test-ok { color: var(--holo-teal); }
.test-fail { color: var(--holo-red); }
</style>
