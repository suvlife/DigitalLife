import { beforeEach, describe, expect, it, vi } from 'vitest';
import { EventsSocket } from './socket';
import { auth } from '../api/auth';
class FakeWebSocket {
 static OPEN=1; static instances:FakeWebSocket[]=[];
 readyState=0; sent:string[]=[]; onopen:(()=>void)|null=null; onmessage:((e:{data:string})=>void)|null=null; onerror:(()=>void)|null=null; onclose:((e:{code:number;reason:string})=>void)|null=null;
 constructor(public url:string){FakeWebSocket.instances.push(this)} send(value:string){this.sent.push(value)} close(){} open(){this.readyState=1;this.onopen?.()} closeWith(code:number,reason=''){this.readyState=3;this.onclose?.({code,reason})}
}
describe('EventsSocket authentication',()=>{
 beforeEach(()=>{FakeWebSocket.instances=[];vi.stubGlobal('WebSocket',FakeWebSocket);auth.clearToken();auth.authenticationAccepted()});
 it('opens without a token so an authenticated browser cookie can be used',()=>{const states:string[]=[];new EventsSocket(()=>{},s=>states.push(s)).connect();expect(FakeWebSocket.instances).toHaveLength(1);FakeWebSocket.instances[0].open();expect(FakeWebSocket.instances[0].sent).toEqual([]);expect(states).toEqual(['connecting','open']);expect(auth.state.required).toBe(false)});
 it('sends an explicitly saved token on open',()=>{auth.saveToken('secret');const states:string[]=[];new EventsSocket(()=>{},s=>states.push(s)).connect();const socket=FakeWebSocket.instances[0];socket.open();expect(socket.sent).toEqual([JSON.stringify({type:'auth',token:'secret'})]);expect(states).toEqual(['connecting','open'])});
 it('turns policy close 1008 into authentication state without reconnecting',()=>{vi.useFakeTimers();const states:string[]=[];new EventsSocket(()=>{},s=>states.push(s)).connect();FakeWebSocket.instances[0].closeWith(1008,'Invalid session');vi.runAllTimers();expect(states.at(-1)).toBe('auth_required');expect(auth.state.required).toBe(true);expect(FakeWebSocket.instances).toHaveLength(1);vi.useRealTimers()});
});
