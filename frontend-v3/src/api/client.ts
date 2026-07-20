import type { Activity, Agent, I18n, Message, Room, RunArchiveEntry, RunPhase, RunSnapshot, Task, Team } from '../domain/types';
import { localized, masterName } from '../domain/presentation';
import { getToken, requireAuthentication } from './auth';
const BASE=(import.meta.env.VITE_API_BASE_URL||'').replace(/\/$/,'');
const fileBase=()=>BASE || '';
function getXsrfToken():string|null{const m=document.cookie.match(/(?:^|;\s*)_xsrf=([^;]+)/);return m?decodeURIComponent(m[1]):null;}
export function fileDownloadUrl(path:string,teamId:number):string{return `${fileBase()}/files/download.json?team_id=${encodeURIComponent(teamId)}&path=${encodeURIComponent(path)}`;}
function downloadName(response:Response,fallback:string):string{
 const value=response.headers.get('Content-Disposition')||'';
 const utf8=value.match(/filename\*=UTF-8''([^;]+)/i);
 if(utf8){try{return decodeURIComponent(utf8[1]);}catch{}}
 const plain=value.match(/filename="?([^";]+)"?/i); return plain?.[1]||fallback.split('/').pop()||'download';
}
export async function downloadFile(path:string,teamId:number):Promise<void>{
 const token=getToken(); const headers=new Headers(); if(token)headers.set('Authorization',`Bearer ${token}`);
 const response=await fetch(fileDownloadUrl(path,teamId),{credentials:'include',headers});
 if(!response.ok){let message=`下载失败 (${response.status})`;try{const body=await response.json();message=body.error_desc||body.message||message;}catch{}if(response.status===401)requireAuthentication(message);throw new ApiError(message,response.status);}
 const blob=await response.blob(); const objectUrl=URL.createObjectURL(blob); const anchor=document.createElement('a');
 anchor.href=objectUrl; anchor.download=downloadName(response,path); anchor.style.display='none'; document.body.appendChild(anchor); anchor.click(); anchor.remove(); URL.revokeObjectURL(objectUrl);
}
function url(path:string){return `${BASE}${path}`;}
export class ApiError extends Error { constructor(message:string, public readonly status:number){super(message);this.name='ApiError';} }
async function json<T>(path:string, init:RequestInit={}):Promise<T>{
 const token=getToken(); const headers=new Headers(init.headers);
 if(!headers.has('Content-Type')) headers.set('Content-Type','application/json'); if(token&&!headers.has('Authorization')) headers.set('Authorization',`Bearer ${token}`);
 const method=(init.method||'GET').toUpperCase(); if(method!=='GET'){const xsrf=getXsrfToken(); if(xsrf&&!headers.has('X-Xsrftoken')) headers.set('X-Xsrftoken',xsrf);}
 const response=await fetch(url(path),{credentials:'include',...init,headers});
 if(!response.ok){let message=`请求失败 (${response.status})`;try{const body=await response.json();message=body.error_desc||body.message||message;}catch{}if(response.status===401)requireAuthentication(message);throw new ApiError(message,response.status);} return response.json() as Promise<T>;
}
const i18n=(x:unknown):I18n => x && typeof x==='object' ? x as I18n : {};
export async function getTeams():Promise<Team[]>{const d=await json<{teams:any[]}>('/teams/list.json');return (d.teams||[]).map(x=>({id:Number(x.id),name:localized(i18n(x.i18n),'display_name',String(x.name||'')),i18n:i18n(x.i18n),enabled:Boolean(x.enabled),config:x.config||{},questionRoomId:x.question_room_id==null?null:Number(x.question_room_id),createdAt:x.created_at,updatedAt:x.updated_at}));}

export type LlmServiceType='openai-compatible'|'anthropic'|'google'|'deepseek';
export interface LlmServiceInfo{name:string;base_url:string;api_key:string;has_api_key?:boolean;is_builtin?:boolean;index?:number;type:LlmServiceType;model:string;enable:boolean;extra_headers:Record<string,string>;provider_params?:Record<string,unknown>;temperature?:number|null;context_window_tokens?:number;reserve_output_tokens?:number;compact_trigger_ratio?:number;compact_summary_max_tokens?:number;max_concurrency?:number;requests_per_minute?:number;}
export interface LlmServiceListResponse{llm_services:LlmServiceInfo[];default_llm_server:string|null;}
export type LlmServiceCreatePayload=Pick<LlmServiceInfo,'name'|'base_url'|'api_key'|'type'>&Partial<Omit<LlmServiceInfo,'name'|'base_url'|'api_key'|'type'|'has_api_key'|'is_builtin'>>;
export type LlmServiceModifyPayload=Partial<Omit<LlmServiceCreatePayload,'name'>>;
export interface LlmServiceTestPayload{mode:'saved'|'temp';index?:number;base_url?:string;api_key?:string;type?:LlmServiceType;model?:string;extra_headers?:Record<string,string>;provider_params?:Record<string,unknown>;}
export interface LlmServiceTestResult{status:'ok'|'error';message:string;detail?:{model?:string;response_text?:string;duration_ms?:number;usage?:Record<string,unknown>;error_type?:string;raw_error?:string;};}

