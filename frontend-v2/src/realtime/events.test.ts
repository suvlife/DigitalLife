import { describe, expect, it } from 'vitest';
import { normalizeEvent } from './events';
describe('event normalizer',()=>{
 it('normalizes legacy room status',()=>{expect(normalizeEvent({event:'room_status',gt_room:{id:2,team_id:1},state:'SCHEDULING',need_scheduling:true,current_turn_agent_id:8})).toEqual({type:'room_status',teamId:1,roomId:2,state:'SCHEDULING',needScheduling:true,currentAgentId:8})});
 it('normalizes planned run events',()=>{const e=normalizeEvent({event:'run_progress_changed',run_id:99,team_id:1,phase:'DISCUSSING',progress_percent:42});expect(e?.type).toBe('run_changed');if(e?.type==='run_changed')expect(e.run.progress).toBe(42)});
 it.each(['message_changed','team_reloaded','room_added'] as const)('routes %s through reconcile',reason=>{expect(normalizeEvent({event:reason,team_id:7})).toEqual({type:'reconcile',teamId:7,reason})});
 it('derives reconcile team from room payload',()=>expect(normalizeEvent({event:'message_changed',gt_room:{id:2,team_id:9}})).toEqual({type:'reconcile',teamId:9,reason:'message_changed'}));
 it('rejects malformed events',()=>expect(normalizeEvent({event:'room_status'})).toBeNull());
});
