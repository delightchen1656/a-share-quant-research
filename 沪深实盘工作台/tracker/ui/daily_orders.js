// Broker-result gate: never infer executions or silently cancel a live order.
function dailyBuyResult(orderId){
    const order=state.orders.find(o=>o.signal_id===orderId);
    if(!order)return toast('买单已变化，请刷新后重试');
    const task=state.buy_result_tasks?.find(t=>t.order_id===orderId);
    if(task?.type==='cancel')return cancelOrder(orderId);
    if(!task)return record('buy',orderId);
    const remaining=order.quantity-order.filled;
    const reviewDay=state.buy_review_session;
    let outcome='filled';
    openModal(`${order.name||order.symbol} · 更新买入结果`,
        `<div class="modalnote">先核对国金${esc(reviewDay)}的实际成交。未成交只确认今日结果，保留原买单、现金和槽位，不会自动撤单。</div>
        ${card('股票',order.symbol)}${card('待核对股数',remaining)}
        <div class="toolbar" style="margin:16px 0;flex-wrap:wrap"><button type="button" class="primary" id="dailyFilled">买入成功（填写股数）</button><button type="button" class="ghost" id="dailyUnfilled">今日未成交 / 跳过</button></div>
        <fieldset id="dailyExecution" style="border:0;padding:0;margin:0"><div class="formgrid">
        ${field('实际成交日期','date','date',reviewDay,'required')}
        ${field('本次成交股数（非累计）','quantity','number',remaining,`required min="1" max="${remaining}" step="1"`)}
        ${field('实际成交均价','price','number',Number(order.trigger).toFixed(2),'required min="0.001" step="0.0001"')}
        ${field('本次全部税费（元）','fee','number',0,'required min="0" step="0.01"')}
        </div>${field('券商成交编号（选填）','reference','text','')}</fieldset>
        <p id="dailyUnfilledNote" class="muted hidden">本次不扣现金、不增加持仓、不释放槽位；原7自然日有效期不重置。若国金已撤单或到期，请改用“撤单 / 到期”。</p>
        <label class="check"><input name="attested" type="checkbox" required>已核对国金，所选成交／未成交情况属实。</label>
        <p class="muted">部分成交保存后，还需确认剩余委托是否已撤销；保存不会推测剩余数量的状态。</p>`,
        async()=>{
            const data=values();
            if(outcome==='filled')await act('buy',{...data,order_id:orderId});
            else await act('buy_review',{order_id:orderId,day:reviewDay,filled_at_review:order.filled,order_event_id:order.event_id,attested:!!data.attested});
        },'保存实际成交并更新账户');
    const choose=value=>{
        outcome=value;
        $('#dailyExecution').disabled=value!=='filled';
        $('#dailyExecution').classList.toggle('hidden',value!=='filled');
        $('#dailyUnfilledNote').classList.toggle('hidden',value==='filled');
        $('#dailyFilled').className=value==='filled'?'primary':'ghost';
        $('#dailyUnfilled').className=value==='unfilled'?'primary':'ghost';
        $('#submitModal').textContent=value==='filled'?'保存实际成交并更新账户':'确认今日未成交，保留原买单';
    };
    $('#dailyFilled').onclick=()=>choose('filled');
    $('#dailyUnfilled').onclick=()=>choose('unfilled');
}
const taskBeforeDailyOrders=task;
task=function(t){if(t.type==='buy_result')return dailyBuyResult(t.order_id);return taskBeforeDailyOrders(t)};
const reviewBeforeDailyOrders=review;
review=function(){
    const pending=state.buy_result_tasks||[];
    if(pending.length){toast('请先更新现有买单结果，再复核资金');return task(pending[0])}
    reviewBeforeDailyOrders();$('#modalTitle').textContent='复核资金 · 买单结果已处理';
};
$('#reviewBtn').onclick=review;
const cancelBeforeDailyOrders=cancelOrder;
cancelOrder=function(orderId){
    cancelBeforeDailyOrders(orderId);
    $('#modalContent').insertAdjacentHTML('beforeend','<p><button type="button" class="ghost" id="dailyRecordBeforeCancel">有成交，先录入实际买入</button></p>');
    $('#dailyRecordBeforeCancel').onclick=()=>{closeModal();record('buy',orderId)};
};
const renderBeforeDailyOrders=render;
render=function(){
    renderBeforeDailyOrders();const s=state;const pending=s.buy_result_tasks||[];
    $('#reviewBtn').textContent=pending.length?'先更新买单结果':'复核资金';
    $('#tasks').querySelectorAll('[data-task]').forEach(button=>{
        const t=s.tasks.find(x=>x.id===button.dataset.task);
        if(t?.blocked){button.disabled=true;button.title='先处理上方买单结果'}
    });
    const gate=document.querySelector('.fund-gate');
    if(gate){
        if(pending.length){
            gate.className='fund-gate';gate.innerHTML=`<div><strong>01　先更新买单结果 · ${pending.length}项</strong><p>逐单确认买入成功（多少股）／今日未成交，更新现金和持仓后，再复核资金、生成下一交易日推荐。</p></div><button class="primary" id="fundReviewOpen">更新买入结果 →</button>`;
            $('#fundReviewOpen').onclick=()=>task(pending[0]);
        }else{
            const handled=s.history.some(e=>!e.voided&&((e.kind==='buy_review'&&e.data.day===s.buy_review_session)||(e.kind==='buy'&&e.data.date===s.buy_review_session)));
            const title=gate.querySelector('strong');if(title&&!s.confirmed)title.textContent=handled?'02　买单结果已处理 · 复核资金':'01　每日第一步 · 复核资金';
            $('#fundReviewOpen').onclick=review;
        }
    }
    if(pending.length){
        $('#banner').className='banner';
        $('#banner').textContent='现有买单需先更新成交／未成交结果；处理完成后再进入资金复核和新推荐。';
        $('#signals').innerHTML=empty('先更新买单，再进行下一步','未成交买单不会自动扣款或撤销；请按左侧逐单核对。','更新买入结果','buy_result');
        $('#signals [data-empty]')?.addEventListener('click',()=>task(pending[0]));
        $('#signalBadge').textContent='买单结果待更新';
    }
    $('#orders').querySelectorAll('[data-buy]').forEach(button=>{
        if(pending.some(t=>t.order_id===button.dataset.buy&&t.type==='buy_result')){
            button.textContent='买入成功 / 未成交';button.onclick=()=>dailyBuyResult(button.dataset.buy);
        }
    });
    $('#historyList').querySelectorAll('.timeline').forEach((row,index)=>{
        if(s.history[index]?.kind==='buy_review'){
            row.querySelector('.pill').textContent='买单核对：今日未成交';
            const description=row.querySelector('.description');description.title='保留原买单，不改变现金、持仓、槽位或截止日期';
        }
    });
    const calculation=s.calculation_status;
    // The calculation panel owns running detail; keep actionable warnings visible.
    $('#banner').style.display=s.running&&!pending.length?'none':'';
    if(calculation){
        const statusRow=$('#dataDetails').querySelectorAll('.copyrow')[2];
        if(statusRow)statusRow.querySelector('strong').textContent=calculation.label;
        const detail=$('#dataDetails').querySelector('p');if(detail)detail.textContent=calculation.detail||s.market.message;
        if(s.running&&!pending.length)$('#banner').textContent=calculation.detail||'正在核验本地行情和冻结模型…';
    }
};

