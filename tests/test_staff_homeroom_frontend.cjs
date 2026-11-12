const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('frontend/staff.html','utf8');assert.match(html,/<div id="profileHomeroom"/);assert.match(html,/<strong id="staffIdentity">/);assert.match(html,/Классное руководство назначает и изменяет администратор/);
async function run(role,path){
 const elements=new Map();let response={user:{role,homeroom_class:'6Б'}};
 function el(id){if(!elements.has(id)){const classes=new Set();elements.set(id,{textContent:'',innerHTML:'',value:'',classList:{toggle(n,on){on?classes.add(n):classes.delete(n)},contains:n=>classes.has(n)},querySelectorAll(){return []}})}return elements.get(id)}
 const context={document:{getElementById:el,querySelectorAll:()=>[],hidden:false},location:{pathname:path},sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},setInterval(){},fetch:async()=>({ok:true,json:async()=>response}),console};
 vm.createContext(context);vm.runInContext(fs.readFileSync('frontend/js/staff.js','utf8'),context);
 vm.runInContext(`staffToken='token';staffUser={id:'u',role:'${role}',full_name:'Иван',homeroom_class:'<5А>'};showIdentity(staffUser)`,context);
 assert.equal(el('profileHomeroom').classList.contains('hidden'),role!=='teacher');
 if(role==='teacher'){
   assert.equal(el('profileHomeroomStatus').textContent,'Назначено · <5А>');
   el('staffFullName').value='Несохранённые изменения';await vm.runInContext('refreshProfileHomeroom()',context);
   assert.equal(el('profileHomeroomStatus').textContent,'Назначено · 6Б');assert.equal(el('staffFullName').value,'Несохранённые изменения');
   response={user:{role,homeroom_class:''}};await vm.runInContext('refreshProfileHomeroom()',context);assert.equal(el('profileHomeroomStatus').textContent,'Не назначено');
 }
}
(async()=>{await run('teacher','/teacher');await run('associate','/associate');await run('director','/Director');console.log('Teacher homeroom profile OK')})().catch(e=>{console.error(e);process.exitCode=1});
