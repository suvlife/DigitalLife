<script setup lang="ts">
import { computed,onMounted,ref,watch,nextTick } from 'vue';import { useRoute } from 'vue-router';
import DialogueTimeline from '../components/DialogueTimeline.vue';import TaskSidebar from '../components/TaskSidebar.vue';import NpcAvatar from '../components/NpcAvatar.vue';import ProgressScroll from '../components/ProgressScroll.vue';import SpeakerTimeline from '../components/SpeakerTimeline.vue';import FileUploadButton from '../components/FileUploadButton.vue';import { world } from '../store/world';import { deriveRoomRuntime } from '../domain/status';
const route=useRoute();const teamId=computed(()=>Number(route.params.teamId)),roomId=computed(()=>Number(route.params.roomId));const isNewSession=computed(()=>route.query.new==='1');const room=computed(()=>world.state.rooms.find(r=>r.id===roomId.value));const members=computed(()=>world.state.agents.filter(a=>room.value?.agentIds.includes(a.id)));const runtime=computed(()=>{
  // 优先使用 native run 的 roomRuns；不存在时用 fallback 推导
  const native=world.state.run?.roomRuns[roomId.value];
  if(native) return native;
  // fallback：基于 tasks 和 activities 推导进度
  if(room.value){
    return deriveRoomRuntime(room.value,tasks.value,activities.value,(id:number|null)=>members.value.find(a=>a.id===id)?.name||'大师');
  }
  return undefined;
});const messages=computed(()=>world.state.messages[roomId.value]||[]);const tasks=computed(()=>world.state.tasks.filter(t=>t.roomId===roomId.value));const activities=computed(()=>world.state.activities.filter(a=>a.roomId===roomId.value||room.value?.agentIds.includes(a.agentId)));const text=ref(''),immediate=ref(false),sending=ref(false),error=ref('');
const isRootRoom=computed(()=>world.state.run?.rootRoomId===roomId.value);
const runFinished=computed(()=>['completed','partial_failed','failed','cancelled'].includes(String(world.state.run?.phase)));
const roomState=computed(()=>room.value?.state||'idle');
const isDiscussing=computed(()=>runtime.value?.status==='discussing'||roomState.value==='scheduling');
const isIdle=computed(()=>runtime.value?.status==='completed'||runtime.value?.status==='waiting'||roomState.value==='idle');
const speakersWhoSpoke=computed(()=>{const ids=new Set(messages.value.filter(m=>m.senderId>0).map(m=>m.senderId));return members.value.filter(a=>a.id>0).map(a=>({agent:a,spoke:ids.has(a.id)}));});
const conclusionSubmitted=computed(()=>messages.value.some(m=>m.content&&m.content.includes('submit_conclusion'))||runtime.value?.status==='completed');
function startNewTopic(){text.value='';nextTick(()=>{const el=document.getElementById('message') as HTMLTextAreaElement|null;el?.focus();el?.scrollIntoView({behavior:'smooth',block:'center'});});}
async function load(){/* 先加载房间消息，再加载团队（避免 loadTeam 重置 messages） */await world.loadRoomMessages(roomId.value).catch(()=>{});if(!world.state.team||world.state.team.id!==teamId.value){await world.loadTeam(teamId.value);}await world.loadRoomMessages(roomId.value).catch(()=>{});/* 新会话模式：清空输入并聚焦 */if(isNewSession.value){text.value='';await nextTick();const el=document.getElementById('message') as HTMLTextAreaElement|null;el?.focus();el?.scrollIntoView({behavior:'smooth',block:'center'});}}
async function send(){if(!text.value.trim()||sending.value)return;sending.value=true;error.value='';try{await world.submitMessage(roomId.value,text.value.trim(),immediate.value);text.value='';immediate.value=false;}catch(e){error.value=e instanceof Error?e.message:'传讯失败';}finally{sending.value=false;}}
async function jumpToMessage(key:string){await nextTick();document.getElementById(key)?.scrollIntoView({behavior:'smooth',block:'center'});document.getElementById(key)?.classList.add('timeline-focus');window.setTimeout(()=>document.getElementById(key)?.classList.remove('timeline-focus'),1800);}
async function uploaded(){await world.loadRoomMessages(roomId.value);}
onMounted(load);watch([teamId,roomId],load);
</script>
<template><div class="room-page"><header class="room-header"><RouterLink :to="{name:'team',params:{teamId}}">← 返回院落</RouterLink><div><small>研究室内景</small><h1>{{room?.name||'正在入室'}}</h1><p>{{runtime?.activityLabel||'静候差遣'}}</p></div><ProgressScroll :value="runtime?.progress||0" label="本室进度"/></header>
<section class="room-members panel" aria-label="本室参与大师"><header><b>本室诸贤</b><span>共 {{members.length}} 位大师 · {{speakersWhoSpoke.filter(s=>s.spoke).length}}/{{speakersWhoSpoke.length}} 已发言</span></header><div class="seating"><NpcAvatar v-for="entry in speakersWhoSpoke" :key="entry.agent.id" :agent="entry.agent" :active="runtime?.currentAgentId===entry.agent.id" :status="runtime?.currentAgentId===entry.agent.id?runtime.currentNpcStatus:(entry.spoke?'idle':'idle')"/></div><div class="room-status-bar" :class="{'status-discussing':isDiscussing,'status-idle':isIdle,'status-finished':conclusionSubmitted}"><span v-if="isDiscussing&&runtime?.currentAgentId">{{members.find(a=>a.id===runtime?.currentAgentId)?.name}} 正在执言 · 讨论进行中</span><span v-else-if="conclusionSubmitted">本室讨论已结束，已提交结论</span><span v-else-if="isIdle">本室静候，可发起新的话题</span><span v-else>等待调度</span></div></section>
<SpeakerTimeline :messages="messages" :agents="members" @jump="jumpToMessage"/>
<div class="room-layout"><section class="discussion-panel panel"><header><h2>堂内对话</h2><span v-if="runtime?.currentAgentId">{{members.find(a=>a.id===runtime?.currentAgentId)?.name}} 当前执言</span></header><div v-if="isNewSession&&!isDiscussing" class="new-session-banner"><span>新讨论会话已就绪，请在下方输入您的问题</span></div><DialogueTimeline :messages="messages" :agents="members" :team-id="teamId" :active-agent-id="runtime?.currentAgentId"/><form class="message-composer" @submit.prevent="send"><div v-if="isRootRoom&&runFinished" class="new-topic-banner"><span>本话题已结束。输入新的问题即可发起新一轮书院讨论。</span><button type="button" class="new-topic-btn" @click="startNewTopic">发起新话题</button></div><label for="message">向本室传讯</label><textarea id="message" v-model="text" rows="4" :placeholder="isNewSession?'输入新的问题，发起一轮全新讨论……':'输入问题或补充说明，支持 Markdown……'" @keydown.ctrl.enter="send"></textarea><p v-if="error" class="error-text">{{error}}</p><div><FileUploadButton :room-id="roomId" :disabled="sending" @uploaded="uploaded"/><label class="check"><input v-model="immediate" type="checkbox"/> 趁本轮议论未歇，立即递入补充</label><small>Ctrl + Enter 发送</small><button :disabled="sending||!text.trim()">{{sending?'传讯中':'飞鸽传书'}}</button></div></form></section><TaskSidebar :tasks="tasks" :activities="activities" :agents="members" :initial-topic="room?.initialTopic" :question="world.state.run?.question" :room-status="runtime?.status"/></div></div>
</template>
<style scoped>
.new-topic-banner{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px;padding:10px 14px;border:1px solid rgba(212,175,55,.45);border-radius:10px;background:rgba(212,175,55,.10);color:#e8dcc0;font-size:14px}
.new-topic-btn{flex:none;padding:6px 16px;border:1px solid rgba(212,175,55,.6);border-radius:8px;background:rgba(212,175,55,.2);color:#f4e6c1;cursor:pointer;font-weight:600}
.new-topic-btn:hover{background:rgba(212,175,55,.35)}
.room-status-bar{margin-top:10px;padding:8px 14px;border-radius:8px;font-size:13px;text-align:center;transition:all .3s}
.room-status-bar.status-discussing{background:rgba(103,189,130,.12);border:1px solid rgba(103,189,130,.35);color:#9fd9ad}
.room-status-bar.status-idle{background:rgba(180,170,150,.08);border:1px solid rgba(180,170,150,.2);color:#b0a896}
.room-status-bar.status-finished{background:rgba(212,175,55,.12);border:1px solid rgba(212,175,55,.35);color:#e8dcc0}
.new-session-banner{padding:10px 14px;margin-bottom:10px;border:1px solid rgba(109,186,138,.45);border-radius:10px;background:rgba(109,186,138,.10);color:#9fd9ad;font-size:14px;text-align:center}
</style>
