const $ = (id) => document.getElementById(id);
const history = {rx:[], tx:[], cpu:[], memory:[]};
const fmtMB=(m)=>m>=1024?(m/1024).toFixed(2)+' GB':m.toFixed(1)+' MB';
const fmtRate=(v)=>v>=100?v.toFixed(0):v>=10?v.toFixed(1):v.toFixed(2);
const MAX = 30;
let socket, paused = false, eventCount = 0, toastTimer;
const colors = {rx:'#4d8dff', tx:'#a78bfa', cpu:'#4d8dff', memory:'#a78bfa', disk:'#36d6a0', gpu:'#f4b860'};
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
 const vals=[...history.rx,...history.tx],max=Math.max(1,...vals)*1.2,left=30,right=8,top=9,bottom=19,plotW=w-left-right,plotH=h-top-bottom;
 ctx.font='9px DM Sans';ctx.textAlign='right';ctx.fillStyle='#71809b';ctx.strokeStyle='#26334a';ctx.lineWidth=1;
 for(let i=0;i<=4;i++){let y=top+plotH*i/4;ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(w-right,y);ctx.stroke();const lv=max*(1-i/4);ctx.fillText(lv>=10?Math.round(lv):lv.toFixed(1),left-7,y+3);}
 for(let i=0;i<5;i++){let x=left+plotW*i/4;ctx.beginPath();ctx.moveTo(x,top);ctx.lineTo(x,top+plotH);ctx.stroke();}
 const series=[['rx','#4d8dff'],['tx','#a78bfa']];
 series.forEach(([key,color])=>{const arr=history[key];if(arr.length<2)return;const pts=arr.map((v,i)=>[left+plotW*i/(MAX-1),top+plotH-(v/max)*plotH]);ctx.beginPath();pts.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.lineWidth=2;ctx.strokeStyle=color;ctx.stroke();ctx.lineTo(pts[pts.length-1][0],top+plotH);ctx.lineTo(pts[0][0],top+plotH);ctx.closePath();ctx.fillStyle=color+'13';ctx.fill();});
}
function setGauge(id, value, color){
 $(id).style.background=`conic-gradient(${color} 0deg ${Math.min(100,value)*3.6}deg,#26334b ${Math.min(100,value)*3.6}deg 360deg)`;
}
function renderEndpoints(list){
 if(!list)return;const body=$('deviceRows');body.replaceChildren();
 $('devSub').textContent='Live latency probes · '+list.length+' endpoints';
 list.forEach(e=>{const tr=document.createElement('tr');
  const c1=document.createElement('td');const ic=document.createElement('span');ic.className='device-icon';ic.textContent='▣';const nm=document.createElement('b');nm.textContent=e.name;c1.append(ic,nm);
  const c2=document.createElement('td');c2.textContent=e.host;
  const c3=document.createElement('td');const st=document.createElement('span');st.className='status '+(e.online?'online':'offline');st.textContent=e.online?'● Online':'● Unreachable';c3.append(st);
  const c4=document.createElement('td');c4.textContent=e.latency==null?'—':e.latency.toFixed(0)+' ms';
  const c5=document.createElement('td');c5.textContent='Just now';
  tr.append(c1,c2,c3,c4,c5);body.append(tr);});
}
const alerted={};
function alertOnce(key,cond,title,detail){if(cond&&!alerted[key]){alerted[key]=true;addEvent(title,detail,true);}else if(!cond&&alerted[key]){alerted[key]=false;addEvent(title.replace(/^.*$/,'Recovered: '+key),'Metric back to normal.');}}
const el=(t,c,txt)=>{const e=document.createElement(t);if(c)e.className=c;if(txt!=null)e.textContent=txt;return e};
const lvl=(p)=>p>90?'crit':p>75?'warn':'';
const num=(v,dp=0,u='')=>v==null?'—':v.toFixed(dp)+u;
function mkBar(cls,p){const b=el('div','bar '+cls);const i=el('i',lvl(p));i.style.width=Math.min(100,p||0)+'%';b.append(i);return b}
function renderGpus(list){
 const box=$('gpuList');box.replaceChildren();
 if(!list||!list.length){$('gpuSub').textContent='No GPU telemetry available';box.append(el('div','empty-event','No GPU detected (or driver tools such as nvidia-smi are unavailable).'));return}
 $('gpuSub').textContent=list.length+' GPU'+(list.length>1?'s':'')+' · live utilization';
 list.forEach((g,i)=>{const c=el('div','gpu-card');
  const t=el('div','hw-title');t.append(el('b',null,'GPU '+i+' · '+g.name),el('span',null,g.vendor));c.append(t);
  const memTxt=g.mem_total_gb!=null?num(g.mem_used_gb,1)+' / '+g.mem_total_gb+' GB':'—';
  c.append(el('div','hw-sub','Utilization '+(g.usage==null?'n/a':g.usage.toFixed(0)+'%')+' · VRAM '+memTxt));
  c.append(mkBar('',g.usage));
  if(g.mem_total_gb)c.append(mkBar('mem',100*g.mem_used_gb/g.mem_total_gb));
  const m=el('div','gpu-metrics');
  [['Usage',num(g.usage,0,'%')],['Temp',num(g.temp,0,'°C')],['Power',num(g.power,0,' W')],['Clock',num(g.clock,0,' MHz')]].forEach(([k,v])=>{const d=el('div',null,k);d.append(el('b',null,v));m.append(d)});
  c.append(m);box.append(c)});
}
function renderVolumes(list,rd,wr){
 $('ioRead').textContent=rd.toFixed(1);$('ioWrite').textContent=wr.toFixed(1);
 const box=$('volList');box.replaceChildren();
 $('volSub').textContent=list.length+' volume'+(list.length===1?'':'s')+' detected';
 list.forEach(v=>{const c=el('div','vol-item');const t=el('div','hw-title');
  t.append(el('b',null,v.mount+(v.model?' · '+v.model:'')),el('span',null,v.percent.toFixed(0)+'% used'));c.append(t);
  c.append(el('div','hw-sub',[v.kind,v.fstype,v.used_gb+' / '+v.total_gb+' GB',v.free_gb+' GB free'].filter(Boolean).join(' · ')));
  c.append(mkBar('disk',v.percent));box.append(c)});
}
function renderHardware(list){
 const body=$('hwRows');body.replaceChildren();$('hwCount').textContent=list.length+' components';
 list.forEach(x=>{const tr=el('tr');const a=el('td');a.append(el('span','type-tag',x.type));
  const b=el('td');b.append(el('b',null,x.name));tr.append(a,b,el('td',null,x.detail||''));body.append(tr)});
}

