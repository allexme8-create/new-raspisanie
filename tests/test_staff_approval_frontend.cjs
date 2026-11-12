const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const els=new Map(),calls=[];let cards=[];
function el(id){if(!els.has(id))els.set(id,{innerHTML:'',textContent:'',value:'',classList:{toggle(){},contains(){return false}},querySelectorAll(s){return s==='[data-task-card]'?cards:[]}});return els.get(id)}
const approve={dataset:{completedAt:'2030-01-01T00:00:00Z'},disabled:false},hide={disabled:false},error={innerHTML:''},comment={elements:{text:{}},querySelector:()=>({})};
const detail={dataset:{discussion:'t1'},open:false,querySelector(s){return ({'.task-action-error':error,'[data-comment]':comment})[s]},querySelectorAll(){return []}};
const card={querySelector(s){return ({'[data-discussion]':detail,'[data-approve]':approve,'[data-hide]':hide})[s]}};
const context={document:{getElementById:el,querySelectorAll:()=>[],hidden:false},location:{pathname:'/users'},sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},setInterval(){},confirm:()=>true,console,fetch:async(path,opts)=>{calls.push({path,opts});return {ok:true,json:async()=>({ok:true})}}};
vm.createContext(context);vm.runInContext(fs.readFileSync('frontend/js/staff.js','utf8'),context);
(async()=>{
 vm.runInContext('staffToken="token";staffUser={id:"author"};loadTasks=async()=>{};loadNotifications=async()=>{}',context);
 const base='{id:"t1",director_id:"author",assignee_id:"teacher",status:"completed_on_time",completed_at:"2030-01-01T00:00:00Z",deadline:"2030-01-01T00:00:00Z",description:"Тест"}';
 let markup=vm.runInContext(`taskMarkup(${base})`,context);assert.match(markup,/data-approve/);assert.match(markup,/data-hide/);assert.match(markup,/data-rework/);
 markup=vm.runInContext(`taskMarkup({...${base},approved_at:"2030-01-02"})`,context);assert.match(markup,/Выполнено полностью/);assert.doesNotMatch(markup,/data-approve|data-rework/);
 markup=vm.runInContext(`taskMarkup({...${base},hidden:true})`,context);assert.match(markup,/data-restore/);assert.doesNotMatch(markup,/data-hide/);
 vm.runInContext('staffUser={id:"teacher"}',context);
 assert.doesNotMatch(vm.runInContext(`taskMarkup(${base})`,context),/data-hide|data-approve/);
 assert.match(vm.runInContext(`taskMarkup({...${base},approved_at:"2030-01-02"})`,context),/data-hide/);
 vm.runInContext('staffUser={id:"author"}',context);cards=[card];vm.runInContext('bindTaskCards("taskList")',context);
 await approve.onclick();assert.equal(calls[0].path,'/api/staff/tasks/t1/approve');assert.equal(JSON.parse(calls[0].opts.body).expected_completed_at,'2030-01-01T00:00:00Z');
 await hide.onclick();assert.equal(calls[1].path,'/api/staff/tasks/t1/hide');
 console.log('Staff final approval UI OK');
})().catch(e=>{console.error(e);process.exitCode=1});
