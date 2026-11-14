"use strict";
/* Конструктор работает с отдельным черновиком, публикация — только явным действием. */
const plannerDays=["Пн","Вт","Ср","Чт","Пт","Сб"];
let plannerProject=null, plannerIssues=[];
let plannerMapClass="",plannerMapSelected=null,plannerMapBusy=false;
let roomRulesSelected="",roomRulesShift=1;
const plannerSearch={classes:"",teachers:"",subjects:"",rooms:"",groups:""};
const plannerRoot=$("plannerRoot");
const optionList=(items,value="name")=>items.map(x=>`<option value="${esc(x[value])}">${esc(x[value])}</option>`).join("");
const dayOptions=plannerDays.map(d=>`<option>${d}</option>`).join("");
const numberOptions=Array.from({length:12},(_,i)=>`<option>${i+1}</option>`).join("");
const field=(id,label,content)=>`<label>${label}${content.replace("<select",`<select id="${id}"`).replace("<input",`<input id="${id}"`)}</label>`;
const select=(id,label,opts)=>field(id,label,`<select required>${opts}</select>`);
const input=(id,label,placeholder,type="text",extra="")=>field(id,label,`<input type="${type}" placeholder="${placeholder}" required ${extra}>`);
function plannerRender(){
  const p=plannerProject;p.groups=p.groups||[];
  const openDetails=[...plannerRoot.querySelectorAll("details")].map(d=>d.open);
  const list=(key,format)=>p[key].length?p[key].map((x,i)=>{
    const editable=["classes","teachers","subjects","rooms","groups"].includes(key);
    const title=editable?`<button type="button" class="planner-name-edit" data-edit-kind="${key}" data-edit-index="${i}" title="Изменить">${format(x)} ✎</button>`:`<span>${format(x)}</span>`;
    const form=editable?`<form class="planner-inline-edit hidden" id="plannerEdit-${key}-${i}"><label class="sr-only" for="plannerEditInput-${key}-${i}">Новое название</label><input id="plannerEditInput-${key}-${i}" maxlength="80" required value="${esc(x.name)}"><button class="btn" type="submit">Сохранить</button><button class="btn secondary" type="button" data-edit-cancel>Отмена</button></form>`:"";
    return `<li class="planner-catalog-item" data-search-name="${esc(`${x.class_name||""} ${x.name||""}`.trim().toLocaleLowerCase("ru-RU"))}"><div class="planner-item-line">${title}<button type="button" class="planner-remove" data-kind="${key}" data-index="${i}" aria-label="Удалить ${esc(x.name||"запись")}">✕</button></div>${form}</li>`;
  }).join(""):'<li class="muted">Пока нет записей</li>';
  const loadOptions=p.loads.map(x=>`<option value="${esc(x.id)}">${esc(`${x.class_name}${x.group?` · ${x.group}`:""} · ${x.subject} · ${x.teacher} · ${x.room}`)}</option>`).join("");
  const nameForm=(type,label)=>`<form data-form="${type}" class="planner-form">${input(`${type}Name`,label,label)}<button class="btn" type="submit">Добавить</button></form>`;
  plannerRoot.innerHTML=`
    <div class="planner-actions planner-main-actions"><button type="button" id="plannerGenerate" class="btn">Автоподбор</button><button type="button" id="plannerPublish" class="btn">Опубликовать</button></div>
    <details class="planner-tools"><summary>Импорт и обновление</summary><div class="planner-actions"><button type="button" id="plannerRefresh" class="btn secondary">Обновить черновик</button><button type="button" id="plannerImportClasses" class="btn secondary">Импорт классов</button><button type="button" id="plannerImportTeachers" class="btn secondary">Импорт учителей</button><button type="button" id="plannerImportSubjects" class="btn secondary">Импорт предметов</button><button type="button" id="plannerImportRooms" class="btn secondary">Импорт кабинетов</button><button type="button" id="plannerImportGroups" class="btn secondary">Импорт групп</button></div></details>
    <div id="plannerMessage" aria-live="polite"></div>
    <p class="hint">Изменения сохраняются в черновике. Автоподбор сохраняет уже расставленные уроки; публикация заменяет текущее расписание на сайте только после проверки.</p>
    <details class="planner-map-section" open><summary>Карта расписания</summary>
      <p class="hint">Черновик выбранного класса. Перетащите урок или нажмите его, затем нажмите нужную ячейку. Изменения попадут на сайт только после публикации.</p>
      <label class="planner-map-picker">Класс <select id="plannerMapClass">${p.classes.map(c=>`<option value="${esc(c.name)}"${c.name===plannerMapClass?' selected':''}>${esc(c.name)}</option>`).join("")}</select></label>
      <p id="plannerMapStatus" class="hint" aria-live="polite"></p><div id="plannerMap"></div>
    </details>
    <details open><summary>1. Справочники</summary><div class="planner-grid">
      <details class="planner-category"><summary>Классы · ${p.classes.length}</summary><form data-form="classes" class="planner-form">${input("className","Класс","Например, 5а")}${select("classShift","Смена",'<option value="1">1</option><option value="2">2</option>')}${input("classMax","Максимум уроков в день","7","number",'min="1" max="12" value="7"')}<button class="btn">Добавить</button></form><details class="planner-catalog-list"><summary>Список классов (${p.classes.length})</summary><input class="planner-search" type="search" data-catalog-search="classes" value="${esc(plannerSearch.classes)}" placeholder="Поиск класса" aria-label="Поиск класса"><ul class="planner-list" data-catalog-list="classes">${list("classes",x=>`${esc(x.name)} · ${x.shift}-я смена`)}</ul></details></details>
      <details class="planner-category"><summary>Учителя · ${p.teachers.length}</summary>${nameForm("teachers","ФИО учителя")}<details class="planner-catalog-list"><summary>Список учителей (${p.teachers.length})</summary><input class="planner-search" type="search" data-catalog-search="teachers" value="${esc(plannerSearch.teachers)}" placeholder="Поиск учителя" aria-label="Поиск учителя"><ul class="planner-list" data-catalog-list="teachers">${list("teachers",x=>esc(x.name))}</ul></details><details class="planner-catalog-list"><summary>Приоритетные кабинеты учителей</summary><p class="hint">При автоподборе предпочитается кабинет учителя; если он занят, подбирается другой из справочника. Кабинет, явно указанный в нагрузке, обязателен и имеет преимущество.</p>${p.teachers.map((teacher,i)=>`<form class="planner-form" data-teacher-room="${i}"><label>${esc(teacher.name)}<select name="room"><option value="">Без предпочтения</option>${p.rooms.map(r=>`<option value="${esc(r.name)}"${r.name===teacher.preferred_room?' selected':''}>${esc(r.name)}</option>`).join("")}</select></label><button class="btn secondary" type="submit">Сохранить</button></form>`).join("")}</details><p class="hint">Это справочник расписания, а не учётные записи сотрудников.</p></details>
      <details class="planner-category"><summary>Группы классов · ${p.groups.length}</summary><p class="hint">Номера групп, определённые по нескольким именам в старом расписании, предположительные: проверьте их. Совместное преподавание не всегда означает разделение класса.</p><form data-form="groups" class="planner-form">${select("groupClass","Класс",optionList(p.classes))}${input("groupName","Название группы","Например, 1 группа")}<button class="btn">Добавить</button></form><details class="planner-catalog-list"><summary>Список групп (${p.groups.length})</summary><input class="planner-search" type="search" data-catalog-search="groups" value="${esc(plannerSearch.groups)}" placeholder="Поиск класса или группы" aria-label="Поиск класса или группы"><ul class="planner-list" data-catalog-list="groups">${list("groups",x=>`${esc(x.class_name)} · ${esc(x.name)}${x.inferred?" · проверить":""}`)}</ul></details></details>
      <details class="planner-category"><summary>Предметы · ${p.subjects.length}</summary>${nameForm("subjects","Предмет")}<details class="planner-catalog-list"><summary>Список предметов (${p.subjects.length})</summary><input class="planner-search" type="search" data-catalog-search="subjects" value="${esc(plannerSearch.subjects)}" placeholder="Поиск предмета" aria-label="Поиск предмета"><ul class="planner-list" data-catalog-list="subjects">${list("subjects",x=>esc(x.name))}</ul></details></details>
      <details class="planner-category"><summary>Кабинеты · ${p.rooms.length}</summary>${nameForm("rooms","Кабинет")}<details class="planner-catalog-list"><summary>Список кабинетов (${p.rooms.length})</summary><input class="planner-search" type="search" data-catalog-search="rooms" value="${esc(plannerSearch.rooms)}" placeholder="Поиск кабинета" aria-label="Поиск кабинета"><ul class="planner-list" data-catalog-list="rooms">${list("rooms",x=>esc(x.name))}</ul></details></details>
    </div></details>
    <details><summary>2. Недоступность учителей</summary><p class="hint">Укажите время по звонкам соответствующей смены. Пересечения со второй сменой тоже учитываются.</p><form data-form="unavailable" class="planner-form">${select("unTeacher","Учитель",optionList(p.teachers))}${select("unDay","День",dayOptions)}${select("unShift","Смена",'<option>1</option><option>2</option>')}${select("unLesson","Урок",numberOptions)}<button class="btn">Добавить</button></form><ul class="planner-list">${p.teachers.flatMap((t,ti)=>t.unavailable.map((s,si)=>`<li><span>${esc(t.name)} · ${esc(s.day)} · смена ${s.shift} · урок ${s.lesson}</span><button type="button" class="planner-remove" data-un-teacher="${ti}" data-index="${si}" aria-label="Удалить">✕</button></li>`)).join("")||'<li class="muted">Ограничений нет</li>'}</ul></details>
    <details><summary>Ограничения кабинетов</summary><p class="hint">Выберите кабинет и смену. Нажмите на ячейку, чтобы запретить или снова разрешить занятия в это время; запреты повторяются каждую неделю. Учитываются пересечения времени двух смен. Ранее расставленные уроки не перемещаются — конфликты будут показаны при проверке.</p><div id="roomRulesUI"></div></details>
    <details><summary>3. Учебная нагрузка</summary><details class="load-import"><summary>Загрузить файл нагрузки</summary><p class="hint">CSV, XLS, XLSX, XLSM, ODS или Excel XML (до 10 МБ). Можно последовательно загружать разные предметы. Перед сохранением проверьте все неточные совпадения. Повторная загрузка обновит количество часов для того же класса, предмета и учителя.</p><form id="loadImportForm" class="planner-form"><label>Файл<input type="file" id="loadImportFile" accept=".csv,.xls,.xlsx,.xlsm,.xml,.ods" required></label><button class="btn">Проверить файл</button></form><div id="loadImportPreview"></div></details><p class="hint">Для всего класса оставьте группу пустой. Для параллельных занятий создайте нагрузку для каждой группы с разными названиями, учителями и кабинетами. Используйте одно название для одной и той же группы во всех предметах.</p><form data-form="loads" class="planner-form">${select("loadClass","Класс",optionList(p.classes))}<label>Группа<select id="loadGroup"><option value="">Весь класс</option></select></label>${select("loadSubject","Предмет",optionList(p.subjects))}${select("loadTeacher","Учитель",optionList(p.teachers))}<label>Кабинет нагрузки<select id="loadRoom"><option value="">Автоподбор</option>${optionList(p.rooms)}</select></label>${input("loadWeek","Уроков в неделю","1","number",'min="1" max="36" value="1"')}${input("loadDay","Не более в день","1","number",'min="1" max="12" value="1"')}<button class="btn">Добавить</button></form><ul class="planner-list">${p.loads.map((x,i)=>`<li class="planner-catalog-item"><div class="planner-item-line"><strong>${esc(x.class_name)} · ${esc(x.subject)} · ${esc(x.teacher)} · ${x.per_week} ч/нед</strong><button type="button" class="planner-remove" data-kind="loads" data-index="${i}" aria-label="Удалить нагрузку">✕</button></div><form class="planner-form" data-load-edit="${esc(x.id)}"><label>Группа<select name="group"><option value="">Весь класс</option>${p.groups.filter(g=>g.class_name===x.class_name).map(g=>`<option value="${esc(g.name)}"${g.name===x.group?' selected':''}>${esc(g.name)}</option>`).join("")}</select></label><label>Кабинет<select name="room"><option value="">Не указан</option>${p.rooms.map(r=>`<option value="${esc(r.name)}"${r.name===x.room?' selected':''}>${esc(r.name)}</option>`).join("")}</select></label><button class="btn secondary" type="submit">Сохранить</button></form></li>`).join("")||'<li class="muted">Пока нет записей</li>'}</ul></details>
    <details><summary>4. Расстановка уроков</summary><p class="hint">Добавьте уроки вручную или используйте автоподбор. Номер урока указывается внутри смены. Если в нагрузке закреплён кабинет, для урока необходимо выбрать тот же кабинет или оставить «Как в нагрузке».</p><form data-form="placements" class="planner-form">${select("placeLoad","Нагрузка",loadOptions)}${select("placeDay","День",dayOptions)}${select("placeLesson","Урок",numberOptions)}<label>Кабинет для урока<select id="placeRoom"><option value="">Как в нагрузке</option>${optionList(p.rooms)}</select></label><button class="btn">Поставить</button></form><ul class="planner-list planner-placements">${list("placements",x=>{const load=p.loads.find(l=>l.id===x.load_id);return `${esc(x.day)} · урок ${x.lesson} · ${esc(load?.class_name||"")}${load?.group?` · ${esc(load.group)}`:""} · ${esc(load?.subject||"")} · ${esc(load?.teacher||"")}`;})}</ul></details>
    <div class="planner-check"><b>Проверка перед публикацией</b>${plannerIssues.length?`<ul>${plannerIssues.map(x=>`<li>${esc(x)}</li>`).join("")}</ul>`:'<p class="tag-ok">Конфликтов и нераспределённой нагрузки нет.</p>'}</div>`;
  plannerRoot.querySelectorAll("details").forEach((d,i)=>{if(openDetails[i]!==undefined)d.open=openDetails[i];});
  if(!p.classes.some(c=>c.name===plannerMapClass))plannerMapClass=p.classes[0]?.name||"";
  $("plannerMapClass").value=plannerMapClass;
  $("plannerMapClass").onchange=()=>{plannerMapClass=$("plannerMapClass").value;plannerMapSelected=null;renderPlannerMap();};
  renderPlannerMap();
  renderRoomRules();
  function applyCatalogSearch(input){
    const kind=input.dataset.catalogSearch,query=input.value.trim().toLocaleLowerCase("ru-RU");
    plannerSearch[kind]=input.value;
    const list=plannerRoot.querySelector(`[data-catalog-list="${kind}"]`);
    if(list)list.querySelectorAll("[data-search-name]").forEach(row=>row.classList.toggle("hidden",!row.dataset.searchName.includes(query)));
  }
  plannerRoot.querySelectorAll("[data-catalog-search]").forEach(input=>{input.oninput=()=>applyCatalogSearch(input);applyCatalogSearch(input);});
  plannerRoot.querySelectorAll("form[data-form]").forEach(form=>form.onsubmit=plannerSubmit);
  plannerRoot.querySelectorAll("[data-edit-kind]").forEach(button=>button.onclick=()=>{
    const kind=button.dataset.editKind,index=Number(button.dataset.editIndex),form=$(`plannerEdit-${kind}-${index}`),input=$(`plannerEditInput-${kind}-${index}`);
    form.classList.remove("hidden");input.focus();input.select();
    form.querySelector("[data-edit-cancel]").onclick=()=>form.classList.add("hidden");
    form.onsubmit=async e=>{
      e.preventDefault();const newName=input.value.trim();if(!newName){input.reportValidity();return;}
      form.querySelectorAll("button").forEach(b=>b.disabled=true);
      try{const item=plannerProject[kind][index];const data=await api(kind==="groups"?"/api/admin/planner/rename-group":`/api/admin/planner/rename/${kind}`,{method:"POST",body:{revision:plannerProject.revision,old_name:item.name,new_name:newName,...(kind==="groups"?{class_name:item.class_name}:{})}});
        plannerProject=data.project;plannerIssues=data.issues;plannerRender();document.dispatchEvent(new Event("planner-catalog-changed"));}
      catch(error){form.querySelectorAll("button").forEach(b=>b.disabled=false);plannerError(error);}
    };
  });
  plannerRoot.querySelectorAll("[data-kind]").forEach(b=>b.onclick=()=>{
    const kind=b.dataset.kind,index=Number(b.dataset.index),item=plannerProject[kind][index];
    if(["classes","teachers","subjects","rooms","groups"].includes(kind)){
      if(kind==="rooms"&&(plannerProject.teachers.some(t=>t.preferred_room===item.name)||plannerProject.placements.some(p=>p.room===item.name))){plannerError(new Error("Кабинет используется в предпочтениях учителей или расставленных уроках. Сначала измените их."));return;}
      const field={classes:"class_name",teachers:"teacher",subjects:"subject",rooms:"room"}[kind];
      const used=plannerProject.loads.filter(load=>kind==="groups"?load.class_name===item.class_name&&load.group?.toLocaleLowerCase("ru-RU")===item.name.toLocaleLowerCase("ru-RU"):load[field]===item.name).length;
      if(kind==="classes"&&plannerProject.groups.some(group=>group.class_name===item.name)){plannerError(new Error(`Сначала удалите группы класса «${item.name}».`));return;}
      if(used){plannerError(new Error(`Нельзя удалить «${item.name}»: есть учебная нагрузка (${used}). Сначала удалите её и связанные уроки.`));return;}
      if(!confirm(`Удалить «${item.name}» из справочника конструктора? Опубликованное расписание и учётные записи не изменятся.`))return;
    }
    plannerChange(d=>d[kind].splice(index,1));
  });
  plannerRoot.querySelectorAll("[data-un-teacher]").forEach(b=>b.onclick=()=>plannerChange(d=>d.teachers[Number(b.dataset.unTeacher)].unavailable.splice(Number(b.dataset.index),1)));
  $("plannerRefresh").onclick=()=>plannerLoad();
  $("plannerImportClasses").onclick=async()=>{
    try{const data=await api("/api/admin/planner/import-classes",{method:"POST"});await plannerLoad();document.dispatchEvent(new Event("planner-catalog-changed"));toast(data.added.length?`Добавлено классов: ${data.added.length}`:"Все классы из расписания уже добавлены");}
    catch(error){plannerError(error);}
  };
  $("plannerImportTeachers").onclick=async()=>{
    try{const data=await api("/api/admin/planner/import-teachers",{method:"POST"});await plannerLoad();toast(data.added.length?`Добавлено учителей: ${data.added.length}`:"Все учителя из расписания уже добавлены");}
    catch(error){plannerError(error);}
  };
  for(const [id,kind,label] of [["plannerImportSubjects","subjects","предметов"],["plannerImportRooms","rooms","кабинетов"]]){
    $(id).onclick=async()=>{
      try{const data=await api(`/api/admin/planner/import-catalog/${kind}`,{method:"POST"});await plannerLoad();toast(data.added.length?`Добавлено ${label}: ${data.added.length}`:`Все данные уже добавлены`);}
      catch(error){plannerError(error);}
    };
  }
  $("plannerImportGroups").onclick=async()=>{
    try{const data=await api("/api/admin/planner/import-groups",{method:"POST"});await plannerLoad();toast(data.added.length?`Добавлено групп: ${data.added.length}`:"Новые группы не найдены");}catch(error){plannerError(error);}
  };
  plannerRoot.querySelectorAll("[data-teacher-room]").forEach(form=>form.onsubmit=e=>{
    e.preventDefault();const index=Number(form.dataset.teacherRoom),room=form.elements.room.value;
    plannerChange(p=>{p.teachers[index].preferred_room=room;});
  });
  $("loadImportForm").onsubmit=async e=>{
    e.preventDefault();const file=$("loadImportFile").files[0];if(!file)return;
    const form=new FormData();form.append("file",file);$("loadImportPreview").textContent="Читаем файл…";
    try{const data=await api("/api/admin/planner/load-import/preview",{method:"POST",form});renderLoadImportPreview(data);}
    catch(error){$("loadImportPreview").textContent=error.message;}
  };
  plannerRoot.querySelectorAll("[data-load-edit]").forEach(form=>form.onsubmit=async e=>{
    e.preventDefault();try{const data=await api("/api/admin/planner/load-change",{method:"POST",body:{revision:plannerProject.revision,load_id:form.dataset.loadEdit,group:form.elements.group.value,room:form.elements.room.value}});plannerProject=data.project;plannerIssues=data.issues;plannerRender();toast("Нагрузка сохранена");}catch(error){plannerError(error);}
  });
  function updateLoadGroups(){
    const cls=$("loadClass").value,select=$("loadGroup"),previous=select.value;
    select.innerHTML='<option value="">Весь класс</option>'+plannerProject.groups.filter(g=>g.class_name===cls).map(g=>`<option value="${esc(g.name)}">${esc(g.name)}${g.inferred?' · проверить':''}</option>`).join("");
    if(plannerProject.groups.some(g=>g.class_name===cls&&g.name===previous))select.value=previous;
  }
  $("loadClass").onchange=updateLoadGroups;updateLoadGroups();
  $("plannerGenerate").onclick=async()=>{if(!confirm("Автоматически расставить оставшиеся уроки? Уже расставленные уроки сохранятся."))return; await plannerAction("generate");};
  $("plannerPublish").onclick=async()=>{if(!confirm("Заменить опубликованное расписание этим черновиком?"))return; await plannerAction("publish");};
}
function renderRoomRules(){
  const root=$("roomRulesUI"),p=plannerProject;
  if(!p.rooms.length){root.innerHTML='<p class="muted">Сначала добавьте кабинеты в справочник.</p>';return;}
  if(!p.rooms.some(r=>r.name===roomRulesSelected))roomRulesSelected=p.rooms[0].name;
  const room=p.rooms.find(r=>r.name===roomRulesSelected),slots=room.unavailable||[];
  const contains=(day,lesson)=>slots.some(s=>s.day===day&&s.shift===roomRulesShift&&s.lesson===lesson);
  const numberOptions=Array.from({length:12},(_,i)=>i+1);
  let html=`<div class="room-rules-controls"><label>Кабинет <select id="roomRulesRoom">${p.rooms.map(r=>`<option value="${esc(r.name)}"${r.name===roomRulesSelected?' selected':''}>${esc(r.name)}${r.unavailable?.length?` · ${r.unavailable.length}`:''}</option>`).join('')}</select></label><label>Смена <select id="roomRulesShift"><option value="1"${roomRulesShift===1?' selected':''}>1</option><option value="2"${roomRulesShift===2?' selected':''}>2</option></select></label></div><p class="hint">Красная ячейка — кабинет недоступен. Всего ограничений для кабинета: ${slots.length}.</p><div class="room-rules-scroll"><div class="room-rules-grid"><span class="room-rules-header">Урок</span>${plannerDays.map(d=>`<span class="room-rules-header">${esc(d)}</span>`).join('')}`;
  for(const lesson of numberOptions){html+=`<span class="room-rules-number">${lesson}</span>`;for(const day of plannerDays){const blocked=contains(day,lesson);html+=`<button type="button" class="room-rule-cell${blocked?' blocked':''}" data-room-rule-day="${day}" data-room-rule-lesson="${lesson}" aria-pressed="${blocked}" aria-label="${esc(room.name)}, ${day}, смена ${roomRulesShift}, урок ${lesson}: ${blocked?'недоступен':'доступен'}">${blocked?'✕':'+'}</button>`;}}
  root.innerHTML=html+'</div></div>';
  $("roomRulesRoom").value=roomRulesSelected;$("roomRulesShift").value=String(roomRulesShift);
  $("roomRulesRoom").onchange=()=>{roomRulesSelected=$("roomRulesRoom").value;renderRoomRules();};
  $("roomRulesShift").onchange=()=>{roomRulesShift=Number($("roomRulesShift").value);renderRoomRules();};
  root.querySelectorAll('[data-room-rule-day]').forEach(button=>button.onclick=()=>{
    const day=button.dataset.roomRuleDay,lesson=Number(button.dataset.roomRuleLesson),shift=roomRulesShift,name=roomRulesSelected;
    plannerChange(next=>{const target=next.rooms.find(r=>r.name===name);target.unavailable=target.unavailable||[];const i=target.unavailable.findIndex(s=>s.day===day&&s.shift===shift&&s.lesson===lesson);if(i<0)target.unavailable.push({day,shift,lesson});else target.unavailable.splice(i,1);});
  });
}

