const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const elements=new Map(),calls=[];let stats={users:[{id:'11111111a',full_name:'Иванов <Иван>',position:'Учитель',completed_on_time:2,overdue:3},{id:'22222222b',full_name:'Иванов <Иван>',position:'Учитель',completed_on_time:0,overdue:0}]};
function el(id){if(!elements.has(id))elements.set(id,{innerHTML:'',textContent:'',value:'',classList:{toggle(){},contains(){return false}},querySelectorAll(){return []}});return elements.get(id)}
const ctx={document:{getElementById:el,querySelectorAll:()=>[],hidden:false},location:{pathname:'/Director'},sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},setInterval(){},fetch:async path=>{calls.push(path);return {ok:true,json:async()=>stats}},console};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('frontend/js/staff.js','utf8'),ctx);
(async()=>{
 vm.runInContext('staffToken="token";staffUser={id:"d"}',ctx);await vm.runInContext('loadDeadlineStats()',ctx);
 assert.match(el('statsAssignee').innerHTML,/Иванов &lt;Иван&gt; \(11111111\)/);assert.match(el('statsAssignee').innerHTML,/Иванов &lt;Иван&gt; \(22222222\)/);
 assert.match(el('deadlineStats').innerHTML,/Выберите исполнителя/);
 el('statsAssignee').value='11111111a';el('statsAssignee').onchange();
 assert.match(el('deadlineStats').innerHTML,/>2<\/strong><span>Выполнено в срок/);assert.match(el('deadlineStats').innerHTML,/>3<\/strong><span>Просрочено по сроку/);
 await el('statsRefresh').onclick();assert.equal(el('statsAssignee').value,'11111111a');assert.match(el('deadlineStats').innerHTML,/>2<\/strong>/);
 el('statsAssignee').value='22222222b';el('statsAssignee').onchange();assert.match(el('deadlineStats').innerHTML,/>0<\/strong><span>Выполнено в срок/);
 stats={users:[]};await el('statsRefresh').onclick();assert.match(el('deadlineStats').innerHTML,/Данных пока нет/);assert.ok(calls.includes('/api/staff/deadline-stats'));
 console.log('Staff deadline statistics UI OK');
})().catch(e=>{console.error(e);process.exitCode=1});