export interface TeamMemberDetail{id:number;name:string;i18n:I18n;employee_number:number;role_template_id:number;model?:string;driver?:string;allow_tools?:string[]|null;allow_skills?:string[]|null;}
export interface TeamRoomDetail{id:number;name:string;i18n:I18n;type:string;initial_topic:string|null;max_rounds:number|null;agent_ids:number[];agents:string[];biz_id:string|null;tags:string[];}
export interface TeamDetail{id:number;name:string;i18n:I18n;working_directory:string;config:Record<string,unknown>;enabled:boolean;deleted?:boolean;created_at?:string;updated_at?:string;agents:TeamMemberDetail[];rooms:TeamRoomDetail[];}
export interface CreateTeamPayload{name:string;working_directory?:string;config?:Record<string,unknown>;}
export interface ModifyTeamPayload{name?:string;working_directory?:string;config?:Record<string,unknown>;agents?:Array<{id:number|null;name:string;role_template_id:number;model:string;driver:string;}>;preset_rooms?:Array<{id?:number|null;name:string;agents:string[];initial_topic?:string|null;max_rounds?:number|null;biz_id?:string|null;tags?:string[];}>;}
export interface TeamPresetExport{uuid?:string|null;name:string;i18n?:I18n;config:Record<string,unknown>;rule_templates:Array<Record<string,unknown>>;agents:Array<Record<string,unknown>>;dept_tree?:Record<string,unknown>|null;preset_rooms:Array<Record<string,unknown>>;auto_start:boolean;is_default?:boolean;}
export interface TeamClearResult{status:string;team_id:number;deleted:{tasks:number;histories:number;messages:number;rooms:number;activities:number;runs?:number;room_runs?:number;publications?:number;};}
export interface TeamMemberSaveItem{id:number|null;name:string;role_template_id:number;model:string;driver:string;allow_tools?:string[]|null;allow_skills?:string[]|null;}
export interface DeptTreeNode{id?:number|null;name:string;i18n?:I18n;responsibility:string;manager_id:number|null;agent_ids:number[];children:DeptTreeNode[];}
export interface RoomSavePayload{name:string;type?:string;agent_ids:number[];initial_topic?:string|null;max_rounds?:number|null;}
export interface AgentClearResult{status:string;agent_id:number;deleted:{histories:number;[key:string]:number};}

export interface RoleTemplate{id:number;name:string;i18n:I18n;soul:string;type:string|null;}
export interface RoleTemplatePayload{name:string;soul:string;}

export interface GhostConfig{enabled:boolean;api_url:string;admin_api_key:string;content_api_key:string;auto_publish:boolean;publish_status:'published'|'draft';has_admin_key:boolean;has_content_key:boolean;skip_ssl_verify:boolean;has_key?:boolean;is_builtin?:boolean;}
export interface GhostConfigPatch{enabled?:boolean;api_url?:string;admin_api_key?:string;content_api_key?:string;clear_admin_api_key?:boolean;clear_content_api_key?:boolean;auto_publish?:boolean;publish_status?:'published'|'draft';skip_ssl_verify?:boolean;}
export interface GhostSaveResult{success:boolean;has_admin_key:boolean;has_content_key:boolean;}
export interface GhostTestPayload{api_url?:string;admin_api_key?:string;skip_ssl_verify?:boolean;}
export interface GhostTestResult{success:boolean;message:string;site_title?:string;}

