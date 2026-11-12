const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const els=new Map(),calls=[];let cards=[];
function el(id){if(!els.has(id))els.set(id,{innerHTML:'',textContent:'',value:'',classList:{toggle(){},contains(){return false}},querySelectorAll(s){return s==='[data-task-card]'?cards:s==='[data-discussion]'?cards.map(c=>c.detail):[]}});return els.get(id)}
const output={innerHTML:''},error={innerHTML:''},partial={type:'checkbox',checked:false,defaultChecked:false},reason={type:'textarea',value:'',defaultValue:''},text={type:'textarea',value:'',defaultValue:''},button={disabled:false};
const progress={elements:{partial,reason},querySelector:()=>button,remove(){this.removed=true}},comment={elements:{text},querySelector:()=>button};
const detail={dataset:{discussion:'task1'},open:false,querySelector(s){return ({'.task-comments':output,'.task-action-error':error,'[data-comment]':comment,'[data-progress]':progress})[s]},querySelectorAll:()=>[partial,reason,text]};
const box={checked:false,disabled:false,dataset:{cycle:"0"}},status={textContent:''},summary={textContent:''},reasonOut={textContent:''};
const card={detail,className:'',querySelector(s){return ({'[data-discussion]':detail,'[data-complete]':box,'.task-status':status,'.task-progress-summary':summary,'.task-reason':reasonOut,'.task-rework':{textContent:''}})[s]}};
const context={document:{getElementById:el,querySelectorAll:()=>[],hidden:false},location:{pathname:'/users'},sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},setInterval(){},confirm:()=>true,console,fetch:async(path,opts)=>{calls.push({path,opts});let data=path.endsWith('/comments')?(opts.method==='POST'?{ok:true}:{comments:[{author_name:'<Учитель>',author_position:'Учитель',created_at:'2030-01-01T00:00:00Z',text:'<script>опасно</script>'}]}):path.endsWith('/progress')?{task:{partial:true,failure_reason:'Ждём'}}:{task:{status:'completed_on_time',failure_reason:'Ждём'}};return {ok:true,json:async()=>data}}};
vm.createContext(context);vm.runInContext(fs.readFileSync('frontend/js/staff.js','utf8'),context);
(async()=>{
 vm.runInContext('staffToken="token";staffUser={id:"u"}',context);
 const markup=vm.runInContext('taskMarkup({id:"task1",assignee_id:"u",status:"pending",description:"Тест",deadline:"2030-01-01T00:00:00Z",partial:true,failure_reason:"<опасно>"})',context);
 assert.match(markup,/Частично выполнено/);assert.match(markup,/&lt;опасно&gt;/);assert.match(markup,/data-progress/);assert.match(markup,/data-comment/);
 cards=[card];vm.runInContext('bindTaskCards("taskList")',context);
 detail.open=true;detail.ontoggle();await new Promise(resolve=>setImmediate(resolve));
 assert.match(output.innerHTML,/&lt;script&gt;опасно&lt;\/script&gt;/);
 partial.checked=true;reason.value='Ждём';await progress.onsubmit({preventDefault(){}});
 assert.equal(summary.textContent,'Частично выполнено');assert.equal(reasonOut.textContent,'Причина невыполнения: Ждём');
 assert.equal(reason.defaultValue,'Ждём');
 text.value='В работе';await comment.onsubmit({preventDefault(){}});assert.equal(text.value,'');
 detail.open=false;text.value='Черновик';assert.equal(vm.runInContext('taskDraftsOpen()',context),true);
 text.value='';assert.equal(vm.runInContext('taskDraftsOpen()',context),false);
 detail.open=true;box.checked=true;await box.onchange();assert.equal(status.textContent,'Выполнено в срок');assert.equal(progress.removed,true);assert.match(reasonOut.textContent,/Ранее указанная причина/);
 assert.ok(calls.some(c=>c.path.endsWith('/progress')&&JSON.parse(c.opts.body).partial));
 assert.ok(calls.some(c=>c.path.endsWith('/comments')&&c.opts.method==='POST'));
 console.log('Staff comments and progress UI OK');
})().catch(e=>{console.error(e);process.exitCode=1});
