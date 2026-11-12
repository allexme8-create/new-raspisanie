const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const page=fs.readFileSync('frontend/admin.html','utf8');
assert.doesNotMatch(page,/SMTP_PASSWORD|data-oauth-provider|mailSettingsForm/);
assert.match(page,/Создать пользователя/);
const map=new Map(),handlers={};
const buttons={show:{dataset:{showUser:'0'}},reset:{dataset:{resetUser:'0'}},del:{dataset:{deleteUser:'0'}}};
function element(id){
 if(!map.has(id))map.set(id,{innerHTML:'',textContent:'',value:'',disabled:false,classList:{contains:()=>true},querySelector:selector=>selector.startsWith('[data-show-user')?buttons.show:{disabled:false},querySelectorAll:selector=>selector==='[data-show-user]'?[buttons.show]:selector==='[data-reset-user]'?[buttons.reset]:selector==='[data-delete-user]'?[buttons.del]:[]});
 return map.get(id);
}
const calls=[];
const context={token:'admin-token',$:element,esc:s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),confirm:()=>true,document:{addEventListener:(event,fn)=>handlers[event]=fn},api:async(path,opts={})=>{calls.push({path,opts});if(path==='/api/admin/users'&&!opts.method)return {users:[{id:'u1',email:'teacher@example.com',role:'associate'}]};if(path.endsWith('/password/reset'))return {password:'new-secret'};if(path.endsWith('/password'))return {password:'current-secret'};if(path==='/api/admin/users')return {user:{id:'u1',email:'teacher@example.com'},password:'initial-secret'};return {ok:true}},console};
vm.createContext(context);vm.runInContext(fs.readFileSync('frontend/js/staff-admin.js','utf8'),context);
(async()=>{
 await handlers['admin-panel-open']();
 assert.match(element('staffUsersList').innerHTML,/Показать пароль/);
 assert.doesNotMatch(element('staffUsersList').innerHTML,/current-secret/);
 await buttons.show.onclick();
 assert.equal(element('staffPassword0').textContent,'Пароль: current-secret');
 await buttons.show.onclick();assert.equal(element('staffPassword0').textContent,'');
 await buttons.reset.onclick();
 assert.equal(element('staffPassword0').textContent,'Новый пароль: new-secret');
 element('staffEmail').value='teacher@example.com';element('staffRole').value='associate';element('staffPosition').value='Заместитель директора по УВР';
 await element('staffCreateForm').onsubmit({preventDefault(){},currentTarget:{querySelector:()=>({disabled:false})}});
 assert.match(element('staffAdminResult').innerHTML,/initial-secret/);
 assert.equal(calls.find(c=>c.path==='/api/admin/users' && c.opts.method==='POST').opts.body.position,'Заместитель директора по УВР');
 handlers['admin-panel-close']();assert.equal(element('staffAdminResult').innerHTML,'');assert.equal(element('staffUsersList').innerHTML,'');
 assert.ok(calls.some(c=>c.path==='/api/admin/users/u1/password/reset'));
 console.log('Staff admin password UI OK');
})().catch(e=>{console.error(e);process.exitCode=1});