function suggestImportGroups(rows,existing){
  // Повторяем порядок сохранения на сервере: сначала существующая нагрузка,
  // затем новые строки файла. Сопоставления, ещё не подтверждённые, не учитываются.
  const buckets=new Map(),result=rows.map(()=>"");
  const key=(cls,subject)=>JSON.stringify([cls,subject]);
  const add=(cls,subject,teacher,group,index)=>{
    const k=key(cls,subject);if(!buckets.has(k))buckets.set(k,[]);
    const bucket=buckets.get(k);let item=bucket.find(x=>x.teacher===teacher);
    if(!item){item={teacher,group:group||"",indices:[]};bucket.push(item);}
    if(index!==null)item.indices.push(index);
  };
  existing.forEach(x=>add(x.class_name,x.subject,x.teacher,x.group,null));
  rows.forEach((x,i)=>{if(x.class_name&&x.subject&&x.teacher)add(x.class_name,x.subject,x.teacher,"",i);});
  for(const bucket of buckets.values()){
    if(bucket.length<2)continue;
    const used=new Set(bucket.map(x=>x.group.toLocaleLowerCase("ru-RU")).filter(Boolean));
    for(const item of bucket){
      if(!item.group){let n=1;while(used.has(`${n} группа`))n++;item.group=`${n} группа`;used.add(item.group);}
      item.indices.forEach(i=>{result[i]=item.group;});
    }
  }
  return result;
}