export interface SystemStatus{initialized:boolean;language?:string;version?:string;auth_enabled?:boolean;default_llm_server?:string;message?:string;schedule_state?:string;not_running_reason?:string;demo_mode?:boolean;freeze_data?:boolean;read_only?:boolean;hide_sensitive_info?:boolean;development_mode?:boolean;auto_check_update?:boolean;}
export interface DatabaseBackupResult{status:string;backup_path:string;backup_file_name:string;}
export interface UpdateCheckResult{has_update:boolean;current_version:string;latest_version:string;release_url:string;release_notes:string;}
export interface SkillConfig{name:string;description:string;is_builtin:boolean;files:string[];}
export interface ToolConfig{name:string;category:string;}

const record=(x:unknown):Record<string,unknown>=>x&&typeof x==='object'?x as Record<string,unknown>:{};
const roleTemplate=(x:any,fallbackId=0):RoleTemplate=>({id:Number(x.id??fallbackId),name:String(x.name||''),i18n:i18n(x.i18n),soul:String(x.soul||''),type:x.type==null?null:String(x.type)});
export async function getTeamDetail(teamId:number):Promise<TeamDetail>{const x=await json<any>(`/teams/${teamId}.json`);return{id:Number(x.id),name:String(x.name||''),i18n:i18n(x.i18n),working_directory:String(x.working_directory||''),config:record(x.config),enabled:Boolean(x.enabled),deleted:x.deleted==null?undefined:Boolean(x.deleted),created_at:x.created_at,updated_at:x.updated_at,agents:(x.agents||[]).map((a:any)=>({id:Number(a.id),name:String(a.name||''),i18n:i18n(a.i18n),employee_number:Number(a.employee_number||0),role_template_id:Number(a.role_template_id||0)})),rooms:(x.rooms||[]).map((r:any)=>({id:Number(r.id),name:String(r.name||''),i18n:i18n(r.i18n),type:String(r.type||'group').toLowerCase(),initial_topic:r.initial_topic==null?null:String(r.initial_topic),max_rounds:r.max_rounds==null?null:Number(r.max_rounds),agent_ids:(r.agent_ids||[]).map(Number),agents:(r.agents||[]).map(String),biz_id:r.biz_id==null?null:String(r.biz_id),tags:Array.isArray(r.tags)?r.tags.map(String):[]}))};}
export async function modifyTeam(teamId:number,body:ModifyTeamPayload):Promise<{status:string;name:string}>{return json(`/teams/${teamId}/modify.json`,{method:'POST',body:JSON.stringify(body)});}
export async function createTeam(body:CreateTeamPayload):Promise<{status:string;id:number;name:string}>{return json('/teams/create.json',{method:'POST',body:JSON.stringify(body)});}
export async function setTeamEnabled(teamId:number,enabled:boolean):Promise<{status:string;enabled:boolean}>{return json(`/teams/${teamId}/set_enabled.json`,{method:'POST',body:JSON.stringify({enabled})});}
export async function deleteTeam(teamId:number):Promise<{status:string;name:string}>{return json(`/teams/${teamId}/delete.json`,{method:'POST'});}
export async function clearTeamData(teamId:number):Promise<TeamClearResult>{return json(`/teams/${teamId}/clear_data.json`,{method:'POST'});}
export async function exportTeam(teamId:number):Promise<TeamPresetExport>{return json(`/teams/${teamId}/export_preset.json`);}
export async function getTeamMembers(teamId:number):Promise<TeamMemberDetail[]>{const d=await json<{agents:any[]}>(`/agents/list.json?team_id=${teamId}`);return(d.agents||[]).map(a=>({id:Number(a.id),name:String(a.name||''),i18n:i18n(a.i18n),employee_number:Number(a.employee_number||0),role_template_id:Number(a.role_template_id||0),model:String(a.model||''),driver:String(a.driver||'native').toLowerCase(),allow_tools:Array.isArray(a.allow_tools)?a.allow_tools.map(String):null,allow_skills:Array.isArray(a.allow_skills)?a.allow_skills.map(String):null}));}
export async function saveTeamMembers(teamId:number,agents:TeamMemberSaveItem[]):Promise<TeamMemberDetail[]>{const d=await json<{agents:any[]}>(`/teams/${teamId}/agents/save.json`,{method:'PUT',body:JSON.stringify({agents})});return(d.agents||[]).map(a=>({id:Number(a.id),name:String(a.name||''),i18n:i18n(a.i18n),employee_number:Number(a.employee_number||0),role_template_id:Number(a.role_template_id||0),model:String(a.model||''),driver:String(a.driver||'native').toLowerCase(),allow_tools:Array.isArray(a.allow_tools)?a.allow_tools.map(String):null,allow_skills:Array.isArray(a.allow_skills)?a.allow_skills.map(String):null}));}
export async function clearAgentData(agentId:number):Promise<AgentClearResult>{return json(`/agents/${agentId}/clear_data.json`,{method:'POST'});}
export async function getDeptTree(teamId:number):Promise<DeptTreeNode|null>{const d=await json<{dept_tree?:DeptTreeNode|null}>(`/teams/${teamId}/dept_tree.json`);return d.dept_tree??null;}
export async function saveDeptTree(teamId:number,deptTree:DeptTreeNode):Promise<{status:string}>{return json(`/teams/${teamId}/dept_tree/update.json`,{method:'PUT',body:JSON.stringify({dept_tree:deptTree})});}
export async function createTeamRoom(teamId:number,payload:RoomSavePayload):Promise<{status:string;room_name:string}>{return json(`/teams/${teamId}/rooms/create.json`,{method:'POST',body:JSON.stringify(payload)});}
export async function updateTeamRoom(teamId:number,roomId:number,payload:Omit<RoomSavePayload,'agent_ids'>):Promise<{status:string;room_name:string}>{return json(`/teams/${teamId}/rooms/${roomId}/modify.json`,{method:'POST',body:JSON.stringify(payload)});}
export async function updateTeamRoomAgents(teamId:number,roomId:number,agentIds:number[]):Promise<{status:string;room_name:string}>{return json(`/teams/${teamId}/rooms/${roomId}/agents/modify.json`,{method:'POST',body:JSON.stringify({agent_ids:agentIds})});}
export async function deleteTeamRoom(teamId:number,roomId:number):Promise<{status:string;room_name:string}>{return json(`/teams/${teamId}/rooms/${roomId}/delete.json`,{method:'POST'});}
export const getTeamPresetExport=exportTeam;

