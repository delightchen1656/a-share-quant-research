const $=id=>document.getElementById(id);const stateNames={running:'正在下载',preparing:'正在准备',completed:'全部完成',stopped:'已安全暂停',interrupted:'下载已中断',failed:'发生错误',idle:'等待开始'};
async function api(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});return r.json()}
function fmtEta(v){if(v===null||v===undefined)return '计算中';if(v<1)return Math.max(1,Math.round(v*60))+' 分钟';return Number(v).toFixed(1)+' 小时'}
function render(s){const preparing=s.state==='preparing';$('percent').textContent=s.percent.toFixed(2)+'%';$('fraction').textContent=`${s.completed.toLocaleString()} / ${s.total.toLocaleString()} 项`;$('progressBar').style.width=Math.min(100,s.percent)+'%';$('range').textContent=`数据范围 ${s.range[0]} 至 ${s.range[1]}`;$('current').textContent=s.current||(preparing?'准备中':'—');$('kind').textContent=s.current?(s.kind==='qfq'?'前复权':'原始价'):(s.phase||'等待任务');$('speed').textContent=s.speed?Number(s.speed).toLocaleString():(preparing?'准备中':'—');$('eta').textContent=preparing?'约 1 分钟内':fmtEta(s.eta);$('failures').textContent=s.failures||0;$('shRaw').textContent=s.counts.SH.raw;$('shQfq').textContent=s.counts.SH.qfq;$('szRaw').textContent=s.counts.SZ.raw;$('szQfq').textContent=s.counts.SZ.qfq;$('shStocks').textContent=s.stocks.SH+' 只';$('szStocks').textContent=s.stocks.SZ+' 只';$('updated').textContent=s.updated_at?'更新 '+s.updated_at.replace('T',' '):'实时扫描完成标记';$('state').className='status-pill '+(s.running?'running':'');$('state').querySelector('span').textContent=preparing?(s.phase||'正在准备'):(stateNames[s.state]||s.state);$('startBtn').disabled=s.running;$('stopBtn').disabled=!s.running;$('recent').innerHTML=s.recent.length?s.recent.map(x=>`<div class="file"><b>${x.symbol}</b><span>${x.kind==='qfq'?'前复权':'原始价'} · ${x.rows} 行</span></div>`).join(''):'<span class="muted">暂时没有已完成文件</span>'}
let refreshTimer=null;
async function refresh(){
  clearTimeout(refreshTimer);
  try{
    render(await api('/api/status'));
    refreshTimer=setTimeout(refresh,1000);
  }catch(e){
    $('state').className='status-pill';
    $('state').querySelector('span').textContent='连接断开，自动重连中';
    refreshTimer=setTimeout(refresh,3000);
  }
}
function bubble(text,type='bot'){const e=document.createElement('div');e.className='bubble '+type;e.textContent=text;$('chat').appendChild(e);$('chat').scrollTop=$('chat').scrollHeight}
async function action(path,body={}){const r=await api(path,body);bubble(r.message);render(r.status)}
$('startBtn').onclick=()=>action('/api/start',{exchange:'ALL'});$('stopBtn').onclick=()=>action('/api/stop');$('chatForm').onsubmit=async e=>{e.preventDefault();const t=$('chatInput').value.trim();if(!t)return;bubble(t,'user');$('chatInput').value='';await action('/api/chat',{message:t})};refresh();
