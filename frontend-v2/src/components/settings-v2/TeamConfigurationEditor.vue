<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import type { DeptTreeNode, LlmServiceInfo, RoleTemplate, TeamMemberDetail, TeamRoomDetail } from '../../api/client';
import DeptNodeEditor from './DeptNodeEditor.vue';

const props = defineProps<{ members: TeamMemberDetail[]; rooms: TeamRoomDetail[]; roles: RoleTemplate[]; llmServices: LlmServiceInfo[]; teamLlm: string; deptTree: DeptTreeNode|null; busy?: boolean }>();
const emit = defineEmits<{ saveMembers:[TeamMemberDetail[]]; clearAgent:[TeamMemberDetail]; saveRoom:[TeamRoomDetail]; deleteRoom:[TeamRoomDetail]; saveDept:[DeptTreeNode]; saveTeamLlm:[string] }>();
const memberDrafts=ref<TeamMemberDetail[]>([]); const roomDrafts=ref<TeamRoomDetail[]>([]); const deptDraft=ref<DeptTreeNode|null>(null); const selectedLlm=ref('');
const drivers=['native','claude_code','codex'];
const clone=<T,>(value:T):T=>JSON.parse(JSON.stringify(value));
watch(()=>props.members,v=>memberDrafts.value=clone(v),{immediate:true,deep:true});
watch(()=>props.rooms,v=>roomDrafts.value=clone(v),{immediate:true,deep:true});
watch(()=>props.deptTree,v=>deptDraft.value=v?clone(v):null,{immediate:true,deep:true});
watch(()=>props.teamLlm,v=>selectedLlm.value=v||'',{immediate:true});
function addMember(){memberDrafts.value.push({id:0,name:'',i18n:{},employee_number:0,role_template_id:props.roles[0]?.id||0,model:'',driver:'native'});}
function addRoom(){roomDrafts.value.push({id:0,name:'',i18n:{},type:'group',initial_topic:'',max_rounds:10,agent_ids:memberDrafts.value.filter(x=>x.id>0).map(x=>x.id),agents:[],biz_id:null,tags:[]});}
function toggleRoomMember(room:TeamRoomDetail,id:number,checked:boolean){room.agent_ids=checked?[...new Set([...room.agent_ids,id])]:room.agent_ids.filter(x=>x!==id);}
function newRoot(){deptDraft.value={name:'总院',responsibility:'统筹全院协作',manager_id:null,agent_ids:memberDrafts.value.map(x=>x.id).filter(Boolean),children:[]};}
const enabledLlms=computed(()=>props.llmServices.filter(x=>x.enable));
</script>
<template>
  <div class="team-config-editor">
    <section class="settings-subsection"><div class="subsection-head"><div><h3>成员与模型</h3><p>新增、编辑或移除大师，并绑定角色模板、模型和运行 Driver。</p></div><button class="gold-button" type="button" @click="addMember">新增成员</button></div>
      <div v-if="!memberDrafts.length" class="empty-state">尚无成员，请先新增成员。</div>
      <article v-for="(member,index) in memberDrafts" :key="member.id || `new-${index}`" class="settings-editor member-editor"><div class="settings-form-grid"><label>姓名<input v-model="member.name" aria-label="成员姓名" /></label><label>角色模板<select v-model="member.role_template_id"><option v-for="role in roles" :key="role.id" :value="role.id">{{ role.name }}</option></select></label><label>模型<input v-model="member.model" placeholder="留空使用团队默认模型" /></label><label>Driver<select v-model="member.driver"><option v-for="driver in drivers" :key="driver" :value="driver">{{ driver }}</option></select></label></div><div class="settings-actions compact"><button v-if="member.id" class="text-button" type="button" @click="emit('clearAgent',member)">清理该成员数据</button><button class="text-button danger-text" type="button" @click="memberDrafts.splice(index,1)">移除成员</button></div></article>
      <div class="settings-actions"><button class="gold-button" :disabled="busy" type="button" @click="emit('saveMembers',memberDrafts)">保存成员名册</button></div>
    </section>
    <section class="settings-subsection"><div class="subsection-head"><div><h3>团队默认模型</h3><p>成员模型留空时使用此模型服务。</p></div></div><div class="settings-form-grid"><label>默认 LLM<select v-model="selectedLlm"><option value="">跟随系统默认</option><option v-for="service in enabledLlms" :key="service.name" :value="service.name">{{ service.name }} · {{ service.model }}</option></select></label></div><div class="settings-actions"><button class="gold-button" :disabled="busy" @click="emit('saveTeamLlm',selectedLlm)">保存团队模型</button></div></section>
    <section class="settings-subsection"><div class="subsection-head"><div><h3>组织与部门树</h3><p>部门保存后会由服务端同步部门研究室；每个部门至少选择两位成员。</p></div><button v-if="!deptDraft" class="gold-button" type="button" @click="newRoot">建立组织树</button></div><DeptNodeEditor v-if="deptDraft" root :node="deptDraft" :members="memberDrafts.filter(x=>x.id>0)" @add-child="deptDraft.children.push({name:'新部门',responsibility:'',manager_id:null,agent_ids:memberDrafts.filter(x=>x.id>0).map(x=>x.id),children:[]})" /><div v-if="deptDraft" class="settings-actions"><button class="gold-button" :disabled="busy" @click="emit('saveDept',deptDraft)">保存组织树</button></div></section>
    <section class="settings-subsection"><div class="subsection-head"><div><h3>研究室与问策房间</h3><p>配置房间成员、初始主题与最大讨论轮次。</p></div><button class="gold-button" type="button" @click="addRoom">新增研究室</button></div>
      <article v-for="(room,index) in roomDrafts" :key="room.id || `new-room-${index}`" class="settings-editor room-editor"><div class="settings-form-grid"><label>房间名称<input v-model="room.name" aria-label="研究室名称" /></label><label>最大轮次<input v-model.number="room.max_rounds" type="number" min="1" /></label><label class="wide">初始主题<textarea v-model="room.initial_topic" rows="3" /></label></div><fieldset class="member-picker"><legend>房间成员</legend><label><input type="checkbox" :checked="room.agent_ids.includes(-1)" @change="toggleRoomMember(room,-1,($event.target as HTMLInputElement).checked)" />操作者（入殿问策）</label><label v-for="member in memberDrafts.filter(x=>x.id>0)" :key="member.id"><input type="checkbox" :checked="room.agent_ids.includes(member.id)" @change="toggleRoomMember(room,member.id,($event.target as HTMLInputElement).checked)" />{{ member.name }}</label></fieldset><div class="settings-actions compact"><button class="gold-button" :disabled="busy" @click="emit('saveRoom',room)">保存研究室</button><button class="text-button danger-text" @click="room.id ? emit('deleteRoom',room) : roomDrafts.splice(index,1)">删除</button></div></article>
    </section>
  </div>
</template>