let bdView='services', lastBd=null;
const fmtBw=(m)=>m>=1?fmtRate(m)+' Mbps':(m*1000).toFixed(0)+' Kbps';
function renderBreakdown(bd){
 if(bd)lastBd=bd;else bd=lastBd;
 const box=$('bdList');if(!box)return;box.replaceChildren();
 if(!bd){box.append(el('div','empty-event','Waiting for traffic data…'));return}
 if(!bd.available){$('bdSub').textContent='Capture unavailable';box.append(el('div','empty-event',bd.reason||'Packet capture is not running.'));return}
 const rows=(bdView==='apps'?bd.apps:bd.services)||[];
 $('bdSub').textContent='Top '+(bdView==='apps'?'applications':'services')+' by bandwidth · sorted high → low';
 if(!rows.length){box.append(el('div','empty-event','No traffic observed yet.'));return}
 const top=rows[0].avg||1;
 rows.forEach((r,i)=>{
  const row=el('div','bd-row');
  row.append(el('span','bd-rank',String(i+1)),el('b','bd-name',r.name));
  const track=el('div','bd-track');const fill=el('div','bd-fill');fill.style.width=Math.max(2,100*r.avg/top)+'%';
  const rxw=r.rx+r.tx>0?100*r.rx/(r.rx+r.tx):50;
  const a=el('i','bd-rx');a.style.width=rxw+'%';const b=el('i','bd-tx');b.style.width=(100-rxw)+'%';fill.append(a,b);track.append(fill);
  row.append(track);
  const v=el('span','bd-val',fmtBw(r.avg));v.append(el('small',null,' ↓'+fmtBw(r.rx)+' ↑'+fmtBw(r.tx)));
  row.append(v,el('span','bd-share',r.share.toFixed(0)+'%'),el('span','bd-total',fmtMB(r.total_mb)));
  box.append(row);
 });
}
document.querySelectorAll('.bd-tab').forEach(t=>t.addEventListener('click',()=>{bdView=t.dataset.view;document.querySelectorAll('.bd-tab').forEach(x=>x.classList.toggle('active',x===t));renderBreakdown();}));
function updateHealthNames(d){
 const info=window.sysInfo||{},hw=window.hw||[];
 $('cpuName').textContent=info.cpu||'Processor';
 $('cpuDetail').textContent=[info.cores?info.cores+' threads':null,d.cpu_freq?(d.cpu_freq/1000).toFixed(2)+' GHz now':null].filter(Boolean).join(' · ')||'Processor utilization';
 const mods=hw.filter(x=>x.type==='RAM');
 $('memName').textContent=mods.length?mods.length+'× '+mods[0].name+(mods[0].detail?' ('+mods[0].detail+')':''):'System memory'+(info.ram_gb?' · '+info.ram_gb+' GB':'');
 const sys=(d.volumes||[]).find(v=>v.mount==='/'||/^C/i.test(v.mount))||(d.volumes||[])[0];
 $('diskName').textContent=sys?(sys.mount+(sys.model?' · '+sys.model:'')+(sys.kind?' ('+sys.kind+')':'')):'System drive';
 const g=(d.gpus||[])[0],row=$('gpuRow');
 if(!g){row.hidden=true;return}
 row.hidden=false;$('gpuName').textContent=g.name;
 const u=g.usage==null?0:g.usage;
 $('gpuValue').textContent=g.usage==null?'n/a':u.toFixed(0)+'%';
 $('gpuState').textContent=g.usage==null?'No usage data':u>85?'High utilization':u>50?'Moderate load':'Normal load';
 $('gpuDetail').textContent=[g.mem_total_gb?'VRAM '+num(g.mem_used_gb,1)+' / '+g.mem_total_gb+' GB':null,g.temp!=null?g.temp.toFixed(0)+'°C':null].filter(Boolean).join(' · ')||'Graphics';
 $('gpuBar').style.width=u+'%';setGauge('gpuGauge',u,colors.gpu);
}
function handleMetrics(d){
 updateHealthNames(d);
 renderGpus(d.gpus);renderVolumes(d.volumes||[],d.disk_read||0,d.disk_write||0);
 alertOnce('cpu',d.cpu>90,'High CPU usage','CPU at '+d.cpu.toFixed(0)+'%');alertOnce('memory',d.memory>90,'High memory usage','Memory at '+d.memory.toFixed(0)+'%');alertOnce('network',!d.online,'Internet unreachable','All probes timed out');
 for(const key of ['rx','tx','cpu','memory']){history[key].push(d[key]);if(history[key].length>MAX)history[key].shift();}
 $('rxValue').textContent=fmtRate(d.rx);$('txValue').textContent=fmtRate(d.tx);$('rxTotal').textContent='Total '+fmtMB(d.total_rx);$('txTotal').textContent='Total '+fmtMB(d.total_tx);
 $('latencyValue').textContent=d.online?d.latency.toFixed(0):'—';$('lossValue').textContent=d.loss.toFixed(2);
 $('chartRx').innerHTML=fmtRate(d.rx)+' <small>Mbps</small>';$('chartTx').innerHTML=fmtRate(d.tx)+' <small>Mbps</small>';
 $('latencyBar').style.width=Math.min(100,d.latency/2)+'%';$('latencyStatus').textContent=!d.online?'Offline':d.latency<80?'Healthy':'Elevated';
 $('lossBar').style.width=Math.min(100,d.loss*40)+'%';$('lossStatus').textContent=d.loss===0?'No packet loss':d.loss<1?'Within threshold':'Packet loss detected';
 $('lossStatus').className='trend '+(d.loss<1?'good':'neutral');
 $('cpuValue').textContent=d.cpu.toFixed(0)+'%';$('memoryValue').textContent=d.memory.toFixed(0)+'%';
 $('cpuState').textContent=d.cpu>75?'High utilization':d.cpu>50?'Moderate load':'Normal load';
 $('memoryState').textContent=d.memory>80?'Memory pressure':d.memory>65?'Moderate usage':'Normal usage';
 $('memDetail').textContent=d.memory_used_gb+' GB in use of '+(window.sysInfo?sysInfo.ram_gb+' GB':'RAM');$('diskValue').textContent=d.disk.toFixed(0)+'%';$('diskState').textContent=d.disk>90?'Almost full':d.disk>75?'Filling up':'Healthy';$('diskFree').textContent=d.disk_free_gb+' GB free';$('diskBar').style.width=d.disk+'%';setGauge('diskGauge',d.disk,colors.disk);$('cpuBar').style.width=d.cpu+'%';$('memoryBar').style.width=d.memory+'%';setGauge('cpuGauge',d.cpu,colors.cpu);setGauge('memoryGauge',d.memory,colors.memory);
  renderEndpoints(d.endpoints);renderBreakdown(d.breakdown);
 drawLine('rxSpark',history.rx,colors.rx,true);drawLine('txSpark',history.tx,colors.tx,true);drawTraffic();
}
function connect(){
 const scheme=location.protocol==='https:'?'wss':'ws';socket=new WebSocket(`${scheme}://${location.host}/ws`);
 socket.addEventListener('open',()=>{setConnection(true,'WebSocket active');$('pauseBtn').disabled=false;addEvent('WebSocket connected','Persistent bidirectional channel established.');});
 socket.addEventListener('message',(event)=>{let d;try{d=JSON.parse(event.data)}catch{return}
  if(d.type==='hello'){window.sysInfo=d.info;$('hostName').textContent=d.info.hostname;$('userTitle').textContent=d.info.os;$('sysInfo').textContent=d.info.hostname+' · '+d.info.os+' · '+d.info.cores+' logical cores · '+d.info.ram_gb+' GB RAM';$('verLabel').textContent='v'+d.version;}
  if(d.type==='hardware'){window.hw=d.components;renderHardware(d.components);}
  if(d.type==='metrics'){handleMetrics(d);$('clock').textContent=d.time;}
  if(d.type==='status'){addEvent(d.message,'Server event received over WebSocket.',d.message.toLowerCase().includes('pause'));showToast(d.message);}
  if(d.type==='pong'){addEvent('WebSocket pong','Server replied at '+d.time);showToast('Pong received from server');}
 });
 socket.addEventListener('close',()=>{setConnection(false);$('pauseBtn').disabled=true;setTimeout(connect,1800);});
 socket.addEventListener('error',()=>setConnection(false));
}
$('pauseBtn').addEventListener('click',()=>{paused=!paused;$('pauseBtn').textContent=paused?'▶ Resume stream':'Ⅱ Pause stream';if(socket&&socket.readyState===WebSocket.OPEN)socket.send(JSON.stringify({action:'pause',value:paused}));});
$('pingBtn').addEventListener('click',()=>{if(socket&&socket.readyState===WebSocket.OPEN){socket.send(JSON.stringify({action:'ping'}));showToast('Ping sent over WebSocket');}else showToast('WebSocket is not connected yet');});
$('refreshBtn').addEventListener('click',()=>{if(socket&&socket.readyState===WebSocket.OPEN)socket.send(JSON.stringify({action:'refresh'}));});
window.addEventListener('resize',()=>{drawTraffic();drawLine('rxSpark',history.rx,colors.rx,true);drawLine('txSpark',history.tx,colors.tx,true)});
setConnection(false,'Connecting…');connect();


