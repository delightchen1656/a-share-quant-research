import fs from 'node:fs/promises';
import path from 'node:path';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const dir=path.resolve('leader_pattern_research/outputs/first_below_ma60_20261027/holdout_restricted');
const d=JSON.parse(await fs.readFile(path.join(dir,'workbook_data.json'),'utf8'));
const w=Workbook.create();const s=w.worksheets.add('结果对比');const e=w.worksheets.add('筛选信号与路径');const n=w.worksheets.add('规则与数据');
const pct='0.00%;[Red]-0.00%;0.00%';
function col(n){let s='';while(n){n--;s=String.fromCharCode(65+n%26)+s;n=Math.floor(n/26);}return s;}
function base(s,r){s.showGridLines=false;s.getRange(r).format={font:{name:'Microsoft YaHei',size:10,color:'#222222'},rowHeight:23,verticalAlignment:'center'};s.getRange('A2').format.font={name:'Microsoft YaHei',size:15,bold:true,color:'#29496C'};}
function head(s,r){s.getRange(r).format={fill:'#29496C',font:{name:'Microsoft YaHei',size:10,bold:true,color:'#FFFFFF'},rowHeight:34,wrapText:true,horizontalAlignment:'center',verticalAlignment:'center'};}
const last=d.rows.length+6,c=col(d.headers.length);
base(e,`A1:${c}${last}`);e.getRange(`A1:${c}${last}`).format.columnWidth=14;
e.getRange('A2').values=[['五阴接三阳，信号收盘低于MA60']];
e.getRange('A3').values=[['D0为第3根阳线收盘，MA60含当日。右侧D0—D40为每日收盘相对D0的价格变化。']];
e.getRange('A4').values=[['价格为供应商前复权口径，未扣费。观察期未满或终点无有效报价时，40日价格变化留空。']];
e.getRange(`A6:${c}6`).values=[d.headers];
e.getRange(`A7:${c}${last}`).values=d.rows.map(r=>r.map((x,j)=>[3,4].includes(j)&&x?Date.parse(x+'T00:00:00Z')/86400000+25569:x));
e.getRange('J7').formulas=[['=IF(OR(F7="",I7=""),"",I7/F7-1)']];e.getRange(`J7:J${last}`).fillDown();
e.tables.add(`A6:${c}${last}`,true,'BelowMA60Events');head(e,`A6:${c}6`);
e.getRange(`A6:A${last}`).format.columnWidth=34;e.getRange(`B6:B${last}`).format.columnWidth=10;e.getRange(`C6:C${last}`).format.columnWidth=14;
e.getRange(`D7:E${last}`).setNumberFormat('yyyy-mm-dd');e.getRange(`B7:B${last}`).setNumberFormat('000000');
e.getRange(`F7:G${last}`).setNumberFormat('0.0000');e.getRange(`I7:I${last}`).setNumberFormat('0.0000');
e.getRange(`H7:H${last}`).setNumberFormat(pct);e.getRange(`J7:L${last}`).setNumberFormat(pct);e.getRange(`P7:${c}${last}`).setNumberFormat(pct);
e.freezePanes.freezeRows(6);e.freezePanes.freezeColumns(3);
base(s,'A1:H40');s.tabColor='#29496C';s.getRange('A1:A40').format.columnWidth=34;s.getRange('B1:H40').format.columnWidth=15;
s.getRange('A2').values=[['五阴接三阳：低于MA60的筛选效果']];
s.getRange('A3').values=[['185只股票，2019-01-01至2026-10-26。第3根阳线收盘低于当日60日均线。']];
s.getRange('A4').values=[['供应商前复权价格观察，未扣费、未合并账户。当前选池及新增条件均属历史回看。']];
s.getRange('A6:H6').values=[['规则','信号数','有效终点数','平均变化','中位变化','胜率','10%分位','90%分位']];head(s,'A6:H6');
s.getRange('A7:H9').values=d.summary.comparison.map(x=>[x.label,x.signals,x.n,x.mean,x.median,x.win_rate,x.p10,x.p90]);
const ref=`'筛选信号与路径'!$J$7:$J$${last}`;
s.getRange('B8:F8').formulas=[[
  `=COUNTA('筛选信号与路径'!$A$7:$A$${last})`,`=COUNT(${ref})`,`=AVERAGE(${ref})`,`=MEDIAN(${ref})`,`=COUNTIFS(${ref},">0")/C8`
]];s.getRange('D7:H9').setNumberFormat(pct);
s.getRange('A11').values=[['不同观察期限']];s.getRange('A11').format.font.bold=true;
s.getRange('A12:H12').values=[['随后交易日','筛后有效样本','原平均变化','筛后平均变化','原中位数','筛后中位数','原胜率','筛后胜率']];head(s,'A12:H12');
s.getRange('A13:H17').values=[1,5,10,20,40].map(day=>{
 const a=d.summary.horizons.find(x=>x.label==='原规则'&&x.day===day),b=d.summary.horizons.find(x=>x.label==='加收盘低于MA60'&&x.day===day);
 return [day,b.n,a.mean,b.mean,a.median,b.median,a.win_rate,b.win_rate];});s.getRange('C13:H17').setNumberFormat(pct);
