import { computed, reactive, readonly } from 'vue';
import * as api from '../api/client';
import { calculateRunProgress, deriveRoomRuntime } from '../domain/status';
import type { NormalizedEvent, RunSnapshot, WorldSnapshot } from '../domain/types';
import { EventsSocket } from '../realtime/socket';
const initial:WorldSnapshot={team:null,teams:[],rooms:[],agents:[],messages:{},activities:[],tasks:[],run:null,loading:false,error:'',connection:'connecting',lastUpdated:null};
const state=reactive<WorldSnapshot>({...initial,messages:{}});let socket:EventsSocket|null=null;let loadedTeam:number|null=null;let loadGeneration=0;
const agentName=(id:number|null)=>state.agents.find(a=>a.id===id)?.name || (id ? `大师 ${id}`:'大师');
function fallbackRun(teamId:number,runId='live'):RunSnapshot{
 const roomRuns=Object.fromEntries(state.rooms.filter(r=>r.type==='group').map(r=>[r.id,deriveRoomRuntime(r,state.tasks,state.activities,agentName)]));const rr=Object.values(roomRuns);const latestUser=Object.values(state.messages).flat().filter(m=>m.senderId<0).sort((a,b)=>Date.parse(b.sentAt)-Date.parse(a.sentAt))[0];const root=(()=>{const groups=state.rooms.filter(r=>r.type==='group');const tagged=groups.find(r=>r.tags.includes('task')||r.tags.includes('root'));if(tagged)return tagged;const operatorRooms=groups.filter(r=>r.operatorEnabled);return [...(operatorRooms.length?operatorRooms:groups)].sort((a,b)=>b.agentIds.length-a.agentIds.length)[0];})();const final=(root?state.messages[root.id]||[]:[]).filter(m=>m.senderId>0).at(-1)?.content||'';const completed=rr.filter(r=>r.status==='completed').map(r=>r.roomId);const active=rr.filter(r=>['discussing','synthesizing'].includes(r.status));const phase=rr.length&&completed.length===rr.length?'synthesizing':active.length?'discussing':'queued';return{id:runId,teamId,rootRoomId:state.team?.questionRoomId??null,phase,progress:calculateRunProgress(rr,phase),question:latestUser?.content||'',finalAnswer:final,roomRuns,activeAgentIds:[...new Set(active.map(r=>r.currentAgentId).filter((x):x is number=>Boolean(x)))],completedRoomIds:completed,publication:{status:'idle'},source:'fallback'};
}
export function applyEvent(e:NormalizedEvent){if(loadedTeam&&'teamId'in e&&e.teamId!==loadedTeam)return;
 if(e.type==='message'){const list=state.messages[e.roomId]||(state.messages[e.roomId]=[]);if(!list.some(m=>m.id!=null&&m.id===e.message.id))list.push(e.message);}
 else if(e.type==='room_status'){const r=state.rooms.find(r=>r.id===e.roomId);if(r){r.state=e.state;r.needScheduling=e.needScheduling;r.currentTurnAgentId=e.currentAgentId;}}
 else if(e.type==='agent_status'){const a=state.agents.find(a=>a.id===e.agentId);if(a)a.status=e.status;}
 else if(e.type==='agent_activity'){const i=state.activities.findIndex(a=>a.id===e.activity.id);if(i>=0)state.activities[i]=e.activity;else state.activities.unshift(e.activity);}
 else if(e.type==='task_changed'){const i=state.tasks.findIndex(t=>t.id===e.task.id);if(i>=0)state.tasks[i]=e.task;else state.tasks.push(e.task);}
 else if(e.type==='run_changed'){const current=state.run||fallbackRun(e.teamId,e.run.id);state.run={...current,...e.run,source:'native'} as RunSnapshot;}
 else if(e.type==='room_run_changed'&&state.run?.id===e.runId){state.run.roomRuns[e.roomRuntime.roomId]=e.roomRuntime;if(e.roomRuntime.status==='completed'&&!state.run.completedRoomIds.includes(e.roomRuntime.roomId))state.run.completedRoomIds=[...state.run.completedRoomIds,e.roomRuntime.roomId];}
 else if(e.type==='publication_changed'&&state.run?.id===e.runId)state.run.publication=e.publication;
 else if(e.type==='reconcile'){void reconcile();return;}
 if(!state.run||state.run.source==='fallback')state.run=fallbackRun(loadedTeam||('teamId'in e?e.teamId:0),state.run?.id||'live');state.lastUpdated=Date.now();}
