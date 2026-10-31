'use strict';
const $=id=>document.getElementById(id),R={data:null,candidates:[],selected:new Set(),limit:150,request:0,loading:false,busy:false,count:110,start:0,hover:-1,geometry:null};
const canvas=$('chart'),ctx=canvas.getContext('2d'),params=new URLSearchParams(location.search);
const pct=n=>n==null?'—':(n>0?'+':'')+(n*100).toFixed(2)+'%',price=n=>n==null?'—':Number(n).toFixed(2),tone=n=>n>0?'up':n<0?'down':'neutral';
function error(message){$('error').textContent=message||'';$('error').hidden=!message;}
async function api(path,data){const response=await fetch(path,{cache:'no-store',...(data?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}:{})});const result=await response.json();if(!response.ok)throw Error(result.error||'读取失败');return result;}
function busy(on){R.busy=on;document.querySelectorAll('button').forEach(b=>b.disabled=on);if(!on){updateSelected();if(R.data&&!$('practice').hidden)updateActions();}}
function filters(){return {scope:$('scope').value,direction:$('direction').value,year:$('year').value,q:$('search').value.trim()};}
function backLink(){const f=filters(),p=new URLSearchParams({pattern:'volume'});if(f.scope==='leaders')p.set('scope','leaders');p.set('direction',f.direction);$('back').href='/?'+p;}
async function loadCandidates(initial=false){
 const token=++R.request;R.loading=true;updateSelected();error('');$('candidate-count').textContent='正在筛选…';
 try{const d=await api('/api/replay/candidates?'+new URLSearchParams(filters()));if(token!==R.request)return;R.candidates=d.rows;R.limit=150;
  if(initial){const year=params.get('year')||'';$('year').replaceChildren();const all=document.createElement('option');all.value='';all.textContent='全部年份';$('year').append(all);for(const y of d.years){const o=document.createElement('option');o.value=y;o.textContent=y+'年';$('year').append(o);}$('year').value=year;}
  $('candidate-count').textContent=d.total+'个可练信号';$('availability').textContent=d.availability+'；新测试还需D61有效开盘。复盘展示截至D120的可用行情。行情截至 '+d.cutoff+'。';renderCandidates();backLink();
 }catch(e){if(token===R.request){R.candidates=[];error(e.message);}}finally{if(token===R.request){R.loading=false;updateSelected();}}
}
function renderCandidates(){
 const list=$('candidates');list.replaceChildren();
 if(!R.candidates.length){const p=document.createElement('p');p.className='empty';p.textContent='当前筛选下没有完整60日行情的信号';list.append(p);}
 for(const s of R.candidates.slice(0,R.limit)){
  const label=document.createElement('label');label.className='candidate';const input=document.createElement('input');input.type='checkbox';input.checked=R.selected.has(s.id);input.setAttribute('aria-label',`${s.name} ${s.code} ${s.date}`);
  input.addEventListener('change',()=>{if(input.checked){if(R.selected.size>=200){input.checked=false;error('一次最多选择200个信号');return;}R.selected.add(s.id);}else R.selected.delete(s.id);updateSelected();});
  const body=document.createElement('div'),name=document.createElement('strong'),code=document.createElement('small'),tag=document.createElement('span'),date=document.createElement('time');
  name.textContent=(s.is_leader?'★ ':'')+s.name;if(s.is_leader)name.className='star';code.textContent=s.code;tag.className='tag';tag.textContent=s.direction==='2'?'方向1.2':'方向1.1';date.textContent=s.date;body.append(name,code,tag);label.append(input,body,date);list.append(label);
 }
 if(R.limit<R.candidates.length){const more=document.createElement('button');more.textContent='再显示150条';more.addEventListener('click',()=>{R.limit+=150;renderCandidates();});list.append(more);}
 updateSelected();
}
function updateSelected(){const n=Number($('round-count').value);$('random-ten').disabled=R.busy||R.loading||R.candidates.length<n;$('random-ten').textContent=`随机开始 · ${n}轮`;$('random-hint').textContent=R.loading?'正在更新筛选…':R.candidates.length<n?`当前筛选不足${n}个信号，请放宽条件。`:`从当前筛选随机抽取${n}个不同信号，每轮全仓、自动买入；完成${n}轮后结束。`;$('selected-count').textContent=`已选${R.selected.size}个`;$('start').disabled=R.busy||R.selected.size===0;}
async function savedSessions(){try{const d=await api('/api/replay/sessions');$('saved').replaceChildren();const first=document.createElement('option');first.value='';first.textContent='继续已保存练习';$('saved').append(first);for(const s of d.sessions){const o=document.createElement('option');o.value=s.id;o.textContent=s.title+' · '+s.updated_at.slice(0,16).replace('T',' ');$('saved').append(o);}}catch(e){error(e.message);}}
function updateActions(){
 const d=R.data;if(!d)return;
 for(const [id,show] of [['buy',d.stage==='signal'],['skip',d.stage==='signal'&&d.mode!=='random10'],['advance',['holding','closed'].includes(d.stage)],['sell',['holding','closed'].includes(d.stage)],['next-round',['closed','skipped'].includes(d.stage)&&d.has_next],['review',d.stage==='closed'&&!d.review&&!d.read_only]]){$(id).hidden=!show;$(id).disabled=R.busy;}
 $('advance').disabled=R.busy||d.stage!=='holding';$('sell').disabled=R.busy||d.stage!=='holding';$('next-stock-panel').hidden=!(['closed','skipped'].includes(d.stage)&&d.has_next&&!d.read_only);$('next-stock-note').textContent=`第${d.round}轮已结束，结算净值 ${d.realized_nav.toFixed(4)}。查看结果后，可在右侧进入第${d.round+1}轮。`;$('export').disabled=R.busy;$('return-current').hidden=!d.read_only;if(d.read_only){$('next-round').hidden=true;$('review').hidden=true;}
}
function setMetric(id,value,n){$(id).textContent=value;$(id).className=n===undefined?'':tone(n);}
function showState(d){
 R.data=d;R.hover=-1;R.count=d.review&&d.mode==='random'?Math.min(d.bars.length,180):Math.min(R.count,d.bars.length);R.start=Math.max(0,d.bars.length-R.count);
 $('setup').hidden=true;$('records-panel').hidden=true;$('practice').hidden=false;history.replaceState(null,'','/simulator?session='+d.id+(d.read_only?'&round='+d.round:''));error('');
 $('round-label').textContent=`第 ${d.round} / ${d.total_rounds} 个信号 · ${d.title}`;$('stock-name').textContent=(d.signal.is_leader?'★ ':'')+d.signal.name+' '+d.signal.code;
 $('signal-label').textContent=`信号日 ${d.signal.date} · 单笔${d.weight===1?'全仓100%':'半仓50%'} · 行情截至当前揭示日 ${d.visible_through}`;
 $('stage').textContent={signal:'等待买入',holding:'持有中',closed:'本笔已结算',skipped:'已跳过'}[d.stage]+(d.review?' · 复盘中':'');if(['random10','random'].includes(d.mode)&&d.stage==='closed'&&!d.has_next&&!d.read_only)$('stage').textContent=d.total_rounds+'轮测试已结束';if(d.read_only)$('stage').textContent='已结算轮次复盘';
 setMetric('nav',d.nav.toFixed(4),d.nav-1);setMetric('total-return',pct(d.nav-1),d.nav-1);setMetric('completed',String(d.completed));setMetric('drawdown',pct(d.max_drawdown),d.max_drawdown);setMetric('entry-price',d.entry==null?'待买入':price(d.entry)+' 元');
 let status=d.stage==='signal'?`当前只显示到信号日。点击买入后，以次日开盘投入当前练习资产的${Math.round(d.weight*100)}%，并揭示D1完整K线。`:d.stage==='holding'?`已揭示至D${d.day}收盘。继续持有可看下一日；现在点击卖出，将使用D${d.day+1}开盘价。`:d.stage==='skipped'?'此信号未买入，练习净值不变。':`${d.exit.reason}：${d.exit.date}，前复权价 ${price(d.exit.price)} 元。本笔结算净值 ${d.realized_nav.toFixed(4)}。`;
 if(d.stage==='closed'&&!d.review&&d.exit.reason==='点击后次日开盘卖出')status+=' 卖出日仅揭示开盘价，高、低、收及成交量仍隐藏。';
 if(d.stage==='closed'&&!d.has_next&&!d.read_only)status+=['random10','random'].includes(d.mode)?` 随机${d.total_rounds}轮已结束，可导出累计净值和交易记录。`:' 所选信号已全部练习完毕，可导出记录或选择新信号。';
 if(d.stage==='skipped'&&!d.has_next)status+=' 所选信号已全部处理完毕，可导出记录或选择新信号。';
 if(d.review)status+=d.mode==='random'?` 已展示至信号后D120的可用K线${d.review_complete120?'':'（行情未满120日或存在缺价）'}，后续行情不再改变结算净值。`:' 已切换事后复盘，后续行情不会重新计入净值。';
 $('status-text').textContent=status;$('progress-label').textContent=d.stage==='signal'?'D0 / D60':d.stage==='closed'&&['点击后次日开盘卖出','D60到期次日开盘平仓'].includes(d.exit.reason)?`D${d.exit.day}开盘已结算 / 持有上限D60`:`D${d.day} / D60`;
 $('basis-note').textContent=d.basis+'。理想开/收盘价成交，不模拟停牌及涨跌停排队；这不是新的盲测。进度与操作记录自动保存在本机。';
 $('chart-title').textContent=d.review?'日K · 卖出后复盘':'日K · 仅已揭示行情';$('reveal-state').textContent=d.review?(d.mode==='random'?'复盘：信号后D120可用行情':'复盘：旧版60日行情'):d.stage==='closed'&&d.exit.reason==='点击后次日开盘卖出'?'仅新增卖出日开盘价':'未揭示的未来行情已隐藏';
 const tbody=$('results');tbody.replaceChildren();
 for(const r of d.outcomes){const tr=document.createElement('tr');for(const [value,color] of [[r.name+' '+r.code], [r.buy_date+' / '+price(r.buy_price)], [r.sell_date+' / '+price(r.sell_price)], [pct(r.stock_return),tone(r.stock_return)],[pct(r.account_return),tone(r.account_return)],[r.nav_after.toFixed(4)]]){const td=document.createElement('td');td.textContent=value;if(color)td.className=color;tr.append(td);}const link=document.createElement('button');link.className='round-review';link.textContent='复盘';link.setAttribute('aria-label',`复盘第${r.round}轮`);link.addEventListener('click',()=>reviewRound(r.round));tr.firstChild.append(document.createElement('br'),link);tbody.append(tr);}
 if(!d.outcomes.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=6;td.className='empty';td.textContent='结算后在这里显示每笔结果';tr.append(td);tbody.append(tr);}
 $('result-count').textContent=d.completed+'笔';updateActions();syncPan();draw();drawEquity();updateQuote();
}
async function resume(id){if(!id||R.busy)return;busy(true);try{showState(await api('/api/replay/state?id='+encodeURIComponent(id)));}catch(e){error(e.message);}finally{busy(false);}}
async function action(name){if(R.busy||!R.data)return;busy(true);try{showState(await api('/api/replay/action',{id:R.data.id,action:name,revision:R.data.revision}));await savedSessions();}catch(e){error(e.message);try{const d=await api('/api/replay/state?id='+R.data.id);showState(d);error(e.message);}catch{}}finally{busy(false);}}
$('start').addEventListener('click',async()=>{if(R.busy)return;busy(true);try{showState(await api('/api/replay/create',{ids:[...R.selected],title:$('practice-title').value}));await savedSessions();}catch(e){error(e.message);}finally{busy(false);}});
$('random-ten').addEventListener('click',async()=>{if(R.busy||R.loading)return;busy(true);try{showState(await api('/api/replay/create',{mode:'random',rounds:Number($('round-count').value),filters:filters(),title:$('practice-title').value}));await savedSessions();}catch(e){error(e.message);}finally{busy(false);}});
for(const [id,name] of [['buy','buy'],['advance','advance'],['sell','sell'],['skip','skip'],['next-round','next'],['review','review']])$(id).addEventListener('click',()=>action(name));
$('new-practice').addEventListener('click',()=>location.assign('/simulator?'+new URLSearchParams(filters())));
$('saved').addEventListener('change',()=>resume($('saved').value));
$('pick-ten').addEventListener('click',()=>{R.selected=new Set(R.candidates.slice(0,10).map(s=>s.id));renderCandidates();});$('clear-picks').addEventListener('click',()=>{R.selected.clear();renderCandidates();});
$('round-count').addEventListener('change',updateSelected);$('return-current').addEventListener('click',()=>resume(R.data.id));
for(const id of ['scope','direction','year'])$(id).addEventListener('change',()=>loadCandidates());
let searchTimer;$('search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>loadCandidates(),220);});
$('export').addEventListener('click',()=>{if(!R.data)return;const data={title:R.data.title,mode:R.data.mode,total_rounds:R.data.total_rounds,basis:R.data.basis,weight:R.data.weight,net_value:R.data.nav,completed:R.data.completed,outcomes:R.data.outcomes,curve:R.data.curve};const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='逐日练习_'+R.data.id.slice(0,8)+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
function syncPan(){if(!R.data)return;const max=Math.max(0,R.data.bars.length-R.count);R.start=Math.max(0,Math.min(max,R.start));$('pan').max=max;$('pan').value=R.start;$('visible-range').textContent=`${R.start+1}—${R.start+R.count} / ${R.data.bars.length}根`;}
function zoom(factor){if(!R.data)return;R.count=Math.min(R.data.bars.length,Math.max(25,Math.round(R.count*factor)));R.start=R.data.bars.length-R.count;R.hover=-1;syncPan();draw();updateQuote();}
$('zoom-in').addEventListener('click',()=>zoom(.75));$('zoom-out').addEventListener('click',()=>zoom(1/.75));$('all-visible').addEventListener('click',()=>{if(!R.data)return;R.count=R.data.bars.length;R.start=0;syncPan();draw();});$('pan').addEventListener('input',()=>{R.start=Number($('pan').value);R.hover=-1;syncPan();draw();updateQuote();});$('ma-visible').addEventListener('change',draw);
function chartSize(el){const r=el.getBoundingClientRect(),dpr=Math.min(devicePixelRatio||1,2);el.width=Math.round(r.width*dpr);el.height=Math.round(r.height*dpr);const c=el.getContext('2d');c.setTransform(dpr,0,0,dpr,0,0);return {w:r.width,h:r.height,c};}
function line(c,x,y,x2,y2,color,width=1,dash=[]){c.beginPath();c.strokeStyle=color;c.lineWidth=width;c.setLineDash(dash);c.moveTo(x,y);c.lineTo(x2,y2);c.stroke();c.setLineDash([]);}
function label(c,value,x,y,color='#91a0b5',align='left',size=10){c.fillStyle=color;c.textAlign=align;c.textBaseline='middle';c.font=`${size}px Arial,"Microsoft YaHei"`;c.fillText(value,x,y);}
function draw(){
 if(!R.data||$('practice').hidden)return;const {w,h,c}=chartSize(canvas);if(!w||!h)return;
 const bars=R.data.bars.slice(R.start,R.start+R.count),left=9,right=w-65,top=24,bottom=h*.70,volTop=bottom+30,volBottom=h-27;
 const values=bars.flatMap(b=>b.slice(1,5).filter(v=>v!=null));if($('ma-visible').checked)for(const b of bars)values.push(...b.slice(6,10).filter(v=>v!=null));
 let lo=Math.min(...values),hi=Math.max(...values),pad=Math.max((hi-lo)*.1,hi*.01);lo-=pad;hi+=pad;
 const spacing=(right-left)/bars.length,x=i=>left+(i+.5)*spacing,y=v=>bottom-(v-lo)/(hi-lo)*(bottom-top);
 const mv=Math.max(...bars.map(b=>b[5]||0),1)*1.1,vy=v=>volBottom-v/mv*(volBottom-volTop);R.geometry={left,right,top,bottom,volBottom,spacing,bars,x,y};
 c.fillStyle='#fff';c.fillRect(0,0,w,h);
 for(let i=0;i<=4;i++){const yy=top+i*(bottom-top)/4;line(c,left,yy,right,yy,'#edf1f6');label(c,price(hi-i*(hi-lo)/4),right+9,yy);}
 line(c,left,volTop,right,volTop,'#edf1f6');label(c,'成交量（手）',left+2,volTop-12,'#9caabc');
 const cw=Math.max(1,Math.min(12,spacing*.62));
 for(let i=0;i<bars.length;i++){
  const b=bars[i],xx=x(i),shade={decline:'#7c94b009',base:'#319c9310',spike:'#e2b14d20'}[b[11]];
  if(shade){c.fillStyle=shade;c.fillRect(xx-spacing/2,top,spacing,bottom-top);}
  if(b[4]==null){c.beginPath();c.fillStyle='#9a7cba';c.arc(xx,y(b[1]),4,0,Math.PI*2);c.fill();label(c,'仅开盘',xx-5,y(b[1])-13,'#9a7cba','right');continue;}
  const color=b[4]>=b[1]?'#db5666':'#228f7e';line(c,xx,y(b[2]),xx,y(b[3]),color);
  const by=Math.min(y(b[1]),y(b[4])),bh=Math.max(1,Math.abs(y(b[1])-y(b[4])));c.fillStyle=color;c.fillRect(xx-cw/2,by,cw,bh);
  c.fillRect(xx-cw/2,vy(b[5]),cw,Math.max(1,volBottom-vy(b[5])));
 }
 if($('ma-visible').checked){for(const [key,color] of [[6,'#bd9341'],[7,'#9374cb'],[8,'#56a0b7'],[9,'#d1729a']]){c.beginPath();c.strokeStyle=color;c.lineWidth=1.1;let active=false;bars.forEach((b,i)=>{if(b[key]==null){active=false;return;}if(active)c.lineTo(x(i),y(b[key]));else{c.moveTo(x(i),y(b[key]));active=true;}});c.stroke();}}
 const e=R.data.signal,baseIndices=bars.map((b,i)=>b[11]==='base'?i:-1).filter(i=>i>=0);
 if(baseIndices.length)for(const v of [e.box_low,e.box_high])line(c,x(baseIndices[0])-spacing/2,y(v),x(baseIndices.at(-1))+spacing/2,y(v),'#73aaa2',1,[4,3]);
 const si=bars.findIndex(b=>b[0]===e.date);if(si>=0){line(c,x(si),top,x(si),volBottom,'#92a6cb',1,[3,4]);label(c,'信号',x(si)+5,top+7,'#849bc2');}
 if(R.data.entry!=null){const bi=bars.findIndex(b=>b[0]>e.date);if(bi>=0){const xx=x(bi),yy=y(R.data.entry);c.beginPath();c.fillStyle='#5a88c8';c.arc(xx,yy,3.5,0,Math.PI*2);c.fill();label(c,R.data.weight===1?'全仓买入':'半仓买入',xx+6,yy+13,'#5a88c8');}}
 if(R.data.exit){const ei=bars.findIndex(b=>b[0]===R.data.exit.date);if(ei>=0){c.beginPath();c.fillStyle='#a082bc';c.arc(x(ei),y(R.data.exit.price),4,0,Math.PI*2);c.fill();}}
 const step=Math.max(1,Math.ceil(bars.length/Math.max(2,Math.floor((right-left)/120))));for(let i=0;i<bars.length;i+=step)label(c,bars[i][0],Math.min(right-28,Math.max(left+30,x(i))),h-10,'#98a9bd','center',9);
 if(R.hover>=0&&R.hover<bars.length)line(c,x(R.hover),top,x(R.hover),volBottom,'#9aa9ba',.8,[3,3]);
 $('chart-window').textContent=bars[0][0]+' — '+bars.at(-1)[0];
}
function updateQuote(){if(!R.data)return;const bars=R.data.bars.slice(R.start,R.start+R.count),b=bars[R.hover>=0?R.hover:bars.length-1];if(!b)return;$('quote').textContent=`${b[0]}   开 ${price(b[1])}   高 ${price(b[2])}   低 ${price(b[3])}   收 ${price(b[4])}   量 ${b[5]==null?'—':b[5]>=10000?(b[5]/10000).toFixed(2)+'万手':Math.round(b[5])+'手'}`+(b[4]==null?'   卖出日仅开盘已揭示':'   前复权');}
canvas.addEventListener('pointermove',e=>{if(!R.geometry)return;const r=canvas.getBoundingClientRect(),g=R.geometry;R.hover=Math.max(0,Math.min(g.bars.length-1,Math.floor((e.clientX-r.left-g.left)/g.spacing)));draw();updateQuote();});canvas.addEventListener('pointerleave',()=>{R.hover=-1;draw();updateQuote();});canvas.addEventListener('wheel',e=>{if(!R.data)return;e.preventDefault();zoom(e.deltaY<0?.8:1.25);},{passive:false});
function drawEquity(){if(!R.data||$('practice').hidden)return;const el=$('equity-chart'),{w,h,c}=chartSize(el),v=R.data.curve.map(p=>p.nav),lo=Math.min(...v,1),hi=Math.max(...v,1),pad=Math.max((hi-lo)*.15,.005),y=n=>h-22-(n-lo+pad)/(hi-lo+2*pad)*(h-42);c.clearRect(0,0,w,h);line(c,6,y(1),w-42,y(1),'#e3eaf3',1,[3,3]);c.beginPath();c.strokeStyle='#6f91c4';c.lineWidth=1.8;v.forEach((n,i)=>{const x=8+i/Math.max(1,v.length-1)*(w-55);if(i)c.lineTo(x,y(n));else c.moveTo(x,y(n));});c.stroke();label(c,v.at(-1).toFixed(4),w-3,y(v.at(-1)),'#6f91c4','right',11);label(c,'已揭示步骤',8,h-8,'#a1afc0','left',9);}
new ResizeObserver(()=>{draw();drawEquity();}).observe($('practice'));
let testsPage=1;
async function loadTests(page=1){error('');try{const d=await api('/api/replay/tests?page='+page);testsPage=d.page;$('setup').hidden=true;$('practice').hidden=true;$('records-panel').hidden=false;$('test-list').replaceChildren();for(const row of d.rows){const tr=document.createElement('tr'),f=row.selection_filters||{},scope=f.scope==='all'?'全部沪深主板':'★ 龙头',filterText=row.selection_filters?`${scope} · ${f.year||'全部年份'} · ${f.direction==='2'?'方向1.2':f.direction==='1'?'方向1.1':'历史筛选'}${f.q?' · '+f.q:''}`:'旧版测试';const values=[row.title,filterText,`${row.completed} / ${row.total_rounds}轮`,row.finished?'已结束':row.stage==='holding'?'持仓中':'进行中',row.realized_nav.toFixed(4),pct(row.realized_nav-1)];values.forEach((v,i)=>{const td=document.createElement('td');td.textContent=v;if(i===0){const small=document.createElement('small');small.textContent=row.created_at.slice(0,16).replace('T',' ');td.append(small);}tr.append(td);});const td=document.createElement('td'),a=document.createElement('a');a.href='/simulator?session='+row.id;a.textContent=row.finished?'查看结果':'继续测试';td.append(a);tr.append(td);$('test-list').append(tr);}if(!d.rows.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=7;td.textContent='暂无测试记录，先创建一次随机测试。';tr.append(td);$('test-list').append(tr);}$('tests-page').textContent=`第 ${d.page} / ${d.pages} 页 · 共 ${d.total} 次测试`;$('tests-prev').disabled=d.page<=1;$('tests-next').disabled=d.page>=d.pages;}catch(e){error(e.message);}}
async function reviewRound(round){if(R.busy||!R.data)return;busy(true);try{showState(await api('/api/replay/round?id='+R.data.id+'&round='+round));}catch(e){error(e.message);}finally{busy(false);}}
$('tests-prev').addEventListener('click',()=>loadTests(testsPage-1));$('tests-next').addEventListener('click',()=>loadTests(testsPage+1));
async function init(){const records=location.pathname==='/simulator/tests';$('tab-tests').classList.toggle('active',records);$('tab-new').classList.toggle('active',!records);if(records){$('setup').hidden=true;await loadTests(Number(params.get('page')||1));return;}for(const [id,key] of [['scope','scope'],['direction','direction']])if(params.has(key))$(id).value=params.get(key);$('search').value=params.get('q')||'';if(params.has('year')){const o=document.createElement('option');o.value=params.get('year');o.textContent=params.get('year')+'年';$('year').append(o);$('year').value=o.value;}
 await loadCandidates(true);await savedSessions();if(params.get('session')){await resume(params.get('session'));if(params.has('round')&&R.data)await reviewRound(Number(params.get('round')));}}
init();
