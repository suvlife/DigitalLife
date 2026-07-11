import type { Activity, Agent, I18n, NpcStatus, RoomStatus, Task } from './types';

const aliases: Record<string,string> = {
  synthesizer:'综合研判官', scholar:'国学博雅先生', ziping:'子平格局派大师', dts:'滴天髓派大师',
  blind:'盲派命理大师', ziwei:'紫微斗数大师', meihua:'梅花易数大师', fortune:'运势研判师',
  sizhu_analyst:'四柱排盘师', operator:'问道之人', OPERATOR:'问道之人',
};

export function localized(i18n:I18n|undefined, category:string, fallback=''):string {
  const values=i18n?.[category];
  return values?.['zh-CN'] || values?.zh_CN || values?.zh || fallback;
}
export function masterName(agent?:Pick<Agent,'name'|'i18n'>|null, fallback='无名先生'):string {
  if(!agent)return fallback;
  return localized(agent.i18n,'display_name',aliases[agent.name]||agent.name||fallback);
}
export function speakerName(raw:string, agent?:Pick<Agent,'name'|'i18n'>|null):string {
  if(agent)return masterName(agent);
  return aliases[raw] || raw || '来客';
}
export const taskStatusText=(status:string)=>({TODO:'待参详',PENDING:'待参详',IN_PROGRESS:'推演中',RUNNING:'推演中',DONE:'已圆满',COMPLETED:'已圆满',SUCCEEDED:'已圆满',FAILED:'遇阻',CANCELLED:'已止议'}[status.toUpperCase()]||'参详中');
export const priorityText=(priority:string)=>({LOW:'从容',NORMAL:'寻常',MEDIUM:'要紧',HIGH:'紧要',URGENT:'急务'}[priority.toUpperCase()]||'寻常');
export const roomStatusText=(status?:RoomStatus)=>({waiting:'静候开议',discussing:'众师推演中',synthesizing:'正在合议定论',completed:'本室议毕',failed:'推演遇阻',skipped:'本室暂歇'}[status||'waiting']);

const activityByType:Record<string,string>={
  llm_infer:'凝神推演，正在参详其中脉络', reasoning:'捻须沉思，正在梳理玄机', tool_call:'取出法器，正在查验推算',
  chat_reply:'起身执言，向诸位陈述见解', message_received:'接过传书，正在阅览来意', task_received:'领下议题，准备开坛参详',
  compact:'收拢案上卷宗，整理前番思路', agent_state:'调整心神，静候下一轮问道',
};
export function activityNarrative(activity:Activity, agentName:string):string {
  const status=activity.status.toLowerCase();
  if(status==='failed') return `${agentName}推演暂遇阻碍，正在另寻门径`;
  if(status==='succeeded' || status==='completed'){
    if(activity.type.toLowerCase()==='chat_reply') return `${agentName}已陈述本轮见解`;
    if(activity.type.toLowerCase()==='agent_state') return `${agentName}已归座静候`;
    return `${agentName}已完成一番推演`;
  }
  return `${agentName}${activityByType[activity.type.toLowerCase()]||'正在堂中参详议题'}`;
}
export function activityDetail(activity:Activity):string {
  const raw=(activity.title||activity.detail||'').trim();
  const hidden=new Set(['agent_state','状态变更','推理','压缩上下文','reasoning','compact']);
  return !raw || hidden.has(raw.toLowerCase()) || hidden.has(raw) ? '' : raw;
}
export function activityNpcStatus(activity:Activity):NpcStatus {
  const type=activity.type.toLowerCase();
  if(activity.status.toLowerCase()==='failed')return 'failed';
  if(type==='chat_reply')return 'speaking';
  if(type==='llm_infer'||type==='reasoning')return 'thinking';
  if(type==='message_received'||type==='task_received')return 'reading';
  if(type==='tool_call'||type==='compact')return 'working';
  return 'idle';
}
export function taskTheme(tasks:readonly Task[], initialTopic?:string|null, question?:string):string {
  return tasks[0]?.description || tasks[0]?.title || initialTopic || question || '本室正静候新的问道之题；议题一到，诸位先生便会开坛参详。';
}
