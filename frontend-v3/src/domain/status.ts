import type { Activity, NpcStatus, Room, RoomRuntime, RoomStatus, Task } from './types';
const completed = new Set(['DONE','COMPLETED','SUCCEEDED']);
const failed = new Set(['FAILED','CANCELLED']);
export function npcStatusFromActivity(activity?: Activity|null): NpcStatus {
  if (!activity) return 'idle';
  if (activity.status.toLowerCase() === 'failed') return 'failed';
  const retry = Number(activity.metadata.retry_attempt ?? 0);
  if (retry > 0 && activity.status.toLowerCase() === 'started') return 'retrying';
  const type = activity.type.toLowerCase();
  if (type === 'llm_infer' || type === 'reasoning') return 'thinking';
  if (type === 'chat_reply') return 'speaking';
  if (type === 'message_received' || type === 'task_received') return 'reading';
  if (type === 'tool_call' || type === 'compact') return 'working';
  return activity.status.toLowerCase() === 'succeeded' ? 'completed' : 'idle';
}
export function activityLabel(status:NpcStatus, agentName='大师'): string {
  return ({ idle:'静候差遣',reading:`${agentName}正在阅卷`,thinking:`${agentName}正在思考`,speaking:`${agentName}正在发言`,working:`${agentName}正在调用工具`,retrying:`${agentName}稍候重试`,completed:'本轮已完成',failed:'执行遇阻' })[status];
}
export function deriveRoomRuntime(room:Room, tasks:Task[], activities:Activity[], agentName=(id:number|null)=>id ? `大师 ${id}` : '大师'):RoomRuntime {
  const roomTasks = tasks.filter(t=>t.roomId===room.id);
  const roomActivities = activities.filter(a=>a.roomId===room.id || room.agentIds.includes(a.agentId)).sort((a,b)=>Date.parse(b.startedAt||'')-Date.parse(a.startedAt||''));
  const latest = roomActivities[0];
  const totalTasks=roomTasks.length;
  const completedTasks=roomTasks.filter(t=>completed.has(t.status.toUpperCase())).length;
  const anyFailed=roomTasks.some(t=>failed.has(t.status.toUpperCase())) || latest?.status.toLowerCase()==='failed';
  const active=room.needScheduling || room.state.toLowerCase()==='scheduling' || latest?.status.toLowerCase()==='started';
  const allDone=totalTasks>0 && completedTasks===totalTasks;
  let status:RoomStatus='waiting';
  if(anyFailed) status='failed'; else if(allDone) status='completed'; else if(active) status=latest?.type.toLowerCase()==='chat_reply' && latest.status.toLowerCase()==='succeeded' ? 'synthesizing':'discussing';
  const npc=npcStatusFromActivity(latest);
  const taskProgress=totalTasks ? Math.round(completedTasks/totalTasks*100) : 0;
  const progress=status==='completed'?100:status==='failed'?taskProgress:active?Math.max(15,Math.min(90,taskProgress || (roomActivities.length ? 35 : 15))):0;
  return { roomId:room.id,status,progress,currentAgentId:room.currentTurnAgentId ?? latest?.agentId ?? null,currentNpcStatus:npc,activityLabel:activityLabel(npc,agentName(room.currentTurnAgentId ?? latest?.agentId ?? null)),completedTasks,totalTasks,lastActivityAt:latest?.startedAt ?? null,error:anyFailed?(latest?.detail||'房间任务执行失败'):undefined };
}
export function calculateRunProgress(runtimes:RoomRuntime[], phase?:string):number {
  if(!runtimes.length) return phase==='completed'?100:0;
  const roomPart=runtimes.reduce((n,r)=>n+r.progress,0)/runtimes.length;
  const phaseBase:Record<string,number>={queued:2,planning:5,dispatching:10,discussing:10,synthesizing:65,publishing:90,completed:100,failed:100,partial_failed:100,cancelled:100};
  const p=(phase||'discussing').toLowerCase();
  if(p==='completed'||p==='failed'||p==='partial_failed'||p==='cancelled') return 100;
  if(p==='synthesizing') return Math.max(65,Math.min(89,Math.round(65+roomPart*.24)));
  if(p==='publishing') return Math.max(90,Math.min(99,Math.round(90+roomPart*.09)));
  if(p==='discussing') return Math.max(10,Math.min(64,Math.round(10+roomPart*.54)));
  return phaseBase[p] ?? Math.round(roomPart*.64);
}
