import { wsUrl } from '../api/client';
import { normalizeEvent } from './events';
import type { NormalizedEvent } from '../domain/types';
export class EventsSocket{
 private socket:WebSocket|null=null;private timer:number|null=null;private stopped=false;private attempts=0;
 constructor(private event:(e:NormalizedEvent)=>void,private state:(s:'connecting'|'open'|'closed'|'error')=>void){}
 connect(){this.stopped=false;this.open();}
 private open(){if(this.stopped)return;this.state('connecting');this.socket=new WebSocket(wsUrl());
  this.socket.onopen=()=>{this.attempts=0;this.state('open');const token=localStorage.getItem('teamagent_token');if(token)this.socket?.send(JSON.stringify({type:'auth',token}));};
  this.socket.onmessage=e=>{try{const n=normalizeEvent(JSON.parse(String(e.data)));if(n)this.event(n);}catch{}};
  this.socket.onerror=()=>this.state('error');this.socket.onclose=()=>{this.state('closed');if(!this.stopped){const delay=Math.min(30000,1000*2**this.attempts++);this.timer=window.setTimeout(()=>this.open(),delay);}};
 }
 close(){this.stopped=true;if(this.timer)clearTimeout(this.timer);this.socket?.close();}
}
