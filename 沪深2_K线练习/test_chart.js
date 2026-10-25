const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(__dirname+'/dist/app.js','utf8');
const block=source.slice(source.indexOf('function tradingAxis('),source.indexOf('class Candles{'));
const context={time:d=>Date.parse(d+'T00:00:00Z')};vm.createContext(context);vm.runInContext(block,context);
const card={bars:[{time:'2020-01-03'},{time:'2020-01-06'},{time:'2020-01-07'},{time:'2020-01-23'},{time:'2020-02-03'}],axis_sessions:['2020-02-04','2020-02-05']};
const day=context.tradingAxis(card,'day');
assert.equal(day.position('2020-01-06')-day.position('2020-01-03'),1,'Weekend consumes no slot');
assert.equal(day.position('2020-02-03')-day.position('2020-01-23'),1,'Holiday consumes no slot');
assert.equal(day.position('2020-02-04')-day.position('2020-02-03'),1,'Reserved future trading slots contiguous');
assert.equal(day.position('2020-01-05'),day.position('2020-01-03'),'Calendar deadline on Sunday maps to preceding session');
const week=context.tradingAxis(card,'week');
assert.equal(week.position('2020-01-06'),week.position('2020-01-07'),'Same week shares one slot');
assert.equal(week.position('2020-02-03')-week.position('2020-01-23'),1,'No empty holiday weeks');
console.log('6 trading-day/week continuity assertions passed');
vm.runInContext(source.slice(source.indexOf('function practiceNavAxis('),source.indexOf('function drawNav(')),context);
for(const values of [[1],[.85,1.33],[.2,2.4],[0],[20,21],[.8,1.4],[.99,1.01]]){
 const a=context.practiceNavAxis(values);assert.equal(a.ticks.length,5);
 assert(a.min<=Math.min(...values)&&a.max>=Math.max(...values));
 const step=a.ticks[0]-a.ticks[1];
 for(let i=0;i<5;i++){
  assert(Math.abs(a.ticks[i]*5-Math.round(a.ticks[i]*5))<1e-8);
  if(i)assert(Math.abs(a.ticks[i-1]-a.ticks[i]-step)<1e-8);
 }
 console.log('Five-line NAV axis:',values,'=>',a.ticks);
}
