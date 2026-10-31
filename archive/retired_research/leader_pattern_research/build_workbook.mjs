import fs from 'node:fs/promises';
import path from 'node:path';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';

const dir=path.resolve('leader_pattern_research/outputs/patterns_20261027/holdout_restricted');
const data=JSON.parse(await fs.readFile(path.join(dir,'workbook_data.json'),'utf8'));
const wb=Workbook.create();
const overview=wb.worksheets.add('结果汇总');
const details=data.tabs.map(t=>({t,s:wb.worksheets.add(t.name)}));
const notes=wb.worksheets.add('规则与数据');
const col=n=>{let s='';while(n){n--;s=String.fromCharCode(65+n%26)+s;n=Math.floor(n/26);}return s;};
const pct='0.00%;[Red]-0.00%;0.00%';

function base(s,end){
  s.showGridLines=false;
  s.getRange(end).format.font={name:'Microsoft YaHei',size:10,color:'#222222'};
  s.getRange(end).format.rowHeight=23;
  s.getRange(end).format.verticalAlignment='center';
  s.getRange('A2').format.font={name:'Microsoft YaHei',size:15,bold:true,color:'#233958'};
}
function header(s,range){
  s.getRange(range).format={fill:'#29496C',font:{name:'Microsoft YaHei',size:10,bold:true,color:'#FFFFFF'},rowHeight:33,wrapText:true,horizontalAlignment:'center',verticalAlignment:'center'};
}
for(const {t,s} of details){
  const n=t.rows.length,last=n+6,c=col(t.headers.length);
  base(s,`A1:${c}${last}`);s.getRange(`A1:${c}${last}`).format.columnWidth=13;
  s.getRange('A2').values=[[t.name==='五阴三阳逐次'?'五阴三阳：逐次信号与40日路径':'缩量回调后放量：逐次信号与D+5路径']];
  s.getRange('A3').values=[['价格变化以供应商前复权价格为口径；D列为信号日期，D0路径从E列日期开始。']];
  s.getRange('A4').values=[['未走完观察期或终点无有效报价时，价格变化留空。右侧D0之后各列为每天的收盘价格变化。']];
  s.getRange(`A6:${c}6`).values=[t.headers];
  const rows=t.rows.map(row=>row.map((x,j)=>j>=3&&j<=5&&x?Date.parse(x+'T00:00:00Z')/86400000+25569:x));
  s.getRange(`A7:${c}${last}`).values=rows;
  s.getRange('I7').formulas=[['=IF(OR(G7="",H7=""),"",H7/G7-1)']];
  s.getRange(`I7:I${last}`).fillDown();
  s.tables.add(`A6:${c}${last}`,true,t.rule==='first'?'FirstEvents':'ThirdEvents');
  header(s,`A6:${c}6`);
  s.getRange(`B7:B${last}`).setNumberFormat('000000');
  s.getRange(`D7:F${last}`).setNumberFormat('yyyy-mm-dd');
  s.getRange(`G7:H${last}`).setNumberFormat('0.0000');
  s.getRange(`I7:K${last}`).setNumberFormat(pct);
  s.getRange(`S7:${c}${last}`).setNumberFormat(pct);
  s.getRange(`R7:R${last}`).setNumberFormat('0.00');
  s.getRange(`Q7:Q${last}`).setNumberFormat('0');
  s.getRange(`A6:A${last}`).format.columnWidth=34;
  s.getRange(`B6:B${last}`).format.columnWidth=10;
  s.getRange(`C6:C${last}`).format.columnWidth=14;
  s.getRange(`D6:F${last}`).format.columnWidth=15;
  s.getRange(`L6:P${last}`).format.columnWidth=16;
  s.getRange(`T6:${c}${last}`).format.columnWidth=13;
  s.getRange(`I7:K${last}`).conditionalFormats.add('cellIs',{operator:'lessThan',formula:0,format:{font:{color:'#B43A36'}}});
  s.freezePanes.freezeRows(6);s.freezePanes.freezeColumns(3);
}
base(overview,'A1:H42');overview.tabColor='#29496C';
overview.getRange('A1:A42').format.columnWidth=35;
overview.getRange('B1:H42').format.columnWidth=14;
overview.getRange('A2').values=[['185只板块指示股票：形态信号研究']];
overview.getRange('A3').values=[['2019-01-01至2026-10-26。当前选池回看，存在事后选池偏差。']];
overview.getRange('A4').values=[['供应商前复权价格变化，未扣费、未合并账户，也未完成真实股东权益与成交核验。']];
overview.getRange('A6:H6').values=[['规则及观察期限','信号数','有效终点数','平均变化','中位变化','胜率','10%分位','90%分位']];header(overview,'A6:H6');
for(let i=0;i<details.length;i++){
  const {t}=details[i],r=7+i,end=t.rows.length+6,sn=`'${t.name}'`,ref=`${sn}!$I$7:$I$${end}`;
  overview.getRange(`A${r}`).values=[[i===0?'五阴三阳，之后40个交易日':'缩量放量，次日开盘至D+5']];
  overview.getRange(`B${r}:F${r}`).formulas=[[
    `=COUNTA(${sn}!$A$7:$A$${end})`,`=COUNT(${ref})`,`=AVERAGE(${ref})`,
    `=MEDIAN(${ref})`,`=COUNTIFS(${ref},">0")/C${r}`
  ]];
  const stats=data.summary.summaries[t.rule].price_change;
  overview.getRange(`G${r}:H${r}`).values=[[stats.p10,stats.p90]];
}
overview.getRange('A9:H9').values=[['首板开板，最多持有5日','待分钟数据',null,null,null,null,null,null]];
overview.getRange('D7:H8').setNumberFormat(pct);
overview.getRange('A11').values=[['第一条不同观察期限']];overview.getRange('A11').format.font.bold=true;
overview.getRange('A12:G12').values=[['随后交易日','有效样本','平均变化','中位变化','胜率','10%分位','90%分位']];header(overview,'A12:G12');
overview.getRange('A13:G17').values=data.horizons.map(x=>[x.day,x.n,x.mean,x.median,x.win_rate,x.p10,x.p90]);
overview.getRange('C13:G17').setNumberFormat(pct);
overview.getRange('A19').values=[['按信号发生年份统计']];overview.getRange('A19').format.font.bold=true;
overview.getRange('A20:H20').values=[['规则','年份','信号数','有效终点数','平均变化','中位变化','胜率','未满观察期']];header(overview,'A20:H20');
overview.getRange('A21:H36').values=data.yearly.map(x=>[x.rule==='first'?'五阴三阳，40日':'缩量放量，D+5',x.year,x.signals,x.n,x.mean,x.median,x.win_rate,x.censored]);
overview.getRange('E21:G36').setNumberFormat(pct);
overview.getRange('A38').values=[['第一条另有31次未满40日、2次成熟终点无报价，均未当作0收益。']];
overview.getRange('A39').values=[['第一条同股40日去重：892次有效终点，平均5.05%，中位0.71%，胜率51.23%。']];
overview.getRange('A40').values=[['第三条仅107次样本，均值受少数大涨明显影响。逐年结果有明显差异。']];
overview.getRange('A41').values=[['胜率＝价格变化严格大于0的次数／有效终点数。横向两条规则期限不同，不直接比较年化。']];