export async function getLlmServiceConfig():Promise<LlmServiceListResponse>{const d=await json<{llm_services?:LlmServiceInfo[];services?:LlmServiceInfo[];default_llm_server?:string|null}>('/config/llm_services/list.json');return{llm_services:d.llm_services||d.services||[],default_llm_server:d.default_llm_server??null};}
export async function getLlmServices():Promise<LlmServiceInfo[]>{return(await getLlmServiceConfig()).llm_services;}
export async function createLlmService(body:LlmServiceCreatePayload):Promise<{status:string;index:number}>{return json('/config/llm_services/create.json',{method:'POST',body:JSON.stringify(body)});}
export async function modifyLlmService(index:number,body:LlmServiceModifyPayload):Promise<{status:string}>{return json(`/config/llm_services/${index}/modify.json`,{method:'POST',body:JSON.stringify(body)});}
export async function deleteLlmService(index:number):Promise<{status:string;deleted_name:string}>{return json(`/config/llm_services/${index}/delete.json`,{method:'POST'});}
export async function setDefaultLlmService(index:number):Promise<{status:string;default_llm_server:string}>{return json(`/config/llm_services/${index}/set_default.json`,{method:'POST'});}
export async function testLlmService(body:LlmServiceTestPayload):Promise<LlmServiceTestResult>{return json('/config/llm_services/test.json',{method:'POST',body:JSON.stringify(body)});}

// LLM 厂商预设目录（#5：预设下拉 + 多模型）与「首选/兜底」链（#3）
export interface LlmProviderCatalogEntry{id:string;display_name:Record<string,string>;type:LlmServiceType|string;base_url:string;default_model:string;signup_url:string;models:string[];}
export interface LlmServiceFromProviderPayload{provider_id:string;api_key:string;model?:string;name?:string;}
export interface LlmFallbackInfo{default_llm_server:string|null;fallback_llm_servers:string[];}
const strMap=(x:unknown):Record<string,string>=>{const r=record(x);const out:Record<string,string>={};for(const k of Object.keys(r))out[k]=String(r[k]??'');return out;};
export function providerDisplayName(entry:Pick<LlmProviderCatalogEntry,'display_name'|'id'>):string{const d=entry.display_name||{};return d['zh-CN']||d.zh_CN||d.zh||d.en||entry.id;}
export async function getLlmProviderCatalog():Promise<LlmProviderCatalogEntry[]>{const d=await json<{providers?:any[]}>('/config/llm_providers/catalog.json');return(d.providers||[]).map(x=>({id:String(x.id||''),display_name:strMap(x.display_name),type:String(x.type||'openai-compatible'),base_url:String(x.base_url||''),default_model:String(x.default_model||''),signup_url:String(x.signup_url||''),models:Array.isArray(x.models)?x.models.map(String):[]}));}
export async function createLlmServiceFromProvider(body:LlmServiceFromProviderPayload):Promise<{status:string;index:number;service:LlmServiceInfo}>{return json('/config/llm_services/from_provider.json',{method:'POST',body:JSON.stringify(body)});}
export async function getLlmFallback():Promise<LlmFallbackInfo>{const d=await json<any>('/config/llm_services/fallback.json');return{default_llm_server:d.default_llm_server??null,fallback_llm_servers:Array.isArray(d.fallback_llm_servers)?d.fallback_llm_servers.map(String):[]};}
export async function setLlmFallback(fallbackServers:string[]):Promise<{status:string}>{return json('/config/llm_services/fallback.json',{method:'POST',body:JSON.stringify({fallback_llm_servers:fallbackServers})});}

