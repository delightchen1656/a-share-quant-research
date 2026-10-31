const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(__dirname+'/tracking.js','utf8');
const section=source.slice(source.indexOf('function dailyFinalPoints('),source.indexOf('renderChart=function(points)'));
const context={Date,Map,Number,state:null,money:v=>String(v),esc:v=>String(v)};
vm.createContext(context);vm.runInContext(section,context);
const points=[
 {id:1,day:'2026-10-21',at:'2026-10-21T21:00:00+08:00',equity:101,net_equity:101},
 {id:2,day:'2026-10-21',at:'2026-10-21T20:00:00+08:00',equity:102,net_equity:102},
 {id:3,day:'2026-10-21',at:'2026-10-21T21:00:00+08:00',equity:103,net_equity:null},
 {id:4,day:'2026-10-20',at:'2026-10-21T01:00:00+08:00',equity:99,net_equity:99}
];
const result=context.dailyFinalPoints(points);
assert.deepEqual(Array.from(result,p=>[p.day,p.equity]),[['2026-10-20',99],['2026-10-21',103]]);
assert.equal(points.length,4);
let target={innerHTML:''};context.drawTrack(target,points,'equity',true);
assert.equal((target.innerHTML.match(/<circle /g)||[]).length,2);
assert.ok(target.innerHTML.includes('2026-10-20最终点'));
context.drawTrack(target,points,'net_equity',true);
assert.equal((target.innerHTML.match(/<circle /g)||[]).length,1);
assert.equal(context.dailyFinalPoints([]).length,0);
console.log('PASS: one final point per accounting day, latest timestamp then id, midnight accounting day, no unknown-value fallback, source preserved');
