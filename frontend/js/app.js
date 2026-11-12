"use strict";
/* Клиент просмотра расписания: получает готовые данные с backend'а (/api/schedule). */
const DAYS=["Пн","Вт","Ср","Чт","Пт","Сб"];
const DAY_FULL={Пн:"Понедельник",Вт:"Вторник",Ср:"Среда",Чт:"Четверг",Пт:"Пятница",Сб:"Суббота"};
const SERVICE=new Set(["Классный час","СФУ","Экскурсия"]);

const jsDay=new Date().getDay();
const TODAY=jsDay===0?-1:jsDay-1;
const DEF_DAY=TODAY>=0?TODAY:0;

const state={
  teachers:null, subjects:null,
  classes:[], teacherNames:[], rooms:[],
  curClass:null, curTeacher:null, teacherQuery:"",
  classSel:DEF_DAY, teacherSel:DEF_DAY, favDay:DEF_DAY,
  roomOnlyFree:false,
  bellSchedule:null, secondShiftClasses:[],
  updatedAt:null
};

const FAV_KEY="schedule_favorites_v1";
let favs=(()=>{ try{ const f=JSON.parse(localStorage.getItem(FAV_KEY)); return f&&Array.isArray(f.classes)&&Array.isArray(f.teachers)?f:{classes:[],teachers:[]}; }catch(e){ return {classes:[],teachers:[]}; } })();
function saveFavs(){ try{ localStorage.setItem(FAV_KEY,JSON.stringify(favs)); }catch(e){} }
function toggleFav(kind,name){
  const arr=favs[kind], i=arr.indexOf(name);
  if(i>=0) arr.splice(i,1); else arr.push(name);
  saveFavs();
  toast(i>=0?`Убрано из избранного: ${name}`:`⭐ В избранном: ${name}`);
  renderClassArea(); renderTeacherArea(); renderFavArea();
}

const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function toast(msg){ const t=$("toast"); t.textContent=msg; t.classList.add("show"); clearTimeout(t._h); t._h=setTimeout(()=>t.classList.remove("show"),2600); }

