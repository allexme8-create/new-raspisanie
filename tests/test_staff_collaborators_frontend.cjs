const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const els=new Map(),calls=[];let cards=[];
function el(id){if(!els.has(id))els.set(id,{innerHTML:'',textContent:'',value:'',classList:{toggle(){},contains(){return false}},querySelectorAll(s){return s==='[data-task-card]'?cards:[]}});return els.get(id)}
const output={innerHTML:''},error={innerHTML:''},names={textContent:''},select={value:'u2',innerHTML:''},button={disabled:false};
const invite={elements:{user_id:select},querySelector:()=>button};
const comment={elements:{text:{value:'',defaultValue:''}},querySelector:()=>button};
const detail={dataset:{discussion:'task1'},open:false,querySelector(s){return ({'.task-comments':output,'.task-action-error':error,'[data-invite]':invite,'[data-comment]':comment})[s]},querySelectorAll(){return []}};
const card={detail,querySelector(s){return ({'[data-discussion]':detail,'[data-complete]':null,'.task-collaborators':names})[s]}};
const context={document:{getElementById:el,querySelectorAll:()=>[],hidden:false},location:{pathname:'/associate'},sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},setInterval(){},console,fetch:async(path,opts)=>{calls.push({path,opts});let data=path.endsWith('/candidates')?{users:[{id:'u2',full_name:'<Иван>',position:'Учитель',role:'teacher'}]}:path.endsWith('/comments')?{comments:[{id:'c',author_name:'А',created_at:'2030-01-02T00:00:00Z',text:'Комментарий'}],events:[{id:'e',author_name:'Б',created_at:'2030-01-01T00:00:00Z',text:'<история>'}]}:{user:{id:'u2',full_name:'<Иван>',position:'Учитель',role:'teacher'}};return {ok:true,json:async()=>data}}};
vm.createContext(context);vm.runInContext(fs.readFileSync('frontend/js/staff.js','utf8'),context);
(async()=>{
 vm.runInContext('staffToken="token";staffUser={id:"author"}',context);
 const task='{id:"task1",director_id:"author",assignee_id:"u",status:"pending",deadline:"2030-01-01T00:00:00Z",description:"Тест",collaborators:[{full_name:"<Имя>",position:"Учитель"}]}';
 const markup=vm.runInContext(`taskMarkup(${task})`,context);
 assert.match(markup,/data-invite/);assert.match(markup,/Соисполнители: &lt;Имя&gt; · Учитель/);
 assert.doesNotMatch(vm.runInContext(`taskMarkup({...${task},completed_at:"2030-01-01"})`,context),/data-invite/);
 assert.doesNotMatch(vm.runInContext(`taskMarkup({...${task},director_id:"someone"})`,context),/data-invite/);
 cards=[card];vm.runInContext('bindTaskCards("taskList")',context);detail.open=true;detail.ontoggle();await new Promise(r=>setImmediate(r));
 assert.match(select.innerHTML,/&lt;Иван&gt; · Учитель/);assert.match(output.innerHTML,/&lt;история&gt;/);assert.ok(output.innerHTML.indexOf('история')<output.innerHTML.indexOf('Комментарий'));
 await invite.onsubmit({preventDefault(){}});assert.equal(names.innerHTML,'Соисполнители: <span class="person-teacher">&lt;Иван&gt;</span> · Учитель');assert.ok(calls.some(c=>c.path.endsWith('/collaborators')&&JSON.parse(c.opts.body).user_id==='u2'));
 console.log('Staff collaborators UI OK');
})().catch(e=>{console.error(e);process.exitCode=1});
