import type { Agent, NpcStatus } from './types';
export interface VisualProfile { archetype:string; color:string; accent:string; accessory:string; glyph:string }
const profiles:Record<string,VisualProfile>={
  strategist:{archetype:'strategist',color:'#435b47',accent:'#d7b56d',accessory:'羽扇',glyph:'策'},
  scholar:{archetype:'scholar',color:'#36556b',accent:'#c5d8d0',accessory:'竹简',glyph:'文'},
  ziping:{archetype:'astrologer',color:'#67503b',accent:'#e0c27b',accessory:'命书',glyph:'命'},
  ziwei:{archetype:'stargazer',color:'#403e68',accent:'#c9b5e8',accessory:'星盘',glyph:'星'},
  meihua:{archetype:'diviner',color:'#4c5360',accent:'#d8c7a0',accessory:'卦盘',glyph:'易'},
  healer:{archetype:'healer',color:'#466657',accent:'#d5a6a0',accessory:'药囊',glyph:'养'},
};
export function visualProfile(agent:Pick<Agent,'id'|'name'>):VisualProfile {
  const name=agent.name.toLowerCase();
  if(/紫微|星|ziwei/.test(name))return profiles.ziwei;
  if(/梅花|易数|meihua/.test(name))return profiles.meihua;
  if(/子平|盲派|滴天髓|四柱|八字|ziping|命理/.test(name))return profiles.ziping;
  if(/综合|研判|synthesizer|策/.test(name))return profiles.strategist;
  if(/国学|博雅|scholar|文/.test(name))return profiles.scholar;
  return Object.values(profiles)[Math.abs(agent.id)%Object.keys(profiles).length];
}
export const npcStatusText:Record<NpcStatus,string>={idle:'静候',reading:'阅卷',thinking:'推演',speaking:'执言',working:'排盘',retrying:'另寻门径',completed:'议毕',failed:'遇阻'};