function renderLoadImportPreview(data){
  const root=$("loadImportPreview"),labels={teacher:"Учитель",subject:"Предмет",class_name:"Класс"};
  const field=(row,index,key)=>{const match=row.matches[key];return `<label>${labels[key]}: ${esc(row[key])}<select required data-import-row="${index}" data-import-field="${key}" data-suggestion="${esc(match.suggestion)}"><option value="">${match.suggestion?'Предложение: '+esc(match.suggestion)+' — подтвердите':'Выберите из справочника'}</option>${data.choices[key].map(name=>`<option value="${esc(name)}"${match.value===name?' selected':''}>${esc(name)}</option>`).join('')}</select></label>`;};
  root.innerHTML=`<p>Найдено записей: ${data.rows.length}. Неточные и неоднозначные совпадения необходимо подтвердить или выбрать вручную. Для одного класса и предмета у разных учителей предлагаются группы по порядку; существующие назначения сохраняются. После импорта группы можно переставить. Кабинеты можно назначить после импорта или оставить для автоподбора. Текущий автоподбор ограничен 150 уроками в неделю.</p><button type="button" class="btn secondary" id="loadImportAcceptSuggestions">Принять все предложенные совпадения</button><form id="loadImportApply"><div class="load-import-rows">${data.rows.map((row,i)=>`<div class="load-import-row"><strong>Строка ${row.line} · ${row.per_week} ч/нед</strong>${field(row,i,'teacher')}${field(row,i,'class_name')}${field(row,i,'subject')}<span class="load-import-group" data-import-group="${i}" aria-live="polite"></span></div>`).join('')}</div><button class="btn" type="submit">Сохранить нагрузку в черновик</button></form>`;
  const selectedRows=()=>{const rows=data.rows.map(row=>({per_week:row.per_week}));root.querySelectorAll('[data-import-row]').forEach(el=>{rows[Number(el.dataset.importRow)][el.dataset.importField]=el.value;});return rows;};
  const updateGroups=()=>{const rows=selectedRows(),groups=suggestImportGroups(rows,plannerProject?.loads||[]);root.querySelectorAll('[data-import-group]').forEach(el=>{const i=Number(el.dataset.importGroup),row=rows[i];el.textContent=!row.teacher||!row.subject||!row.class_name?"Группа: подтвердите сопоставления":groups[i]?`Предлагается: ${groups[i]}`:"Весь класс (другой учитель не указан)";});};
  root.querySelectorAll('[data-import-row]').forEach(el=>{el.onchange=updateGroups;});
  $("loadImportAcceptSuggestions").onclick=()=>{if(!confirm("Вы проверили все предложенные совпадения? Они будут выбраны для сохранения."))return;root.querySelectorAll('[data-suggestion]').forEach(el=>{if(!el.value&&el.dataset.suggestion)el.value=el.dataset.suggestion;});updateGroups();};
  updateGroups();
  $("loadImportApply").onsubmit=async e=>{e.preventDefault();const rows=selectedRows();
    if(rows.some(row=>!row.teacher||!row.subject||!row.class_name)){toast("Выберите все совпадения");return;}
    if(!confirm(`Сохранить ${rows.length} записей нагрузки в черновик?`))return;
    try{const result=await api("/api/admin/planner/load-import/apply",{method:"POST",body:{revision:data.revision,rows}});plannerProject=result.project;plannerIssues=result.issues;plannerRender();toast(`Добавлено: ${result.added}, обновлено: ${result.updated}`);}catch(error){plannerError(error);}
  };
}