s.getRange('A19').values=[['按信号发生年份对比40日结果']];s.getRange('A19').format.font.bold=true;
s.getRange('A20:H20').values=[['年份','原有效样本','筛后有效样本','原平均变化','筛后平均变化','原胜率','筛后胜率','筛后中位数']];head(s,'A20:H20');
s.getRange('A21:H28').values=[2019,2020,2021,2022,2023,2024,2025,2026].map(year=>{
 const a=d.summary.yearly.find(x=>x.label==='原规则'&&x.year===year),b=d.summary.yearly.find(x=>x.label==='加收盘低于MA60'&&x.year===year);
 return [year,a.n,b.n,a.mean,b.mean,a.win_rate,b.win_rate,b.median];});s.getRange('D21:H28').setNumberFormat(pct);
s.getRange('A30').values=[['筛后619次信号中，21次未满40日，1次成熟终点缺价，597次参与终点收益统计。']];
s.getRange('A31').values=[['原1008次信号中有10次缺少完整MA60窗口，本次不纳入低于或不低于MA60的分组。']];
const u=d.summary.filtered_nonoverlap40;
s.getRange('A32').values=[[`筛后按同股40日去重，有效${u.n}次：平均${(u.mean*100).toFixed(2)}%，中位${(u.median*100).toFixed(2)}%，胜率${(u.win_rate*100).toFixed(2)}%。`]];
s.getRange('A33').values=[['总体均值、中位数及胜率有所提高。2023年和2026年仍为负，2025年及2026年均值低于原规则。']];
base(n,`A1:B${d.notes.length+6}`);n.getRange(`A1:A${d.notes.length+6}`).format.columnWidth=23;n.getRange(`B1:B${d.notes.length+6}`).format.columnWidth=110;
n.getRange('A2').values=[['筛选定义与数据口径']];n.getRange('A6:B6').values=[['项目','定义或来源']];head(n,'A6:B6');
n.getRange(`A7:B${d.notes.length+6}`).values=d.notes;n.getRange(`B7:B${d.notes.length+6}`).format.wrapText=true;n.getRange(`A7:B${d.notes.length+6}`).format.rowHeight=44;n.freezePanes.freezeRows(6);
w.recalculate();
console.log((await w.inspect({kind:'table',range:'结果对比!A6:H9',include:'values,formulas',tableMaxRows:4,tableMaxCols:8,maxChars:1800})).ndjson);
console.log((await w.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!',options:{useRegex:true,maxResults:5},maxChars:800})).ndjson);
await fs.mkdir(path.join(dir,'previews'),{recursive:true});
for(const [sheetName,range,key] of [['结果对比','A1:H33','summary'],['筛选信号与路径','A1:L12','events'],['筛选信号与路径','AT6:BD12','paths_end'],['规则与数据','A1:B17','rules']]){
 const blob=await w.render({sheetName,range,scale:1.15,format:'png'});await fs.writeFile(path.join(dir,'previews',key+'.png'),new Uint8Array(await blob.arrayBuffer()));}
await (await SpreadsheetFile.exportXlsx(w)).save(path.join(dir,'五阴三阳低于MA60对比.xlsx'));
console.log('Saved MA60 comparison workbook.');