base(notes,`A1:B${data.notes.length+6}`);notes.getRange(`A1:A${data.notes.length+6}`).format.columnWidth=23;
notes.getRange(`B1:B${data.notes.length+6}`).format.columnWidth=110;
notes.getRange('A2').values=[['规则、来源与未完成的数据项']];
notes.getRange('A6:B6').values=[['项目','定义或状态']];header(notes,'A6:B6');
notes.getRange(`A7:B${data.notes.length+6}`).values=data.notes;
notes.getRange(`B7:B${data.notes.length+6}`).format.wrapText=true;
notes.getRange(`A7:B${data.notes.length+6}`).format.rowHeight=44;
notes.freezePanes.freezeRows(6);

wb.recalculate();
const inspect=await wb.inspect({kind:'table',range:'结果汇总!A6:H9',include:'values,formulas',tableMaxRows:4,tableMaxCols:8,maxChars:1800});
console.log(inspect.ndjson);
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!',options:{useRegex:true,maxResults:10},maxChars:1000});
console.log(errors.ndjson);
await fs.mkdir(path.join(dir,'previews'),{recursive:true});
for(const [sheetName,range,key] of [
  ['结果汇总','A1:H41','summary'],['五阴三阳逐次','A1:K13','first'],
  ['缩量回调逐次','A1:K13','third'],['规则与数据','A1:B17','rules'],
  ['五阴三阳逐次','T6:AE12','first_path_start'],['五阴三阳逐次','AW6:BH12','first_path_end'],
  ['缩量回调逐次','T6:Y12','third_path'],['规则与数据','A18:B30','rules_rest']
]){
  const blob=await wb.render({sheetName,range,scale:1.25,format:'png'});
  await fs.writeFile(path.join(dir,'previews',key+'.png'),new Uint8Array(await blob.arrayBuffer()));
}
const xlsx=await SpreadsheetFile.exportXlsx(wb);await xlsx.save(path.join(dir,'三种形态逐次信号研究.xlsx'));
console.log('Saved workbook with four sheets.');