function renderPlannerMap(){
  const map=$("plannerMap"),status=$("plannerMapStatus"),project=plannerProject;
  if(!plannerMapClass){map.innerHTML='<p class="muted">Добавьте класс в справочник.</p>';status.textContent="";return;}
  const loads=new Map(project.loads.map(load=>[load.id,load]));
  const selected=plannerMapSelected===null?null:project.placements[plannerMapSelected];
  const selectedLoad=selected?loads.get(selected.load_id):null;
  status.textContent=selectedLoad?`Выбран урок: ${selectedLoad.subject}${selectedLoad.group?' · '+selectedLoad.group:''}. Нажмите ячейку для переноса.`:"Нажмите на урок или перетащите его в другую ячейку.";
  let html='<div class="planner-map-scroll"><div class="planner-map-grid"><div class="planner-map-head">Урок</div>'+plannerDays.map(day=>`<div class="planner-map-head">${esc(day)}</div>`).join("");
  for(let lesson=1;lesson<=12;lesson++){
    html+=`<div class="planner-map-number">${lesson}</div>`;
    for(const day of plannerDays){
      const items=project.placements.map((placement,index)=>({placement,index,load:loads.get(placement.load_id)})).filter(x=>x.load?.class_name===plannerMapClass&&x.placement.day===day&&x.placement.lesson===lesson);
      html+=`<div class="planner-map-cell" data-map-day="${day}" data-map-lesson="${lesson}"><button type="button" class="planner-map-drop" data-map-target aria-label="Перенести в ${esc(day)}, урок ${lesson}">+</button>${items.map(({index,load,placement})=>`<button type="button" class="planner-map-lesson ${plannerMapSelected===index?'selected':''}" data-map-index="${index}" aria-pressed="${plannerMapSelected===index?'true':'false'}"><strong>${esc(load.subject)}</strong><span>${esc(load.group||"Весь класс")}</span><span>${esc(load.teacher)} · ${esc(load.room||placement.room||"кабинет не указан")}</span></button>`).join("")}</div>`;
    }
  }
  map.innerHTML=html+'</div></div>';
  if(!project.placements.some(p=>loads.get(p.load_id)?.class_name===plannerMapClass))status.textContent="В черновике этого класса пока нет расставленных уроков. Добавьте нагрузку и расставьте уроки или используйте автоподбор.";
  map.querySelectorAll("[data-map-target]").forEach(target=>target.onclick=()=>{
    const cell=target.closest("[data-map-day]");if(plannerMapSelected!==null&&cell)movePlannerLesson(plannerMapSelected,cell.dataset.mapDay,Number(cell.dataset.mapLesson));
  });
  map.querySelectorAll("[data-map-index]").forEach(chip=>{
    let pointer=null,suppressClick=false;
    chip.onclick=()=>{if(suppressClick){suppressClick=false;return;}if(plannerMapBusy)return;const index=Number(chip.dataset.mapIndex);plannerMapSelected=plannerMapSelected===index?null:index;renderPlannerMap();};
    chip.onpointerdown=e=>{if(plannerMapBusy||e.button!==0)return;pointer={id:e.pointerId,x:e.clientX,y:e.clientY,drag:false};chip.setPointerCapture(e.pointerId);};
    chip.onpointermove=e=>{if(!pointer||e.pointerId!==pointer.id)return;if(Math.hypot(e.clientX-pointer.x,e.clientY-pointer.y)>8){pointer.drag=true;chip.classList.add("dragging");}};
    chip.onpointercancel=()=>{pointer=null;chip.classList.remove("dragging");};
    chip.onpointerup=e=>{if(!pointer||e.pointerId!==pointer.id)return;const wasDrag=pointer.drag;pointer=null;chip.classList.remove("dragging");if(!wasDrag)return;
      suppressClick=true;const target=document.elementFromPoint(e.clientX,e.clientY)?.closest("[data-map-day]");
      if(target&&map.contains(target))movePlannerLesson(Number(chip.dataset.mapIndex),target.dataset.mapDay,Number(target.dataset.mapLesson));
      else {status.textContent="Перенос отменён: выберите ячейку на карте.";setTimeout(()=>{suppressClick=false;},0);}
    };
  });
}
async function movePlannerLesson(index,day,lesson){
  if(plannerMapBusy)return;plannerMapBusy=true;$("plannerMapStatus").textContent="Сохраняем перенос…";
  try{const data=await api("/api/admin/planner/move",{method:"POST",body:{revision:plannerProject.revision,index,day,lesson}});
    plannerProject=data.project;plannerIssues=data.issues;plannerMapSelected=null;plannerRender();$("plannerMapStatus").textContent="Урок перенесён в черновике.";
  }catch(error){$("plannerMapStatus").textContent=error.message;}finally{plannerMapBusy=false;}
}

