export type RoomStatus = 'waiting' | 'discussing' | 'synthesizing' | 'completed' | 'failed' | 'skipped';
export type NpcStatus = 'idle' | 'reading' | 'thinking' | 'speaking' | 'working' | 'retrying' | 'completed' | 'failed';
export type RunPhase = 'queued' | 'planning' | 'dispatching' | 'discussing' | 'synthesizing' | 'publishing' | 'completed' | 'partial_failed' | 'failed' | 'cancelled';
export interface I18n { [category: string]: Record<string, string> }
export interface Team { id: number; name: string; i18n: I18n; enabled: boolean; config: Record<string, unknown>; questionRoomId?:number|null; createdAt?: string; updatedAt?: string }
export interface Agent { id: number; teamId: number; name: string; i18n: I18n; status: string; roleTemplateId?: number | null; model?: string; special?: string | null }
export interface Room { id: number; teamId: number; name: string; i18n: I18n; type: 'group'|'private'; state: string; needScheduling: boolean; currentTurnAgentId: number|null; agentIds: readonly number[]; tags: readonly string[]; operatorEnabled?: boolean; initialTopic?: string|null }
export interface Message { id: number|null; roomId: number; senderId: number; senderName: string; content: string; sentAt: string; seq: number|null; immediate: boolean }
export interface Activity { id: number; agentId: number; teamId: number; roomId: number|null; type: string; status: string; title: string; detail: string; startedAt: string|null; finishedAt: string|null; metadata: Record<string, unknown> }
export interface Task { id:number; teamId:number; roomId:number|null; assigneeId:number; title:string; description:string; status:string; priority:string; result:string; updatedAt:string|null }
export interface RoomRuntime { roomId:number; status:RoomStatus; progress:number; currentAgentId:number|null; currentNpcStatus:NpcStatus; activityLabel:string; completedTasks:number; totalTasks:number; lastActivityAt:string|null; error?:string }
export interface Publication { status:'idle'|'pending'|'publishing'|'published'|'failed'; url?:string; error?:string }
export interface RunSnapshot { id:string; teamId:number; rootRoomId:number|null; phase:RunPhase; progress:number; question:string; finalAnswer:string; roomRuns:Record<number, RoomRuntime>; activeAgentIds:readonly number[]; completedRoomIds:readonly number[]; publication:Publication; reportPath?:string; startedAt?:string; finishedAt?:string; source:'native'|'fallback' }
export interface RunArchiveEntry { id:string; teamId:number; title:string; question:string; phase:RunPhase; progress:number; publication:Publication; createdAt?:string; updatedAt?:string; startedAt?:string; finishedAt?:string }
export interface WorldSnapshot { team:Team|null; teams:Team[]; rooms:Room[]; agents:Agent[]; messages:Record<number,Message[]>; activities:Activity[]; tasks:Task[]; run:RunSnapshot|null; loading:boolean; error:string; connection:'connecting'|'open'|'closed'|'error'; lastUpdated:number|null }
export type NormalizedEvent =
 | { type:'message'; teamId:number; roomId:number; message:Message }
 | { type:'room_status'; teamId:number; roomId:number; state:string; needScheduling:boolean; currentAgentId:number|null }
 | { type:'agent_status'; teamId:number; agentId:number; status:string }
 | { type:'agent_activity'; activity:Activity }
 | { type:'task_changed'; teamId:number; task:Task }
 | { type:'run_changed'; teamId:number; run:Partial<RunSnapshot> & { id:string } }
 | { type:'room_run_changed'; teamId:number; runId:string; roomRuntime:RoomRuntime }
 | { type:'publication_changed'; teamId:number; runId:string; publication:Publication }
 | { type:'reconcile'; teamId:number; reason:'message_changed'|'team_reloaded'|'room_added' };
