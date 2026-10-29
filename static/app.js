const $ = (id) => document.getElementById(id);
const history = {rx:[], tx:[], cpu:[], memory:[]};
const MAX = 30;
let socket, paused = false, eventCount = 0, toastTimer;
const colors = {rx:'#4d8dff', tx:'#a78bfa', cpu:'#4d8dff', memory:'#a78bfa'};
function showToast(message){const el=$('toast');el.textContent=message;el.classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.classList.remove('show'),2600)}
function setConnection(ok, message){
  $('liveText').textContent=ok?'LIVE':'DISCONNECTED';
  $('sideConnection').textContent=message || (ok?'Receiving telemetry':'Reconnecting…');
  $('footerStatus').textContent=ok?'Connected':'Disconnected';
  $('transportLabel').textContent='WebSocket';
  document.querySelector('.live-pill').style.borderColor=ok?'#285544':'#69413e';
  document.querySelector('.live-pill').style.color=ok?'#5be1b1':'#ff958a';
}
function addEvent(title, detail, warn=false){
  eventCount++; $('eventCount').textContent=eventCount+' event'+(eventCount===1?'':'s');
  const list=$('eventList');const empty=list.querySelector('.empty-event');if(empty)empty.remove();
  const item=document.createElement('div');item.className='event-item';
  const sym=document.createElement('div');sym.className='event-symbol'+(warn?' warn':'');sym.textContent=warn?'!':'↔';
  const copy=document.createElement('div');const b=document.createElement('b');b.textContent=title;const p=document.createElement('p');p.textContent=detail;copy.append(b,p);
  const time=document.createElement('time');time.textContent=new Date().toLocaleTimeString('en-GB');
  item.append(sym,copy,time);list.prepend(item);while(list.children.length>5)list.lastElementChild.remove();
}
function drawLine(canvasId, values, color, fill=false){
 const c=$(canvasId),ctx=c.getContext('2d'),w=c.clientWidth,h=c.clientHeight,dpr=window.devicePixelRatio||1;
 c.width=Math.max(1,Math.round(w*dpr));c.height=Math.max(1,Math.round(h*dpr));ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);
 if(values.length<2)return;
 const max=Math.max(10,...values)*1.2, step=w/(MAX-1), pts=values.map((v,i)=>[i*step,h-5-(v/max)*(h-12)]);
 ctx.beginPath();pts.forEach((p,i)=>i?ctx.lineTo(p[0],p[1]):ctx.moveTo(p[0],p[1]));ctx.strokeStyle=color;ctx.lineWidth=2;ctx.lineJoin='round';ctx.stroke();
 if(fill){ctx.lineTo(pts[pts.length-1][0],h);ctx.lineTo(pts[0][0],h);ctx.closePath();ctx.fillStyle=color+'20';ctx.fill();}
}
function drawTraffic(){
 const c=$('trafficChart'),ctx=c.getContext('2d'),w=c.clientWidth,h=c.clientHeight,dpr=window.devicePixelRatio||1;
 c.width=Math.max(1,Math.round(w*dpr));c.height=Math.max(1,Math.round(h*dpr));ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);
 const vals=[...history.rx,...history.tx],max=Math.max(100,...vals)*1.2,left=30,right=8,top=9,bottom=19,plotW=w-left-right,plotH=h-top-bottom;
 ctx.font='9px DM Sans';ctx.textAlign='right';ctx.fillStyle='#71809b';ctx.strokeStyle='#26334a';ctx.lineWidth=1;
 for(let i=0;i<=4;i++){let y=top+plotH*i/4;ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(w-right,y);ctx.stroke();ctx.fillText(Math.round(max*(1-i/4)),left-7,y+3);}
 for(let i=0;i<5;i++){let x=left+plotW*i/4;ctx.beginPath();ctx.moveTo(x,top);ctx.lineTo(x,top+plotH);ctx.stroke();}
 const series=[['rx','#4d8dff'],['tx','#a78bfa']];
 series.forEach(([key,color])=>{const arr=history[key];if(arr.length<2)return;const pts=arr.map((v,i)=>[left+plotW*i/(MAX-1),top+plotH-(v/max)*plotH]);ctx.beginPath();pts.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.lineWidth=2;ctx.strokeStyle=color;ctx.stroke();ctx.lineTo(pts[pts.length-1][0],top+plotH);ctx.lineTo(pts[0][0],top+plotH);ctx.closePath();ctx.fillStyle=color+'13';ctx.fill();});
}
function setGauge(id, value, color){
 $(id).style.background=`conic-gradient(${color} 0deg ${Math.min(100,value)*3.6}deg,#26334b ${Math.min(100,value)*3.6}deg 360deg)`;
}
function handleMetrics(d){
 for(const key of ['rx','tx','cpu','memory']){history[key].push(d[key]);if(history[key].length>MAX)history[key].shift();}
 $('rxValue').textContent=d.rx.toFixed(1);$('txValue').textContent=d.tx.toFixed(1);
 $('latencyValue').textContent=d.latency.toFixed(0);$('lossValue').textContent=d.loss.toFixed(2);
 $('chartRx').innerHTML=d.rx.toFixed(1)+' <small>Mbps</small>';$('chartTx').innerHTML=d.tx.toFixed(1)+' <small>Mbps</small>';
 $('latencyBar').style.width=Math.min(100,d.latency/2)+'%';$('latencyStatus').textContent=d.latency<50?'Healthy':'Elevated';
 $('lossBar').style.width=Math.min(100,d.loss*40)+'%';$('lossStatus').textContent=d.loss===0?'No packet loss':d.loss<1?'Within threshold':'Packet loss detected';
 $('lossStatus').className='trend '+(d.loss<1?'good':'neutral');
 $('cpuValue').textContent=d.cpu.toFixed(0)+'%';$('memoryValue').textContent=d.memory.toFixed(0)+'%';
 $('cpuState').textContent=d.cpu>75?'High utilization':d.cpu>50?'Moderate load':'Normal load';
 $('memoryState').textContent=d.memory>80?'Memory pressure':d.memory>65?'Moderate usage':'Normal usage';
 $('cpuBar').style.width=d.cpu+'%';$('memoryBar').style.width=d.memory+'%';setGauge('cpuGauge',d.cpu,colors.cpu);setGauge('memoryGauge',d.memory,colors.memory);
 $('devLat1').textContent=Math.max(4,d.latency*.35).toFixed(0)+' ms';$('devLat2').textContent=d.latency.toFixed(0)+' ms';$('devLat3').textContent=(d.latency*1.4).toFixed(0)+' ms';
 drawLine('rxSpark',history.rx,colors.rx,true);drawLine('txSpark',history.tx,colors.tx,true);drawTraffic();
}
function connect(){
 const scheme=location.protocol==='https:'?'wss':'ws';socket=new WebSocket(`${scheme}://${location.host}/ws`);
 socket.addEventListener('open',()=>{setConnection(true,'WebSocket active');$('pauseBtn').disabled=false;addEvent('WebSocket connected','Persistent bidirectional channel established.');});
 socket.addEventListener('message',(event)=>{let d;try{d=JSON.parse(event.data)}catch{return}
  if(d.type==='metrics'){handleMetrics(d);$('clock').textContent=d.time;}
  if(d.type==='status'){addEvent(d.message,'Server event received over WebSocket.',d.message.toLowerCase().includes('pause'));showToast(d.message);}
  if(d.type==='pong'){addEvent('WebSocket pong','Server replied at '+d.time);showToast('Pong received from server');}
 });
 socket.addEventListener('close',()=>{setConnection(false);$('pauseBtn').disabled=true;setTimeout(connect,1800);});
 socket.addEventListener('error',()=>setConnection(false));
}
$('pauseBtn').addEventListener('click',()=>{paused=!paused;$('pauseBtn').textContent=paused?'▶ Resume stream':'Ⅱ Pause stream';if(socket&&socket.readyState===WebSocket.OPEN)socket.send(JSON.stringify({action:'pause',value:paused}));});
$('pingBtn').addEventListener('click',()=>{if(socket&&socket.readyState===WebSocket.OPEN){socket.send(JSON.stringify({action:'ping'}));showToast('Ping sent over WebSocket');}else showToast('WebSocket is not connected yet');});
$('refreshBtn').addEventListener('click',()=>{showToast('Endpoint table refreshed');addEvent('Endpoint inventory refreshed','3 demo endpoints checked.');});
window.addEventListener('resize',()=>{drawTraffic();drawLine('rxSpark',history.rx,colors.rx,true);drawLine('txSpark',history.tx,colors.tx,true)});
setConnection(false,'Connecting…');connect();