function plannerError(e){const box=$("plannerMessage"); if(box) box.innerHTML=`<div class="alert err">${esc(e.message)}</div>`;}
async function plannerLoad(){try{const data=await api("/api/admin/planner");plannerProject=data.project;plannerIssues=data.issues;plannerRender();}catch(e){plannerRoot.classList.remove("hidden");plannerRoot.innerHTML=`<div class="alert err">${esc(e.message)}</div>`;}}
async function plannerChange(update){
  const next=JSON.parse(JSON.stringify(plannerProject)); update(next);
  plannerRoot.querySelectorAll("button").forEach(b=>b.disabled=true);
  try{const data=await api("/api/admin/planner",{method:"PUT",body:next});plannerProject=data.project;plannerIssues=data.issues;plannerRender();document.dispatchEvent(new Event("planner-catalog-changed"));}
  catch(e){plannerRoot.querySelectorAll("button").forEach(b=>b.disabled=false);plannerError(e);}
}
async function plannerAction(action){
  plannerRoot.querySelectorAll("button").forEach(b=>b.disabled=true);
  try{const data=await api(`/api/admin/planner/${action}`,{method:"POST",body:{revision:plannerProject.revision}});
    if(action==="generate"){plannerProject=data.project;plannerIssues=data.issues;plannerRender();toast("Уроки расставлены в черновике");}
    else{plannerRoot.querySelectorAll("button").forEach(b=>b.disabled=false);toast("Расписание опубликовано");await loadStatus();}
  }catch(e){plannerRoot.querySelectorAll("button").forEach(b=>b.disabled=false);plannerError(e);}
}
function plannerSubmit(event){
  event.preventDefault(); const kind=event.currentTarget.dataset.form;
  const val=id=>$(id).value.trim();
  plannerChange(p=>{
    if(kind==="groups")p.groups.push({class_name:val("groupClass"),name:val("groupName"),inferred:false});
    else if(kind==="classes")p.classes.push({name:val("className"),shift:Number(val("classShift")),max_daily:Number(val("classMax"))});
    else if(["teachers","subjects","rooms"].includes(kind))p[kind].push(kind==="teachers"?{name:val(`${kind}Name`),unavailable:[]}:{name:val(`${kind}Name`)});
    else if(kind==="unavailable")p.teachers.find(t=>t.name===val("unTeacher")).unavailable.push({day:val("unDay"),shift:Number(val("unShift")),lesson:Number(val("unLesson"))});
    else if(kind==="loads")p.loads.push({id:crypto.randomUUID(),class_name:val("loadClass"),group:val("loadGroup"),subject:val("loadSubject"),teacher:val("loadTeacher"),room:val("loadRoom"),per_week:Number(val("loadWeek")),max_per_day:Number(val("loadDay"))});
    else if(kind==="placements")p.placements.push({load_id:val("placeLoad"),day:val("placeDay"),lesson:Number(val("placeLesson")),room:val("placeRoom")});
  });
}
$("plannerOpen").onclick=()=>{if(!plannerRoot.classList.contains("hidden")){plannerRoot.classList.add("hidden");$("plannerOpen").textContent="Открыть конструктор";}else{plannerRoot.classList.remove("hidden");$("plannerOpen").textContent="Скрыть конструктор";plannerLoad();}};
