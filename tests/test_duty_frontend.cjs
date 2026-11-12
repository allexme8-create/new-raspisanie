const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
async function run(role){
 const els=new Map(),calls=[];let failNext=false,calendar={quarter:2,start:'2026-11-01',end:'2026-11-30',today:'2026-11-09',active:true,timezone:'Asia/Krasnoyarsk',entries:[{day:'2026-11-10',slot:0,full_name:'<Админ>',role:'associate',position:'Заместитель',class_name:'',mine:false},{day:'2026-11-10',slot:1,full_name:'Учитель',role:'teacher',position:'Учитель',class_name:'5А',mine:false}]};
 const adminEdit={dataset:{dutyAdmin:'2026-11-10'}};
 const selected={dataset:{dutySelect:role==='teacher'?'2026-11-10':'2026-11-11',slot:role==='teacher'?'2':'0'}};
 function el(id){if(!els.has(id))els.set(id,{innerHTML:'',textContent:'',value:'',disabled:false,required:false,classList:{toggle(){},add(){},remove(){},contains(){return false}},scrollIntoView(){this.scrolled=true},appendChild(child){child.parent=this},querySelectorAll(s){return s==='[data-duty-select]'?[selected]:s==='[data-duty-admin]'?[adminEdit]:[]}});return els.get(id)}
 const ctx={byId:el,role,staffToken:'token',staffUser:{id:'u'},document:{hidden:false},setInterval(){},confirm:()=>true,escapeHTML:s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),errorAt:(id,e)=>el(id).innerHTML=e.message,request:async(path,opts)=>{calls.push({path,opts});if(opts?.method==='POST'&&failNext){failNext=false;calendar.entries.push({day:'2026-11-10',slot:2,full_name:'Другой учитель',position:'Учитель',class_name:'9А',mine:false});throw new Error('Место уже занято');}if(!opts)return path==='/api/staff/duty/classes'?{classes:['7Б','8А'],homeroom_class:role==='teacher'?'7Б':''}:path.startsWith('/api/staff/duty/quarters/')?{quarters:[{start:'2026-09-01',end:'2026-10-31'},{start:'2026-11-01',end:'2026-12-31'},{start:'2027-01-10',end:'2027-03-31'},{start:'2027-04-01',end:'2027-05-31'}]}:path==='/api/staff/duty/week-template'?{week:[null,null,null,null,null],deputies:[{id:'dep1',full_name:'Заместитель',position:'Завуч'}]}:path==='/api/staff/assignees'?{users:[{id:'abc12345',role:'teacher',full_name:'Учитель <Иван>',position:'Математик',homeroom_class:'7Б'},{id:'other123',role:'teacher',full_name:'Учитель <Иван>'},{id:'blank123',role:'teacher',full_name:''}]}:calendar;return {ok:true}},console};
 vm.createContext(ctx);vm.runInContext(fs.readFileSync('frontend/js/duty.js','utf8'),ctx);await vm.runInContext('loadDutyCalendar()',ctx);
 assert.match(el('dutyPeriod').textContent,/2-я четверть: 1 ноября 2026 года — 30 ноября 2026 года/);assert.doesNotMatch(el('dutyPeriod').textContent,/часовой пояс|Krasnoyarsk/i);assert.match(el('dutyMap').innerHTML,/10\.11 · вт/);assert.match(el('dutyMap').innerHTML,/09\.11 · пн · сегодня/);assert.match(el('dutyMap').innerHTML,/class="person-associate">&lt;Админ&gt;/);assert.match(el('dutyMap').innerHTML,/class="person-teacher">Учитель/);assert.match(el('dutyMap').innerHTML,/Учитель · 5А/);assert.match(el('dutyMap').innerHTML,/data-duty-select="2026-11-09"/);assert.doesNotMatch(el('dutyMap').innerHTML,/data-duty-select="2026-11-08"/);assert.doesNotMatch(el('dutyMap').innerHTML,/15\.11 · вс/);assert.match(el('dutyMap').innerHTML,/14\.11 · сб/);
 selected.onclick();assert.equal(el('dutyForm').parent,el('dutyFormHere'));assert.equal(el('dutyForm').scrolled,undefined);assert.match(el('dutyMap').innerHTML,/id="dutyFormHere"/);el('dutyClass').value='7Б';await el('dutyForm').onsubmit({preventDefault(){}});
 const post=calls.find(c=>c.opts?.method==='POST');assert.equal(post.opts.body.day,role==='teacher'?'2026-11-10':'2026-11-11');assert.equal(post.opts.body.shift,role==='teacher'?2:null);assert.equal(post.opts.body.class_name,role==='teacher'?'7Б':'');
 assert.match(el('dutyMap').innerHTML,/Вы записаны на дежурство/);assert.equal(el('dutyForm').parent,el('dutyFormParking'));
 if(role==='associate'){
   assert.match(el('dutyMap').innerHTML,/data-duty-select="2026-11-10" data-slot="2"/);
   assert.match(el('dutyTeacher').innerHTML,/Учитель &lt;Иван&gt; \(abc12345\)/);assert.match(el('dutyTeacher').innerHTML,/value="blank123" class="person-teacher" disabled/);
   selected.dataset.dutySelect='2026-11-10';selected.dataset.slot='2';selected.onclick();el('dutyTeacher').value='abc12345';el('dutyTeacher').onchange();
   assert.equal(el('dutyTeacher').required,true);assert.equal(el('dutyClass').value,'7Б');assert.equal(el('dutyClass').disabled,true);assert.equal(el('dutyClass').required,false);
   await el('dutyForm').onsubmit({preventDefault(){}});
   const assignment=calls.filter(c=>c.opts?.method==='POST').at(-1).opts.body;
   assert.equal(assignment.teacher_id,'abc12345');assert.equal(assignment.shift,2);assert.equal(assignment.class_name,'7Б');
   assert.match(el('dutyMap').innerHTML,/Учитель назначен/);
   selected.onclick();el('dutyTeacher').value='abc12345';el('dutyClass').value='7Б';failNext=true;await el('dutyForm').onsubmit({preventDefault(){}});
   assert.match(el('dutyMap').innerHTML,/Место уже занято/);assert.equal(el('dutyForm').parent,el('dutyFormParking'));

   assert.equal(el('dutyQuarterYear').value,'2026');await el('dutyQuarterLoad').onclick();assert.match(el('dutyQuarterFields').innerHTML,/1-я четверть/);
   for(let i=0;i<4;i++){el(`quarterStart${i}`).value=`2026-09-0${i+1}`;el(`quarterEnd${i}`).value=`2026-09-1${i+1}`;}
   await el('dutyQuarterForm').onsubmit({preventDefault(){}});const quarters=calls.find(c=>c.path==='/api/staff/duty/quarters/2026'&&c.opts?.method==='PUT');assert.equal(quarters.opts.body.quarters.length,4);assert.equal(quarters.opts.body.quarters[0].start,'2026-09-01');
   assert.match(el('dutyWeekFields').innerHTML,/Понедельник/);assert.match(el('dutyWeekFields').innerHTML,/Заместитель · Завуч/);
   el('dutyWeek0').value='dep1';await el('dutyWeekForm').onsubmit({preventDefault(){}});
   const weekCall=calls.find(c=>c.path==='/api/staff/duty/week-template'&&c.opts?.method==='PUT');assert.equal(weekCall.opts.body.deputies[0],'dep1');assert.equal(weekCall.opts.body.deputies.length,5);
   adminEdit.onclick();assert.match(el('dutyAdminSelected').textContent,/10 ноября 2026 года/);el('dutyAdminDeputy').value='dep1';
   await el('dutyAdminForm').onsubmit({preventDefault(){}});const override=calls.find(c=>c.path==='/api/staff/duty/admin/2026-11-10'&&c.opts?.method==='PUT');assert.equal(override.opts.body.user_id,'dep1');
   adminEdit.onclick();await el('dutyAdminRestore').onclick();assert.ok(calls.some(c=>c.path==='/api/staff/duty/admin/2026-11-10'&&c.opts?.method==='DELETE'));

 }
}
(async()=>{await run('teacher');await run('associate');console.log('Duty calendar UI OK')})().catch(e=>{console.error(e);process.exitCode=1});
