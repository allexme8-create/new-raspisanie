"use strict";
/* Общая карта текущего расписания использует тот же черновик, что и карта класса. */
let overviewData=null,overviewSelected=null,overviewBusy=false,datedData=null;
const overviewDays=['Пн','Вт','Ср','Чт','Пт','Сб'];
const overviewDayNames={'Пн':'Понедельник','Вт':'Вторник','Ср':'Среда','Чт':'Четверг','Пт':'Пятница','Сб':'Суббота'};
async function loadOverview(){
  try{overviewData=await api('/api/admin/schedule-map?all_entries=true');overviewSelected=null;$("overviewSelected").classList.add('hidden');renderOverview();}
  catch(e){$("overviewStatus").textContent=e.message;}
}
function renderOverview(){
  const data=overviewData,root=$("overviewGrid"),status=$("overviewStatus");if(!data)return;
  $("overviewPublish").disabled=data.stale||!data.has_changes;
  const teacherMode=$("overviewMode").value==='teachers',dayFilter=$("overviewDay").value,query=$("overviewSearch").value.trim().toLocaleLowerCase('ru-RU');
  const days=dayFilter?[dayFilter]:overviewDays;
  // Keep columns shared across all rows; a hidden empty slot can still be exposed for moves.
  const slots=days.flatMap(day=>Array.from({length:12},(_,i)=>({day,lesson:i+1})).filter(slot=>$("overviewShowEmpty").checked||data.entries.some(e=>e.day===slot.day&&e.lesson===slot.lesson)));
  root.classList.toggle('overview-selecting',Boolean(overviewSelected));
  const rows=teacherMode?[...new Set(data.entries.flatMap(e=>e.teachers.names||[]))].sort((a,b)=>a.localeCompare(b,'ru')):data.classes;
  const filtered=rows.filter(x=>x.toLocaleLowerCase('ru-RU').includes(query));
  status.textContent=data.stale?'Опубликованное расписание изменилось. Отмените старый черновик карты, чтобы загрузить актуальные данные.':data.has_changes?'Изменения сохранены в черновике. Публикация доступна под общей картой.':'Показано текущее расписание. Нажмите карточку, затем ячейку назначения.';
  let html=`<div class="overview-scroll"><div class="overview-table" style="grid-template-columns: ${teacherMode?110:68}px repeat(${slots.length},64px)"><div class="overview-corner">${teacherMode?'Учитель':'Класс'}</div>`;
  for(const day of days){
    const count=slots.filter(slot=>slot.day===day).length;
    if(count)html+=`<div class="overview-day-head" style="grid-column:span ${count}" title="${overviewDayNames[day]}">${overviewDayNames[day]}</div>`;
  }
  for(const {lesson} of slots)html+=`<div class="overview-head">${lesson}</div>`;
  for(const row of filtered){html+=`<div class="overview-row-label">${esc(row)}</div>`;for(const {day,lesson} of slots){
    const entries=data.entries.filter(e=>e.day===day&&e.lesson===lesson&&(teacherMode?(e.teachers.names||[]).includes(row):e.class_name===row));
    html+=`<div class="overview-cell" data-overview-row="${esc(row)}" data-overview-day="${day}" data-overview-lesson="${lesson}"><button type="button" class="overview-target" data-overview-target aria-label="${esc(row)}, ${day}, урок ${lesson}">+</button>${entries.map(e=>`<button type="button" class="overview-lesson ${lessonColorClass(e.subjects.names,e.subjects.raw)} ${e.change==='removed'?'removed':e.change==='added'?'changed':''}" data-overview-class="${esc(e.class_name)}" data-overview-day-src="${esc(e.day)}" data-overview-raw="${esc(e.raw)}" data-overview-row-src="${esc(row)}" data-overview-change="${esc(e.change||'')}"><strong>${esc((e.subjects.names||[]).join(', ')||e.subjects.raw||'Урок')}</strong><span>${esc(teacherMode?e.class_name:(e.teachers.names||[]).join(', '))}</span><span>${esc([...new Set([...(e.teachers.rooms||[]),...(e.subjects.rooms||[])])].join(', '))}</span>${e.before_shift?'<span>до смены</span>':''}</button>`).join('')}</div>`;
  }}root.innerHTML=slots.length?html+'</div></div>':'<p class="muted">Уроков за выбранный период нет. Чтобы увидеть пустые часы, включите их показ.</p>';
  root.querySelectorAll('[data-overview-target]').forEach(button=>button.onclick=()=>{const cell=button.closest('[data-overview-row]');if(overviewSelected&&cell)overviewMove(overviewSelected,cell);});
  root.querySelectorAll('[data-overview-class]').forEach(button=>{
    let pointer=null,suppress=false;
    const source=()=>({class_name:button.dataset.overviewClass,day:button.dataset.overviewDaySrc,raw:button.dataset.overviewRaw,row:button.dataset.overviewRowSrc});
    button.onclick=()=>{if(suppress){suppress=false;return;}if(button.dataset.overviewChange==='removed'||data.stale||overviewBusy)return;chooseOverview(source());};
    button.onpointerdown=e=>{if(e.button!==0||data.stale||button.dataset.overviewChange==='removed'||overviewBusy)return;pointer={id:e.pointerId,x:e.clientX,y:e.clientY,drag:false};button.setPointerCapture(e.pointerId);};
    button.onpointermove=e=>{if(pointer&&pointer.id===e.pointerId&&Math.hypot(e.clientX-pointer.x,e.clientY-pointer.y)>8){pointer.drag=true;moveDragCard(button,e.clientX-pointer.x,e.clientY-pointer.y);}};
    button.onpointercancel=()=>{pointer=null;finishDragCard(button);};
    button.onpointerup=e=>{if(!pointer||pointer.id!==e.pointerId)return;const drag=pointer.drag;pointer=null;if(!drag){finishDragCard(button);return;}suppress=true;const cell=document.elementFromPoint(e.clientX,e.clientY)?.closest('[data-overview-row]');finishDragCard(button);setTimeout(()=>{suppress=false},0);if(cell&&root.contains(cell))overviewMove(source(),cell);else{status.textContent='Перенос отменён.';setTimeout(()=>{suppress=false},0);}};
  });
}
function chooseOverview(source){
  overviewSelected=source;$("overviewGrid").classList.add("overview-selecting");const e=overviewData.entries.find(e=>e.class_name===source.class_name&&e.day===source.day&&e.raw===source.raw&&e.change!=='removed');if(!e)return;
  $("overviewSelectionLabel").textContent=`${source.class_name} · ${source.day} · урок ${e.lesson}: ${(e.subjects.names||[]).join(', ')} · ${(e.teachers.names||[]).join(', ')}`;
  $("overviewSubjects").value=(e.subjects.names||[]).join(', ');$("overviewTeachers").value=(e.teachers.names||[]).join(', ');$("overviewRooms").value=[...new Set([...(e.subjects.rooms||[]),...(e.teachers.rooms||[])])].join(', ');
  $("overviewRemove").disabled=(e.teachers.names||[]).length!==1;$("overviewSelected").classList.remove('hidden');$("overviewStatus").textContent='Урок выбран. Нажмите «+» в той же строке или исправьте его выше.';
}
async function overviewMove(source,cell){
  if(overviewBusy||overviewData.stale)return;if(cell.dataset.overviewRow!==source.row){$("overviewStatus").textContent='Переносите урок только внутри строки выбранного класса или учителя.';return;}
  overviewBusy=true;try{await api('/api/admin/schedule-map/move',{method:'POST',body:{revision:overviewData.revision,class_name:source.class_name,day:source.day,raw:source.raw,target_day:cell.dataset.overviewDay,target_lesson:Number(cell.dataset.overviewLesson)}});await loadOverview();if(typeof loadPublishedMap==='function')await loadPublishedMap();$("overviewStatus").textContent='Урок перенесён в черновике; опубликуйте изменения ниже.';}catch(e){$("overviewStatus").textContent=e.message;}finally{overviewBusy=false;}
}
$("overviewRemove").onclick=async()=>{if(!overviewSelected||overviewBusy||overviewData.stale)return;const entry=overviewData.entries.find(e=>e.class_name===overviewSelected.class_name&&e.day===overviewSelected.day&&e.raw===overviewSelected.raw&&e.change!=='removed');const teacher=entry?.teachers?.names?.[0];if(!teacher||!confirm(`Снять урок ${teacher} у класса ${overviewSelected.class_name} из недельного черновика?`))return;overviewBusy=true;try{await api('/api/admin/schedule-map/remove',{method:'POST',body:{revision:overviewData.revision,class_name:overviewSelected.class_name,day:overviewSelected.day,raw:overviewSelected.raw,teacher}});await loadOverview();if(typeof loadPublishedMap==='function')await loadPublishedMap();$("overviewStatus").textContent='Урок снят в черновике; опубликуйте изменения ниже.';}catch(e){$("overviewStatus").textContent=e.message;}finally{overviewBusy=false;}};
$("overviewEdit").onsubmit=async e=>{e.preventDefault();if(!overviewSelected||overviewBusy||overviewData.stale)return;const list=id=>$(id).value.split(',').map(x=>x.trim()).filter(Boolean);overviewBusy=true;try{await api('/api/admin/schedule-map/edit',{method:'POST',body:{revision:overviewData.revision,class_name:overviewSelected.class_name,day:overviewSelected.day,raw:overviewSelected.raw,teachers:list('overviewTeachers'),subjects:list('overviewSubjects'),rooms:list('overviewRooms')}});await loadOverview();if(typeof loadPublishedMap==='function')await loadPublishedMap();$("overviewStatus").textContent='Изменения сохранены в черновике.';}catch(err){$("overviewStatus").textContent=err.message;}finally{overviewBusy=false;}};
$("overviewClear").onclick=()=>{overviewSelected=null;$("overviewSelected").classList.add('hidden');renderOverview();};
$("overviewMapSection").ontoggle=()=>{if($("overviewMapSection").open){loadOverview();loadDatedChanges();}};
$("overviewMode").onchange=()=>{overviewSelected=null;$("overviewSelected").classList.add('hidden');renderOverview();};
$("overviewShowEmpty").onchange=renderOverview;$("overviewDay").onchange=renderOverview;$("overviewSearch").oninput=renderOverview;$("overviewRefresh").onclick=loadOverview;
async function overviewCommit(action){
  if(!overviewData||overviewBusy||(action==='publish'&&(overviewData.stale||!overviewData.has_changes)))return;
  if(!confirm(action==='publish'?'Опубликовать все изменения карты вместо текущего расписания?':'Отменить все неопубликованные изменения карты?'))return;
  overviewBusy=true;
  try{
    await api(`/api/admin/schedule-map/${action}`,{method:'POST',body:{revision:overviewData.revision}});
    await loadOverview();
    if(typeof loadPublishedMap==='function')await loadPublishedMap();
    if(action==='publish'&&typeof loadStatus==='function')await loadStatus();
    $("overviewStatus").textContent=action==='publish'?'Расписание опубликовано.':'Изменения карты отменены.';
  }catch(e){$("overviewStatus").textContent=e.message;}finally{overviewBusy=false;}
}
$("overviewReset").onclick=()=>overviewCommit('reset');
$("overviewPublish").onclick=()=>overviewCommit('publish');