/* ═══ Загрузка готового расписания с сервера ═══ */
function showLoading(){
  $("loadStatus").innerHTML=`<div class="spinner"></div><span class="msg">Загрузка расписания с сервера…</span>`;
  $("reloadBtn").classList.add("hidden");
}
function showError(msg){
  $("loadStatus").innerHTML=`<span style="font-size:20px">⚠️</span><span class="msg" style="color:var(--busy)">${esc(msg)}</span>`;
  $("reloadBtn").classList.remove("hidden");
  if(!hasData())for(const id of ["classArea","teacherArea","roomsArea","favArea"]){
    const box=$(id);
    box.innerHTML=`<div class="nodata">${esc(msg)}<br><button class="change-selection" type="button" data-retry>Попробовать снова</button></div>`;
    box.querySelectorAll("[data-retry]").forEach(button=>button.onclick=()=>loadSchedule());
  }
}
function showSuccess(){
  const label=state.updatedAt?`Последнее обновление: ${state.updatedAt}`:"Расписание загружено";
  $("loadStatus").innerHTML=`<span style="font-size:20px">✔</span><span class="msg" style="color:var(--ok)">${esc(label)}</span>`;
  $("reloadBtn").classList.remove("hidden");
}
function formatDate(iso){
  try{ return new Date(iso).toLocaleString("ru-RU",{day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit"}); }
  catch(e){ return ""; }
}
function roomKey(value){
  return String(value??"").replace(/\s+/g," ").trim().toLocaleLowerCase("ru-RU");
}
function uniqueRooms(...lists){
  const result=[],seen=new Set();
  for(const item of lists.flat()){
    const room=String(item??"").replace(/\s+/g," ").trim();
    const key=roomKey(room);
    if(room&&!seen.has(key)){seen.add(key);result.push(room);}
  }
  return result;
}
function bellPeriod(shift,day,lesson){
  return state.bellSchedule?.shifts?.[String(shift)]?.[day]?.[String(lesson)]||null;
}
function lessonTime(cls,day,lesson){
  const shift=state.secondShiftClasses.includes(cls)?"2":"1";
  const period=bellPeriod(shift,day,lesson);
  return period?`${period.start}–${period.end}`:"";
}
function shiftHasClasses(shift){
  if(!state.classes.length)return shift==="1";
  return shift==="2"
    ?state.secondShiftClasses.length>0
    :state.classes.some(cls=>!state.secondShiftClasses.includes(cls));
}
function lessonMarker(lesson,time=""){
  return `<div class="lesson-marker"><span class="lnum">${esc(lesson)}</span>${time?`<span class="lesson-time">${esc(time)}</span>`:""}</div>`;
}
function clockMinutes(value){
  const match=/^(\d{1,2}):(\d{2})$/.exec(String(value||""));
  return match?Number(match[1])*60+Number(match[2]):null;
}
function renderCurrentLesson(){
  const box=$("currentLesson"),shifts=state.bellSchedule?.shifts;
  if(!box)return;
  if(!shifts){box.classList.add("hidden");return;}
  const now=new Date(),day=DAYS[now.getDay()-1];
  const nowMinutes=now.getHours()*60+now.getMinutes()+now.getSeconds()/60;
  const active=[],upcoming=[];
  if(day){
    for(const shift of ["1","2"]){
      if(!shiftHasClasses(shift))continue;
      const lessons=shifts[shift]?.[day]||{};
      for(const [number,period] of Object.entries(lessons)){
        const start=clockMinutes(period.start),end=clockMinutes(period.end);
        if(start===null||end===null)continue;
        const item={number:Number(number),shift,start,end,period};
        if(nowMinutes>=start&&nowMinutes<end){
          item.remaining=Math.ceil(end-nowMinutes);
          active.push(item);
        }else if(start>nowMinutes){upcoming.push(item);}
      }
    }
  }
  active.sort((a,b)=>a.shift.localeCompare(b.shift));
  upcoming.sort((a,b)=>a.start-b.start||a.shift.localeCompare(b.shift));
  box.classList.remove("hidden","idle");
  if(active.length===1){
    const lesson=active[0];
    box.innerHTML=`Сейчас идёт урок № ${lesson.number} (${lesson.shift}-я смена), до конца урока осталось ${lesson.remaining} мин.`;
  }else if(active.length>1){
    box.innerHTML=`Сейчас идут уроки: ${active.map(x=>`№ ${x.number} (${x.shift}-я смена) — до конца ${x.remaining} мин.`).join("; ")}`;
  }else if(upcoming.length){
    const next=upcoming[0];
    box.classList.add("idle");
    box.innerHTML=`Сейчас перемена. Ближайший урок № ${next.number} (${next.shift}-я смена) начнётся в ${esc(next.period.start)}.`;
  }else{
    box.classList.add("idle");
    box.textContent="Сейчас уроки не идут.";
  }
}

let publicDuty=null, publicDutyError=false;
function activeDutyShifts(timezone){
  if(!state.bellSchedule?.shifts)return [];
  try{
    const parts=new Intl.DateTimeFormat("en-US",{timeZone:timezone,weekday:"short",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).formatToParts(new Date());
    const values=Object.fromEntries(parts.map(p=>[p.type,p.value])),day=({Mon:"Пн",Tue:"Вт",Wed:"Ср",Thu:"Чт",Fri:"Пт",Sat:"Сб"})[values.weekday];
    if(!day)return [];
    const minute=Number(values.hour)*60+Number(values.minute);
    return [1,2].filter(shift=>{
      const periods=Object.values(state.bellSchedule.shifts[String(shift)]?.[day]||{}).map(p=>({start:clockMinutes(p.start),end:clockMinutes(p.end)})).filter(p=>p.start!==null&&p.end!==null&&p.start<p.end);
      return periods.length&&minute>=Math.min(...periods.map(p=>p.start))&&minute<Math.max(...periods.map(p=>p.end));
    });
  }catch(e){return [];}
}
function renderDutyBanner(){
  const boxes=["classDuty","teacherDuty"].map(id=>$(id)).filter(Boolean);
  if(!boxes.length)return;
  if(!publicDuty){for(const box of boxes)box.textContent=publicDutyError?"Не удалось загрузить данные о дежурстве.":"Загрузка дежурства…";return;}
  const active=activeDutyShifts(publicDuty.timezone),entries=publicDuty.entries||[];
  const describe=entry=>{
    if(!entry)return "Не назначен";
    const name=esc(entry.full_name||"ФИО не указано"),role=["teacher","associate","director"].includes(entry.role)?entry.role:"";
    return `${entry.full_name&&role?`<span class="person-${role}">${name}</span>`:name}${entry.position?` · ${esc(entry.position)}`:""}${entry.class_name?` · ${esc(entry.class_name)}`:""}`;
  };
  const formatDay=value=>{
    const day=new Date(value+"T00:00:00Z");
    return `${day.toLocaleDateString("ru-RU",{timeZone:"UTC",day:"numeric",month:"long"})} ${day.getUTCFullYear()} года`;
  };
  const line=(label,entry,isActive)=>`<p class="${isActive?'duty-active':''}">${esc(label)}: ${entry?`<strong>${describe(entry)}</strong>`:describe(entry)}</p>`;
  const html=`<p class="muted">${esc(formatDay(publicDuty.today))}${!active.length?' · текущая смена не определяется':''}</p>`+
    line("Дежурный администратор",entries.find(e=>e.slot===0),active.length>0)+[1,2].map(shift=>line(`${shift}-я смена · дежурный учитель`,entries.find(e=>e.slot===shift),active.includes(shift))).join("");
  for(const box of boxes)box.innerHTML=html;
}
async function loadPublicDuty(){
  try{const response=await fetch("/api/duties/today",{cache:"no-store"});if(!response.ok)throw new Error("ошибка сервера");
    const data=await response.json();if(!data.today||!data.timezone||!Array.isArray(data.entries))throw new Error("нет данных");publicDuty=data;publicDutyError=false;renderDutyBanner();
  }catch(e){publicDuty=null;publicDutyError=true;renderDutyBanner();}
}

async function loadSchedule(){
  showLoading();
  try{
    const resp=await fetch("/api/schedule",{cache:"no-store"});
    if(!resp.ok) throw new Error(`Сервер ответил: ${resp.status}`);
    const data=await resp.json();
    state.teachers=data.teachers||null;
    state.subjects=data.subjects||null;
    state.bellSchedule=data.bell_schedule||null;
    state.secondShiftClasses=Array.isArray(data.second_shift_classes)?data.second_shift_classes:[];
    renderDutyBanner();
    state.updatedAt=data.updated_at?formatDate(data.updated_at):null;
    if(!state.teachers && !state.subjects){
      rebuildAll();
      showError("Расписание пока не загружено администратором. Зайдите позже.");
      $("currentLesson").classList.add("hidden");
      return;
    }
    rebuildAll();
    showSuccess();
    renderCurrentLesson();
  }catch(e){
    console.error(e);
    showError(`Не удалось загрузить расписание: ${e.message}. Проверьте подключение и обновите страницу.`);
  }
}

function collectTeachers(){
  const set=new Set();
  if(state.teachers) for(const d of DAYS){
    const lessons=state.teachers.grid[d]||{};
    for(const l in lessons){ const slot=lessons[l];
      for(const cls in slot){ const cell=slot[cls];
        for(const n of cell.names){
          if(SERVICE.has(n)) continue;
          if(state.teachers.numbering!=="local"&&!/^[А-ЯЁ][а-яё-]+(\s+[А-ЯЁ]{1,3}\.?)?$/.test(n)) continue;
          set.add(n);
        }
      }
    }
  }
  state.teacherNames=[...set].sort((a,b)=>a.localeCompare(b,"ru"));
}
function roomCmp(a,b){
  const na=parseInt(a,10),nb=parseInt(b,10);
  const an=String(na)===a,bn=String(nb)===b;
  if(an&&bn)return na-nb; if(an)return -1; if(bn)return 1;
  return a.localeCompare(b,"ru");
}
function collectRooms(){
  const all=[];
  [state.teachers,state.subjects].forEach(d=>{ if(!d) return;
    for(const day of DAYS){ const lessons=d.grid[day]||{};
      for(const l in lessons){ const slot=lessons[l];
        for(const cls in slot) all.push(...(slot[cls].rooms||[]));
      }
    }
  });
  state.rooms=uniqueRooms(all).sort(roomCmp);
}

const hasData=()=>!!(state.teachers||state.subjects);
const noData=()=>`<div class="nodata">📂 Расписание ещё не загружено.<br><span class="muted">Зайдите позже — администратор скоро обновит данные.</span></div>`;
function favBtn(kind,name){
  const on=favs[kind].includes(name);
  return `<button class="fav-btn ${on?'on':''}" data-kind="${kind}" data-name="${esc(name)}">${on?"★ В избранном":"☆ В избранное"}</button>`;
}
function cellLabel(cell){
  if(!cell)return "";
  const names=Array.isArray(cell.names)?cell.names.filter(Boolean):[];
  return names.length?names.join(", "):(cell.raw||"");
}
function cellFor(cls,day,lesson){
  const t=state.teachers?.grid[day]?.[lesson]?.[cls];
  const s=state.subjects?.grid[day]?.[lesson]?.[cls];
  const tText=cellLabel(t),sText=cellLabel(s);
  if(!tText && !sText) return "";
  let title,sub="";
  if(sText){ title=sText; if(tText && !SERVICE.has(sText) && !SERVICE.has(tText)) sub=tText; }
  else title=tText;
  const rooms=uniqueRooms(t?.rooms||[],s?.rooms||[]);
  return `<div class="lc ${SERVICE.has(title)?'svc':''}">
    <div class="subj">${esc(title)}</div>
    ${sub?`<div class="teach">${esc(sub)}</div>`:""}
    ${rooms.length?`<div class="rb">${rooms.map(r=>`<span class="room-badge">${esc(r)}</span>`).join("")}</div>`:""}
  </div>`;
}
function secondShiftGridOffset(day){
  const first=state.bellSchedule?.shifts?.["1"]?.[day]||{};
  const secondFirst=bellPeriod("2",day,1);
  const secondStart=clockMinutes(secondFirst?.start);
  if(secondStart!==null){
    for(const [number,period] of Object.entries(first)){
      const start=clockMinutes(period.start),end=clockMinutes(period.end);
      if(start!==null&&end!==null&&secondStart>=start&&secondStart<end)return Math.max(0,Number(number)-1);
    }
  }
  return Math.max(0,...Object.keys(first).map(Number).filter(Number.isFinite));
}
function classUsesGlobalShiftGrid(cls){
  if(state.teachers?.numbering==="local"||state.subjects?.numbering==="local")return false;
  if(!state.bellSchedule?.shifts?.["2"])return false;
  let hasGlobalRows=false,hasLocalRows=false;
  for(const day of DAYS){
    const offset=secondShiftGridOffset(day),teacherSlots=state.teachers?.grid[day]||{},subjectSlots=state.subjects?.grid[day]||{};
    const rawLessons=new Set([...Object.keys(teacherSlots),...Object.keys(subjectSlots)]);
    for(const raw of rawLessons){
      const teacher=teacherSlots[raw]?.[cls],subject=subjectSlots[raw]?.[cls];
      if(!cellLabel(teacher)&&!cellLabel(subject))continue;
      const number=Number(raw);
      if(!Number.isFinite(number))continue;
      if(number>offset)hasGlobalRows=true;
      // The final row before shift two can contain a class hour; rows before it
      // indicate that the source already numbers this class from lesson one.
      if(number<offset-1)hasLocalRows=true;
    }
  }
  return hasGlobalRows&&!hasLocalRows;
}
function classLessonEntries(cls,day){
  const teacherSlots=state.teachers?.grid[day]||{},subjectSlots=state.subjects?.grid[day]||{};
  const rawLessons=new Set([...Object.keys(teacherSlots),...Object.keys(subjectSlots)]);
  const isSecondShift=state.secondShiftClasses.includes(cls);
  const usesGlobalGrid=isSecondShift&&classUsesGlobalShiftGrid(cls);
  const offset=usesGlobalGrid?secondShiftGridOffset(day):0;
  const entries=[];
  for(const raw of rawLessons){
    const teacher=teacherSlots[raw]?.[cls],subject=subjectSlots[raw]?.[cls];
    if(!cellLabel(teacher)&&!cellLabel(subject))continue;
    const rawNumber=Number(raw);
    if(!Number.isFinite(rawNumber))continue;
    const beforeSecondShift=usesGlobalGrid&&rawNumber<=offset;
    const shift=isSecondShift?"2":"1";
    const timeShift=beforeSecondShift?"1":shift;
    const lesson=usesGlobalGrid&&!beforeSecondShift?rawNumber-offset:rawNumber;
    const timePeriod=bellPeriod(timeShift,day,lesson);
    const special=cellLabel(subject)||cellLabel(teacher);
    const isClassHour=SERVICE.has(special)&&special==="Классный час";
    entries.push({
      raw,lesson,shift,timeShift,
      time:timePeriod?`${timePeriod.start}–${timePeriod.end}`:"",
      beforeSecondShift,
      displayLesson:beforeSecondShift?(isClassHour?"КЧ":"до"):lesson,
      weekKey:beforeSecondShift?`before:${raw}`:`lesson:${lesson}`,
      weekLabel:beforeSecondShift?"до смены":String(lesson),
      order:rawNumber
    });
  }
  return entries.sort((a,b)=>a.order-b.order);
}
function pairValueForTeacher(values,index,teacherCount){
  const rooms=uniqueRooms(values||[]);
  return teacherCount>1&&rooms.length===teacherCount?(rooms[index]?[rooms[index]]:[]):rooms;
}
function teacherDayRows(name,dayName){
  const rows=[];
  for(const cls of state.classes){
    const shift=state.secondShiftClasses.includes(cls)?"2":"1";
    for(const entry of classLessonEntries(cls,dayName)){
      const c=state.teachers?.grid[dayName]?.[entry.raw]?.[cls];
      if(!c||!c.names.includes(name)) continue;
      const s=state.subjects?.grid[dayName]?.[entry.raw]?.[cls];
      const teacherIndex=c.names.indexOf(name), teacherCount=c.names.length;
      const subjectNames=s&&!SERVICE.has(s.raw)?(s.names||[]):[];
      let subj="";
      if(subjectNames.length){
        subj=teacherCount>1&&subjectNames.length===teacherCount
          ?(subjectNames[teacherIndex]||"")
          :subjectNames.join(", ");
      }
      const teacherRooms=pairValueForTeacher(c.rooms||[],teacherIndex,teacherCount);
      const subjectRooms=pairValueForTeacher(s?.rooms||[],teacherIndex,teacherCount);
      rows.push({l:entry.lesson,displayLesson:entry.displayLesson,order:entry.order,beforeSecondShift:entry.beforeSecondShift,cls,shift,subj,rooms:uniqueRooms(teacherRooms,subjectRooms),time:entry.time});
    }
  }
  return rows.sort((a,b)=>a.shift.localeCompare(b.shift)||a.order-b.order||a.cls.localeCompare(b.cls,"ru"));
}
const trowHTML=r=>`<div class="trow">
  ${lessonMarker(r.displayLesson??r.l,r.time)}
  <span class="tcls">${esc(r.cls)}</span>
  <span class="tsubj">${r.subj?esc(r.subj):'<span class="muted">—</span>'}</span>
  <span class="trooms">${r.rooms.map(x=>`<span class="room-badge">${esc(x)}</span>`).join(" ")||'<span class="muted">без каб.</span>'}</span>
</div>`;
function teacherShiftGroupHTML(rows,dayLabel=""){
  return ["1","2"].map(shift=>{
    const group=rows.filter(row=>row.shift===shift);
    if(!group.length)return "";
    const label=[dayLabel,`${shift}-я смена`].filter(Boolean).join(" · ");
    return `<h3>${esc(label)}</h3>${group.map(trowHTML).join("")}`;
  }).join("");
}
const dateLabel=di=> di===TODAY
  ? `Сегодня · ${new Date().toLocaleDateString("ru-RU",{weekday:"long",day:"numeric",month:"long"})}`
  : DAY_FULL[DAYS[di]];

function rebuildAll(){
  const data=state.teachers||state.subjects;
  state.classes=data?[...new Set(data.classes||[])]:[];
  collectTeachers(); collectRooms();
  if(state.curClass && !state.classes.includes(state.curClass)) state.curClass=null;
  if(state.curTeacher && !state.teacherNames.includes(state.curTeacher)) state.curTeacher=null;
  renderClassArea(); renderTeacherArea(); renderRoomsArea(); renderFavArea();
}
function renderClassArea(){
  const box=$("classArea");
  if(!hasData()){ box.innerHTML=noData(); return; }
  if(!state.curClass){
    box.innerHTML=`<p class="picker-hint">Выберите класс</p><div class="chips wrap selection-list">${state.classes.map(c=>
      `<button class="chip" type="button" data-cls="${esc(c)}">${esc(c)}</button>`).join("")||'<span class="muted">Классы не найдены</span>'}</div>`;
    box.querySelectorAll("[data-cls]").forEach(b=>b.onclick=()=>{state.curClass=b.dataset.cls;renderClassArea();});
    return;
  }
  box.innerHTML=`<div class="schedule-heading"><button class="change-selection" id="changeClass" type="button">← Все классы</button><strong>Класс ${esc(state.curClass)}</strong></div><section class="duty-public" aria-label="Дежурство сегодня"><h3>Дежурство сегодня</h3><div id="classDuty" aria-live="polite"></div></section><div id="classPanel"></div>`;
  renderDutyBanner();
  $("changeClass").onclick=()=>{state.curClass=null;renderClassArea();};
  renderClassPanel();
}
function renderClassPanel(){
  const p=$("classPanel"); if(!p) return;
  const sel=state.classSel;
  const pills=DAYS.map((d,i)=>`<button class="pill ${sel===i?'active':''}" data-cs="${i}">${d}${i===TODAY?'<span class="dot"></span>':''}</button>`).join("")
    +`<button class="pill ${sel==='week'?'active':''}" data-cs="week">📅 Неделя</button>`;
  p.innerHTML=`<div class="toolbar"><div class="pills">${pills}</div>${favBtn("classes",state.curClass)}</div><div id="classBody"></div>`;
  p.querySelectorAll("[data-cs]").forEach(b=>b.onclick=()=>{ state.classSel=b.dataset.cs==="week"?"week":+b.dataset.cs; renderClassPanel(); });
  renderClassBody();
}
function renderClassBody(){
  const out=$("classBody"); if(!out) return;
  const cls=state.curClass, sel=state.classSel;
  if(sel==="week"){ renderWeekInto(out,cls); return; }
  const d=DAYS[sel];
  let rows="",count=0;
  for(const entry of classLessonEntries(cls,d)){
    const c=cellFor(cls,d,entry.raw);
    if(!c) continue; count++;
    rows+=`<div class="lrow">${lessonMarker(entry.displayLesson,entry.time)}<div class="lcell">${c}</div></div>`;
  }
  out.innerHTML=`<p class="date-label"><b>${esc(cls)}</b> · ${dateLabel(sel)} · уроков: ${count}</p>`
    +(rows||`<div class="nodata">В этот день уроков нет 🎉</div>`);
}
function renderWeekInto(out,cls){
  const entriesByDay=Object.fromEntries(DAYS.map(d=>[d,classLessonEntries(cls,d)]));
  const rowMap=new Map();
  for(const entries of Object.values(entriesByDay))for(const entry of entries){
    if(!rowMap.has(entry.weekKey))rowMap.set(entry.weekKey,{key:entry.weekKey,label:entry.weekLabel,order:entry.order});
  }
  const weekRows=[...rowMap.values()].sort((a,b)=>a.order-b.order);
  if(!weekRows.length){ out.innerHTML=`<div class="nodata">У этого класса нет уроков.</div>`; return; }
  let html=`<div class="week-scroll"><table class="week"><thead><tr><th>Урок</th>`+
    DAYS.map((d,i)=>`<th class="${i===TODAY?'today':''}">${DAY_FULL[d]}</th>`).join("")+`</tr></thead><tbody>`;
  for(const row of weekRows){
    html+=`<tr><td>${esc(row.label)}</td>`+DAYS.map((d,i)=>{
      const entry=entriesByDay[d].find(item=>item.weekKey===row.key);
      const c=entry?cellFor(cls,d,entry.raw):"";
      return `<td class="${i===TODAY?'today':''}">${c?`${c}${entry.time?`<div class="week-time">${esc(entry.time)}</div>`:""}`:'<span class="dash">—</span>'}</td>`;
    }).join("")+`</tr>`;
  }
  const mobileWeek=DAYS.map((d,i)=>{
    const rows=entriesByDay[d].map(entry=>{
      const cell=cellFor(cls,d,entry.raw);
      return cell?`<div class="lrow">${lessonMarker(entry.displayLesson,entry.time)}<div class="lcell">${cell}</div></div>`:"";
    }).join("");
    return `<section class="mobile-week-day"><h3>${esc(DAY_FULL[d])}${i===TODAY?" · сегодня":""}</h3>${rows||'<p class="muted">Уроков нет</p>'}</section>`;
  }).join("");
  out.innerHTML=html+`</tbody></table></div><div class="mobile-week">${mobileWeek}</div>`;
}

function renderTeacherArea(){
  const box=$("teacherArea");
  if(!state.teachers){
    box.innerHTML=hasData()?`<div class="nodata">👩‍🏫 Данные расписания учителей пока недоступны.</div>`:noData();
    return;
  }
  if(state.curTeacher){
    box.innerHTML=`<div class="schedule-heading"><button class="change-selection" id="changeTeacher" type="button">← Все учителя</button><strong>${esc(state.curTeacher)}</strong></div><section class="duty-public" aria-label="Дежурство сегодня"><h3>Дежурство сегодня</h3><div id="teacherDuty" aria-live="polite"></div></section><div id="teacherPanel"></div>`;
    renderDutyBanner();
    $("changeTeacher").onclick=()=>{state.curTeacher=null;state.teacherQuery="";renderTeacherArea();$("teacherSearch").focus();};
    renderTeacherPanel();
    return;
  }
  box.innerHTML=`<p class="picker-hint">Выберите учителя</p>
    <input class="search" id="teacherSearch" aria-label="Поиск учителя" placeholder="🔍 Поиск учителя…" value="${esc(state.teacherQuery)}">
    <div class="chips wrap selection-list" id="teacherChips"></div>`;
  const inp=$("teacherSearch");
  const drawChips=()=>{
    const q=inp.value.trim().toLowerCase();
    $("teacherChips").innerHTML=state.teacherNames
      .filter(n=>!q||n.toLowerCase().includes(q))
      .map(n=>`<button class="chip" type="button" data-t="${esc(n)}">${favs.teachers.includes(n)?"★ ":""}${esc(n)}</button>`)
      .join("")||`<span class="muted">Никого не найдено</span>`;
    $("teacherChips").querySelectorAll(".chip").forEach(b=>b.onclick=()=>{state.curTeacher=b.dataset.t;renderTeacherArea();});
  };
  inp.oninput=()=>{state.teacherQuery=inp.value;drawChips();};
  drawChips();
}
function renderTeacherPanel(){
  const p=$("teacherPanel"); if(!p) return;
  const name=state.curTeacher;
  if(!name){ p.innerHTML=`<div class="nodata">Выберите учителя из списка.</div>`; return; }
  const sel=state.teacherSel;
  const pills=`<button class="pill ${sel==='all'?'active':''}" data-ts="all">Вся неделя</button>`+
    DAYS.map((d,i)=>`<button class="pill ${sel===i?'active':''}" data-ts="${i}">${d}${i===TODAY?'<span class="dot"></span>':''}</button>`).join("");
  let total=0; DAYS.forEach(d=>total+=teacherDayRows(name,d).length);
  p.innerHTML=`
    <div class="toolbar"><div class="pills">${pills}</div>${favBtn("teachers",name)}</div>
    <p class="ttotal">Уроков в неделю: ${total}</p>
    <div id="teacherOut"></div>`;
  p.querySelectorAll("[data-ts]").forEach(b=>b.onclick=()=>{ state.teacherSel=b.dataset.ts==="all"?"all":+b.dataset.ts; renderTeacherPanel(); });
  renderTeacherSchedule();
}
function renderTeacherSchedule(){
  const out=$("teacherOut"); if(!out) return;
  const name=state.curTeacher, sel=state.teacherSel;
  const dayIdxs=sel==="all"?DAYS.map((_,i)=>i):[sel];
  let html="";
  for(const di of dayIdxs){
    const rows=teacherDayRows(name,DAYS[di]);
    if(!rows.length) continue;
    const dayLabel=`${DAY_FULL[DAYS[di]]}${di===TODAY?" · сегодня":""}`;
    html+=teacherShiftGroupHTML(rows,dayLabel);
  }
  out.innerHTML=html||`<div class="nodata">${sel==="all"?"Уроков не найдено.":"В этот день уроков нет 🎉"}</div>`;
}

// Занятость определяется по реальному времени, а не по номеру урока:
// одинаковые номера в разных сменах обычно не совпадают по времени.
function roomOccupancyAt(now){
  const day=DAYS[now.getDay()-1];
  const minute=now.getHours()*60+now.getMinutes()+now.getSeconds()/60;
  const byRoom=Object.create(null);
  if(!day)return {day,byRoom};
  for(const cls of state.classes){
    for(const entry of classLessonEntries(cls,day)){
      const t=state.teachers?.grid[day]?.[entry.raw]?.[cls];
      const s=state.subjects?.grid[day]?.[entry.raw]?.[cls];
      const rooms=uniqueRooms(t?.rooms||[],s?.rooms||[]);
      if(!rooms.length)continue;
      const period=bellPeriod(entry.timeShift,day,entry.lesson);
      const start=clockMinutes(period?.start),end=clockMinutes(period?.end);
      const valid=start!==null&&end!==null&&start<end;
      const subj=s&&!SERVICE.has(s.raw)?cellLabel(s):"";
      const teach=t&&!SERVICE.has(t.raw)?cellLabel(t):"";
      const who=[subj,teach].filter(Boolean).join(" · ");
      for(const room of rooms){
        const info=byRoom[roomKey(room)]??(byRoom[roomKey(room)]={active:[],next:null,unknown:false});
        if(!valid){info.unknown=true;continue;}
        if(start<=minute&&minute<end){
          const existing=info.active.find(item=>item.cls===cls);
          if(existing){if(who&&!existing.who.includes(who))existing.who.push(who);}
          else info.active.push({cls,who:who?[who]:[]});
        }else if(start>minute&&(info.next===null||start<info.next.minutes)){
          info.next={minutes:start,label:period.start};
        }
      }
    }
  }
  return {day,byRoom};
}
function renderRoomsArea(){
  const box=$("roomsArea");
  if(!hasData()){ box.innerHTML=noData(); return; }
  box.innerHTML=`
    <div class="rooms-controls">
      <label class="chk"><input type="checkbox" id="onlyFree" ${state.roomOnlyFree?'checked':''}> только свободные</label>
    </div>
    <div class="rooms-summary" id="roomsSummary" aria-live="polite"></div>
    <div class="rooms-grid" id="roomsGrid"></div>`;
  $("onlyFree").onchange=()=>{state.roomOnlyFree=$("onlyFree").checked;renderRooms();};
  renderRooms();
}
function renderRooms(){
  const summary=$("roomsSummary"),grid=$("roomsGrid");
  if(!summary||!grid)return;
  const now=new Date(),{day,byRoom}=roomOccupancyAt(now);
  const status=room=>{
    const info=byRoom[roomKey(room)];
    return info?.active.length?"busy":info?.unknown?"unknown":"free";
  };
  const free=state.rooms.filter(r=>status(r)==="free");
  const unknown=state.rooms.filter(r=>status(r)==="unknown").length;
  const dayLabel=day?DAY_FULL[day]:"Воскресенье";
  const clock=now.toLocaleTimeString("ru-RU",{hour:"2-digit",minute:"2-digit"});
  summary.innerHTML=`${esc(dayLabel)}, ${esc(clock)}: <b>свободно ${free.length}</b> из ${state.rooms.length} кабинетов${unknown?` · неизвестно: ${unknown}`:""}`;
  const list=state.roomOnlyFree?free:state.rooms;
  grid.innerHTML=list.map(r=>{
    const info=byRoom[roomKey(r)],roomStatus=status(r);
    if(roomStatus==="unknown")return `<div class="room unknown"><div class="rnum">${esc(r)}</div><div class="rstatus">Нет данных о времени</div></div>`;
    if(roomStatus==="free")return `<div class="room free"><div class="rnum">${esc(r)}</div><div class="rstatus">Свободен${info?.next?` до ${esc(info.next.label)}`:""}</div></div>`;
    const occ=info.active.map(o=>`${esc(o.cls)}${o.who.length?": "+esc(o.who.join(" · ")):""}`).join("<br>");
    return `<div class="room busy"><div class="rnum">${esc(r)}</div><div class="rstatus">Занят</div><div class="rocc">${occ}</div>${info.unknown?'<div class="rocc">Для других занятий время не указано</div>':""}</div>`;
  }).join("")||`<div class="nodata">${state.roomOnlyFree&&state.rooms.length?"Нет свободных кабинетов.":"Нет данных по кабинетам."}</div>`;
}

function renderFavArea(){
  const box=$("favArea");
  if(!hasData()){ box.innerHTML=noData(); return; }
  favs.classes=favs.classes.filter(c=>state.classes.includes(c));
  favs.teachers=favs.teachers.filter(t=>state.teacherNames.includes(t));
  if(!favs.classes.length && !favs.teachers.length){
    box.innerHTML=`<div class="nodata">⭐ Здесь пока пусто.<br><br>
      Ученику: откройте <b>«Классы»</b>, выберите свой класс и нажмите <b>«☆ В избранное»</b>.<br>
      Учителю: откройте <b>«Учителя»</b>, найдите себя и нажмите <b>«☆ В избранное»</b>.<br><br>
      Тогда здесь всегда будут видны <b>только ваши уроки</b>, по умолчанию — на сегодня.</div>`;
    return;
  }
  const sel=state.favDay, d=DAYS[sel];
  const pills=DAYS.map((dd,i)=>`<button class="pill ${sel===i?'active':''}" data-fd="${i}">${dd}${i===TODAY?'<span class="dot"></span>':''}</button>`).join("");
  let html=`<div class="toolbar"><div class="pills">${pills}</div></div><p class="date-label">${dateLabel(sel)}</p>`;
  if(favs.classes.length){
    html+=`<h3>🎓 Мои классы</h3>`;
    for(const cls of favs.classes){
      let rows="",count=0;
      for(const entry of classLessonEntries(cls,d)){ const c=cellFor(cls,d,entry.raw); if(!c)continue; count++;
        rows+=`<div class="lrow">${lessonMarker(entry.displayLesson,entry.time)}<div class="lcell">${c}</div></div>`; }
      html+=`<div class="fav-card"><div class="fav-head"><b>${esc(cls)}</b><span class="muted">класс · уроков: ${count}</span>
        <button class="rm-fav" data-kind="classes" data-name="${esc(cls)}">убрать ✕</button></div>
        ${rows||'<div class="muted">В этот день уроков нет 🎉</div>'}</div>`;
    }
  }
  if(favs.teachers.length){
    html+=`<h3>👩‍🏫 Мои учителя</h3>`;
    for(const name of favs.teachers){
      const rows=teacherDayRows(name,d);
      html+=`<div class="fav-card"><div class="fav-head"><b>${esc(name)}</b><span class="muted">учитель · уроков: ${rows.length}</span>
        <button class="rm-fav" data-kind="teachers" data-name="${esc(name)}">убрать ✕</button></div>
        ${teacherShiftGroupHTML(rows)||'<div class="muted">В этот день уроков нет 🎉</div>'}</div>`;
    }
  }
  box.innerHTML=html;
  box.querySelectorAll("[data-fd]").forEach(b=>b.onclick=()=>{ state.favDay=+b.dataset.fd; renderFavArea(); });
}
document.addEventListener("click",e=>{
  const b=e.target.closest(".fav-btn, .rm-fav");
  if(b) toggleFav(b.dataset.kind, b.dataset.name);
});

function showView(viewId){
  document.querySelectorAll(".view").forEach(view=>view.classList.toggle("hidden",view.id!==viewId));
  $("homeBack").classList.toggle("hidden",viewId==="view-home");
}
function openPicker(viewId){
  if(viewId==="view-classes"){state.curClass=null;renderClassArea();}
  if(viewId==="view-teachers"){state.curTeacher=null;state.teacherQuery="";renderTeacherArea();}
  showView(viewId);
}
$("homeBack").onclick=()=>showView("view-home");
document.querySelectorAll("[data-open-view]").forEach(button=>button.onclick=()=>openPicker(button.dataset.openView));

$("reloadBtn").onclick=()=>loadSchedule();

/* Обновляем сетку каждые 5 минут, а таймер урока — каждые 30 секунд. */
setInterval(()=>{ if(!document.hidden) loadSchedule(); }, 5*60*1000);
setInterval(()=>{ if(!document.hidden){renderCurrentLesson();renderRooms();renderDutyBanner();} }, 30*1000);
setInterval(()=>{if(!document.hidden)loadPublicDuty();},60*1000);
document.addEventListener("visibilitychange",()=>{ if(!document.hidden){loadSchedule();loadPublicDuty();renderCurrentLesson();renderRooms();} });

/* Запуск */
loadSchedule();
loadPublicDuty();
