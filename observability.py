"""Local persistent telemetry; no credentials or packet payloads stored."""
import asyncio, csv, io, json, sqlite3, time, datetime as dt, subprocess, sys, socket, re
from pathlib import Path
from collections import deque
import psutil
from aiohttp import web

class Store:
    def __init__(self,path):
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(path)
        self.db.executescript('''PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, ts REAL, level TEXT, source TEXT, message TEXT, parent INTEGER, acknowledged INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS usage(day TEXT PRIMARY KEY, rx INTEGER, tx INTEGER, up REAL, observed REAL);
        CREATE INDEX IF NOT EXISTS event_ts ON events(ts);''')
        self.db.commit()
    def event(self,level,source,message,parent=None):
        with self.db:
            return self.db.execute('INSERT INTO events(ts,level,source,message,parent) VALUES(?,?,?,?,?)',(time.time(),level,source,message,parent)).lastrowid
    def sample(self,rx,tx,up,elapsed):
        with self.db:
            self.db.execute('INSERT INTO usage VALUES(?,?,?,?,?) ON CONFLICT(day) DO UPDATE SET rx=rx+excluded.rx,tx=tx+excluded.tx,up=up+excluded.up,observed=observed+excluded.observed',(dt.date.today().isoformat(),rx,tx,elapsed if up else 0,elapsed))
    def history(self):
        today=dt.date.today(); out={}
        for label,start in [('day',today),('week',today-dt.timedelta(days=today.weekday())),('month',today.replace(day=1))]:
            r=self.db.execute('SELECT coalesce(sum(rx),0),coalesce(sum(tx),0),coalesce(sum(up),0),coalesce(sum(observed),0) FROM usage WHERE day>=? AND day<=?',(str(start),str(today))).fetchone();out[label]=dict(zip(('rx','tx','up','observed'),r))
        return out
    def events(self,q,limit=500):
        sql='SELECT id,ts,level,source,message,parent,acknowledged FROM events WHERE 1=1'; args=[]
        for key in ('level','source'):
            if q.get(key):sql+=' AND '+key+'=?';args.append(q[key])
        if q.get('q'):sql+=' AND message LIKE ?';args.append('%'+q['q']+'%')
        if q.get('since'):sql+=' AND ts>=?';args.append(float(q['since']))
        cur=self.db.execute(sql+' ORDER BY id DESC LIMIT ?',(*args,limit));return [dict(zip([c[0] for c in cur.description],r)) for r in cur]

def command(args,timeout=12):
    try:
        p=subprocess.run(args,capture_output=True,text=True,errors='replace',timeout=timeout,**({'creationflags':0x08000000} if sys.platform=='win32' else {}));return {'output':(p.stdout+p.stderr)[-16000:],'code':p.returncode}
    except Exception as e:return {'output':type(e).__name__,'code':-1}

def interfaces():
    stats=psutil.net_if_stats(); counters=psutil.net_io_counters(pernic=True); result=[]
    for name,addresses in psutil.net_if_addrs().items():
        s=stats.get(name); c=counters.get(name);result.append({'name':name,'up':s.isup if s else None,'speed':s.speed if s else None,'mtu':s.mtu if s else None,'addresses':[{'family':str(a.family.name),'address':a.address,'netmask':a.netmask} for a in addresses],'counters':c._asdict() if c else {}})
    wifi=command(['netsh','wlan','show','interfaces']) if sys.platform=='win32' else {'output':'Wi-Fi details unavailable on this platform'}
    config=command(['ipconfig','/all']) if sys.platform=='win32' else {'output':'See interface addresses'}
    try:
        rows=[]; names={}
        for c in psutil.net_connections(kind='inet'):
            if c.pid not in names:
                try:names[c.pid]=psutil.Process(c.pid).name()
                except (psutil.Error,TypeError):names[c.pid]='Unknown'
            addr=lambda a: f'{a.ip}:{a.port}' if a else '—'
            rows.append({'process':names[c.pid],'pid':c.pid,'protocol':'TCP' if c.type==socket.SOCK_STREAM else 'UDP','local':addr(c.laddr),'remote':addr(c.raddr),'state':c.status})
        error=None
    except psutil.Error as e:rows=[];error=type(e).__name__
    return {'interfaces':result,'wifi':wifi['output'],'config':config['output'],'connections':rows[:2000],'connection_error':error}

async def probe():
    args=['ping','-n','4','-w','1000','1.1.1.1'] if sys.platform=='win32' else ['ping','-c','4','-W','1','1.1.1.1']
    r=await asyncio.to_thread(command,args,12); times=[float(x.replace(',','.')) for x in re.findall(r'time\s*[=<]\s*(\d+(?:[.,]\d+)?)\s*ms',r['output'],re.I)]
    loss=100*(4-len(times))/4 if times or re.search(r'100%|100 %',r['output']) else None
    latency=sum(times)/len(times) if times else None;jitter=sum(abs(a-b) for a,b in zip(times,times[1:]))/(len(times)-1) if len(times)>1 else None
    score=round(max(0,100-(loss or 0)*0.7-min(30,(latency or 0)/5)-min(20,(jitter or 0)/2))) if loss is not None else None
    if loss==100:score=0
    return {'latency':latency,'jitter':jitter,'loss':loss,'score':score,'raw':r['output']}

async def context(app):
    store=app['store'];store.event('INFO','System','NetPulse started');app['network_detail']={};app['quality']={};app['series']=deque(maxlen=60)
    async def slow():
        while True:
            try:app['network_detail'],app['quality']=await asyncio.gather(asyncio.to_thread(interfaces),probe())
            except Exception as e:store.event('ERROR','Network',type(e).__name__)
            await asyncio.sleep(10)
    task=asyncio.create_task(slow())
    try:yield
    finally:
        task.cancel();await asyncio.gather(task,return_exceptions=True);store.event('INFO','System','NetPulse stopped');store.db.close()

async def traffic(request):
    a=request.app;return web.json_response({'live':a['collector'].latest or {},'detail':a['network_detail'],'quality':a['quality'],'history':a['store'].history(),'series':list(a['series'])})
async def events(request):
    try:rows=request.app['store'].events(request.query,100000 if request.query.get('format') else 500)
    except ValueError:raise web.HTTPBadRequest()
    fmt=request.query.get('format')
    if fmt=='csv':
        f=io.StringIO();w=csv.DictWriter(f,fieldnames=['id','ts','level','source','message','parent','acknowledged']);w.writeheader();w.writerows(rows);return web.Response(text=f.getvalue(),content_type='text/csv',headers={'Content-Disposition':'attachment; filename=events.csv'})
    return web.json_response(rows,headers={'Content-Disposition':'attachment; filename=events.json'} if fmt=='json' else {})
async def ack(request):
    s=request.app['store'];
    with s.db:s.db.execute('UPDATE events SET acknowledged=1 WHERE id=?',(int(request.match_info['id']),))
    return web.json_response({'ok':True})
async def diagnostics(request):
    kind=request.match_info['kind']; win=sys.platform=='win32'; commands={'ping':['ping','-n' if win else '-c','4','1.1.1.1'],'trace':['tracert','-d','-h','12','-w','500','1.1.1.1'] if win else ['traceroute','-n','-m','12','1.1.1.1'],'dns':['nslookup','example.com']}
    if kind not in commands:raise web.HTTPNotFound()
    return web.json_response(await asyncio.to_thread(command,commands[kind],25))
