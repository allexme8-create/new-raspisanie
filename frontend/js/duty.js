"use strict";
let dutyCalendar=null, dutySelected=null, dutyTeachers=[], dutyVersion=0, dutyWeek=null, dutyWeekDirty=false, dutyAdminDay=null, dutyQuarterYear=null, dutyQuarterVersion=0, dutyFeedback=null, dutySaving=false, dutyClasses=[], ownHomeroom="";
function resetDuty(){
  byId("dutyFormParking").appendChild(byId("dutyForm"));byId("dutyForm").classList.add("hidden");dutyFeedback=null;
  dutyVersion++;dutyQuarterVersion++;dutyQuarterYear=null;byId("dutyQuarterSection").classList.add("hidden");byId("dutyQuarterForm").classList.add("hidden");byId("dutyQuarterYear").value="";dutyCalendar=null;dutySelected=null;byId("dutyAnyDate").classList.add("hidden");dutyTeachers=[];dutyClasses=[];ownHomeroom="";byId("dutyClassManual").value="";dutyWeek=null;dutyWeekDirty=false;dutyAdminDay=null;byId("dutyWeekFields").innerHTML="";byId("dutyWeekSection").classList.add("hidden");byId("dutyAdminForm").classList.add("hidden");byId("dutyTeacher").innerHTML="";byId("dutyClass").value="";byId("dutyMap").innerHTML="";
  byId("dutyError").innerHTML="";byId("dutySelected").textContent="Выберите свободное место на карте.";byId("dutySubmit").disabled=true;
}
const dutyRoleClass=role=>["teacher","associate","director"].includes(role)?`person-${role}`:"";
function dutyShortName(fullName){
  const parts=String(fullName||"").trim().split(/\s+/).filter(Boolean);
  if(!parts.length)return "ФИО не указано";
  return [parts[0],...parts.slice(1).map(part=>/^(?:\p{L}\.)+$/u.test(part)?part:`${Array.from(part)[0]}.`)].join(" ");
}
const dutySlotLabel=slot=>slot===0?"Дежурный администратор":`${slot}-я смена · учитель`;
function dutyDateText(value){const date=new Date(value+"T00:00:00Z");return `${date.toLocaleDateString("ru-RU",{timeZone:"UTC",day:"numeric",month:"long"})} ${date.getUTCFullYear()} года`;}
function dutyShortDate(value){
  const date=new Date(value+"T00:00:00Z"),weekday=["вс","пн","вт","ср","чт","пт","сб"][date.getUTCDay()];
  return `${String(date.getUTCDate()).padStart(2,"0")}.${String(date.getUTCMonth()+1).padStart(2,"0")} · ${weekday}`;
}
function dutyDays(start,end){
  const result=[];for(let d=new Date(start+"T00:00:00Z"),last=new Date(end+"T00:00:00Z");d<=last;d.setUTCDate(d.getUTCDate()+1))if(d.getUTCDay()!==0)result.push(d.toISOString().slice(0,10));return result;
}
function renderDuty(){
  if(!dutyCalendar)return;
  const data=dutyCalendar,map=new Map(data.entries.map(e=>[`${e.day}:${e.slot}`,e]));
  byId("dutyPeriod").textContent=`${data.quarter}-я четверть: ${dutyDateText(data.start)} — ${dutyDateText(data.end)}.`+(data.active?"":" Сейчас каникулы: показана следующая четверть, запись откроется с её начала.");
  const chosen=dutySelected&&map.get(`${dutySelected.day}:${dutySelected.slot}`);
  if(dutySelected&&!dutySelected.replace&&(chosen||!data.active||dutySelected.day<data.today||dutySelected.day<data.start||dutySelected.day>data.end))dutySelected=null;
  const teacherSlot=!!dutySelected&&dutySelected.slot!==0;
  byId("dutyClassField").classList.toggle("hidden",!teacherSlot);
  updateDutyClass(teacherSlot);
  byId("dutyTeacherField").classList.toggle("hidden",role!=="associate"||!teacherSlot);
  byId("dutyTeacher").required=role==="associate"&&teacherSlot;
  byId("dutySubmit").textContent=dutySelected?.replace?"Сохранить назначение":role==="associate"&&teacherSlot?"Назначить учителя":"Записаться";
  byId("dutySelected").textContent=dutySelected?`Выбрано: ${dutyDateText(dutySelected.day)} · ${dutySlotLabel(dutySelected.slot)}`:"Выберите свободное место на карте.";
  byId("dutySubmit").disabled=!dutySelected||(!dutySelected.replace&&!data.active);
  // Preserve the form, its entered values and listeners before rebuilding the map.
  byId("dutyFormParking").appendChild(byId("dutyForm"));
  byId("dutyForm").classList.toggle("hidden",!dutySelected);
  byId("dutyMap").innerHTML=`<div class="duty-grid"><div class="duty-grid-head"><b>Дата</b><b>Дежурный администратор</b><b>1-я смена</b><b>2-я смена</b></div>${dutyDays(data.start,data.end).map(day=>{
    const slots=[0,1,2].map(slot=>{
      const entry=map.get(`${day}:${slot}`),mine=entry?.mine,allowed=(role==="associate"||slot!==0),canAct=data.active&&day>=data.today;
      const editAdmin=role==="associate"&&slot===0&&canAct?` <button type="button" class="duty-action" data-duty-admin="${escapeHTML(day)}">Изменить на эту дату</button>`:"";
      const editTeacher=role==="associate"&&slot!==0?` <button type="button" class="duty-action" data-duty-replace="${escapeHTML(day)}" data-slot="${slot}">Изменить учителя</button>`:"";
      if(entry){const name=entry.full_name||"ФИО не указано",position=entry.position?` · ${entry.position}`:"",cls=entry.class_name?` · ${entry.class_name}`:"";
        return `<div class="duty-slot occupied"><span class="duty-mobile-label">${escapeHTML(dutySlotLabel(slot))}: </span><strong><span class="${entry.full_name?dutyRoleClass(entry.role):''}">${escapeHTML(name)}</span>${escapeHTML(position)}</strong>${escapeHTML(cls)}${mine&&day>=data.today?` <button type="button" class="duty-action" data-duty-cancel="${escapeHTML(day)}" data-slot="${slot}">Отменить запись</button>`:""}${editAdmin}${editTeacher}</div>`;}
      const selected=dutySelected?.day===day&&dutySelected?.slot===slot;
      return `<div class="duty-slot"><span class="duty-mobile-label">${escapeHTML(dutySlotLabel(slot))}: </span>${allowed&&canAct?`<button type="button" class="duty-action ${selected?'selected':''}" data-duty-select="${escapeHTML(day)}" data-slot="${slot}">${selected?'Выбрано':'Свободно · выбрать'}</button>`:'<span class="muted">Свободно</span>'}${editAdmin}</div>`;
    }).join("");
    return `<div class="duty-row ${day===data.today?'duty-today':''}${new Date(day+"T00:00:00Z").getUTCDay()===6?' duty-saturday':''}"><strong>${escapeHTML(dutyShortDate(day))}${day===data.today?' · сегодня':''}</strong>${slots}</div>${dutyFeedback?.day===day?`<div class="duty-inline-feedback alert ${dutyFeedback.error?'err':'ok'}" role="status">${escapeHTML(dutyFeedback.text)}</div>`:""}${dutySelected?.day===day?'<div id="dutyFormHere" class="duty-inline-location"></div>':""}`;
  }).join("")}</div>`;
  if(dutySelected&&dutySelected.day>=data.start&&dutySelected.day<=data.end)byId("dutyFormHere").appendChild(byId("dutyForm"));
  byId("dutyMap").querySelectorAll("[data-duty-select]").forEach(button=>button.onclick=()=>{
    if(dutySaving)return;dutyFeedback=null;dutySelected={day:button.dataset.dutySelect,slot:Number(button.dataset.slot)};renderDuty();
  });
  byId("dutyMap").querySelectorAll("[data-duty-replace]").forEach(button=>button.onclick=()=>{
    if(dutySaving)return;dutyFeedback=null;dutySelected={day:button.dataset.dutyReplace,slot:Number(button.dataset.slot),replace:true};byId("dutyTeacher").value="";byId("dutyClass").value="";byId("dutyClassManual").value="";renderDuty();
  });
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
  try{const [data,teachers,week,catalog]=await Promise.all([request("/api/staff/duty"),role==="associate"?request("/api/staff/assignees"):Promise.resolve(null),role==="associate"?request("/api/staff/duty/week-template"):Promise.resolve(null),request("/api/staff/duty/classes")]);if(staffToken!==session||version!==dutyVersion)return;
    dutyClasses=catalog.classes;ownHomeroom=catalog.homeroom_class||"";
    const classSelect=byId("dutyClass"),previousClass=classSelect.value;
    classSelect.innerHTML='<option value="">Выберите класс</option>'+dutyClasses.map(name=>`<option value="${escapeHTML(name)}">${escapeHTML(name)}</option>`).join("");
    if(dutyClasses.includes(previousClass))classSelect.value=previousClass;
    if(teachers){
      dutyTeachers=teachers.users.filter(u=>u.role==="teacher");
      const select=byId("dutyTeacher"),previous=select.value,counts=new Map();
      dutyTeachers.forEach(u=>{const name=dutyShortName(u.full_name);counts.set(name,(counts.get(name)||0)+1);});
      select.innerHTML='<option value="">Выберите учителя</option>'+dutyTeachers.map(u=>{
        const name=dutyShortName(u.full_name),label=name+(counts.get(name)>1||!u.full_name?` (${u.id.slice(0,8)})`:"")+(u.position?` · ${u.position}`:"");
        return `<option value="${escapeHTML(u.id)}" class="person-teacher"${u.full_name?"":" disabled"}>${escapeHTML(label)}</option>`;
      }).join("");
      if(dutyTeachers.some(u=>u.id===previous&&u.full_name))select.value=previous;
    }
    if(week){byId("dutyAnyDate").classList.remove("hidden");dutyWeek=week;byId("dutyWeekSection").classList.remove("hidden");byId("dutyQuarterSection").classList.remove("hidden");
      if(!byId("dutyQuarterYear").value){const day=new Date(data.start+"T00:00:00Z");byId("dutyQuarterYear").value=String(day.getUTCFullYear()-(day.getUTCMonth()<7?1:0));}
      if(!dutyWeekDirty)renderDutyWeek();}
    dutyCalendar=data;renderDuty();}
  catch(e){if(staffToken===session&&version===dutyVersion)errorAt("dutyError",e);}
}
function updateDutyClass(teacherSlot){
  const teacher=role==="teacher"?null:dutyTeachers.find(u=>u.id===byId("dutyTeacher").value);
  const homeroom=role==="teacher"?ownHomeroom:(teacher?.homeroom_class||"");
  const select=byId("dutyClass"),manual=byId("dutyClassManual"),usingCatalog=dutyClasses.length>0;
  select.classList.toggle("hidden",!usingCatalog);manual.classList.toggle("hidden",usingCatalog);
  select.disabled=!teacherSlot||!usingCatalog||!!homeroom;manual.disabled=!teacherSlot||usingCatalog||!!homeroom;
  select.required=teacherSlot&&usingCatalog&&!homeroom;manual.required=teacherSlot&&!usingCatalog&&!homeroom;
  if(homeroom){if(usingCatalog)select.value=homeroom;else manual.value=homeroom;}
  byId("dutyClassHint").textContent=homeroom?`Классное руководство: ${homeroom}. Класс подставляется автоматически.`:usingCatalog?"Выберите класс из конструктора расписания.":"Список классов пока пуст. Укажите класс вручную или добавьте классы в конструкторе расписания.";
}
byId("dutyTeacher").onchange=()=>{byId("dutyClass").value="";byId("dutyClassManual").value="";updateDutyClass(!!dutySelected&&dutySelected.slot!==0);};
byId("dutyQuarterLoad").onclick=async()=>{
  const input=byId("dutyQuarterYear"),year=Number(input.value),session=staffToken,version=++dutyQuarterVersion;
  if(!Number.isInteger(year)||year<1900||year>2200){errorAt("dutyError",new Error("Укажите учебный год от 1900 до 2200"));return;}
  byId("dutyQuarterForm").classList.add("hidden");dutyQuarterYear=null;byId("dutyError").innerHTML="";
  try{const result=await request(`/api/staff/duty/quarters/${year}`);if(session!==staffToken||version!==dutyQuarterVersion)return;
    dutyQuarterYear=year;byId("dutyQuarterFields").innerHTML=result.quarters.map((q,i)=>`<div class="field"><strong>${i+1}-я четверть</strong><label for="quarterStart${i}">Начало</label><input type="date" id="quarterStart${i}" value="${escapeHTML(q.start)}" required><label for="quarterEnd${i}">Окончание</label><input type="date" id="quarterEnd${i}" value="${escapeHTML(q.end)}" required></div>`).join("");
    byId("dutyQuarterForm").classList.remove("hidden");
  }catch(error){if(session===staffToken&&version===dutyQuarterVersion)errorAt("dutyError",error);}
};
byId("dutyQuarterYear").oninput=()=>{dutyQuarterVersion++;dutyQuarterYear=null;byId("dutyQuarterForm").classList.add("hidden");};
byId("dutyQuarterForm").onsubmit=async e=>{
  e.preventDefault();if(dutyQuarterYear===null)return;const year=dutyQuarterYear,button=byId("dutyQuarterSave"),session=staffToken;button.disabled=true;byId("dutyError").innerHTML="";
  try{await request(`/api/staff/duty/quarters/${year}`,{method:"PUT",body:{quarters:[0,1,2,3].map(i=>({start:byId(`quarterStart${i}`).value,end:byId(`quarterEnd${i}`).value}))}});
    if(session!==staffToken)return;byId("dutyError").innerHTML='<div class="alert ok">Даты четвертей сохранены.</div>';await loadDutyCalendar();
  }catch(error){if(session===staffToken)errorAt("dutyError",error);}finally{button.disabled=false;}
};
const dutyWeekDays=["Понедельник","Вторник","Среда","Четверг","Пятница"];
function deputyOptions(selected){
  const users=dutyWeek?.deputies||[],counts=new Map();users.forEach(u=>{const name=dutyShortName(u.full_name);counts.set(name,(counts.get(name)||0)+1);});
  let options=`<option value="">Не назначен</option>`+users.map(u=>{
    const name=dutyShortName(u.full_name),label=name+(counts.get(name)>1||!u.full_name?` (${u.id.slice(0,8)})`:"")+(u.position?` · ${u.position}`:"");
    return `<option value="${escapeHTML(u.id)}" class="person-associate"${u.id===selected?' selected':''}${u.full_name?'':' disabled'}>${escapeHTML(label)}</option>`;
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
byId("dutyAnyOpen").onclick=()=>{
  if(role!=="associate"||!dutyCalendar||dutySaving)return;
  const day=byId("dutyAnyDay").value,slot=Number(byId("dutyAnyShift").value),parsed=new Date(day+"T00:00:00Z");
  if(!/^\d{4}-\d{2}-\d{2}$/.test(day)||Number.isNaN(parsed.getTime())||parsed.toISOString().slice(0,10)!==day||parsed.getUTCDay()===0||![1,2].includes(slot)){
    errorAt("dutyError",new Error("Выберите дату, кроме воскресенья, и смену."));return;
  }
  byId("dutyError").innerHTML="";dutyFeedback=null;dutySelected={day,slot,replace:true};byId("dutyTeacher").value="";byId("dutyClass").value="";byId("dutyClassManual").value="";renderDuty();
};
byId("dutyRefresh").onclick=()=>{byId("dutyError").innerHTML="";loadDutyCalendar();};
byId("dutyClose").onclick=()=>{if(dutySaving)return;dutySelected=null;dutyFeedback=null;renderDuty();};
byId("dutyForm").onsubmit=async e=>{
  e.preventDefault();if(!dutySelected||dutySaving)return;dutySaving=true;const button=byId("dutySubmit");button.disabled=true;byId("dutyError").innerHTML="";
  const selection=dutySelected;
  const teacherSlot=selection.slot!==0, assignTeacher=role==="associate"&&teacherSlot;
  const session=staffToken;
  try{await request(selection.replace?`/api/staff/duty/teacher/${encodeURIComponent(selection.day)}/${selection.slot}`:"/api/staff/duty",{method:selection.replace?"PUT":"POST",body:{day:selection.day,shift:teacherSlot?selection.slot:null,class_name:teacherSlot?(dutyClasses.length?byId("dutyClass").value:byId("dutyClassManual").value.trim()):"",...(assignTeacher?{teacher_id:byId("dutyTeacher").value}: {})}});
    if(session!==staffToken)return;
    dutySelected=null;dutyFeedback={day:selection.day,text:assignTeacher?"Учитель назначен на дежурство.":"Вы записаны на дежурство."};if(selection.replace)byId("dutyError").innerHTML='<div class="alert ok">Назначение сохранено.</div>';renderDuty();await loadDutyCalendar();
  }catch(error){if(session!==staffToken)return;dutyFeedback={day:selection.day,text:error.message,error:true};if(selection.replace)errorAt("dutyError",error);renderDuty();await loadDutyCalendar();}finally{dutySaving=false;if(dutySelected)button.disabled=false;}
};

setInterval(()=>{if(!document.hidden&&staffToken&&staffUser&&!dutySelected&&!dutySaving&&!byId("staffDutyView").classList.contains("hidden"))loadDutyCalendar();},60000);
