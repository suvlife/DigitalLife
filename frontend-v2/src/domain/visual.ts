import type { NpcStatus } from './types';
export interface VisualProfile { archetype:string; color:string; accent:string; accessory:string; glyph:string }
const archetypes=[
  {archetype:'strategist',color:'#435b47',accent:'#d7b56d',accessory:'羽扇',glyph:'策'},
  {archetype:'scholar',color:'#36556b',accent:'#c5d8d0',accessory:'竹简',glyph:'文'},
  {archetype:'swordsman',color:'#633e39',accent:'#d9b36c',accessory:'长剑',glyph:'侠'},
  {archetype:'artisan',color:'#67503b',accent:'#b9c47f',accessory:'机巧匣',glyph:'工'},
  {archetype:'hermit',color:'#4c5360',accent:'#d8c7a0',accessory:'葫芦',glyph:'隐'},
  {archetype:'healer',color:'#466657',accent:'#d5a6a0',accessory:'药囊',glyph:'医'},
];
export function visualProfile(agentId:number):VisualProfile { return archetypes[Math.abs(agentId)%archetypes.length]; }
export const npcStatusText:Record<NpcStatus,string>={idle:'静候',reading:'阅卷',thinking:'思考',speaking:'发言',working:'办事',retrying:'重试',completed:'完成',failed:'遇阻'};