// Signal-generation progress uses completed steps/observed counters, not time.
function calculationDuration(seconds){
    seconds=Math.max(0,Math.floor(Number(seconds)||0));
    return seconds>=60?`${Math.floor(seconds/60)}分${String(seconds%60).padStart(2,'0')}秒`:`${seconds}秒`;
}
let previousCalculationCode=null;
function signalGenerationBar(s,stages,index,detail){
    if(!s.running&&s.calculation_status?.code==='ready')return {percent:100,label:'次日信号已就绪',active:false};
    const observed=s.calculation_status?.progress_percent;
    if(Number.isFinite(observed)){
        const percent=Math.max(0,Math.min(99,observed));
        return {percent,label:s.running?`后台核验与新推荐生成 ${percent.toFixed(1)}%`:s.calculation_status?.label||'等待生成',active:!!s.running};
    }
    let fraction=0;
    const stage=stages[index].id;
    const files=detail.match(/feature files (\d+)\/(\d+)/);
    if(stage==='features'&&files&&Number(files[2])>0)fraction=Math.min(1,Number(files[1])/Number(files[2]));
    const model=detail.match(/冻结模型 (utility|pen025|pen100)/);
    if(stage==='models'&&model)fraction=['utility','pen025','pen100'].indexOf(model[1])/3;
    const percent=s.running||s.calculation_status?.code==='blocked'?Math.min(99,100*(index+fraction)/stages.length):0;
    return {percent,label:s.running?`生成步骤进度 ${percent.toFixed(1)}%`:s.calculation_status?.label||'等待生成',active:!!s.running};
}
function renderCalculationProgress(s){
    let panel=$('#calculationProgress');
    if(!panel){panel=document.createElement('section');panel.id='calculationProgress';panel.className='calculation-progress';$('#banner').after(panel)}
    const c=s.calculation_status||{},code=c.code||(s.running?'running':s.market.status);
    const stages=c.stages||[{id:'check',label:'行情与账户核验'},{id:'features',label:'历史特征计算'},{id:'models',label:'冻结模型评分'},{id:'ranking',label:'因子排名与ATR筛选'},{id:'freeze',label:'冻结信号校验'},{id:'publish',label:'发布次日推荐'}];
    const detail=c.detail||s.update_progress||s.market.message||'';
    let stage=c.stage;
    if(!stage){stage=/feature files|历史特征/.test(detail)?'features':/预测中|加载冻结模型/.test(detail)?'models':/因子排序/.test(detail)?'ranking':/冻结信号/.test(detail)?'freeze':'check'}
    const index=Math.max(0,stages.findIndex(x=>x.id===stage));
    const elapsed=c.elapsed_seconds??(c.started_at?Math.max(0,(Date.now()-Date.parse(c.started_at))/1000):0);
    const fileCount=detail.match(/feature files (\d+)\/(\d+)/);
    const ready=code==='ready'&&!s.running;
    const title=s.running?(c.cache_reused?'读取本地已保存结果':c.full_model_run===false?'核验本地行情与已存结果':'后台模型计算'):ready?'推荐已就绪':c.label||'等待更新';
    let reference='';
    if(s.running){
        reference=c.estimated_remaining_seconds>0?`预计剩余约 ${calculationDuration(c.estimated_remaining_seconds)}（按上次完整计算估算）`:c.last_full_model_seconds?`上次完整计算 ${calculationDuration(c.last_full_model_seconds)}；当前阶段仍在运行`:'首次记录用时，暂不估算剩余时间';
    }
    const modelRows=detail.match(/冻结模型 (utility|pen025|pen100).*rows (\d+)\/(\d+)/);
    const countText=fileCount?`历史特征：已核验并计算 ${Number(fileCount[1]).toLocaleString()} / ${Number(fileCount[2]).toLocaleString()} 只股票`:modelRows?`冻结模型 ${modelRows[1]}：已评分 ${Number(modelRows[2]).toLocaleString()} / ${Number(modelRows[3]).toLocaleString()} 条历史特征`:detail;
    const bar=signalGenerationBar(s,stages,index,detail);
    const refreshed=new Date().toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});
    panel.className='calculation-progress'+(ready?' ready':code==='blocked'?' failed':'');
    panel.innerHTML=`<div class="calculation-heading"><strong>${esc(title)}</strong><span>${s.running?`已运行 ${calculationDuration(elapsed)}`:ready?'可以处理推荐清单':''}</span></div>
        <div class="signal-progress-heading"><strong>${esc(bar.label)}</strong><span>每3秒刷新 · ${esc(refreshed)}</span></div>
        <div class="signal-progress-track ${bar.active?'active':''}" role="progressbar" aria-label="次日信号生成步骤进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${bar.percent.toFixed(1)}" aria-valuetext="${esc(bar.label)}"><div class="signal-progress-fill" style="width:${bar.percent.toFixed(1)}%"></div></div>
        <div class="calculation-detail" role="status" aria-live="polite">${esc(countText)}</div>
        ${c.cache_reused?'<div class="calculation-meta">本轮复用已核验的当日冻结信号，无需重新计算历史特征及模型评分。</div>':''}
        ${s.running?`<div class="calculation-meta">${esc(reference)}</div>`:''}`;
    if(previousCalculationCode==='running'&&ready)toast('计算完成，次日推荐已就绪');
    previousCalculationCode=code;
}
const renderBeforeCalculationProgress=render;
render=function(){renderBeforeCalculationProgress();renderCalculationProgress(state)};
let calculationPollInFlight=false;
async function pollSignalGeneration(){
    if(calculationPollInFlight)return;
    calculationPollInFlight=true;
    try{
        const fresh=await api('/api/state');
        if($('#modal').open)renderCalculationProgress(fresh);
        else{state=fresh;render();$('#connection').textContent='● 本地已连接'}
    }catch(error){
        const progress=$('#calculationProgress');
        if(progress){const heading=progress.querySelector('.signal-progress-heading span');if(heading)heading.textContent='连接暂时中断，3秒后自动重试'}
    }finally{calculationPollInFlight=false}
}
setInterval(pollSignalGeneration,3000);
if(state)render();
