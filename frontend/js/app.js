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
    state.updatedAt=data.updated_at?formatDate(data.updated_at):null;
    if(!state.teachers && !state.subjects){
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
          if(!/^[А-ЯЁ][а-яё-]+(\s+[А-ЯЁ]{1,3}\.?)?$/.test(n)) continue;
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
  if(state.classes.length && !state.curClass) state.curClass=state.classes[0];
  renderClassArea(); renderTeacherArea(); renderRoomsArea(); renderFavArea();
}
function renderClassArea(){
  const box=$("classArea");
  if(!hasData()){ box.innerHTML=noData(); return; }
  box.innerHTML=`<div class="chips">${state.classes.map(c=>
    `<button class="chip ${c===state.curClass?'active':''}" data-cls="${esc(c)}">${esc(c)}</button>`).join("")}</div>
    <div id="classPanel"></div>`;
  box.querySelectorAll("[data-cls]").forEach(b=>b.onclick=()=>{ state.curClass=b.dataset.cls; renderClassArea(); });
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
  out.innerHTML=html+`</tbody></table></div>`;
}

function renderTeacherArea(){
  const box=$("teacherArea");
  if(!state.teachers){
    box.innerHTML=hasData()?`<div class="nodata">👩‍🏫 Данные расписания учителей пока недоступны.</div>`:noData();
    return;
  }
  box.innerHTML=`
    <input class="search" id="teacherSearch" placeholder="🔍 Поиск учителя…" value="${esc(state.teacherQuery)}">
    <div class="chips wrap" id="teacherChips"></div>
    <div id="teacherPanel"></div>`;
  const inp=$("teacherSearch");
  const drawChips=()=>{
    const q=inp.value.trim().toLowerCase();
    $("teacherChips").innerHTML=state.teacherNames
      .filter(n=>!q||n.toLowerCase().includes(q))
      .map(n=>`<button class="chip ${n===state.curTeacher?'active':''}" data-t="${esc(n)}">${favs.teachers.includes(n)?"★ ":""}${esc(n)}</button>`)
      .join("")||`<span class="muted">Никого не найдено</span>`;
    $("teacherChips").querySelectorAll(".chip").forEach(b=>b.onclick=()=>{ state.curTeacher=b.dataset.t; renderTeacherArea(); });
  };
  inp.oninput=()=>{ state.teacherQuery=inp.value; drawChips(); };
  drawChips();
  renderTeacherPanel();
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
    <p class="ttotal">${esc(name)}: ${total} уроков в неделю</p>
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

function slotInfo(day,lesson){
  const byRoom=Object.create(null);
  for(const cls of state.classes){
    for(const entry of classLessonEntries(cls,day).filter(item=>item.lesson===Number(lesson))){
      const t=state.teachers?.grid[day]?.[entry.raw]?.[cls];
      const s=state.subjects?.grid[day]?.[entry.raw]?.[cls];
      const rooms=uniqueRooms(t?.rooms||[],s?.rooms||[]);
      if(!rooms.length) continue;
      const subj=s&&!SERVICE.has(s.raw)?cellLabel(s):"";
      const teach=t&&!SERVICE.has(t.raw)?cellLabel(t):"";
      const who=[subj,teach].filter(Boolean).join(" · ");
      for(const room of rooms){
        const key=roomKey(room),occupants=byRoom[key]??(byRoom[key]=[]);
        const existing=occupants.find(item=>item.cls===cls);
        if(existing){ if(who&&!existing.who.includes(who))existing.who.push(who); }
        else occupants.push({cls,who:who?[who]:[]});
      }
    }
  }
  return byRoom;
}
function renderRoomsArea(){
  const box=$("roomsArea");
  if(!hasData()){ box.innerHTML=noData(); return; }
  const defDay=TODAY>=0?DAYS[TODAY]:"Пн";
  box.innerHTML=`
    <div class="rooms-controls">
      <label>День <select id="roomDay">${DAYS.map(d=>`<option ${d===defDay?'selected':''}>${d}</option>`).join("")}</select></label>
      <label>Урок <select id="roomLesson">${Array.from({length:13},(_,i)=>`<option value="${i+1}">${i+1}-й урок</option>`).join("")}</select></label>
      <label class="chk"><input type="checkbox" id="onlyFree"> только свободные</label>
    </div>
    <div class="rooms-summary" id="roomsSummary"></div>
    <div class="rooms-grid" id="roomsGrid"></div>`;
  ["roomDay","roomLesson","onlyFree"].forEach(id=>$(id).onchange=renderRooms);
  renderRooms();
}
function renderRooms(){
  const day=$("roomDay").value, lesson=+$("roomLesson").value, onlyFree=$("onlyFree").checked;
  const busy=slotInfo(day,lesson);
  const free=state.rooms.filter(r=>!busy[roomKey(r)]);
  const shiftTimes=["1","2"].filter(shiftHasClasses).map(shift=>{
    const period=bellPeriod(shift,day,lesson);
    return period?`${shift}-я смена: ${period.start}–${period.end}`:"";
  }).filter(Boolean);
  const timeLabel=shiftTimes.length?` · ${shiftTimes.join(" · ")}`:"";
  $("roomsSummary").innerHTML=`${DAY_FULL[day]}, ${lesson}-й урок${timeLabel}: <b>свободно ${free.length}</b> из ${state.rooms.length} кабинетов`;
  const list=onlyFree?free:state.rooms;
  $("roomsGrid").innerHTML=list.map(r=>{
    const occupants=busy[roomKey(r)]||[];
    if(!occupants.length) return `<div class="room free"><div class="rnum">${esc(r)}</div><div class="rstatus">Свободен</div></div>`;
    const occ=occupants.map(o=>`${esc(o.cls)}${o.who.length?": "+esc(o.who.join(" · ")):""}`).join("<br>");
    return `<div class="room busy"><div class="rnum">${esc(r)}</div><div class="rstatus">Занят</div><div class="rocc">${occ}</div></div>`;
  }).join("")||`<div class="nodata">Нет данных по кабинетам.</div>`;
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

/* Нижняя навигация на мобильных */
function setupMobileNav(){
  const mq=matchMedia("(max-width:640px)");
  const apply=()=>document.body.classList.toggle("mobile-nav",mq.matches);
  mq.addEventListener?mq.addEventListener("change",apply):mq.addListener(apply);
  apply();
}

document.querySelectorAll(".tab").forEach(t=>t.onclick=()=>{
  document.querySelectorAll(".tab").forEach(x=>x.classList.remove("active"));
  t.classList.add("active");
  document.querySelectorAll(".view").forEach(v=>v.classList.add("hidden"));
  $(t.dataset.view).classList.remove("hidden");
});

$("reloadBtn").onclick=()=>loadSchedule();

/* Обновляем сетку каждые 5 минут, а таймер урока — каждые 30 секунд. */
setInterval(()=>{ if(!document.hidden) loadSchedule(); }, 5*60*1000);
setInterval(()=>{ if(!document.hidden) renderCurrentLesson(); }, 30*1000);
document.addEventListener("visibilitychange",()=>{ if(!document.hidden){loadSchedule();renderCurrentLesson();} });

/* Запуск */
setupMobileNav();
loadSchedule();
