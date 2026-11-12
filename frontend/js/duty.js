"use strict";
let dutyCalendar=null, dutySelected=null, dutyTeachers=[], dutyVersion=0;
function resetDuty(){
  dutyVersion++;dutyCalendar=null;dutySelected=null;dutyTeachers=[];byId("dutyTeacher").innerHTML="";byId("dutyClass").value="";byId("dutyMap").innerHTML="";
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
      if(entry){const name=entry.full_name||"ФИО не указано",position=entry.position?` · ${entry.position}`:"",cls=entry.class_name?` · ${entry.class_name}`:"";
        return `<div class="duty-slot occupied"><span class="duty-mobile-label">${escapeHTML(dutySlotLabel(slot))}: </span><strong>${escapeHTML(name)}</strong>${escapeHTML(position+cls)}${mine&&day>=data.today?` <button type="button" class="duty-action" data-duty-cancel="${escapeHTML(day)}" data-slot="${slot}">Отменить запись</button>`:""}</div>`;}
      const selected=dutySelected?.day===day&&dutySelected?.slot===slot;
      return `<div class="duty-slot"><span class="duty-mobile-label">${escapeHTML(dutySlotLabel(slot))}: </span>${allowed&&canAct?`<button type="button" class="duty-action ${selected?'selected':''}" data-duty-select="${escapeHTML(day)}" data-slot="${slot}">${selected?'Выбрано':'Свободно · выбрать'}</button>`:'<span class="muted">Свободно</span>'}</div>`;
    }).join("");
    return `<div class="duty-row ${day===data.today?'duty-today':''}"><strong>${escapeHTML(dutyDateText(day))}${day===data.today?' · сегодня':''}</strong>${slots}</div>`;
  }).join("")}</div>`;
  byId("dutyMap").querySelectorAll("[data-duty-select]").forEach(button=>button.onclick=()=>{dutySelected={day:button.dataset.dutySelect,slot:Number(button.dataset.slot)};renderDuty();byId("dutyForm").scrollIntoView({behavior:"smooth",block:"center"});});
  byId("dutyMap").querySelectorAll("[data-duty-cancel]").forEach(button=>button.onclick=async()=>{
    if(!confirm("Отменить вашу запись на дежурство?"))return;button.disabled=true;byId("dutyError").innerHTML="";
    try{await request(`/api/staff/duty/${encodeURIComponent(button.dataset.dutyCancel)}/${Number(button.dataset.slot)}`,{method:"DELETE"});await loadDutyCalendar();}
    catch(e){errorAt("dutyError",e);button.disabled=false;}
  });
}
async function loadDutyCalendar(){
  if(role==="director"||!staffToken||!staffUser)return;
  const session=staffToken, version=++dutyVersion;
  try{const [data,teachers]=await Promise.all([request("/api/staff/duty"),role==="associate"?request("/api/staff/assignees"):Promise.resolve(null)]);if(staffToken!==session||version!==dutyVersion)return;
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
    dutyCalendar=data;renderDuty();}
  catch(e){if(staffToken===session&&version===dutyVersion)errorAt("dutyError",e);}
}
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
