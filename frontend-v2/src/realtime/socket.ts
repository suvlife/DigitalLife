import { getToken, requireAuthentication } from '../api/auth';
import { wsUrl } from '../api/client';
import { normalizeEvent } from './events';
import type { NormalizedEvent } from '../domain/types';
type SocketState='connecting'|'open'|'closed'|'error'|'auth_required';
export class EventsSocket{
 private socket:WebSocket|null=null;private timer:number|null=null;private stableTimer:number|null=null;private heartbeatTimer:number|null=null;private stopped=false;private attempts=0;private generation=0;
 constructor(private event:(e:NormalizedEvent)=>void,private state:(s:SocketState, recovered?:boolean)=>void){}
 connect(){this.stopped=false;this.open();}
 private open(){if(this.stopped)return;const token=getToken();const generation=++this.generation;this.state('connecting');const socket=new WebSocket(wsUrl());this.socket=socket;
  socket.onopen=()=>{if(generation!==this.generation)return;if(token)socket.send(JSON.stringify({type:'auth',token}));this.state('open',this.attempts>0);this.stableTimer=window.setTimeout(()=>{if(generation===this.generation&&socket.readyState===WebSocket.OPEN)this.attempts=0;},15000);this.startHeartbeat(generation);};
  socket.onmessage=e=>{if(generation!==this.generation)return;try{const n=normalizeEvent(JSON.parse(String(e.data)));if(n)this.event(n);}catch(error){console.warn('[DigitalLife] 无法识别实时传讯',error);}};
  socket.onerror=()=>{if(generation===this.generation)this.state('error');};
  socket.onclose=e=>{if(generation!==this.generation)return;if(this.stableTimer)clearTimeout(this.stableTimer);this.stopHeartbeat();this.socket=null;if(e.code===1008){requireAuthentication(e.reason||'实时连接鉴权失败，请重新输入 Token');this.state('auth_required');return;}this.state('closed');if(this.stopped)return;const delay=Math.min(5000,1000*2**this.attempts++);this.timer=window.setTimeout(()=>this.open(),delay);};
 }
 private startHeartbeat(generation:number){this.stopHeartbeat();this.heartbeatTimer=window.setInterval(()=>{if(generation===this.generation&&this.socket&&this.socket.readyState===WebSocket.OPEN){try{this.socket.send(JSON.stringify({type:'ping'}));}catch(e){/* socket closing */}}},25000);}
 private stopHeartbeat(){if(this.heartbeatTimer){clearInterval(this.heartbeatTimer);this.heartbeatTimer=null;}}
 close(){this.stopped=true;this.generation++;if(this.timer)clearTimeout(this.timer);if(this.stableTimer)clearTimeout(this.stableTimer);this.stopHeartbeat();this.socket?.close();this.socket=null;}
}
