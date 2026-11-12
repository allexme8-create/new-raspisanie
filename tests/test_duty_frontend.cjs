const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
async function run(role){
 const els=new Map(),calls=[];let calendar={quarter:2,start:'2026-11-01',end:'2026-11-30',today:'2026-11-09',active:true,timezone:'Asia/Krasnoyarsk',entries:[{day:'2026-11-10',slot:0,full_name:'<Админ>',position:'Заместитель',class_name:'',mine:false},{day:'2026-11-10',slot:1,full_name:'Учитель',position:'Учитель',class_name:'5А',mine:false}]};
 const selected={dataset:{dutySelect:role==='teacher'?'2026-11-10':'2026-11-11',slot:role==='teacher'?'2':'0'}};
 function el(id){if(!els.has(id))els.set(id,{innerHTML:'',textContent:'',value:'',disabled:false,required:false,classList:{toggle(){},contains(){return false}},scrollIntoView(){},querySelectorAll(s){return s==='[data-duty-select]'?[selected]:[]}});return els.get(id)}
 const ctx={byId:el,role,staffToken:'token',staffUser:{id:'u'},document:{hidden:false},setInterval(){},confirm:()=>true,escapeHTML:s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),errorAt:(id,e)=>el(id).innerHTML=e.message,request:async(path,opts)=>{calls.push({path,opts});if(!opts)return calendar;return {ok:true}},console};
 vm.createContext(ctx);vm.runInContext(fs.readFileSync('frontend/js/duty.js','utf8'),ctx);await vm.runInContext('loadDutyCalendar()',ctx);
 assert.match(el('dutyPeriod').textContent,/2-я четверть: 1 ноября 2026 года — 30 ноября 2026 года/);assert.doesNotMatch(el('dutyPeriod').textContent,/часовой пояс|Krasnoyarsk/i);assert.match(el('dutyMap').innerHTML,/10 ноября 2026 года/);assert.match(el('dutyMap').innerHTML,/&lt;Админ&gt;/);assert.match(el('dutyMap').innerHTML,/Учитель · 5А/);assert.match(el('dutyMap').innerHTML,/data-duty-select="2026-11-09"/);assert.doesNotMatch(el('dutyMap').innerHTML,/data-duty-select="2026-11-08"/);
 selected.onclick();el('dutyClass').value='7Б';await el('dutyForm').onsubmit({preventDefault(){}});
 const post=calls.find(c=>c.opts?.method==='POST');assert.equal(post.opts.body.day,role==='teacher'?'2026-11-10':'2026-11-11');assert.equal(post.opts.body.shift,role==='teacher'?2:null);assert.equal(post.opts.body.class_name,role==='teacher'?'7Б':'');
 assert.match(el('dutyError').innerHTML,/Вы записаны/);
}
(async()=>{await run('teacher');await run('associate');console.log('Duty calendar UI OK')})().catch(e=>{console.error(e);process.exitCode=1});