// 搜索工具配置（#5：多引擎 + 多 key，key 脱敏，后台增删改查）
export interface SearchProviderInfo{provider:string;enable:boolean;api_keys:string[];api_keys_count:number;has_api_key:boolean;}
export interface SearchToolsConfig{enabled:boolean;max_content_length:number;max_fetch_bytes:number;providers:SearchProviderInfo[];}
export interface SearchProviderCreatePayload{provider:string;api_keys?:string[];enable?:boolean;}
export interface SearchProviderModifyPayload{provider?:string;api_keys?:string[];enable?:boolean;clear_api_keys?:boolean;}
export async function getSearchConfig():Promise<SearchToolsConfig>{const d=await json<any>('/config/search.json');return{enabled:Boolean(d.enabled),max_content_length:Number(d.max_content_length||0),max_fetch_bytes:Number(d.max_fetch_bytes||0),providers:(d.providers||[]).map((p:any)=>({provider:String(p.provider||''),enable:Boolean(p.enable),api_keys:Array.isArray(p.api_keys)?p.api_keys.map(String):[],api_keys_count:Number(p.api_keys_count||0),has_api_key:Boolean(p.has_api_key)}))};}
export async function updateSearchSettings(body:{enabled?:boolean;max_content_length?:number;max_fetch_bytes?:number}):Promise<{status:string}>{return json('/config/search/settings.json',{method:'POST',body:JSON.stringify(body)});}
export async function createSearchProvider(body:SearchProviderCreatePayload):Promise<{status:string;index:number}>{return json('/config/search/providers/create.json',{method:'POST',body:JSON.stringify(body)});}
export async function modifySearchProvider(index:number,body:SearchProviderModifyPayload):Promise<{status:string}>{return json(`/config/search/providers/${index}/modify.json`,{method:'POST',body:JSON.stringify(body)});}
export async function deleteSearchProvider(index:number):Promise<{status:string;deleted_provider:string}>{return json(`/config/search/providers/${index}/delete.json`,{method:'POST'});}

export async function getGhostConfig():Promise<GhostConfig>{return json('/config/ghost.json');}
export async function saveGhostConfig(body:GhostConfigPatch):Promise<GhostSaveResult>{return json('/config/ghost.json',{method:'POST',body:JSON.stringify(body)});}
export async function testGhostConfig(body:GhostTestPayload={}):Promise<GhostTestResult>{return json('/config/ghost/test.json',{method:'POST',body:JSON.stringify(body)});}
export const testGhost=testGhostConfig;

export async function getSystemStatus():Promise<SystemStatus>{return json('/system/status.json');}
export async function backupDatabase():Promise<DatabaseBackupResult>{return json('/system/database/backup.json',{method:'POST'});}
export async function checkUpdate(force=false):Promise<UpdateCheckResult>{return json(`/system/check_update.json${force?'?force=true':''}`);}
export async function updateSystemConfig(body:{auto_check_update?:boolean}):Promise<{status:string;auto_check_update:boolean}>{return json('/system/update_config.json',{method:'POST',body:JSON.stringify(body)});}

