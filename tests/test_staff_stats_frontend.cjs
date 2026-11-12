const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const elements=new Map(),calls=[];let stats={total:5,in_progress:1,overdue:1,completed_on_time:2,completed_late:1};
function el(id){if(!elements.has(id))elements.set(id,{innerHTML:'',textContent:'',value:'',classList:{toggle(){},contains(){return false}},querySelectorAll(){return []}});return elements.get(id)}
const ctx={document:{getElementById:el,querySelectorAll:()=>[],hidden:false},location:{pathname:'/Director'},sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},setInterval(){},fetch:async path=>{calls.push(path);return {ok:true,json:async()=>stats}},console};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('frontend/js/staff.js','utf8'),ctx);
(async()=>{
 vm.runInContext('staffToken="token";staffUser={id:"d"}',ctx);await vm.runInContext('loadDeadlineStats()',ctx);
 const html=el('deadlineStats').innerHTML;assert.match(html,/>5<\/strong><span>Всего задач/);assert.match(html,/>1<\/strong><span>Просрочено/);assert.match(html,/>2<\/strong><span>Выполнено в срок/);assert.match(html,/>67%<\/strong>/);
 stats={total:0,in_progress:0,overdue:0,completed_on_time:0,completed_late:0};await el('statsRefresh').onclick();assert.match(el('deadlineStats').innerHTML,/>—<\/strong>/);assert.ok(calls.includes('/api/staff/deadline-stats'));
 console.log('Staff deadline statistics UI OK');
})().catch(e=>{console.error(e);process.exitCode=1});
