"use strict";
const byId=id=>document.getElementById(id);
const escapeHTML=value=>String(value).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const role=location.pathname==="/Director"?"director":location.pathname==="/teacher"?"teacher":"associate";
const manager=role!=="teacher", key=`schedule_staff_${role}`;
let staffToken=sessionStorage.getItem(key)||"", staffUser=null, refreshing=false, unreadNotifications=[], showHidden=false;
byId("pageTitle").textContent=role==="director"?"Кабинет директора":role==="associate"?"Кабинет заместителя директора":"Кабинет учителя";
const roleNames={director:"Директор",associate:"Заместитель директора",teacher:"Учитель"};
function showIdentity(user){byId("staffIdentity").textContent=`${user.full_name||"ФИО не указано — заполните профиль"} · ${user.position||roleNames[user.role]||"Сотрудник"}`;}
const statuses={pending:"В работе",overdue:"Просрочено",completed_on_time:"Выполнено в срок",completed_late:"Выполнено с просрочкой"};
function screen(id){["staffLoginCard","changePasswordCard","staffPanel"].forEach(x=>byId(x).classList.toggle("hidden",x!==id));}
const staffViews=["staffProfileView","staffCreateView","staffStatsView","staffTasksView","staffProjectsView"];
function openStaffView(id){
  if((id==="staffCreateView"||id==="staffStatsView")&&!manager)return;
  if(id!=="staffHome"&&!staffViews.includes(id))return;
  byId("staffHome").classList.toggle("hidden",id!=="staffHome");
  byId("staffBack").classList.toggle("hidden",id==="staffHome");
  staffViews.forEach(view=>byId(view).classList.toggle("hidden",view!==id));
  if(id==="staffStatsView")loadDeadlineStats();
}
document.querySelectorAll("[data-staff-view]").forEach(button=>button.onclick=()=>openStaffView(button.dataset.staffView));
byId("staffBack").onclick=()=>openStaffView("staffHome");
function errorAt(id,error){byId(id).innerHTML=`<div class="alert err">${escapeHTML(error.message)}</div>`;}
async function request(path,{method="GET",body,anonymous=false}={}){
  const headers={};
  if(!anonymous&&staffToken){headers.Authorization=`Bearer ${staffToken}`;headers["X-Staff-Token"]=staffToken;}
  if(body!==undefined)headers["Content-Type"]="application/json";
  const response=await fetch(path,{method,headers,body:body===undefined?undefined:JSON.stringify(body),cache:"no-store"});
  let data={};try{data=await response.json();}catch(e){}
  if(response.status===401&&!anonymous){staffToken="";staffUser=null;sessionStorage.removeItem(key);screen("staffLoginCard");}
  if(!response.ok)throw new Error(typeof data.detail==="string"?data.detail:Array.isArray(data.detail)?data.detail.map(x=>x.msg).join("; "):`Ошибка ${response.status}`);
  return data;
}
async function showSession(data){
  staffUser=data.user;
  if(staffUser.role!==role){staffToken="";sessionStorage.removeItem(key);screen("staffLoginCard");throw new Error("Откройте кабинет вашей роли");}
  if(data.must_change){screen("changePasswordCard");return;}
  screen("staffPanel");showIdentity(staffUser);
  byId("staffFullName").value=staffUser.full_name||"";byId("staffPosition").value=staffUser.position||"";byId("profileResult").innerHTML="";
  byId("staffCreateChoice").classList.toggle("hidden",!manager);byId("staffStatsChoice").classList.toggle("hidden",!manager);openStaffView("staffHome");
  if(manager)await loadAssignees();
  await loadTasks();
  await loadNotifications();
  if(manager)await loadDeadlineStats();
}
async function loadDeadlineStats(){
  if(!manager||!staffToken||!staffUser)return;
  const tokenAtStart=staffToken;
  try{
    const stats=await request("/api/staff/deadline-stats");if(staffToken!==tokenAtStart)return;
    const number=value=>Number.isSafeInteger(value)&&value>=0?value:0;
    const total=number(stats.total),onTime=number(stats.completed_on_time),late=number(stats.completed_late),done=onTime+late;
    byId("statsError").innerHTML="";
    byId("deadlineStats").innerHTML=`<div class="deadline-stats"><div><strong>${total}</strong><span>Всего задач</span></div><div><strong>${number(stats.in_progress)}</strong><span>В работе, срок не истёк</span></div><div class="deadline-stat-warn"><strong>${number(stats.overdue)}</strong><span>Просрочено</span></div><div class="deadline-stat-ok"><strong>${onTime}</strong><span>Выполнено в срок</span></div><div class="deadline-stat-warn"><strong>${late}</strong><span>Выполнено с опозданием</span></div><div><strong>${done?`${Math.round(onTime/done*100)}%`:"—"}</strong><span>В срок среди выполненных</span></div></div>`;
  }catch(e){if(staffToken===tokenAtStart)errorAt("statsError",e);}
}
byId("statsRefresh").onclick=loadDeadlineStats;
async function loadAssignees(){
  try{
    const data=await request("/api/staff/assignees"),select=byId("taskAssignee"),previous=select.value;
    const names=new Map();data.users.forEach(u=>{if(u.full_name)names.set(u.full_name,(names.get(u.full_name)||0)+1);});
    select.innerHTML='<option value="">Выберите исполнителя</option>'+data.users.map(u=>{
      const label=u.full_name?u.full_name+(names.get(u.full_name)>1?` (${u.id.slice(0,8)})`:""):`ФИО не указано (${u.id.slice(0,8)})`;
      const roleName=u.position||roleNames[u.role]||"Сотрудник";
      return `<option value="${escapeHTML(u.id)}">${escapeHTML(label)} · ${escapeHTML(roleName)}</option>`;
    }).join("");
    if(data.users.some(u=>u.id===previous))select.value=previous;
    if(!data.users.length)select.innerHTML='<option value="">Нет доступных исполнителей</option>';
  }catch(e){errorAt("taskCreateError",e);}
}
function fmtDate(iso){return new Date(iso).toLocaleString("ru-RU",{day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit"});}
function personName(name,position){return (name||"ФИО не указано")+(position?` · ${position}`:"");}
function taskMarkup(t){
  const mine=t.assignee_id===staffUser.id, author=t.director_id===staffUser.id, participant=mine||(t.collaborators||[]).some(u=>u.id===staffUser.id);
  return `<article class="task-card status-${escapeHTML(t.status)}" data-task-card="${escapeHTML(t.id)}"><div class="task-top"><span class="task-status">${t.approved_at?"Выполнено полностью":escapeHTML(statuses[t.status]||t.status)}</span><span class="task-deadline">Срок: ${escapeHTML(fmtDate(t.deadline))}</span></div>
    <p class="task-notice hidden"></p>
    <p class="task-description">${escapeHTML(t.description)}</p>
    <p class="task-meta">Исполнитель: ${escapeHTML(personName(t.assignee_name,t.assignee_position))} · Автор: ${escapeHTML(personName(t.director_name,t.director_position))}</p>
    <p class="task-meta task-collaborators">${(t.collaborators||[]).length?`Соисполнители: ${(t.collaborators||[]).map(u=>escapeHTML(personName(u.full_name,u.position))).join("; ")}`:""}</p>
    ${t.hidden?'<p class="task-meta">Удалена из вашего списка</p>':""}
    <div class="task-actions">
      ${author&&t.completed_at&&!t.approved_at?`<button class="btn secondary" type="button" data-approve data-completed-at="${escapeHTML(t.completed_at)}">Выполнено полностью</button>`:""}
      ${t.hidden?'<button class="btn secondary" type="button" data-restore>Вернуть в список</button>':(author||(participant&&t.approved_at))?'<button class="btn secondary" type="button" data-hide>Удалить из моего списка</button>':""}
    </div>
    <p class="task-rework">${t.rework?"🔄 Доделать — задача возвращена на доработку":""}</p>
    <p class="task-progress-summary">${t.partial?'Частично выполнено':""}</p>
    <p class="task-reason">${t.failure_reason?`${t.completed_at?'Ранее указанная причина':'Причина невыполнения'}: ${escapeHTML(t.failure_reason)}`:""}</p>
    ${t.completed_at?`<p class="task-meta task-completed-at">Отмечено: ${escapeHTML(fmtDate(t.completed_at))}</p>`:""}
    ${mine?`<label class="task-complete"><input type="checkbox" data-complete="${escapeHTML(t.id)}" data-cycle="${Number.isInteger(t.cycle)?t.cycle:0}" data-completed-at="${escapeHTML(t.completed_at||"")}" ${t.completed_at?"checked":""} ${t.approved_at?"disabled":""}> Выполнено</label>`:""}
    <details class="task-discussion" data-discussion="${escapeHTML(t.id)}"><summary>Ход работы и комментарии</summary>
      ${t.director_id===staffUser.id&&t.completed_at&&!t.approved_at?`<form data-rework data-completed-at="${escapeHTML(t.completed_at)}"><h3>Вернуть на доработку</h3><div class="field"><label>Комментарий — что нужно доделать<textarea name="comment" maxlength="2000" rows="2" required></textarea></label></div><div class="field"><label>Новый срок<input name="deadline" type="datetime-local" required></label></div><button class="btn secondary" type="submit">Отправить на доработку</button></form>`:""}
      ${t.director_id===staffUser.id&&!t.completed_at?`<form data-invite><label>Добавить соисполнителя<select name="user_id" required><option value="">Загрузка пользователей…</option></select></label><p class="hint">Соисполнитель увидит задачу, историю и сможет писать комментарии. Изменять состояние может основной исполнитель.</p><button class="btn secondary" type="submit">Добавить</button></form>`:""}
      ${mine&&!t.completed_at?`<form data-progress><label class="task-complete"><input type="checkbox" name="partial" ${t.partial?"checked":""}> Частично выполнено</label><div class="field"><label>Причина невыполнения (необязательно)<textarea name="reason" maxlength="2000" rows="2">${escapeHTML(t.failure_reason||"")}</textarea></label></div><button class="btn secondary" type="submit">Сохранить состояние</button></form>`:""}
      <div class="task-comments" aria-live="polite">Загрузка комментариев…</div>
      <form data-comment><label>Комментарий<textarea name="text" maxlength="2000" rows="2" required></textarea></label><button class="btn secondary" type="submit">Отправить комментарий</button></form>
      <div class="task-action-error" aria-live="polite"></div>
    </details></article>`;
}
function taskDraftsOpen(){
  return ["taskList","projectList"].some(id=>Array.from(byId(id).querySelectorAll("[data-discussion]")).some(detail=>{
    if(detail.open)return true;
    return Array.from(detail.querySelectorAll("textarea,input[type=checkbox],input[type=datetime-local]")).some(input=>input.type==="checkbox"?input.checked!==input.defaultChecked:input.value!==input.defaultValue);
  }));
}
async function refreshComments(detail){
  const out=detail.querySelector(".task-comments");
  const data=await request(`/api/staff/tasks/${encodeURIComponent(detail.dataset.discussion)}/comments`);
  const history=[...(data.comments||[]).map(c=>({...c,event:false})),...(data.events||[]).map(c=>({...c,event:true}))].sort((a,b)=>a.created_at.localeCompare(b.created_at)||a.id.localeCompare(b.id));
  out.innerHTML=history.length?history.map(c=>`<div class="task-comment"><b>${escapeHTML(personName(c.author_name,c.author_position))}</b> <span class="task-meta">${escapeHTML(fmtDate(c.created_at))}${c.event?" · Событие":""}</span><p>${escapeHTML(c.text)}</p></div>`).join(""):'<p class="hint">Истории пока нет.</p>';
  if(detail.open&&data.notification_through_id){
    await request(`/api/staff/tasks/${encodeURIComponent(detail.dataset.discussion)}/notifications/read`,{method:"POST",body:{through_id:data.notification_through_id}});
    await loadNotifications();
  }
}
async function loadInviteOptions(form,tid){
  const data=await request(`/api/staff/tasks/${encodeURIComponent(tid)}/collaborators/candidates`),select=form.elements.user_id,previous=select.value;
  const names=new Map();data.users.forEach(u=>{const n=u.full_name||"ФИО не указано";names.set(n,(names.get(n)||0)+1)});
  select.innerHTML='<option value="">Выберите сотрудника</option>'+data.users.map(u=>{
    const name=u.full_name||"ФИО не указано",label=name+(names.get(name)>1||!u.full_name?` (${u.id.slice(0,8)})`:"");
    return `<option value="${escapeHTML(u.id)}">${escapeHTML(personName(label,u.position||roleNames[u.role]))}</option>`;
  }).join("");
  if(data.users.some(u=>u.id===previous))select.value=previous;
}
function paintTaskNotifications(){
  const counts=new Map();unreadNotifications.forEach(n=>counts.set(n.task_id,(counts.get(n.task_id)||0)+1));
  for(const id of ["taskList","projectList"])byId(id).querySelectorAll("[data-task-card]").forEach(card=>{
    const count=counts.get(card.dataset.taskCard)||0;card.classList.toggle("task-has-notification",count>0);
    const badge=card.querySelector(".task-notice");if(badge){badge.textContent=count?`🔔 Новых событий: ${count}`:"";badge.classList.toggle("hidden",!count);}
  });
}
async function loadNotifications(){
  if(!staffToken||!staffUser)return;
  const tokenAtStart=staffToken;
  try{
    const data=await request("/api/staff/notifications");if(staffToken!==tokenAtStart)return;
    unreadNotifications=data.notifications||[];
    const box=byId("staffNotifications"),list=byId("staffNotificationList");
    box.classList.toggle("hidden",unreadNotifications.length===0);
    list.innerHTML=unreadNotifications.map((n,i)=>`<button class="staff-notification" type="button" data-notification-index="${i}"><strong>${n.kind==="completed"?"✅ Задача выполнена":n.kind==="completion_undone"?"↩️ Отметка выполнения снята":n.kind==="approved"?"✅ Задача подтверждена полностью":n.kind==="rework"?"🔄 Задача возвращена на доработку":"💬 Новый комментарий"}</strong><span>${escapeHTML(n.description)}</span><small>${escapeHTML(personName(n.actor_name,n.actor_position))} · ${escapeHTML(fmtDate(n.created_at))}</small></button>`).join("");
    list.querySelectorAll("[data-notification-index]").forEach(button=>button.onclick=async()=>{
      const n=unreadNotifications[Number(button.dataset.notificationIndex)];if(!n)return;
      const view=n.project_id?"staffProjectsView":"staffTasksView",container=byId(n.project_id?"projectList":"taskList");
      let card=Array.from(container.querySelectorAll("[data-task-card]")).find(c=>c.dataset.taskCard===n.task_id);
      if((!card||n.kind==="rework")&&!taskDraftsOpen()){if(!card){showHidden=true;updateHiddenButtons();}await loadTasks();card=Array.from(container.querySelectorAll("[data-task-card]")).find(c=>c.dataset.taskCard===n.task_id);}
      if(!card){errorAt("taskListError",new Error("Не удалось открыть задачу. Закройте обсуждения и сохраните черновики, затем обновите список."));return;}
      openStaffView(view);card.scrollIntoView({behavior:"smooth",block:"center"});
      const detail=card.querySelector("[data-discussion]");if(detail.open)refreshComments(detail).catch(e=>errorAtElement(detail.querySelector(".task-action-error"),e));else detail.open=true;
      const completion=card.querySelector("[data-complete]");
      if(n.kind==="rework"&&completion&&completion.checked)errorAtElement(detail.querySelector(".task-action-error"),new Error("Чтобы обновить состояние задачи, сохраните черновики, закройте обсуждения и нажмите «Обновить»."));
    });
    paintTaskNotifications();
  }catch(e){if(staffToken===tokenAtStart)errorAt("taskListError",e);}
}
function bindTaskCards(id){
  byId(id).querySelectorAll("[data-task-card]").forEach(card=>{
    const detail=card.querySelector("[data-discussion]"),error=detail.querySelector(".task-action-error"),tid=detail.dataset.discussion;
    for(const action of ["approve","hide","restore"]){
      const button=card.querySelector(`[data-${action}]`);if(!button)continue;
      button.onclick=async()=>{
        if(taskDraftsOpen()){errorAt("taskListError",new Error("Закройте обсуждения и сохраните или очистите черновики перед изменением задачи."));return;}
        const message=action==="approve"?"Подтвердить, что задача выполнена полностью? Вернуть её на доработку после подтверждения нельзя.":action==="hide"?"Удалить задачу только из вашего списка? У остальных участников она останется.":"Вернуть задачу в список?";
        if(!confirm(message))return;button.disabled=true;
        try{await request(`/api/staff/tasks/${encodeURIComponent(tid)}/${action}`,{method:"POST",...(action==="approve"?{body:{expected_completed_at:button.dataset.completedAt}}:{})});await loadTasks();await loadNotifications();}
        catch(e){errorAt("taskListError",e);button.disabled=false;}
      };
    }
    const invite=detail.querySelector("[data-invite]");
    detail.ontoggle=()=>{if(detail.open){refreshComments(detail).catch(e=>errorAtElement(error,e));if(invite)loadInviteOptions(invite,tid).catch(e=>errorAtElement(error,e));}};
    if(invite)invite.onsubmit=async e=>{e.preventDefault();const button=invite.querySelector("button"),select=invite.elements.user_id;button.disabled=true;error.innerHTML="";
      try{const data=await request(`/api/staff/tasks/${encodeURIComponent(tid)}/collaborators`,{method:"POST",body:{user_id:select.value}});
        const out=card.querySelector(".task-collaborators"),label=personName(data.user.full_name,data.user.position||roleNames[data.user.role]);
        out.textContent=out.textContent?`${out.textContent}; ${label}`:`Соисполнители: ${label}`;await loadInviteOptions(invite,tid);
      }catch(e){errorAtElement(error,e);}finally{button.disabled=false;}
    };
    const rework=detail.querySelector("[data-rework]");
    if(rework)rework.onsubmit=async e=>{e.preventDefault();const button=rework.querySelector("button"),deadline=new Date(rework.elements.deadline.value);error.innerHTML="";
      if(Number.isNaN(deadline.getTime())){errorAtElement(error,new Error("Укажите новый срок"));return;}
      if(!confirm("Вернуть задачу исполнителю на доработку?"))return;button.disabled=true;
      try{const result=await request(`/api/staff/tasks/${encodeURIComponent(tid)}/rework`,{method:"POST",body:{comment:rework.elements.comment.value,deadline:deadline.toISOString(),expected_completed_at:rework.dataset.completedAt}});
        card.classList.remove("status-completed_on_time","status-completed_late","status-pending","status-overdue");card.classList.add(`status-${result.task.status}`);
        card.querySelector(".task-status").textContent=statuses[result.task.status]||result.task.status;
        card.querySelector(".task-deadline").textContent=`Срок: ${fmtDate(result.task.deadline)}`;
        card.querySelector(".task-rework").textContent="🔄 Доделать — задача возвращена на доработку";
        card.querySelector(".task-progress-summary").textContent="";card.querySelector(".task-reason").textContent="";
        const completed=card.querySelector(".task-completed-at");if(completed)completed.remove();rework.remove();
        if(detail.open)refreshComments(detail).catch(e=>errorAtElement(error,e));
      }catch(e){errorAtElement(error,e);}finally{button.disabled=false;}
    };
    const comment=detail.querySelector("[data-comment]");
    comment.onsubmit=async e=>{e.preventDefault();const button=comment.querySelector("button"),text=comment.elements.text;button.disabled=true;error.innerHTML="";
      try{await request(`/api/staff/tasks/${encodeURIComponent(tid)}/comments`,{method:"POST",body:{text:text.value}});text.value="";text.defaultValue="";await refreshComments(detail);}
      catch(e){errorAtElement(error,e);}finally{button.disabled=false;}
    };
    const progress=detail.querySelector("[data-progress]");
    if(progress)progress.onsubmit=async e=>{e.preventDefault();const button=progress.querySelector("button"),partial=progress.elements.partial,reason=progress.elements.reason;button.disabled=true;error.innerHTML="";
      try{const result=await request(`/api/staff/tasks/${encodeURIComponent(tid)}/progress`,{method:"PUT",body:{partial:partial.checked,reason:reason.value}});
        partial.checked=result.task.partial;partial.defaultChecked=partial.checked;reason.value=result.task.failure_reason;reason.defaultValue=reason.value;
        card.querySelector(".task-progress-summary").textContent=partial.checked?"Частично выполнено":"";
        card.querySelector(".task-reason").textContent=reason.value?`Причина невыполнения: ${reason.value}`:"";
        if(detail.open)refreshComments(detail).catch(e=>errorAtElement(error,e));
      }catch(e){errorAtElement(error,e);}finally{button.disabled=false;}
    };
    const box=card.querySelector("[data-complete]");
    if(box)box.onchange=async()=>{
      const completing=box.checked,previous=!completing;
      const unsaved=progress&&(progress.elements.partial.checked!==progress.elements.partial.defaultChecked||progress.elements.reason.value!==progress.elements.reason.defaultValue);
      const message=completing?(unsaved?"Отметить выполнение? Несохранённое состояние будет потеряно.":"Отметить задачу выполненной?"):"Снять отметку выполнения и вернуть задачу в работу?";
      if(!confirm(message)){box.checked=previous;return;}
      box.disabled=true;error.innerHTML="";
      try{
        const body={completed:completing,cycle:Number(box.dataset.cycle||0)};if(!completing)body.expected_completed_at=box.dataset.completedAt;
        const result=await request(`/api/staff/tasks/${encodeURIComponent(tid)}/completion`,{method:"PUT",body});
        box.dataset.cycle=String(result.task.cycle);box.dataset.completedAt=result.task.completed_at||"";box.defaultChecked=completing;box.disabled=false;
        card.className=`task-card status-${result.task.status}`;card.querySelector(".task-status").textContent=statuses[result.task.status]||result.task.status;
        card.querySelector(".task-progress-summary").textContent="";card.querySelector(".task-rework").textContent="";
        card.querySelector(".task-reason").textContent=result.task.failure_reason?`${completing?"Ранее указанная причина":"Причина невыполнения"}: ${result.task.failure_reason}`:"";
        if(completing&&progress)progress.remove();
        if(!completing){const completed=card.querySelector(".task-completed-at");if(completed)completed.remove();}
        if(detail.open)refreshComments(detail).catch(e=>errorAtElement(error,e));
        if(!taskDraftsOpen())await loadTasks();
      }catch(e){box.checked=previous;box.disabled=false;errorAtElement(error,e);detail.open=true;}
    };
  });
}
function errorAtElement(element,error){element.innerHTML=`<div class="alert err">${escapeHTML(error.message)}</div>`;}
async function loadTasks(){
  if(!staffToken||refreshing||taskDraftsOpen())return;refreshing=true;
  try{
    const [data,projectData]=await Promise.all([request(`/api/staff/tasks${showHidden?"?include_hidden=true":""}`),request("/api/staff/projects")]);
    if(taskDraftsOpen())return;
    byId("taskListError").innerHTML="";
    const ordinary=data.tasks.filter(t=>!t.project_id);
    byId("taskList").innerHTML=ordinary.length?ordinary.map(taskMarkup).join(""):'<p class="nodata">Задач пока нет.</p>';
    byId("projectList").innerHTML=projectData.projects.length?projectData.projects.map(p=>{
      const tasks=data.tasks.filter(t=>t.project_id===p.id),done=tasks.filter(t=>t.approved_at).length;
      const mine=tasks.filter(t=>t.assignee_id===staffUser.id||(t.collaborators||[]).some(u=>u.id===staffUser.id)),mineDone=mine.filter(t=>t.approved_at).length;
      const limited=role!=="director"&&p.owner_id!==staffUser.id;
      const participants=new Map();
      tasks.forEach(t=>{const people=[{id:t.assignee_id,full_name:t.assignee_name,position:t.assignee_position},...(t.collaborators||[])];people.forEach(u=>{const item=participants.get(u.id)||{name:personName(u.full_name,u.position),total:0,done:0};item.total++;if(t.approved_at)item.done++;participants.set(u.id,item);});});
      const involvement=!limited&&participants.size?`<p class="hint">Участники: ${Array.from(participants.values()).map(x=>`${escapeHTML(x.name)} — ${x.done}/${x.total}`).join(" · ")}</p>`:"";
      return `<article class="project-card"><h3>${escapeHTML(p.title)}</h3><p class="hint">Автор: ${escapeHTML(personName(p.owner_name,p.owner_position))} · ${limited?"Ваши задачи подтверждены":"Подтверждено полностью"}: ${limited?done:(p.approved_tasks??done)} из ${limited?tasks.length:(p.total_tasks??tasks.length)}${mine.length?` · Ваше участие: ${mineDone} из ${mine.length}`:""}</p><p class="task-meta">Проект: ${p.finished_at?"выполнен полностью":"в работе"}</p>${p.owner_id===staffUser.id&&!p.finished_at?`<button class="btn secondary" type="button" data-finish-project="${escapeHTML(p.id)}">Проект выполнен полностью</button>`:""}${involvement}${tasks.length?tasks.map(taskMarkup).join(""):'<p class="nodata">Задач пока нет.</p>'}</article>`;
    }).join(""):'<p class="nodata">Проектов пока нет.</p>';
    if(manager){const select=byId("taskProject"),previous=select.value,editable=projectData.projects.filter(p=>!p.finished_at&&(role==="director"||p.owner_id===staffUser.id));
      select.innerHTML='<option value="">Текущие задачи</option>'+editable.map(p=>`<option value="${escapeHTML(p.id)}">${escapeHTML(p.title)}</option>`).join("");
      if(editable.some(p=>p.id===previous))select.value=previous;
    }
    bindTaskCards("taskList");bindTaskCards("projectList");paintTaskNotifications();
    byId("projectList").querySelectorAll("[data-finish-project]").forEach(button=>button.onclick=async()=>{
      if(taskDraftsOpen()){errorAt("taskListError",new Error("Закройте обсуждения и сохраните черновики перед завершением проекта."));return;}
      if(!confirm("Подтвердить, что проект выполнен полностью? После этого новые задачи добавить нельзя."))return;button.disabled=true;
      try{await request(`/api/staff/projects/${encodeURIComponent(button.dataset.finishProject)}/complete`,{method:"POST"});await loadTasks();}
      catch(e){errorAt("taskListError",e);button.disabled=false;}
    });
  }catch(e){errorAt("taskListError",e);}finally{refreshing=false;}
}
byId("staffLoginForm").onsubmit=async e=>{
  e.preventDefault();const button=e.currentTarget.querySelector("button");button.disabled=true;byId("staffLoginError").innerHTML="";
  try{const data=await request("/api/staff/login",{method:"POST",anonymous:true,body:{email:byId("loginEmail").value.trim(),password:byId("loginPassword").value,role}});staffToken=data.token;sessionStorage.setItem(key,staffToken);byId("loginPassword").value="";await showSession(data);}
  catch(error){errorAt("staffLoginError",error);}finally{button.disabled=false;}
};
byId("staffPasswordForm").onsubmit=async e=>{
  e.preventDefault();const button=e.currentTarget.querySelector("button");button.disabled=true;byId("passwordError").innerHTML="";
  try{await request("/api/staff/password",{method:"POST",body:{password:byId("newPassword").value}});byId("newPassword").value="";await showSession(await request("/api/staff/me"));}
  catch(error){errorAt("passwordError",error);}finally{button.disabled=false;}
};
byId("staffProfileForm").onsubmit=async e=>{
  e.preventDefault();const button=e.currentTarget.querySelector("button");button.disabled=true;byId("profileResult").innerHTML="";
  try{const data=await request("/api/staff/profile",{method:"PUT",body:{full_name:byId("staffFullName").value,position:byId("staffPosition").value}});staffUser=data.user;byId("staffFullName").value=staffUser.full_name;byId("staffPosition").value=staffUser.position||"";showIdentity(staffUser);byId("profileResult").innerHTML='<div class="alert ok">Профиль сохранён.</div>';}
  catch(error){errorAt("profileResult",error);}finally{button.disabled=false;}
};
byId("projectForm").onsubmit=async e=>{
  e.preventDefault();const button=e.currentTarget.querySelector("button");button.disabled=true;byId("projectCreateError").innerHTML="";
  try{const data=await request("/api/staff/projects",{method:"POST",body:{title:byId("projectTitle").value}});byId("projectTitle").value="";await loadTasks();byId("taskProject").value=data.id;}
  catch(error){errorAt("projectCreateError",error);}finally{button.disabled=false;}
};
byId("taskForm").onsubmit=async e=>{
  e.preventDefault();const button=e.currentTarget.querySelector("button");button.disabled=true;byId("taskCreateError").innerHTML="";
  try{const deadline=new Date(byId("taskDeadline").value);if(Number.isNaN(deadline.getTime()))throw new Error("Укажите срок выполнения");
    await request("/api/staff/tasks",{method:"POST",body:{assignee_id:byId("taskAssignee").value,project_id:byId("taskProject").value||null,description:byId("taskDescription").value,deadline:deadline.toISOString()}});
    byId("taskDescription").value="";byId("taskDeadline").value="";await loadTasks();
  }catch(error){errorAt("taskCreateError",error);}finally{button.disabled=false;}
};
document.querySelectorAll("[data-logout]").forEach(button=>button.onclick=async()=>{
  try{await request("/api/staff/logout",{method:"POST"});}catch(e){}staffToken="";staffUser=null;unreadNotifications=[];byId("staffNotifications").classList.add("hidden");byId("staffNotificationList").innerHTML="";sessionStorage.removeItem(key);screen("staffLoginCard");
});
function updateHiddenButtons(){document.querySelectorAll("[data-toggle-hidden]").forEach(button=>button.textContent=showHidden?"Скрыть удалённые мной":"Показать удалённые мной");}
document.querySelectorAll("[data-toggle-hidden]").forEach(button=>button.onclick=()=>{
  if(taskDraftsOpen()){errorAt("taskListError",new Error("Закройте обсуждения и сохраните или очистите черновики."));return;}
  showHidden=!showHidden;updateHiddenButtons();loadTasks();
});
byId("taskRefresh").onclick=byId("projectRefresh").onclick=()=>{if(taskDraftsOpen()){errorAt("taskListError",new Error("Закройте обсуждения и сохраните или очистите черновики перед обновлением."));return;}if(manager)loadAssignees();loadTasks();};
setInterval(()=>{if(!document.hidden&&staffToken&&staffUser&&!byId("staffPanel").classList.contains("hidden")){loadTasks();loadNotifications();if(manager)loadDeadlineStats();}},30000);
if(staffToken)request("/api/staff/me").then(showSession).catch(e=>{if(staffToken)errorAt("staffLoginError",e);screen("staffLoginCard");});