export async function getRoleTemplates():Promise<RoleTemplate[]>{const d=await json<{role_templates?:any[]}>('/role_templates/list.json');return(d.role_templates||[]).map(x=>roleTemplate(x));}
export async function getRoleTemplate(templateId:number):Promise<RoleTemplate>{return roleTemplate(await json<any>(`/role_templates/${templateId}.json`),templateId);}
export const getRoleTemplateDetail=getRoleTemplate;
export async function createRoleTemplate(body:RoleTemplatePayload):Promise<RoleTemplate>{return roleTemplate(await json<any>('/role_templates/create.json',{method:'POST',body:JSON.stringify(body)}));}
export async function modifyRoleTemplate(templateId:number,body:RoleTemplatePayload):Promise<RoleTemplate>{return roleTemplate(await json<any>(`/role_templates/${templateId}/modify.json`,{method:'POST',body:JSON.stringify(body)}),templateId);}
export const updateRoleTemplate=modifyRoleTemplate;
export async function deleteRoleTemplate(templateId:number):Promise<{status:string;id:number;name:string}>{return json(`/role_templates/${templateId}/delete.json`,{method:'POST'});}
export async function getSkills():Promise<SkillConfig[]>{const d=await json<{skills?:SkillConfig[]}>('/config/skills/list.json');return d.skills||[];}
export const getAvailableSkills=getSkills;
export async function getTools():Promise<ToolConfig[]>{const d=await json<{tools?:ToolConfig[]}>('/config/tools/list.json');return d.tools||[];}
export const getAvailableTools=getTools;
export async function getTeam(teamId:number):Promise<Team>{const x=await json<any>(`/teams/${teamId}.json`);return{id:Number(x.id),name:localized(i18n(x.i18n),'display_name',String(x.name||'')),i18n:i18n(x.i18n),enabled:Boolean(x.enabled),config:x.config||{},questionRoomId:x.question_room_id==null?null:Number(x.question_room_id),createdAt:x.created_at,updatedAt:x.updated_at};}
export async function getRooms(teamId:number):Promise<Room[]>{const d=await json<{rooms:any[]}>(`/rooms/list.json?team_id=${teamId}`);return(d.rooms||[]).map(x=>{const r=x.gt_room||{};return{id:Number(r.id),teamId:Number(r.team_id||teamId),name:localized(i18n(r.i18n),'display_name',String(r.name||'')),i18n:i18n(r.i18n),type:String(r.type||'group').toLowerCase()==='private'?'private':'group',state:String(x.state||'IDLE'),needScheduling:Boolean(x.need_scheduling),currentTurnAgentId:Number(x.current_turn_agent_id)>0?Number(x.current_turn_agent_id):null,agentIds:(x.agents||r.agent_ids||[]).map(Number).filter((n:number)=>n>0),tags:Array.isArray(r.tags)?r.tags:[],operatorEnabled:(x.agents||r.agent_ids||[]).map(Number).includes(-1),initialTopic:localized(i18n(r.i18n),'initial_topic',r.initial_topic??'')||null};});}
export async function getAgents(teamId:number):Promise<Agent[]>{const d=await json<{agents:any[]}>(`/agents/list.json?team_id=${teamId}`);return(d.agents||[]).map(x=>({id:Number(x.id),teamId:Number(x.team_id||teamId),name:masterName({name:String(x.name||''),i18n:i18n(x.i18n)}),i18n:i18n(x.i18n),status:String(x.status||'idle').toLowerCase(),roleTemplateId:x.role_template_id,model:x.model,special:x.special}));}
function message(x:any,roomId:number):Message{return{id:x.db_id==null?null:Number(x.db_id),roomId,senderId:Number(x.sender_id),senderName:String(x.sender_display_name||''),content:String(x.content||''),sentAt:String(x.send_time||x.time||''),seq:x.seq==null?null:Number(x.seq),immediate:Boolean(x.insert_immediately)}}
export async function getMessages(roomId:number,limit=100):Promise<Message[]>{const d=await json<{messages:any[]}>(`/rooms/${roomId}/messages/list.json?limit=${limit}`);return(d.messages||[]).map(x=>message(x,roomId));}
export async function getActivities(teamId:number):Promise<Activity[]>{const d=await json<{activities:any[]}>(`/teams/${teamId}/activities.json`);return(d.activities||[]).map(activity);}
export function activity(x:any):Activity{return{id:Number(x.id||0),agentId:Number(x.agent_id||0),teamId:Number(x.team_id||0),roomId:x.room_id==null?(x.metadata?.room_id==null?null:Number(x.metadata.room_id)):Number(x.room_id),type:String(x.activity_type||'unknown').toLowerCase(),status:String(x.status||'started').toLowerCase(),title:String(x.title||''),detail:String(x.detail||x.error_message||''),startedAt:x.started_at||null,finishedAt:x.finished_at||null,metadata:x.metadata||{}}}
export async function getTasks(teamId:number):Promise<Task[]>{const d=await json<{tasks:any[]}>(`/teams/${teamId}/tasks.json?include_closed=true&limit=500`);return(d.tasks||[]).map(x=>task(x));}
export function task(x:any):Task{return{id:Number(x.id),teamId:Number(x.team_id),roomId:x.room_id==null?null:Number(x.room_id),assigneeId:Number(x.assignee_id||0),title:String(x.title||''),description:String(x.description||''),status:String(x.status||'TODO'),priority:String(x.priority||'NORMAL'),result:String(x.result||''),updatedAt:x.updated_at||null}}
export async function sendMessage(roomId:number,content:string,immediate=false):Promise<void>{await json(`/rooms/${roomId}/messages/send.json`,{method:'POST',body:JSON.stringify({content,insert_immediately:immediate})});}
export async function newSession(roomId:number):Promise<void>{await json(`/rooms/${roomId}/new_session.json`,{method:'POST'});}
export function normalizeRoomRuntime(x:any){const status=String(x.status||'waiting').toLowerCase();const reported=Number(x.progress_percent??x.progress??0);const progress=['completed','failed','skipped'].includes(status)?100:status==='synthesizing'?Math.max(92,reported):reported;return{roomId:Number(x.room_id??x.roomId),status,progress,currentAgentId:Number(x.current_agent_id??x.currentAgentId)>0?Number(x.current_agent_id??x.currentAgentId):null,currentNpcStatus:String((x.current_activity??x.currentNpcStatus)||'idle').toLowerCase(),activityLabel:String((x.current_activity??x.activityLabel)||''),completedTasks:Number((x.completed_contributors??x.completedTasks)||0),totalTasks:Number((x.expected_contributors??x.totalTasks)||0),lastActivityAt:x.last_activity_at??x.lastActivityAt??null,error:x.error_message??x.error};}
function normalizePublicationStatus(raw:unknown):RunSnapshot['publication']['status']{const status=String(raw||'').toLowerCase();if(['published','publishing','pending','failed'].includes(status))return status as RunSnapshot['publication']['status'];if(['retry_waiting','not_started','idle',''].includes(status))return status==='publishing'?'publishing':'idle';return 'idle';}
export function normalizeRunSnapshot(payload:any):RunSnapshot|null{const r=payload?.run??payload;if(!r||!Number(r.id))return null;const roomList=Array.isArray(payload?.rooms)?payload.rooms:[];const roomRuns=Object.fromEntries(roomList.map((x:any)=>{const rr=normalizeRoomRuntime(x);return[rr.roomId,rr];}));return{id:String(r.id),teamId:Number(r.team_id??r.teamId),rootRoomId:r.root_room_id==null?(r.rootRoomId==null?null:Number(r.rootRoomId)):Number(r.root_room_id),phase:String((r.status??r.phase)||'queued').toLowerCase() as RunSnapshot['phase'],progress:Number(r.progress_percent??r.progress??0),question:String((r.query??r.question)||''),finalAnswer:String((r.final_answer??r.finalAnswer)||''),roomRuns,activeAgentIds:roomList.map((x:any)=>Number(x.current_agent_id)).filter((id:number)=>id>0),completedRoomIds:roomList.filter((x:any)=>['COMPLETED','SKIPPED'].includes(String(x.status).toUpperCase())).map((x:any)=>Number(x.room_id)),publication:{status:normalizePublicationStatus(r.blog_publish_status),url:r.blog_post_url||undefined,error:r.metadata?.blog_publish_error||undefined},reportPath:r.metadata?.final_report_path||undefined,startedAt:r.started_at,finishedAt:r.finished_at,source:'native'};}
export async function getRun(runId:string):Promise<RunSnapshot|null>{try{return normalizeRunSnapshot(await json<any>(`/runs/${encodeURIComponent(runId)}.json`));}catch{return null;}}
export async function getCurrentRun(teamId:number):Promise<RunSnapshot|null>{try{return normalizeRunSnapshot(await json<any>(`/runs/current.json?team_id=${teamId}`));}catch{return null;}}

