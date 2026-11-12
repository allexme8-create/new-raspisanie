"use strict";
/* Конструктор работает с отдельным черновиком, публикация — только явным действием. */
const plannerDays=["Пн","Вт","Ср","Чт","Пт","Сб"];
let plannerProject=null, plannerIssues=[];
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
  const list=(key,format)=>p[key].length?p[key].map((x,i)=>`<li><span>${format(x)}</span><button type="button" class="planner-remove" data-kind="${key}" data-index="${i}" aria-label="Удалить">✕</button></li>`).join(""):'<li class="muted">Пока нет записей</li>';
  const loadOptions=p.loads.map(x=>`<option value="${esc(x.id)}">${esc(`${x.class_name} · ${x.subject} · ${x.teacher} · ${x.room}`)}</option>`).join("");
  const nameForm=(type,label)=>`<form data-form="${type}" class="planner-form">${input(`${type}Name`,label,label)}<button class="btn" type="submit">Добавить</button></form>`;
  plannerRoot.innerHTML=`
    <div class="planner-actions"><button type="button" id="plannerRefresh" class="btn secondary">Обновить черновик</button><button type="button" id="plannerGenerate" class="btn">Автоподбор</button><button type="button" id="plannerPublish" class="btn">Опубликовать</button></div>
    <div id="plannerMessage" aria-live="polite"></div>
    <p class="hint">Изменения сохраняются в черновике. Автоподбор сохраняет уже расставленные уроки; публикация заменяет текущее расписание на сайте только после проверки.</p>
    <details open><summary>1. Справочники</summary><div class="planner-grid">
      <section><h3>Классы</h3><form data-form="classes" class="planner-form">${input("className","Класс","Например, 5а")}${select("classShift","Смена",'<option value="1">1</option><option value="2">2</option>')}${input("classMax","Максимум уроков в день","7","number",'min="1" max="12" value="7"')}<button class="btn">Добавить</button></form><ul class="planner-list">${list("classes",x=>`${esc(x.name)} · ${x.shift}-я смена · не более ${x.max_daily} в день`)}</ul></section>
      <section><h3>Учителя</h3>${nameForm("teachers","ФИО учителя")}<ul class="planner-list">${list("teachers",x=>esc(x.name))}</ul></section>
      <section><h3>Предметы</h3>${nameForm("subjects","Предмет")}<ul class="planner-list">${list("subjects",x=>esc(x.name))}</ul></section>
      <section><h3>Кабинеты</h3>${nameForm("rooms","Кабинет")}<ul class="planner-list">${list("rooms",x=>esc(x.name))}</ul></section>
    </div></details>
    <details><summary>2. Недоступность учителей</summary><p class="hint">Укажите время по звонкам соответствующей смены. Пересечения со второй сменой тоже учитываются.</p><form data-form="unavailable" class="planner-form">${select("unTeacher","Учитель",optionList(p.teachers))}${select("unDay","День",dayOptions)}${select("unShift","Смена",'<option>1</option><option>2</option>')}${select("unLesson","Урок",numberOptions)}<button class="btn">Добавить</button></form><ul class="planner-list">${p.teachers.flatMap((t,ti)=>t.unavailable.map((s,si)=>`<li><span>${esc(t.name)} · ${esc(s.day)} · смена ${s.shift} · урок ${s.lesson}</span><button type="button" class="planner-remove" data-un-teacher="${ti}" data-index="${si}" aria-label="Удалить">✕</button></li>`)).join("")||'<li class="muted">Ограничений нет</li>'}</ul></details>
    <details open><summary>3. Учебная нагрузка</summary><p class="hint">Одна запись — один предмет, учитель и кабинет для целого класса. Параллельные группы пока не поддерживаются.</p><form data-form="loads" class="planner-form">${select("loadClass","Класс",optionList(p.classes))}${select("loadSubject","Предмет",optionList(p.subjects))}${select("loadTeacher","Учитель",optionList(p.teachers))}${select("loadRoom","Кабинет",optionList(p.rooms))}${input("loadWeek","Уроков в неделю","1","number",'min="1" max="36" value="1"')}${input("loadDay","Не более в день","1","number",'min="1" max="12" value="1"')}<button class="btn">Добавить</button></form><ul class="planner-list">${list("loads",x=>`${esc(x.class_name)} · ${esc(x.subject)} · ${esc(x.teacher)} · каб. ${esc(x.room)} · ${x.per_week} в неделю (до ${x.max_per_day} в день)`)}</ul></details>
    <details open><summary>4. Расстановка уроков</summary><p class="hint">Добавьте уроки вручную или используйте автоподбор. Номер урока указывается внутри смены.</p><form data-form="placements" class="planner-form">${select("placeLoad","Нагрузка",loadOptions)}${select("placeDay","День",dayOptions)}${select("placeLesson","Урок",numberOptions)}<button class="btn">Поставить</button></form><ul class="planner-list planner-placements">${list("placements",x=>{const load=p.loads.find(l=>l.id===x.load_id);return `${esc(x.day)} · урок ${x.lesson} · ${esc(load?.class_name||"")} · ${esc(load?.subject||"")} · ${esc(load?.teacher||"")}`;})}</ul></details>
    <div class="planner-check"><b>Проверка перед публикацией</b>${plannerIssues.length?`<ul>${plannerIssues.map(x=>`<li>${esc(x)}</li>`).join("")}</ul>`:'<p class="tag-ok">Конфликтов и нераспределённой нагрузки нет.</p>'}</div>`;
  plannerRoot.querySelectorAll("details").forEach((d,i)=>{if(openDetails[i]!==undefined)d.open=openDetails[i];});
  plannerRoot.querySelectorAll("form").forEach(form=>form.onsubmit=plannerSubmit);
  plannerRoot.querySelectorAll("[data-kind]").forEach(b=>b.onclick=()=>plannerChange(d=>d[b.dataset.kind].splice(Number(b.dataset.index),1)));
  plannerRoot.querySelectorAll("[data-un-teacher]").forEach(b=>b.onclick=()=>plannerChange(d=>d.teachers[Number(b.dataset.unTeacher)].unavailable.splice(Number(b.dataset.index),1)));
  $("plannerRefresh").onclick=()=>plannerLoad();
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
