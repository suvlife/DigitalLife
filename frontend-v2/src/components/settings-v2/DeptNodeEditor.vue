<script setup lang="ts">
import type { DeptTreeNode, TeamMemberDetail } from '../../api/client';
const props = defineProps<{ node: DeptTreeNode; members: TeamMemberDetail[]; root?: boolean }>();
const emit = defineEmits<{ remove: []; addChild: [] }>();
function toggleAgent(id: number, checked: boolean) {
  props.node.agent_ids = checked ? [...new Set([...props.node.agent_ids, id])] : props.node.agent_ids.filter(value => value !== id);
  if (props.node.manager_id && !props.node.agent_ids.includes(props.node.manager_id)) props.node.manager_id = null;
}
</script>
<template>
  <article class="dept-node-editor">
    <div class="subsection-head"><h4>{{ root ? '总院组织' : '下属部门' }}</h4><button v-if="!root" class="text-button danger-text" type="button" @click="emit('remove')">移除部门</button></div>
    <div class="settings-form-grid compact-grid">
      <label>部门名称<input v-model="node.name" aria-label="部门名称" /></label>
      <label>负责人<select v-model="node.manager_id"><option :value="null">请选择</option><option v-for="member in members.filter(item => node.agent_ids.includes(item.id))" :key="member.id" :value="member.id">{{ member.name }}</option></select></label>
      <label class="wide">职责<input v-model="node.responsibility" /></label>
    </div>
    <fieldset class="member-picker"><legend>部门成员</legend><label v-for="member in members" :key="member.id"><input type="checkbox" :checked="node.agent_ids.includes(member.id)" @change="toggleAgent(member.id, ($event.target as HTMLInputElement).checked)" />{{ member.name }}</label></fieldset>
    <div class="settings-actions compact"><button class="quiet-button" type="button" @click="emit('addChild')">新增下属部门</button></div>
    <div v-if="node.children.length" class="dept-children"><DeptNodeEditor v-for="(child,index) in node.children" :key="child.id ?? `${child.name}-${index}`" :node="child" :members="members" @remove="node.children.splice(index,1)" @add-child="child.children.push({ name:'新部门', responsibility:'', manager_id:null, agent_ids:[], children:[] })" /></div>
  </article>
</template>