export async function getRunTimeline(runId:string,limit=500):Promise<Message[]>{
 const d=await json<{timeline?:any[]}>(`/runs/${encodeURIComponent(runId)}/timeline.json?limit=${Math.max(1,Math.min(500,Math.trunc(limit)))}`);
 return(d.timeline||[]).map(x=>message(x,Number(x.room_id)));
}

function normalizedRunPhase(raw:unknown):RunPhase{const value=String(raw||'queued').split('.').pop()!.toLowerCase();return value as RunPhase;}
export function normalizeRunArchiveEntry(x:any):RunArchiveEntry{return{id:String(x.id),teamId:Number(x.team_id??x.teamId),title:String(x.title||''),question:String((x.query??x.question)||''),phase:normalizedRunPhase(x.status??x.phase),progress:Math.max(0,Math.min(100,Number(x.progress_percent??x.progress??0)||0)),publication:{status:normalizePublicationStatus(x.blog_publish_status??x.publication?.status),url:x.blog_post_url??x.publication?.url??undefined,error:x.metadata?.blog_publish_error??x.publication?.error??undefined},createdAt:x.created_at??x.createdAt,updatedAt:x.updated_at??x.updatedAt,startedAt:x.started_at??x.startedAt,finishedAt:x.finished_at??x.finishedAt};}
export async function getRuns(teamId:number,limit=200):Promise<RunArchiveEntry[]>{const d=await json<{runs?:any[]}>(`/runs/list.json?team_id=${teamId}&limit=${Math.max(1,Math.min(200,Math.trunc(limit)))}`);return(d.runs||[]).map(normalizeRunArchiveEntry);}