export async function loadTeams(){state.loading=true;state.error='';try{state.teams=await api.getTeams();}catch(e){state.error=e instanceof Error?e.message:'无法载入团队';}finally{state.loading=false;}connect();}
export async function loadTeam(teamId:number,runId?:string){
 const generation=++loadGeneration;loadedTeam=teamId;state.loading=true;state.error='';
 try{
  if(runId){
   // Archive pages are deliberately isolated from mutable live team data.  Only
   // the immutable run snapshot and its bounded timeline supply execution data.
   const [team,native,timeline]=await Promise.all([
    api.getTeam(teamId),api.getRun(runId),api.getRunTimeline(runId),
   ]);
   if(generation!==loadGeneration||loadedTeam!==teamId)return;
   if(!native||native.teamId!==teamId)throw new Error('卷宗不存在或不属于当前团队');
   const runRoomIds=new Set(Object.keys(native.roomRuns).map(Number));
   if(native.rootRoomId!=null)runRoomIds.add(native.rootRoomId);
   const historicalAgentIds=[...new Set(timeline.map(message=>message.senderId).filter(id=>id>0))];
   const historicalAgents=historicalAgentIds.map(id=>({id,teamId,name:timeline.find(message=>message.senderId===id)?.senderName||`大师 ${id}`,i18n:{},status:'idle'}));
   const historicalRooms=[...runRoomIds].map(roomId=>({
    id:roomId,teamId,name:`研究室 #${roomId}`,i18n:{},type:'group' as const,state:String(native.roomRuns[roomId]?.status||'completed').toUpperCase(),needScheduling:false,currentTurnAgentId:native.roomRuns[roomId]?.currentAgentId??null,
    agentIds:[...new Set(timeline.filter(message=>message.roomId===roomId&&message.senderId>0).map(message=>message.senderId))],tags:[] as string[],operatorEnabled:timeline.some(message=>message.roomId===roomId&&message.senderId<0),initialTopic:null,
   }));
   state.team=team;
   state.rooms=historicalRooms;
   state.agents=historicalAgents;
   state.activities=[];
   state.tasks=[];
   state.messages=Object.fromEntries([...runRoomIds].map(roomId=>[roomId,timeline.filter(message=>message.roomId===roomId)]));
   state.run={...native,source:'native'};
   state.lastUpdated=Date.now();
   disconnect();
   return;
  }
  const [team,rooms,agents,activities,tasks,native]=await Promise.all([
   api.getTeam(teamId),api.getRooms(teamId),api.getAgents(teamId),api.getActivities(teamId).catch(()=>[]),api.getTasks(teamId).catch(()=>[]),api.getCurrentRun(teamId),
  ]);
  if(generation!==loadGeneration||loadedTeam!==teamId)return;
  const groupRooms=rooms.filter(r=>r.type==='group');
  const loaded=await Promise.all(groupRooms.map(async r=>[r.id,await api.getMessages(r.id).catch(()=>[])] as const));
  if(generation!==loadGeneration||loadedTeam!==teamId)return;
  state.team=team;state.rooms=rooms;state.agents=agents;state.activities=activities;state.tasks=tasks;state.messages=Object.fromEntries(loaded);
  state.run=native?{...native,source:'native'}:fallbackRun(teamId,'live');state.lastUpdated=Date.now();connect();
 }catch(e){if(generation===loadGeneration)state.error=e instanceof Error?e.message:'院落载入失败';}
 finally{if(generation===loadGeneration)state.loading=false;}
}
export async function loadRoomMessages(roomId:number){state.messages[roomId]=await api.getMessages(roomId);}
export async function submitMessage(roomId:number,content:string,immediate=false){await api.sendMessage(roomId,content,immediate);/* 不主动 reload，让 WebSocket 事件驱动更新；兜底延迟 reload 防止 WS 丢失 */setTimeout(()=>{if(!state.messages[roomId]||state.messages[roomId].length===0)loadRoomMessages(roomId);},2000);if(state.run?.source==='fallback')state.run=fallbackRun(loadedTeam||0,state.run.id);}
export async function startNewSession(roomId:number){/* 调用后端归档当前讨论并重置房间状态 */await api.newSession(roomId);/* 清空前端消息显示，展示空白新会话 */state.messages[roomId]=[];/* 重置 Run 为 fallback，让新消息创建全新 Run */if(loadedTeam)state.run=fallbackRun(loadedTeam,'live');state.activities=[];state.tasks=[];state.lastUpdated=Date.now();}
let reconciling=false;async function reconcile(){if(!loadedTeam||reconciling)return;reconciling=true;try{const teamId=loadedTeam;const [rooms,agents,activities,tasks,native]=await Promise.all([api.getRooms(teamId),api.getAgents(teamId),api.getActivities(teamId).catch(()=>[]),api.getTasks(teamId).catch(()=>[]),api.getCurrentRun(teamId)]);if(loadedTeam!==teamId)return;state.rooms=rooms;state.agents=agents;state.activities=activities;state.tasks=tasks;const loaded=await Promise.all(rooms.filter(r=>r.type==='group').map(async r=>[r.id,await api.getMessages(r.id).catch(()=>state.messages[r.id]||[])] as const));state.messages=Object.fromEntries(loaded);state.run=native?{...native,source:'native'}:fallbackRun(teamId,state.run?.id||'live');state.lastUpdated=Date.now();}finally{reconciling=false;}}
let connecting=false;async function connect(){if(socket||connecting)return;connecting=true;try{if(socket)return;socket=new EventsSocket(applyEvent,(s,recovered)=>{state.connection=s==='auth_required'?'closed':s;if(s==='open'&&recovered)void reconcile();});socket.connect();}finally{connecting=false;}}
export function disconnect(){socket?.close();socket=null;state.connection='closed';}
export function reconnect(){disconnect();void connect();}
export function retryAfterAuthentication(){if(loadedTeam)return loadTeam(loadedTeam);return loadTeams();}
export const world={state:readonly(state),loadTeams,loadTeam,loadRoomMessages,submitMessage,startNewSession,applyEvent,reconnect,retryAfterAuthentication,activeRooms:computed(()=>Object.values(state.run?.roomRuns||{}).filter(r=>['discussing','synthesizing'].includes(r.status)))};
