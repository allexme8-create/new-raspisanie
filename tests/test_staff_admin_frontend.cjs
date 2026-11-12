const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const page=fs.readFileSync('frontend/admin.html','utf8');
assert.doesNotMatch(page,/SMTP_PASSWORD|data-oauth-provider|mailSettingsForm/);
assert.match(page,/Создать пользователя/);
assert.match(page,/id="staffFullName"[^>]*maxlength="200"/);
const map=new Map(),handlers={};
const buttons={edit:{dataset:{editUser:'0'},querySelector:()=>({disabled:false})},show:{dataset:{showUser:'0'}},reset:{dataset:{resetUser:'0'}},del:{dataset:{deleteUser:'0'}}};
function element(id){
 if(!map.has(id))map.set(id,{innerHTML:'',textContent:'',value:'',disabled:false,classList:{contains:()=>true,toggle(){}},querySelector:selector=>selector.startsWith('[data-show-user')?buttons.show:{disabled:false},querySelectorAll:selector=>selector==='[data-edit-user]'?[buttons.edit]:selector==='[data-show-user]'?[buttons.show]:selector==='[data-reset-user]'?[buttons.reset]:selector==='[data-delete-user]'?[buttons.del]:[]});
 return map.get(id);
}
const calls=[];
const context={token:'admin-token',$:element,esc:s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),confirm:()=>true,document:{addEventListener:(event,fn)=>handlers[event]=fn},api:async(path,opts={})=>{calls.push({path,opts});if(path==='/api/admin/planner')return {project:{classes:[{name:'5А'},{name:'6Б'}]}};if(path==='/api/admin/users'&&!opts.method)return {users:[{id:'u1',email:'teacher@example.com',full_name:'<Иван>',role:'teacher',homeroom_class:'5А'}]};if(path.endsWith('/password/reset'))return {password:'new-secret'};if(path.endsWith('/password'))return {password:'current-secret'};if(path==='/api/admin/users')return {user:{id:'u1',email:'teacher@example.com'},password:'initial-secret'};return {ok:true}},console};
vm.createContext(context);vm.runInContext(fs.readFileSync('frontend/js/staff-admin.js','utf8'),context);
(async()=>{
 await handlers['admin-panel-open']();
 assert.match(element('staffUsersList').innerHTML,/Показать пароль/);assert.match(element('staffUsersList').innerHTML,/<strong><span class="person-teacher">&lt;Иван&gt;<\/span><\/strong>/);assert.match(element('staffUsersList').innerHTML,/<strong>учитель<\/strong>/);assert.match(element('staffHomeroom').innerHTML,/5А/);
 assert.doesNotMatch(element('staffUsersList').innerHTML,/current-secret/);assert.match(element('staffUsersList').innerHTML,/Классное руководство/);element('staffEditName0').value='Иванова';element('staffEditEmail0').value='teacher@example.com';element('staffEditPosition0').value='Учитель';element('staffEditClass0').value='6Б';await buttons.edit.onsubmit({preventDefault(){}});assert.ok(calls.some(c=>c.path==='/api/admin/users/u1'&&c.opts.body.homeroom_class==='6Б'&&c.opts.body.full_name==='Иванова'));
 await buttons.show.onclick();
 assert.equal(element('staffPassword0').textContent,'Пароль: current-secret');
 await buttons.show.onclick();assert.equal(element('staffPassword0').textContent,'');
 await buttons.reset.onclick();
 assert.equal(element('staffPassword0').textContent,'Новый пароль: new-secret');
 element('staffFullName').value='  Иванова Анна  ';element('staffEmail').value='teacher@example.com';element('staffRole').value='teacher';element('staffHomeroom').value='5А';element('staffPosition').value='Заместитель директора по УВР';
 await element('staffCreateForm').onsubmit({preventDefault(){},currentTarget:{querySelector:()=>({disabled:false})}});
 assert.match(element('staffAdminResult').innerHTML,/initial-secret/);
 assert.equal(calls.find(c=>c.path==='/api/admin/users' && c.opts.method==='POST').opts.body.position,'Заместитель директора по УВР');
 assert.equal(calls.find(c=>c.path==='/api/admin/users' && c.opts.method==='POST').opts.body.full_name,'Иванова Анна');
 assert.equal(calls.find(c=>c.path==='/api/admin/users' && c.opts.method==='POST').opts.body.homeroom_class,'5А');assert.equal(element('staffFullName').value,'');
 handlers['admin-panel-close']();assert.equal(element('staffAdminResult').innerHTML,'');assert.equal(element('staffUsersList').innerHTML,'');
 assert.ok(calls.some(c=>c.path==='/api/admin/users/u1/password/reset'));
 console.log('Staff admin password UI OK');
})().catch(e=>{console.error(e);process.exitCode=1});