// 卷宗（#7）：一次「问策」Run 的最终综合报告，可列举历史卷宗并查看正文。
export interface DossierEntry{run:RunArchiveEntry;reportPath:string|null;reportReady:boolean;hasConclusion:boolean;}
export interface DossierDetail extends DossierEntry{content:string;}
export async function getDossiers(teamId:number,limit=50):Promise<DossierEntry[]>{const d=await json<{dossiers?:any[]}>(`/runs/dossiers/list.json?team_id=${teamId}&limit=${Math.max(1,Math.min(200,Math.trunc(limit)))}`);return(d.dossiers||[]).map(x=>({run:normalizeRunArchiveEntry(x.run||{}),reportPath:x.report_path==null?null:String(x.report_path),reportReady:Boolean(x.report_ready),hasConclusion:Boolean(x.has_conclusion)}));}
export async function getDossier(runId:string|number):Promise<DossierDetail>{const x=await json<any>(`/runs/${encodeURIComponent(String(runId))}/dossier.json`);return{run:normalizeRunArchiveEntry(x.run||{}),content:String(x.content||''),reportPath:x.report_path==null?null:String(x.report_path),reportReady:Boolean(x.report_ready),hasConclusion:Boolean(x.has_conclusion)};}

export async function uploadFile(roomId:number,file:File,message=''):Promise<{filename:string;saved_path:string;size:number}>{const form=new FormData();form.append('file',file);if(message)form.append('message',message);const token=getToken();const headers=new Headers();if(token)headers.set('Authorization',`Bearer ${token}`);const xsrf=getXsrfToken();if(xsrf)headers.set('X-Xsrftoken',xsrf);const response=await fetch(url(`/rooms/${roomId}/messages/upload.json`),{method:'POST',headers,body:form,credentials:'include'});let body:any={};try{body=await response.json();}catch{}if(!response.ok){const detail=body.error_desc||`卷宗上传失败 (${response.status})`;if(response.status===401)requireAuthentication(detail);throw new ApiError(detail,response.status);}return body;}
export function wsUrl():string{if(BASE){const u=new URL(BASE);u.protocol=u.protocol==='https:'?'wss:':'ws:';u.pathname='/ws/events.json';u.search='';return u.toString();}return `${location.protocol==='https:'?'wss:':'ws:'}//${location.host}/ws/events.json`;}

// V3 额外 API
export async function getRecentActivities(limit=20):Promise<Activity[]>{const d=await json<{activities:any[]}>(`/activities.json?limit=${limit}`);return(d.activities||[]).map(activity);}
export async function getUsageRealtime():Promise<{realtimeTokens:number;activeAgents:number}>{const d=await json<any>('/usage/realtime.json');return{realtimeTokens:Number(d.realtime_tokens||d.tokens_per_second||0),activeAgents:Number(d.active_agents||0)};}
export async function getRunDetail(runId:string|number):Promise<any>{return json<any>(`/runs/${encodeURIComponent(String(runId))}.json`);}
export async function getRunFinalAnswer(runId:string|number):Promise<{finalAnswer:string;publication:any}>{const d=await json<any>(`/runs/${encodeURIComponent(String(runId))}/final_answer.json`);return{finalAnswer:String(d.final_answer||''),publication:d.publication||{}};}
