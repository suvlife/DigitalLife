<script setup lang="ts">
import { ref, onMounted } from 'vue';
import * as api from '../../api/client';
import GlassPanel from '../GlassPanel.vue';
import HoloCard from '../HoloCard.vue';
import GlowButton from '../GlowButton.vue';
import FormField from '../form/FormField.vue';
import TextInput from '../form/TextInput.vue';
import FormModal from '../form/FormModal.vue';

const templates = ref<api.RoleTemplate[]>([]);
const loading = ref(false);
const saving = ref(false);
const error = ref(''); const notice = ref('');
const editorOpen = ref(false);
const editing = ref<api.RoleTemplate | null>(null);
const form = ref({ name: '', soul: '' });
const deleteTarget = ref<api.RoleTemplate | null>(null);
const deleting = ref(false);

async function load() {
  loading.value = true; error.value = '';
  try { templates.value = await api.getRoleTemplates(); }
  catch (e: any) { error.value = e?.message || '加载失败'; }
  finally { loading.value = false; }
}

function openCreate() { editing.value = null; form.value = { name: '', soul: '' }; editorOpen.value = true; }
function openEdit(t: api.RoleTemplate) { editing.value = t; form.value = { name: t.name, soul: t.soul }; editorOpen.value = true; }

async function save() {
  if (!form.value.name.trim()) { error.value = '名称必填'; return; }
  saving.value = true; error.value = ''; notice.value = '';
  try {
    if (editing.value) { await api.modifyRoleTemplate(editing.value.id, form.value); notice.value = '已保存'; }
    else { await api.createRoleTemplate(form.value); notice.value = '已创建角色模板'; }
    editorOpen.value = false;
    await load();
  } catch (e: any) { error.value = e?.message || '保存失败'; }
  finally { saving.value = false; }
}

async function confirmDelete() {
  if (!deleteTarget.value) return;
  deleting.value = true; error.value = '';
  try { await api.deleteRoleTemplate(deleteTarget.value.id); notice.value = '已删除'; deleteTarget.value = null; await load(); }
  catch (e: any) { error.value = e?.message || '删除失败'; }
  finally { deleting.value = false; }
}

onMounted(load);
</script>

<template>
  <div class="role-section">
    <div class="section-actions">
      <GlowButton variant="primary" size="sm" @click="openCreate">+ 新建角色模板</GlowButton>
      <GlowButton variant="secondary" size="sm" :loading="loading" @click="load">刷新</GlowButton>
    </div>
    <p v-if="error" class="msg-error">{{ error }}</p>
    <p v-if="notice" class="msg-ok">{{ notice }}</p>

    <div class="tpl-list">
      <HoloCard v-for="t in templates" :key="t.id" status="idle">
        <template #header><div class="svc-header"><span class="svc-name">{{ t.name }}</span></div></template>
        <p class="tpl-soul">{{ t.soul || '（无系统提示词）' }}</p>
        <template #footer>
          <div class="svc-actions">
            <GlowButton variant="secondary" size="sm" @click="openEdit(t)">编辑</GlowButton>
            <GlowButton variant="danger" size="sm" @click="deleteTarget = t">删除</GlowButton>
          </div>
        </template>
      </HoloCard>
      <GlassPanel v-if="!templates.length && !loading" padding="md"><p class="empty-text">暂无角色模板</p></GlassPanel>
    </div>

    <FormModal :open="editorOpen" :title="editing ? '编辑角色模板' : '新建角色模板'" confirm-text="保存"
      :loading="saving" width="640px" @close="editorOpen = false" @confirm="save">
      <FormField label="模板名称" required>
        <TextInput v-model="form.name" placeholder="如：价值分析师" />
      </FormField>
      <FormField label="系统提示词 (soul)" hint="定义该角色的专业能力、人格风格与行为规范">
        <textarea v-model="form.soul" class="soul-input" rows="10" placeholder="你是一位资深的..."></textarea>
      </FormField>
    </FormModal>

    <FormModal :open="deleteTarget !== null" title="删除角色模板" confirm-text="删除" confirm-danger
      :loading="deleting" @close="deleteTarget = null" @confirm="confirmDelete">
      <p class="confirm-text">确定删除角色模板 <strong>{{ deleteTarget?.name }}</strong> 吗？</p>
    </FormModal>
  </div>
</template>

<style scoped>
.role-section { display: flex; flex-direction: column; gap: var(--space-4); }
.section-actions { display: flex; gap: var(--space-3); }
.msg-error { font-size: var(--fs-sm); color: var(--holo-red); margin: 0; }
.msg-ok { font-size: var(--fs-sm); color: var(--holo-teal); margin: 0; }
.tpl-list { display: flex; flex-direction: column; gap: var(--space-3); }
.svc-header { display: flex; align-items: center; gap: 8px; }
.svc-name { font-size: var(--fs-base); font-weight: 500; color: var(--text-primary); }
.tpl-soul { font-size: var(--fs-xs); color: var(--text-muted); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.svc-actions { display: flex; gap: var(--space-2); }
.empty-text { color: var(--text-muted); text-align: center; }
.soul-input { width: 100%; background: rgba(0,0,0,0.25); border: 1px solid var(--glass-border); border-radius: var(--glass-radius-sm); padding: 8px 12px; color: var(--text-primary); font-family: var(--font-body); font-size: var(--fs-sm); resize: vertical; box-sizing: border-box; line-height: var(--lh-normal); }
.soul-input:focus { border-color: var(--glass-border-active); box-shadow: var(--glow-cyan); outline: none; }
.confirm-text { font-size: var(--fs-sm); color: var(--text-secondary); }
</style>