// Chuyển giữa các trang trong sidebar. Bốn trang mới hiện đang để trống,
// chưa gọi API hoặc xử lý dữ liệu riêng.
const pageTitles = {
  overview: 'Overview',
  'traffic-analytics': 'Traffic analytics',
  'hardware-page': 'Hardware',
  'devices-page': 'Devices',
  'event-log': 'Event log'
};
function showPage(page) {
  const isOverview = page === 'overview';
  document.querySelectorAll('.main > :not(.topbar):not(#blankPage)').forEach(section => {
    section.hidden = !isOverview;
  });
  $('blankPage').hidden = page !== 'devices-page';
  $('trafficPage').hidden = page !== 'traffic-analytics';
  $('eventPage').hidden = page !== 'event-log';
  $('hardwarePage').hidden = page !== 'hardware-page';
  if(page === 'hardware-page') refreshHardware();
  $('currentPageName').textContent = pageTitles[page] || 'Overview';
  document.querySelectorAll('.sidebar .nav[data-page]').forEach(link => {
    const active = link.dataset.page === page;
    link.classList.toggle('active', active);
    if (active) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
}
document.querySelectorAll('.sidebar .nav[data-page]').forEach(link => {
  link.addEventListener('click', event => {
    event.preventDefault();
    showPage(link.dataset.page);
    window.history.replaceState(null, '', link.getAttribute('href'));
  });
});


// Hardware details + persisted alert rules; separate from legacy Overview rendering.
let hardwarePoll = null, rulesLoaded = false;
const hwLabels = {cpu:'CPU usage',memory:'RAM usage',disk:'Disk usage',cpu_temp:'CPU temperature',gpu_temp:'GPU temperature',gpu_usage:'GPU usage'};
function hwTile(name, value, detail='') {
  const tile=el('div','hw-detail-tile');tile.append(el('span','hw-tile-name',name),el('b',null,value==null?'N/A':String(value)),el('small',null,detail));return tile;
}
function renderHardwareDetail(d) {
  const m=d.metrics||{}, live=d.live||{}, info=d.info||{}, components=d.components||[];
  const root=$('hardwareSummary');
  const opened=new Set([...root.querySelectorAll('details[open]')].map(x=>x.dataset.key));
  root.replaceChildren();
  const left=el("div","hw-column"), right=el("div","hw-column");root.append(left,right);
  const groups=new Map();
  for(const s of d.sensors||[]){const key=s.hardware_id||String(s.id||'').split('/').slice(0,-2).join('/')||s.hardware||'Other';if(!groups.has(key))groups.set(key,{key,name:s.hardware||key,items:[]});groups.get(key).items.push(s);}
  const remaining=new Set(groups.values());
  const norm=x=>String(x||'').toLowerCase().replace(/[^a-z0-9]/g,'');
  const byType=t=>components.filter(c=>c.type===t);
  const match=(name,pattern)=>[...remaining].filter(g=>pattern.test(g.key)&&norm(g.name)===norm(name));
  const valid=v=>typeof v==='number'&&Number.isFinite(v);
  const fmt=(v,u='')=>valid(v)?Number(v.toFixed(2))+(u?' '+u:''):'N/A';
  const temp=v=>valid(v)&&v>0?v:null;
  const positive=v=>valid(v)&&v>0?v:null;
  const read=(gs,type,re)=>gs.flatMap(g=>g.items).find(s=>String(s.type).toLowerCase()===type.toLowerCase()&&re.test(s.name)&&valid(s.value))?.value;
  const section=(title,subtitle,kind)=>{const p=el('article','panel hw-unit hw-'+kind);const h=el('div','hw-unit-head');h.append(el('h2',null,title),el('p',null,subtitle));p.append(h);(["cpu","ram","other"].includes(kind)?left:right).append(p);return p;};
  const block=(p,name,detail,metrics,gs=[])=>{const b=el('div','hw-unit-block');b.append(el('h3',null,name));if(detail)b.append(el('p','hw-unit-detail',detail));if(metrics.length){const grid=el('div','hw-unit-metrics');for(const [label,value] of metrics)grid.append(hwTile(label,value));b.append(grid);}for(const g of gs){remaining.delete(g);const det=el('details','hw-unit-sensors');det.dataset.key=g.key;det.open=opened.has(g.key);det.append(el('summary',null,'Detailed sensors · '+g.items.length));const table=el('div','hw-sensor-table');for(const s of g.items){const row=el('div','hw-sensor-row');row.append(el('span',null,s.name+' · '+s.type),el('b',null,valid(s.value)?(s.display||fmt(s.value,s.unit)):'N/A'),el('small',null,'Min '+(s.min||'N/A')+' / Max '+(s.max||'N/A')));table.append(row);}det.append(table);b.append(det);}p.append(b);};
  const cpu=section('CPU','Processor telemetry','cpu');const cg=[...remaining].filter(g=>/cpu|k10temp|coretemp/i.test(g.key));
  block(cpu,byType('CPU')[0]?.name||info.cpu||'Processor',byType('CPU')[0]?.detail||'', [['Usage',fmt(m.cpu,'%')],['Temperature',fmt(temp(temp(read(cg,'Temperature',/tctl|package/i))??temp(m.cpu_temp)),'°C')],['Clock',fmt(positive(read(cg,'Clock',/^cores \(average\)$/i))??positive(live.cpu_freq),'MHz')],['Package power',fmt(positive(read(cg,'Power',/^package$/i)),'W')]],cg);
  const gpu=section('GPU','Graphics adapters','gpu');const names=[...new Set([...byType('GPU').map(c=>c.name),...(live.gpus||[]).map(g=>g.name)])];
  const virtual=names.filter(n=>/virtual|remote display|indirect display/i.test(n));
  for(const name of names.filter(n=>!virtual.includes(n))){const g=(live.gpus||[]).find(x=>x.name===name)||{};const gs=match(name,/gpu/i);const c=byType('GPU').find(x=>x.name===name);block(gpu,name,c?.detail||'', [['Usage',fmt(read(gs,'Load',/^gpu core$/i)??g.usage,'%')],['Temperature',fmt(temp(read(gs,'Temperature',/^gpu core$/i)??g.temp),'°C')],['Hotspot',fmt(temp(read(gs,'Temperature',/hot.?spot/i)),'°C')],['Clock',fmt(read(gs,'Clock',/^gpu core$/i)??g.clock,'MHz')],['Power',fmt(read(gs,'Power',/total|board|package/i)??g.power,'W')],['VRAM used',valid(g.mem_used_gb)?fmt(g.mem_used_gb,'GB'):fmt(read(gs,'SmallData',/memory used/i),'MB')]],gs);}
  if(virtual.length){const det=el('details','hw-unit-sensors');det.dataset.key='virtual-gpus';det.open=opened.has(det.dataset.key);det.append(el('summary',null,'Virtual display adapters · '+virtual.length));for(const name of virtual)det.append(el('p','hw-unit-detail',name));gpu.append(det);}
  for(const g of [...remaining].filter(g=>/gpu/i.test(g.key)))block(gpu,g.name,'Sensor provider',[],[g]);
  const ram=section('RAM','System memory','ram');const rg=[...remaining].filter(g=>/ram|memory|dimm/i.test(g.key)&&!/gpu/i.test(g.key));block(ram,'Memory utilization','',[['Usage',fmt(m.memory,'%')],['Usable capacity',fmt(info.ram_gb,'GB')]],rg);for(const c of byType('RAM'))block(ram,c.name.replace(/^Unknown\s+(?=CT\d)/i,'Crucial ').replace(/^Unknown\s+(?=F[345]-)/i,'G.Skill '),c.detail,[]);
  const disk=section('Storage','Physical drives and volumes','disk');for(const c of byType('Disk')){const gs=match(c.name,/storage|hdd|ssd|nvme/i);const vs=(live.volumes||[]).filter(v=>norm(v.model)===norm(c.name));block(disk,c.name,c.detail,[['Temperature',fmt(temp(read(gs,'Temperature',/^(composite temperature|temperature|drive temperature)$/i)),'°C')],...vs.map(v=>[v.mount,fmt(v.percent,'%')+' · '+v.used_gb+'/'+v.total_gb+' GB'])],gs);}for(const v of live.volumes||[])if(!byType('Disk').some(c=>norm(c.name)===norm(v.model)))block(disk,v.mount,v.model||'', [['Used',fmt(v.percent,'%')],['Capacity',v.used_gb+'/'+v.total_gb+' GB']]);
  const other=section('System & peripherals','Motherboard, network, battery and other sensors','other');for(const c of components.filter(c=>!['CPU','GPU','RAM','Disk'].includes(c.type)))block(other,c.name,c.type+' · '+(c.detail||''),[]);for(const g of remaining)block(other,g.name,'Sensor provider',[],[g]);
  const source=[...new Set((d.sensors||[]).map(s=>s.source).filter(Boolean))];root.prepend(el('p','hw-source','Sensor source: '+(source.join(' / ')||'Unavailable')+' · Basic metrics: system APIs'));
  if(!(d.sensors||[]).length)root.append(el('p','empty-event','No additional sensors available. Check embedded sensor permissions and dependencies.'));
}
async function refreshHardware(){
  if($('hardwarePage').hidden)return;
  try {const r=await fetch('/api/hardware');if(!r.ok)throw Error('HTTP '+r.status);renderHardwareDetail(await r.json());}
  catch(e){$('alertFeedback').textContent='Hardware fetch failed: '+e.message;}
}
function renderAlertRules(rules){
 const box=$('alertRules');box.replaceChildren();
 Object.entries(rules).forEach(([key,r])=>{
  const line=el('div','alert-rule');line.dataset.key=key;
  const title=el('label');const check=document.createElement('input');check.type='checkbox';check.className='rule-enabled';check.checked=r.enabled;title.append(check,document.createTextNode(' '+hwLabels[key]));line.append(title);
  const threshold=document.createElement('input');threshold.type='number';threshold.className='rule-threshold';threshold.min='0';threshold.max=key.includes('temp')?'150':'100';threshold.step='0.5';threshold.value=r.threshold;
  const mode=document.createElement('select');mode.className='rule-mode';[['instant','Instant'],['sustained','Sustained']].forEach(([v,t])=>{const o=document.createElement('option');o.value=v;o.textContent=t;mode.append(o)});mode.value=r.mode;
  const duration=document.createElement('input');duration.type='number';duration.className='rule-duration';duration.min='0';duration.max='3600';duration.value=r.duration;
  const cooldown=document.createElement('input');cooldown.type='number';cooldown.className='rule-cooldown';cooldown.min='0';cooldown.max='86400';cooldown.value=r.cooldown;
  const wrap=(name,control)=>{const label=el('label','rule-field',name);label.append(control);return label;};
  line.append(wrap('Threshold '+(key.includes('temp')?'°C':'%'),threshold),wrap('Mode',mode),wrap('Duration (s)',duration),wrap('Cooldown (s)',cooldown));box.append(line);
 });
}
async function loadAlertRules(){
 try {const res=await fetch('/api/alerts');const d=await res.json();renderAlertRules(d.rules);
 $('telegramStatus').textContent=d.telegram_configured?'● Telegram configured':'○ Telegram not configured';rulesLoaded=true;}
 catch(e){$('alertFeedback').textContent='Cannot load rules: '+e.message;}
}
$('saveAlertRules').addEventListener('click',async()=>{
 const rules={};for(const row of document.querySelectorAll('.alert-rule')){
 const val=(cls)=>Number(row.querySelector('.'+cls).value);
 rules[row.dataset.key]={enabled:row.querySelector('.rule-enabled').checked,threshold:val('rule-threshold'),mode:row.querySelector('.rule-mode').value,duration:val('rule-duration'),cooldown:val('rule-cooldown')};}
 try{const r=await fetch('/api/alerts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(rules)});
 if(!r.ok)throw Error(await r.text());$('alertFeedback').textContent='Saved successfully';showToast('Alert rules saved');}
 catch(e){$('alertFeedback').textContent='Save failed: '+e.message;}
});
$('testTelegram').addEventListener('click',async()=>{
 $('alertFeedback').textContent='Sending test…';try{const r=await fetch('/api/telegram/test',{method:'POST'});const d=await r.json();$('alertFeedback').textContent=d.message;}
 catch(e){$('alertFeedback').textContent='Telegram error: '+e.message;}
});
$('hardwareRefresh').addEventListener('click',refreshHardware);
loadAlertRules();
setInterval(refreshHardware,3000);
if(location.hash==='#hardware-page')showPage('hardware-page');
