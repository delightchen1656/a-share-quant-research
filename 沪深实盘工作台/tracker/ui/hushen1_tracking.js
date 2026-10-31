/* Independent manual-account calendar; local daily closes, never inferred fills. */
let h1Month=null,h1Metric='cumulative_pnl',h1Range='all',h1TrackKey='';
const h1Panel=document.createElement('section');h1Panel.className='panel';h1Panel.id='h1Tracking';
h1Panel.innerHTML=`<div class="panelhead"><h2>沪深1 · 每日收益追踪</h2><div class="tracking-tools"><button data-h1metric="cumulative_pnl">累计盈亏</button><button data-h1metric="equity">账户总资产</button><button data-h1metric="net_equity">扣除入出金权益</button></div></div><div id="h1TrackError" class="error"></div><div class="tracking-tools" id="h1Ranges"></div><div id="h1Summary" class="tracking-summary" style="margin-top:20px"></div><div id="h1Chart" class="tracking-chart"></div><p class="tracking-note">按实际成交记录与本地未复权收盘价复算，每个交易日一个收盘点；更新K线后自动刷新（最多约30秒）。累计盈亏扣除已分类入出金，包含浮盈亏、已录费用与到账分红。不是回测收益，不补造成交；缺行情断线显示。</p><div class="panelhead" style="margin-top:28px"><h2>每日盈亏日历</h2><div class="tracking-tools"><button id="h1Prev" aria-label="沪深1上个月">‹</button><strong id="h1Month"></strong><button id="h1Next" aria-label="沪深1下个月">›</button><button id="h1Current">本月</button></div></div><div id="h1MonthSummary" class="tracking-summary"></div><div id="h1Calendar" class="calendar-grid"></div><p class="tracking-note">红盈绿亏。每日盈亏＝当日收盘权益－前一交易日收盘权益－当日净入金；第一天以初始资金为基准。休市不计收益，未收盘或未提交行情的日期不生成收盘点。点击日期查看金额、当日成交和费用；费用为预估时仍需按券商账单核对。分红与送转必须补录真实到账信息。</p><div id="h1Unknown"></div>`;
$('#history').closest('section').before(h1Panel);
function h1Draw(rows){
 const target=$('#h1Chart'),valid=rows.filter(r=>Number.isFinite(r[h1Metric]));
 if(!valid.length){target.innerHTML='<div class="empty">暂无可用收盘收益 · 等待已提交行情或资金归属核对</div>';return}
 const w=900,h=270,l=85,r=22,t=18,b=35,vals=valid.map(p=>p[h1Metric]);let low=Math.min(...vals),high=Math.max(...vals),pad=Math.max((high-low)*.15,Math.abs(high)*.001,1);low-=pad;high+=pad;
 const x=i=>l+(rows.length===1?.5:i/(rows.length-1))*(w-l-r),y=v=>t+(high-v)/(high-low)*(h-t-b);
 let grid='';for(let i=0;i<5;i++){const v=low+(high-low)*i/4;grid+=`<line x1="${l}" x2="${w-r}" y1="${y(v)}" y2="${y(v)}" stroke="#293b55" stroke-dasharray="3 6"/><text x="${l-10}" y="${y(v)+4}" text-anchor="end" fill="#8da0be" font-size="11">${money(v)}</text>`}
 let segments=[],segment=[];rows.forEach((p,i)=>{if(Number.isFinite(p[h1Metric]))segment.push(`${x(i)},${y(p[h1Metric])}`);else{if(segment.length)segments.push(segment);segment=[]}});if(segment.length)segments.push(segment);
 target.innerHTML=`<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="沪深1每日收盘收益折线">${grid}${segments.map(s=>`<polyline points="${s.join(' ')}" fill="none" stroke="#9acaff" stroke-width="2.2"/>`).join('')}${rows.map((p,i)=>!Number.isFinite(p[h1Metric])?'':`<circle cx="${x(i)}" cy="${y(p[h1Metric])}" r="3.5" fill="#a4d4ff" tabindex="0"><title>${esc(p.day)} · ¥${money(p[h1Metric])}</title></circle>`).join('')}<text x="${l}" y="${h-8}" fill="#8da0be" font-size="11">${esc(rows[0].day)}</text><text x="${w-r}" y="${h-8}" text-anchor="end" fill="#8da0be" font-size="11">${esc(rows.at(-1).day)}</text></svg>`;
}
function h1Details(day){const p=state.performance,r=p.daily.find(r=>r.day===day);if(!r)return;
 const events=state.events.filter(e=>!e.voided&&e.data.date===day&&['buy','sell','corporate','cash_adjust'].includes(e.kind));
 open(day+' · 沪深1收盘盈亏',table(['项目','金额'],[['收盘总资产',money(r.equity)],['收盘现金',money(r.cash)],['当日净入金',money(r.external_flow)],['当日盈亏',money(r.pnl)],['当日收益率',r.daily_return==null?'待核对':(r.daily_return*100).toFixed(2)+'%'],['累计盈亏',money(r.cumulative_pnl)]])+`<p class="fine">${r.missing_symbols.length?'缺少当日收盘行情：'+esc(r.missing_symbols.join('、')):r.status==='unclassified_cash'?'资金调整未分类，盈亏待核对。':'基于已录成交与到账记录，含持仓浮盈亏。'}</p>`+table(['当日记录','股票','股数','价格 / 金额','费用'],events.map(e=>[esc(({buy:'买入',sell:'卖出',corporate:'到账',cash_adjust:'资金调整'})[e.kind]),esc(e.data.symbol||'—'),e.data.quantity??e.data.shares??'—',money(e.data.price??e.data.amount??e.data.cash),e.data.fee==null?'—':money(e.data.fee)+(e.data.fee_source==='estimated_policy'?'（预估）':'')])) ,async()=>{});
 $('#modal button[type="submit"]').hidden=true;$('#cancel').textContent='关闭';handler=async()=>{throw Error('详情只读，请关闭窗口')};
}
function h1Render(s){const p=s.performance;if(!p)return;const key=JSON.stringify({p,month:h1Month,metric:h1Metric,range:h1Range});if(key===h1TrackKey)return;h1TrackKey=key;
 $('#h1TrackError').textContent=p.error?'收盘收益暂不可用：'+p.error:'';
 if(!h1Month)h1Month=(p.asof||p.today).slice(0,7);
 const last=p.daily.at(-1);$('#h1Summary').innerHTML=`<div><small>累计盈亏（扣除入出金）</small><strong>${money(last?.cumulative_pnl)}</strong></div><div><small>最近收盘日盈亏</small><strong>${money(last?.pnl)}</strong></div><div><small>收盘行情截至</small><strong>${esc(p.asof||'待核验')}</strong></div>`;
 $('#h1Ranges').innerHTML=[['30','最近30天'],['90','最近90天'],['365','1年'],['all','全部']].map(([v,label])=>`<button data-h1range="${v}" class="${h1Range===v?'selected':''}">${label}</button>`).join('');
 $('#h1Ranges').querySelectorAll('button').forEach(e=>e.onclick=()=>{h1Range=e.dataset.h1range;h1Render(state)});
 h1Panel.querySelectorAll('[data-h1metric]').forEach(e=>{e.classList.toggle('selected',e.dataset.h1metric===h1Metric);e.onclick=()=>{h1Metric=e.dataset.h1metric;h1Render(state)}});
 const cutoff=new Date(p.today+'T00:00:00Z');cutoff.setUTCDate(cutoff.getUTCDate()-Number(h1Range||0));h1Draw(p.daily.filter(r=>h1Range==='all'||r.day>=cutoff.toISOString().slice(0,10)));
 const [yy,mm]=h1Month.split('-').map(Number),count=new Date(Date.UTC(yy,mm,0)).getUTCDate(),offset=new Date(Date.UTC(yy,mm-1,1)).getUTCDay(),byDay=new Map(p.daily.map(r=>[r.day,r])),sessions=new Set(p.calendar_sessions);
 $('#h1Month').textContent=yy+'年'+mm+'月';const monthly=p.daily.filter(r=>r.day.startsWith(h1Month)),known=monthly.filter(r=>r.pnl!==null),sum=known.reduce((v,r)=>v+r.pnl,0);
 $('#h1MonthSummary').innerHTML=`<div><small>${known.length<monthly.length?'本月已知盈亏小计（未完整）':'本月已记录盈亏'}</small><strong class="${sum>=0?'positive':'negative'}">${known.length?money(sum):'—'}</strong></div><div><small>已记录 / 待核对</small><strong>${known.length} / ${monthly.length-known.length} 天</strong></div>`;
 let html=['日','一','二','三','四','五','六'].map(v=>`<div class="calendar-week">${v}</div>`).join('')+'<div class="calendar-cell outside"></div>'.repeat(offset);
 for(let d=1;d<=count;d++){const date=h1Month+'-'+String(d).padStart(2,'0'),r=byDay.get(date),ready=r&&r.pnl!==null;
 const label=r?(r.status==='missing_price'?'缺少行情':r.status==='unclassified_cash'?'资金待分类':'收盘权益盈亏'):date>p.today?'未到日期':date<s.config.created_date?'账户未建立':sessions.has(date)?'等待收盘行情':p.calendar_sessions.length&&date>=p.calendar_sessions[0]&&date<=p.calendar_sessions.at(-1)?'休市':'日历待核验';
 html+=`<div class="calendar-cell ${ready&&r.pnl>0?'profit':ready&&r.pnl<0?'loss':''} ${date===p.today?'today':''}" ${r?`data-h1day="${date}" tabindex="0" role="button" aria-label="${date} 盈亏${ready?money(r.pnl):'待核对'}"`:''}><span class="day-number">${d}${date===p.today?' · 今天':''}</span><span class="day-pnl">${ready?(r.pnl>0?'+':'')+money(r.pnl):'—'}</span><small>${ready&&r.daily_return!=null?(r.daily_return*100).toFixed(2)+'% · 收盘':label}</small></div>`}
 $('#h1Calendar').innerHTML=html;$('#h1Calendar').querySelectorAll('[data-h1day]').forEach(e=>{e.onclick=()=>h1Details(e.dataset.h1day);e.onkeydown=k=>{if(['Enter',' '].includes(k.key)){k.preventDefault();e.click()}}});
 $('#h1Unknown').innerHTML=(p.unknown_cash_adjustments||[]).map(e=>`<div class="cash-classify"><span>${esc(e.date)} · ¥${money(e.amount)} · 资金归属待核对</span><button data-h1class="${e.id}">分类</button></div>`).join('');
 $('#h1Unknown').querySelectorAll('button').forEach(e=>e.onclick=()=>open('分类资金调整','<label>归属</label>'+h1FlowSelect(),()=>act('classify_cash',{event_id:Number(e.dataset.h1class),date:p.unknown_cash_adjustments.find(x=>x.id===Number(e.dataset.h1class)).date,flow_type:values().flow_type})));
}
function h1FlowSelect(){return '<select name="flow_type"><option value="external">实际入金 / 出金（不计盈亏）</option><option value="reconciliation">现金差额更正（计入盈亏）</option></select>'}
function h1Move(n){const [y,m]=h1Month.split('-').map(Number);h1Month=new Date(Date.UTC(y,m-1+n,1)).toISOString().slice(0,7);h1Render(state)}
$('#h1Prev').onclick=()=>h1Move(-1);$('#h1Next').onclick=()=>h1Move(1);$('#h1Current').onclick=()=>{h1Month=state.today.slice(0,7);h1Render(state)};
const h1OldRender=render;render=function(s){h1OldRender(s);h1Render(s)};
const h1OldOpen=open;open=function(...args){$('#modal button[type="submit"]').hidden=false;$('#cancel').textContent='取消';return h1OldOpen(...args)};
$('#adjust').onclick=()=>open('沪深1资金调整',field('实际日期','date','date',state.today,'required')+field('入金为正，出金为负','amount','number','','required step="0.01"')+'<label>资金归属</label>'+h1FlowSelect()+field('说明','note','text','','required'),()=>act('cash_adjust',values()));
if(state)h1Render(state);