async function loadDatedChanges(){
  try{datedData=await api('/api/admin/dated-schedule-changes');const root=$("datedChangeList");root.innerHTML=datedData.changes.map(c=>`<div class="dated-admin-item"><span>${c.stale?'⚠️ Требует проверки: ':''}<s>${esc(c.source_date)} · ${esc(c.class_name)} · урок ${c.source_lesson} · ${esc(c.subject)} · ${esc(c.teacher)}</s>${c.target_date?` → <b>${esc(c.target_date)} · урок ${c.target_lesson}</b>`:' · отменён'}</span><button type="button" class="btn secondary" data-dated-delete="${esc(c.id)}">Отменить изменение</button></div>`).join('')||'<p class="muted">Изменений на даты нет.</p>';root.querySelectorAll('[data-dated-delete]').forEach(button=>button.onclick=async()=>{if(!confirm('Отменить это разовое изменение?'))return;try{await api(`/api/admin/dated-schedule-changes/${encodeURIComponent(button.dataset.datedDelete)}?revision=${datedData.revision}`,{method:'DELETE'});await loadDatedChanges();$("overviewStatus").textContent='Изменение на дату отменено.';}catch(e){$("overviewStatus").textContent=e.message;}});}
  catch(e){$("overviewStatus").textContent=e.message;}
}
$("datedChangeForm").onsubmit=async e=>{
  e.preventDefault();if(!overviewSelected||overviewBusy||!datedData)return;const item=overviewData.entries.find(e=>e.class_name===overviewSelected.class_name&&e.day===overviewSelected.day&&e.raw===overviewSelected.raw&&e.change!=='removed');const teachers=item?.teachers?.names||[];if(teachers.length!==1){$("overviewStatus").textContent='Изменение на дату доступно только для ячейки с одним учителем.';return;}
  const target=$("datedTarget").value,lesson=$("datedLesson").value;
  if(Boolean(target)!==Boolean(lesson)){$("overviewStatus").textContent='Для переноса укажите дату и номер урока.';return;}
  if(!confirm('Это разовое изменение сразу увидят посетители сайта. Продолжить?'))return;
  overviewBusy=true;try{await api('/api/admin/dated-schedule-changes',{method:'POST',body:{revision:datedData.revision,class_name:overviewSelected.class_name,day:overviewSelected.day,raw:overviewSelected.raw,teacher:teachers[0],source_date:$("datedSource").value,target_date:target||null,target_lesson:lesson?Number(lesson):null}});await loadDatedChanges();$("overviewStatus").textContent='Изменение на дату опубликовано.';}catch(error){$("overviewStatus").textContent=error.message;}finally{overviewBusy=false;}
};

$("datedReset").onclick=async()=>{if(!datedData||!datedData.changes.length||!confirm('Отменить ВСЕ изменения на конкретные даты? Это сразу увидят посетители.'))return;try{await api('/api/admin/dated-schedule-changes/reset',{method:'POST',body:{revision:datedData.revision}});await loadDatedChanges();$("overviewStatus").textContent='Изменения на даты отменены.';}catch(e){$("overviewStatus").textContent=e.message;}};
