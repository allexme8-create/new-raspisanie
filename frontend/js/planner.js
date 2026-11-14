"use strict";
/* Конструктор работает с отдельным черновиком, публикация — только явным действием. */
const plannerDays=["Пн","Вт","Ср","Чт","Пт","Сб"];
let plannerProject=null, plannerIssues=[];
const plannerSearch={classes:"",teachers:"",subjects:"",rooms:""};
const plannerRoot=$("plannerRoot");
const optionList=(items,value="name")=>items.map(x=>`<option value="${esc(x[value])}">${esc(x[value])}</option>`).join("");
const dayOptions=plannerDays.map(d=>`<option>${d}</option>`).join("");
const numberOptions=Array.from({length:12},(_,i)=>`<option>${i+1}</option>`).join("");
const field=(id,label,content)=>`<label>${label}${content.replace("<select",`<select id="${id}"`).replace("<input",`<input id="${id}"`)}</label>`;
const select=(id,label,opts)=>field(id,label,`<select required>${opts}</select>`);
const input=(id,label,placeholder,type="text",extra="")=>field(id,label,`<input type="${type}" placeholder="${placeholder}" required ${extra}>`);
function plannerRender(){
  const p=plannerProject;
  const openDetails=[...plannerRoot.querySelectorAll("details")].map(d=>d.open);
  const list=(key,format)=>p[key].length?p[key].map((x,i)=>{
    const editable=["classes","teachers","subjects","rooms"].includes(key);
    const title=editable?`<button type="button" class="planner-name-edit" data-edit-kind="${key}" data-edit-index="${i}" title="Изменить">${format(x)} ✎</button>`:`<span>${format(x)}</span>`;
    const form=editable?`<form class="planner-inline-edit hidden" id="plannerEdit-${key}-${i}"><label class="sr-only" for="plannerEditInput-${key}-${i}">Новое название</label><input id="plannerEditInput-${key}-${i}" maxlength="80" required value="${esc(x.name)}"><button class="btn" type="submit">Сохранить</button><button class="btn secondary" type="button" data-edit-cancel>Отмена</button></form>`:"";
    return `<li class="planner-catalog-item" data-search-name="${esc((x.name||"").toLocaleLowerCase("ru-RU"))}"><div class="planner-item-line">${title}<button type="button" class="planner-remove" data-kind="${key}" data-index="${i}" aria-label="Удалить ${esc(x.name||"запись")}">✕</button></div>${form}</li>`;
  }).join(""):'<li class="muted">Пока нет записей</li>';
  const loadOptions=p.loads.map(x=>`<option value="${esc(x.id)}">${esc(`${x.class_name} · ${x.subject} · ${x.teacher} · ${x.room}`)}</option>`).join("");
  const nameForm=(type,label)=>`<form data-form="${type}" class="planner-form">${input(`${type}Name`,label,label)}<button class="btn" type="submit">Добавить</button></form>`;
  plannerRoot.innerHTML=`
    <div class="planner-actions planner-main-actions"><button type="button" id="plannerGenerate" class="btn">Автоподбор</button><button type="button" id="plannerPublish" class="btn">Опубликовать</button></div>
    <details class="planner-tools"><summary>Импорт и обновление</summary><div class="planner-actions"><button type="button" id="plannerRefresh" class="btn secondary">Обновить черновик</button><button type="button" id="plannerImportClasses" class="btn secondary">Импорт классов</button><button type="button" id="plannerImportTeachers" class="btn secondary">Импорт учителей</button><button type="button" id="plannerImportSubjects" class="btn secondary">Импорт предметов</button><button type="button" id="plannerImportRooms" class="btn secondary">Импорт кабинетов</button></div></details>
    <div id="plannerMessage" aria-live="polite"></div>
    <p class="hint">Изменения сохраняются в черновике. Автоподбор сохраняет уже расставленные уроки; публикация заменяет текущее расписание на сайте только после проверки.</p>
    <details open><summary>1. Справочники</summary><div class="planner-grid">
      <details class="planner-category"><summary>Классы · ${p.classes.length}</summary><form data-form="classes" class="planner-form">${input("className","Класс","Например, 5а")}${select("classShift","Смена",'<option value="1">1</option><option value="2">2</option>')}${input("classMax","Максимум уроков в день","7","number",'min="1" max="12" value="7"')}<button class="btn">Добавить</button></form><details class="planner-catalog-list"><summary>Список классов (${p.classes.length})</summary><input class="planner-search" type="search" data-catalog-search="classes" value="${esc(plannerSearch.classes)}" placeholder="Поиск класса" aria-label="Поиск класса"><ul class="planner-list" data-catalog-list="classes">${list("classes",x=>`${esc(x.name)} · ${x.shift}-я смена`)}</ul></details></details>
      <details class="planner-category"><summary>Учителя · ${p.teachers.length}</summary>${nameForm("teachers","ФИО учителя")}<details class="planner-catalog-list"><summary>Список учителей (${p.teachers.length})</summary><input class="planner-search" type="search" data-catalog-search="teachers" value="${esc(plannerSearch.teachers)}" placeholder="Поиск учителя" aria-label="Поиск учителя"><ul class="planner-list" data-catalog-list="teachers">${list("teachers",x=>esc(x.name))}</ul></details><p class="hint">Это справочник расписания, а не учётные записи сотрудников.</p></details>
      <details class="planner-category"><summary>Предметы · ${p.subjects.length}</summary>${nameForm("subjects","Предмет")}<details class="planner-catalog-list"><summary>Список предметов (${p.subjects.length})</summary><input class="planner-search" type="search" data-catalog-search="subjects" value="${esc(plannerSearch.subjects)}" placeholder="Поиск предмета" aria-label="Поиск предмета"><ul class="planner-list" data-catalog-list="subjects">${list("subjects",x=>esc(x.name))}</ul></details></details>
      <details class="planner-category"><summary>Кабинеты · ${p.rooms.length}</summary>${nameForm("rooms","Кабинет")}<details class="planner-catalog-list"><summary>Список кабинетов (${p.rooms.length})</summary><input class="planner-search" type="search" data-catalog-search="rooms" value="${esc(plannerSearch.rooms)}" placeholder="Поиск кабинета" aria-label="Поиск кабинета"><ul class="planner-list" data-catalog-list="rooms">${list("rooms",x=>esc(x.name))}</ul></details></details>
    </div></details>
    <details><summary>2. Недоступность учителей</summary><p class="hint">Укажите время по звонкам соответствующей смены. Пересечения со второй сменой тоже учитываются.</p><form data-form="unavailable" class="planner-form">${select("unTeacher","Учитель",optionList(p.teachers))}${select("unDay","День",dayOptions)}${select("unShift","Смена",'<option>1</option><option>2</option>')}${select("unLesson","Урок",numberOptions)}<button class="btn">Добавить</button></form><ul class="planner-list">${p.teachers.flatMap((t,ti)=>t.unavailable.map((s,si)=>`<li><span>${esc(t.name)} · ${esc(s.day)} · смена ${s.shift} · урок ${s.lesson}</span><button type="button" class="planner-remove" data-un-teacher="${ti}" data-index="${si}" aria-label="Удалить">✕</button></li>`)).join("")||'<li class="muted">Ограничений нет</li>'}</ul></details>
    <details><summary>3. Учебная нагрузка</summary><p class="hint">Одна запись — один предмет, учитель и кабинет для целого класса. Параллельные группы пока не поддерживаются.</p><form data-form="loads" class="planner-form">${select("loadClass","Класс",optionList(p.classes))}${select("loadSubject","Предмет",optionList(p.subjects))}${select("loadTeacher","Учитель",optionList(p.teachers))}${select("loadRoom","Кабинет",optionList(p.rooms))}${input("loadWeek","Уроков в неделю","1","number",'min="1" max="36" value="1"')}${input("loadDay","Не более в день","1","number",'min="1" max="12" value="1"')}<button class="btn">Добавить</button></form><ul class="planner-list">${list("loads",x=>`${esc(x.class_name)} · ${esc(x.subject)} · ${esc(x.teacher)} · каб. ${esc(x.room)} · ${x.per_week} в неделю (до ${x.max_per_day} в день)`)}</ul></details>
    <details><summary>4. Расстановка уроков</summary><p class="hint">Добавьте уроки вручную или используйте автоподбор. Номер урока указывается внутри смены.</p><form data-form="placements" class="planner-form">${select("placeLoad","Нагрузка",loadOptions)}${select("placeDay","День",dayOptions)}${select("placeLesson","Урок",numberOptions)}<button class="btn">Поставить</button></form><ul class="planner-list planner-placements">${list("placements",x=>{const load=p.loads.find(l=>l.id===x.load_id);return `${esc(x.day)} · урок ${x.lesson} · ${esc(load?.class_name||"")} · ${esc(load?.subject||"")} · ${esc(load?.teacher||"")}`;})}</ul></details>
    <div class="planner-check"><b>Проверка перед публикацией</b>${plannerIssues.length?`<ul>${plannerIssues.map(x=>`<li>${esc(x)}</li>`).join("")}</ul>`:'<p class="tag-ok">Конфликтов и нераспределённой нагрузки нет.</p>'}</div>`;
  plannerRoot.querySelectorAll("details").forEach((d,i)=>{if(openDetails[i]!==undefined)d.open=openDetails[i];});
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
      try{const data=await api(`/api/admin/planner/rename/${kind}`,{method:"POST",body:{revision:plannerProject.revision,old_name:plannerProject[kind][index].name,new_name:newName}});
        plannerProject=data.project;plannerIssues=data.issues;plannerRender();document.dispatchEvent(new Event("planner-catalog-changed"));}
      catch(error){form.querySelectorAll("button").forEach(b=>b.disabled=false);plannerError(error);}
    };
  });
  plannerRoot.querySelectorAll("[data-kind]").forEach(b=>b.onclick=()=>{
    const kind=b.dataset.kind,index=Number(b.dataset.index),item=plannerProject[kind][index];
    if(["classes","teachers","subjects","rooms"].includes(kind)){
      const field={classes:"class_name",teachers:"teacher",subjects:"subject",rooms:"room"}[kind];
      const used=plannerProject.loads.filter(load=>load[field]===item.name).length;
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
  $("plannerGenerate").onclick=async()=>{if(!confirm("Автоматически расставить оставшиеся уроки? Уже расставленные уроки сохранятся."))return; await plannerAction("generate");};
  $("plannerPublish").onclick=async()=>{if(!confirm("Заменить опубликованное расписание этим черновиком?"))return; await plannerAction("publish");};
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
    if(kind==="classes")p.classes.push({name:val("className"),shift:Number(val("classShift")),max_daily:Number(val("classMax"))});
    else if(["teachers","subjects","rooms"].includes(kind))p[kind].push(kind==="teachers"?{name:val(`${kind}Name`),unavailable:[]}:{name:val(`${kind}Name`)});
    else if(kind==="unavailable")p.teachers.find(t=>t.name===val("unTeacher")).unavailable.push({day:val("unDay"),shift:Number(val("unShift")),lesson:Number(val("unLesson"))});
    else if(kind==="loads")p.loads.push({id:crypto.randomUUID(),class_name:val("loadClass"),subject:val("loadSubject"),teacher:val("loadTeacher"),room:val("loadRoom"),per_week:Number(val("loadWeek")),max_per_day:Number(val("loadDay"))});
    else if(kind==="placements")p.placements.push({load_id:val("placeLoad"),day:val("placeDay"),lesson:Number(val("placeLesson"))});
  });
}
$("plannerOpen").onclick=()=>{if(!plannerRoot.classList.contains("hidden")){plannerRoot.classList.add("hidden");$("plannerOpen").textContent="Открыть конструктор";}else{plannerRoot.classList.remove("hidden");$("plannerOpen").textContent="Скрыть конструктор";plannerLoad();}};
