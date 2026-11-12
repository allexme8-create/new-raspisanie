"use strict";
let dutyCalendar=null, dutySelected=null, dutyTeachers=[], dutyVersion=0, dutyWeek=null, dutyWeekDirty=false, dutyAdminDay=null;
function resetDuty(){
  dutyVersion++;dutyCalendar=null;dutySelected=null;dutyTeachers=[];dutyWeek=null;dutyWeekDirty=false;dutyAdminDay=null;byId("dutyWeekFields").innerHTML="";byId("dutyWeekSection").classList.add("hidden");byId("dutyAdminForm").classList.add("hidden");byId("dutyTeacher").innerHTML="";byId("dutyClass").value="";byId("dutyMap").innerHTML="";
  byId("dutyError").innerHTML="";byId("dutySelected").textContent="Выберите свободное место на карте.";byId("dutySubmit").disabled=true;
}
const dutySlotLabel=slot=>slot===0?"Дежурный администратор":`${slot}-я смена · учитель`;
function dutyDateText(value){const date=new Date(value+"T00:00:00Z");return `${date.toLocaleDateString("ru-RU",{timeZone:"UTC",day:"numeric",month:"long"})} ${date.getUTCFullYear()} года`;}
function dutyDays(start,end){
  const result=[];for(let d=new Date(start+"T00:00:00Z"),last=new Date(end+"T00:00:00Z");d<=last;d.setUTCDate(d.getUTCDate()+1))result.push(d.toISOString().slice(0,10));return result;
}
function renderDuty(){
  if(!dutyCalendar)return;
  const data=dutyCalendar,map=new Map(data.entries.map(e=>[`${e.day}:${e.slot}`,e]));
  byId("dutyPeriod").textContent=`${data.quarter}-я четверть: ${dutyDateText(data.start)} — ${dutyDateText(data.end)}.`+(data.active?"":" Сейчас каникулы: показана следующая четверть, запись откроется с её начала.");
  const chosen=dutySelected&&map.get(`${dutySelected.day}:${dutySelected.slot}`);
  if(chosen||(dutySelected&&(!data.active||dutySelected.day<data.today||dutySelected.day<data.start||dutySelected.day>data.end)))dutySelected=null;
  const teacherSlot=!!dutySelected&&dutySelected.slot!==0;
  byId("dutyClassField").classList.toggle("hidden",!teacherSlot);
  byId("dutyClass").required=teacherSlot;
  byId("dutyTeacherField").classList.toggle("hidden",role!=="associate"||!teacherSlot);
  byId("dutyTeacher").required=role==="associate"&&teacherSlot;
  byId("dutySubmit").textContent=role==="associate"&&teacherSlot?"Назначить учителя":"Записаться";
  byId("dutySelected").textContent=dutySelected?`Выбрано: ${dutyDateText(dutySelected.day)} · ${dutySlotLabel(dutySelected.slot)}`:"Выберите свободное место на карте.";
  byId("dutySubmit").disabled=!dutySelected||!data.active;
  byId("dutyMap").innerHTML=`<div class="duty-grid"><div class="duty-grid-head"><b>Дата</b><b>Дежурный администратор</b><b>1-я смена</b><b>2-я смена</b></div>${dutyDays(data.start,data.end).map(day=>{
    const slots=[0,1,2].map(slot=>{
      const entry=map.get(`${day}:${slot}`),mine=entry?.mine,allowed=(role==="associate"||slot!==0),canAct=data.active&&day>=data.today;
      const editAdmin=role==="associate"&&slot===0&&canAct?` <button type="button" class="duty-action" data-duty-admin="${escapeHTML(day)}">Изменить на эту дату</button>`:"";
      if(entry){const name=entry.full_name||"ФИО не указано",position=entry.position?` · ${entry.position}`:"",cls=entry.class_name?` · ${entry.class_name}`:"";
        return `<div class="duty-slot occupied"><span class="duty-mobile-label">${escapeHTML(dutySlotLabel(slot))}: </span><strong>${escapeHTML(name)}</strong>${escapeHTML(position+cls)}${mine&&day>=data.today?` <button type="button" class="duty-action" data-duty-cancel="${escapeHTML(day)}" data-slot="${slot}">Отменить запись</button>`:""}${editAdmin}</div>`;}
      const selected=dutySelected?.day===day&&dutySelected?.slot===slot;
      return `<div class="duty-slot"><span class="duty-mobile-label">${escapeHTML(dutySlotLabel(slot))}: </span>${allowed&&canAct?`<button type="button" class="duty-action ${selected?'selected':''}" data-duty-select="${escapeHTML(day)}" data-slot="${slot}">${selected?'Выбрано':'Свободно · выбрать'}</button>`:'<span class="muted">Свободно</span>'}${editAdmin}</div>`;
    }).join("");
    return `<div class="duty-row ${day===data.today?'duty-today':''}"><strong>${escapeHTML(dutyDateText(day))}${day===data.today?' · сегодня':''}</strong>${slots}</div>`;
  }).join("")}</div>`;
  byId("dutyMap").querySelectorAll("[data-duty-select]").forEach(button=>button.onclick=()=>{dutySelected={day:button.dataset.dutySelect,slot:Number(button.dataset.slot)};renderDuty();byId("dutyForm").scrollIntoView({behavior:"smooth",block:"center"});});
  byId("dutyMap").querySelectorAll("[data-duty-admin]").forEach(button=>button.onclick=()=>{
    dutyAdminDay=button.dataset.dutyAdmin;byId("dutyAdminSelected").textContent=`Изменить дежурного администратора: ${dutyDateText(dutyAdminDay)}`;
    byId("dutyAdminDeputy").innerHTML=deputyOptions(null);byId("dutyAdminForm").classList.remove("hidden");byId("dutyAdminForm").scrollIntoView({behavior:"smooth",block:"center"});
  });
  byId("dutyMap").querySelectorAll("[data-duty-cancel]").forEach(button=>button.onclick=async()=>{
    if(!confirm("Отменить вашу запись на дежурство?"))return;button.disabled=true;byId("dutyError").innerHTML="";
    try{await request(`/api/staff/duty/${encodeURIComponent(button.dataset.dutyCancel)}/${Number(button.dataset.slot)}`,{method:"DELETE"});await loadDutyCalendar();}
    catch(e){errorAt("dutyError",e);button.disabled=false;}
  });
}
async function loadDutyCalendar(){
  if(role==="director"||!staffToken||!staffUser)return;
  const session=staffToken, version=++dutyVersion;
  try{const [data,teachers,week]=await Promise.all([request("/api/staff/duty"),role==="associate"?request("/api/staff/assignees"):Promise.resolve(null),role==="associate"?request("/api/staff/duty/week-template"):Promise.resolve(null)]);if(staffToken!==session||version!==dutyVersion)return;
    if(teachers){
      dutyTeachers=teachers.users.filter(u=>u.role==="teacher");
      const select=byId("dutyTeacher"),previous=select.value,counts=new Map();
      dutyTeachers.forEach(u=>{const name=u.full_name||"ФИО не указано";counts.set(name,(counts.get(name)||0)+1);});
      select.innerHTML='<option value="">Выберите учителя</option>'+dutyTeachers.map(u=>{
        const name=u.full_name||"ФИО не указано",label=name+(counts.get(name)>1||!u.full_name?` (${u.id.slice(0,8)})`:"")+(u.position?` · ${u.position}`:"");
        return `<option value="${escapeHTML(u.id)}"${u.full_name?"":" disabled"}>${escapeHTML(label)}</option>`;
      }).join("");
      if(dutyTeachers.some(u=>u.id===previous&&u.full_name))select.value=previous;
    }
    if(week){dutyWeek=week;byId("dutyWeekSection").classList.remove("hidden");if(!dutyWeekDirty)renderDutyWeek();}
    dutyCalendar=data;renderDuty();}
  catch(e){if(staffToken===session&&version===dutyVersion)errorAt("dutyError",e);}
}
const dutyWeekDays=["Понедельник","Вторник","Среда","Четверг","Пятница"];
function deputyOptions(selected){
  const users=dutyWeek?.deputies||[],counts=new Map();users.forEach(u=>{const name=u.full_name||"ФИО не указано";counts.set(name,(counts.get(name)||0)+1);});
  let options=`<option value="">Не назначен</option>`+users.map(u=>{
    const name=u.full_name||"ФИО не указано",label=name+(counts.get(name)>1||!u.full_name?` (${u.id.slice(0,8)})`:"")+(u.position?` · ${u.position}`:"");
    return `<option value="${escapeHTML(u.id)}"${u.id===selected?' selected':''}${u.full_name?'':' disabled'}>${escapeHTML(label)}</option>`;
  }).join("");
  if(selected&&!users.some(u=>u.id===selected))options+=`<option value="${escapeHTML(selected)}" selected disabled>Пользователь удалён — выберите замену</option>`;
  return options;
}
function renderDutyWeek(){
  byId("dutyWeekFields").innerHTML=dutyWeekDays.map((day,i)=>`<div class="field"><label for="dutyWeek${i}">${day}</label><select id="dutyWeek${i}">${deputyOptions(dutyWeek.week[i])}</select></div>`).join("");
  dutyWeekDays.forEach((_,i)=>byId(`dutyWeek${i}`).onchange=()=>{dutyWeekDirty=true;});
}
byId("dutyWeekForm").onsubmit=async e=>{
  e.preventDefault();const button=byId("dutyWeekSave");button.disabled=true;byId("dutyError").innerHTML="";
  try{await request("/api/staff/duty/week-template",{method:"PUT",body:{deputies:dutyWeekDays.map((_,i)=>byId(`dutyWeek${i}`).value||null)}});dutyWeekDirty=false;byId("dutyError").innerHTML='<div class="alert ok">Недельный шаблон сохранён.</div>';await loadDutyCalendar();}
  catch(error){errorAt("dutyError",error);}finally{button.disabled=false;}
};
byId("dutyAdminClose").onclick=()=>{dutyAdminDay=null;byId("dutyAdminForm").classList.add("hidden");};
async function saveDutyAdmin(restore){
  if(!dutyAdminDay)return;const day=dutyAdminDay,save=byId("dutyAdminSave"),reset=byId("dutyAdminRestore");save.disabled=reset.disabled=true;byId("dutyError").innerHTML="";
  try{await request(`/api/staff/duty/admin/${encodeURIComponent(day)}`,restore?{method:"DELETE"}:{method:"PUT",body:{user_id:byId("dutyAdminDeputy").value||null}});
    byId("dutyAdminClose").onclick();byId("dutyError").innerHTML='<div class="alert ok">Изменения сохранены.</div>';await loadDutyCalendar();
  }catch(error){errorAt("dutyError",error);}finally{save.disabled=reset.disabled=false;}
}
byId("dutyAdminForm").onsubmit=e=>{e.preventDefault();return saveDutyAdmin(false);};
byId("dutyAdminRestore").onclick=()=>saveDutyAdmin(true);
byId("dutyRefresh").onclick=()=>{byId("dutyError").innerHTML="";loadDutyCalendar();};
byId("dutyForm").onsubmit=async e=>{
  e.preventDefault();if(!dutySelected)return;const button=byId("dutySubmit");button.disabled=true;byId("dutyError").innerHTML="";
  const selection=dutySelected;
  const teacherSlot=selection.slot!==0, assignTeacher=role==="associate"&&teacherSlot;
  try{await request("/api/staff/duty",{method:"POST",body:{day:selection.day,shift:teacherSlot?selection.slot:null,class_name:teacherSlot?byId("dutyClass").value.trim():"",...(assignTeacher?{teacher_id:byId("dutyTeacher").value}: {})}});
    dutySelected=null;byId("dutyError").innerHTML=assignTeacher?'<div class="alert ok">Учитель назначен на дежурство.</div>':'<div class="alert ok">Вы записаны на дежурство.</div>';await loadDutyCalendar();
  }catch(error){errorAt("dutyError",error);await loadDutyCalendar();}finally{if(dutySelected)button.disabled=false;}
};

setInterval(()=>{if(!document.hidden&&staffToken&&staffUser&&!byId("staffDutyView").classList.contains("hidden"))loadDutyCalendar();},60000);
