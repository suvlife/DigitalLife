import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import CourtyardScene from './CourtyardScene.vue';

const rooms:any[]=[
 {id:10,teamId:1,name:'错误大房间',i18n:{},type:'group',state:'IDLE',needScheduling:false,currentTurnAgentId:null,agentIds:[1,2,3],tags:['root'],operatorEnabled:true},
 {id:20,teamId:1,name:'服务端主房间',i18n:{},type:'group',state:'IDLE',needScheduling:false,currentTurnAgentId:null,agentIds:[1],tags:[],operatorEnabled:false},
];
const run:any={id:'5',teamId:1,rootRoomId:20,phase:'queued',progress:0,question:'',finalAnswer:'',roomRuns:{},activeAgentIds:[],completedRoomIds:[],publication:{status:'idle'},source:'native'};
describe('CourtyardScene entry room',()=>{
 it('uses only the server supplied root room id',()=>{const wrapper=mount(CourtyardScene,{props:{teamId:1,rooms,agents:[],run},global:{stubs:{RouterLink:{props:['to'],template:'<a :data-to="JSON.stringify(to)"><slot/></a>'},RoomBuilding:true,CentralHall:true}}});expect(wrapper.get('.enter-hall').attributes('data-to')).toContain('20')});
 it('does not guess when the server supplies no room',()=>{const wrapper=mount(CourtyardScene,{props:{teamId:1,rooms,agents:[],run:{...run,rootRoomId:null}},global:{stubs:{RouterLink:true,RoomBuilding:true,CentralHall:true}}});expect(wrapper.find('.enter-hall').exists()).toBe(false)});
});
