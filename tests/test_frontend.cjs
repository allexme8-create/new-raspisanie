const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const elements = new Map();
function element(id) {
  if (!elements.has(id)) {
    const classes = new Set();
    elements.set(id, {
      id,
      innerHTML: "",
      textContent: "",
      value: "",
      checked: false,
      classList: {
        add: (...names) => names.forEach(name => classes.add(name)),
        remove: (...names) => names.forEach(name => classes.delete(name)),
        toggle: (name, force) => {
          if (force === undefined) force = !classes.has(name);
          if (force) classes.add(name); else classes.delete(name);
          return force;
        },
        contains: name => classes.has(name),
      },
      onclick: null,
      onchange: null,
      querySelectorAll: () => [],
      focus: () => {},
    });
  }
  return elements.get(id);
}

class FixedDate extends Date {
  constructor(...args) {
    if (args.length) super(...args);
    else super(2026, 10, 9, 8, 30, 0, 0); // понедельник, 08:30 по локальному времени
  }
  static now() { return new FixedDate().getTime(); }
}

const context = {
  Date: FixedDate,
  FixedDate,
  console,
  localStorage: { getItem: () => null, setItem: () => {} },
  document: {
    hidden: false,
    body: { classList: { toggle: () => {} } },
    getElementById: element,
    querySelectorAll: () => [],
    addEventListener: () => {},
  },
  matchMedia: () => ({ matches: false, addEventListener: () => {}, addListener: () => {} }),
  setInterval: () => 0,
  clearTimeout: () => {},
  fetch: async () => ({ ok: true, json: async () => ({}) }),
};
vm.createContext(context);
const app = fs.readFileSync("frontend/js/app.js", "utf8");
vm.runInContext(app, context, { filename: "frontend/js/app.js" });

vm.runInContext(`
  state.classes = ["5а","6а","7а"];
  state.teachers = {grid:{Пн:{
    "1":{"5а":{
      raw:"Иванова ИИ, Петрова ПП (101, 102, 101)",
      names:["Иванова ИИ","Петрова ПП"], rooms:["101","102","101"]
    },"7а":{raw:"Иванова ИИ",names:["Иванова ИИ"],rooms:[]}},
    "6":{"6а":{raw:"Классный час",names:["Классный час"],rooms:[]}},
    "7":{"6а":{raw:"Иванова ИИ (301)",names:["Иванова ИИ"],rooms:["301"]}},
    "8":{"6а":{raw:"Иванова ИИ",names:["Иванова ИИ"],rooms:[]}},
    "9":{"6а":{raw:"Иванова ИИ",names:["Иванова ИИ"],rooms:[]}},
    "10":{"6а":{raw:"Иванова ИИ",names:["Иванова ИИ"],rooms:[]}},
    "11":{"6а":{raw:"Иванова ИИ",names:["Иванова ИИ"],rooms:[]}},
    "12":{"6а":{raw:"Иванова ИИ",names:["Иванова ИИ"],rooms:[]}}
  }}};
  state.subjects = {grid:{Пн:{
    "1":{"5а":{
      raw:"Алгебра, Геометрия (101, 102)",
      names:["Алгебра","Геометрия"], rooms:["101","102"]
    },"7а":{raw:"Биология",names:["Биология"],rooms:[]}},
    "6":{"6а":{raw:"Классный час",names:["Классный час"],rooms:[]}},
    "7":{"6а":{raw:"История (301)",names:["История"],rooms:["301"]}},
    "8":{"6а":{raw:"География",names:["География"],rooms:[]}},
    "9":{"6а":{raw:"Физика",names:["Физика"],rooms:[]}},
    "10":{"6а":{raw:"Русский",names:["Русский"],rooms:[]}},
    "11":{"6а":{raw:"Литература",names:["Литература"],rooms:[]}},
    "12":{"6а":{raw:"Биология",names:["Биология"],rooms:[]}}
  }}};
  state.secondShiftClasses = ["5а","6а"];
  state.bellSchedule = {shifts:{
    "1":{"Пн":{"1":{"start":"08:25","end":"09:05"},"6":{"start":"13:00","end":"13:40"},"7":{"start":"13:45","end":"14:25"}}},
    "2":{"Пн":{"1":{"start":"13:45","end":"14:25"},"2":{"start":"14:35","end":"15:15"},"3":{"start":"15:35","end":"16:15"},"4":{"start":"16:25","end":"17:05"},"5":{"start":"17:15","end":"17:55"},"6":{"start":"18:05","end":"18:45"}}}
  }};

  const ivan = teacherDayRows("Иванова ИИ","Пн").find(row=>row.cls==="5а");
  const petrova = teacherDayRows("Петрова ПП","Пн").find(row=>row.cls==="5а");
  const mappedRows = teacherDayRows("Иванова ИИ","Пн").filter(row=>row.cls==="6а");
  const allIvanRows = teacherDayRows("Иванова ИИ","Пн");
  const shiftEntries = classLessonEntries("6а","Пн");
  const week={innerHTML:""};
  renderWeekInto(week,"6а");
  state.curClass="6а"; state.classSel=0; renderClassBody();
  const classSchedule=$("classBody").innerHTML;
  collectRooms();
  const roomSlots = roomOccupancyAt(new Date(2026,10,9,13,50)).byRoom;
  globalThis.testResult = {
    ivan:{subj:ivan.subj,rooms:ivan.rooms,l:ivan.l,time:ivan.time},
    petrova:{subj:petrova.subj,rooms:petrova.rooms},
    mapped:mappedRows.map(row=>({l:row.l,subj:row.subj,time:row.time,shift:row.shift})),
    pre:shiftEntries[0],
    split:teacherShiftGroupHTML(allIvanRows,"Понедельник"),
    week:week.innerHTML,
    classSchedule,
    classCell:cellFor("5а","Пн","1"),
    rooms:state.rooms,
    occupancy:Object.values(roomSlots).map(info=>info.active.length),
    roomText:Object.values(roomSlots).flatMap(info=>info.active.flatMap(item=>item.who)),
    secondShiftTime:lessonTime("5а","Пн",1)
  };
  renderCurrentLesson();
`, context);

const result = context.testResult;
assert.equal(result.ivan.subj, "Алгебра");
assert.deepEqual(Array.from(result.ivan.rooms), ["101"]);
assert.equal(result.ivan.l, 1);
assert.equal(result.ivan.time, "13:45–14:25");
assert.equal(result.petrova.subj, "Геометрия");
assert.deepEqual(Array.from(result.petrova.rooms), ["102"]);
assert.deepEqual(Array.from(result.mapped.map(row=>row.l)), [1,2,3,4,5,6]);
assert.deepEqual(Array.from(result.mapped.map(row=>row.time)), ["13:45–14:25","14:35–15:15","15:35–16:15","16:25–17:05","17:15–17:55","18:05–18:45"]);
assert.equal(result.pre.lesson, 6);
assert.equal(result.pre.displayLesson, "КЧ");
assert.equal(result.pre.time, "13:00–13:40");
assert.match(result.classSchedule, /уроков: 7/);
assert.match(result.classSchedule, /13:45–14:25/);
assert.match(result.classSchedule, /18:05–18:45/);
assert.match(result.split, /Понедельник · 1-я смена/);
assert.match(result.split, /Понедельник · 2-я смена/);
assert.match(result.week, /<td>до смены<\/td>/);
assert.match(result.week, /18:05–18:45/);
assert.match(result.week, /class="mobile-week"/);
assert.match(result.week, /class="mobile-week-day"/);
assert.equal((result.classCell.match(/class="room-badge"/g) || []).length, 2);
assert.doesNotMatch(result.classCell, /\(101|\(102/);
assert.deepEqual(Array.from(result.rooms), ["101", "102", "301"]);
assert.deepEqual(Array.from(result.occupancy), [1, 1, 1]);
assert.ok(Array.from(result.roomText).every(text=>!/\(101|\(102|\(301/.test(text)));
// Ранний классный час и шестой урок не занимают кабинет одновременно.
vm.runInContext(`
  state.teachers.grid.Пн["6"]["6а"].rooms = ["401"];
  state.teachers.grid.Пн["12"]["6а"].rooms = ["402"];
  globalThis.beforeRooms = roomOccupancyAt(new Date(2026,10,9,13,20)).byRoom;
  globalThis.sixthRooms = roomOccupancyAt(new Date(2026,10,9,18,20)).byRoom;
  state.teachers.grid.Пн["6"]["6а"].rooms = [];
  state.teachers.grid.Пн["12"]["6а"].rooms = [];
`, context);
assert.equal(context.beforeRooms["401"].active.length, 1);
assert.equal(context.beforeRooms["402"].active.length, 0);
assert.equal(context.sixthRooms["401"].active.length, 0);
assert.equal(context.sixthRooms["402"].active.length, 1);
assert.equal(result.secondShiftTime, "13:45–14:25");
assert.match(element("currentLesson").innerHTML, /урок № 1/);
assert.match(element("currentLesson").innerHTML, /осталось 35 мин/);

// Во время пересечения расписаний двух смен показываются оба номера урока.
vm.runInContext(`
  Date = class extends FixedDate { constructor(...args){ args.length?super(...args):super(2026,10,9,13,50,0,0); } };
  renderCurrentLesson();
`, context);
assert.match(element("currentLesson").innerHTML, /№ 7 \(1-я смена\)/);
assert.match(element("currentLesson").innerHTML, /№ 1 \(2-я смена\)/);

// Конструктор явно помечает локальные номера, даже в разреженной сетке.
vm.runInContext(`
  state.teachers.numbering="local";
  state.subjects.numbering="local";
  state.teachers.grid.Пн["1"]["5а"].names=["Мария Ивановна"];
  collectTeachers();
  globalThis.localNumberingResult={global:classUsesGlobalShiftGrid("6а"),teachers:state.teacherNames};
  delete state.teachers.numbering; delete state.subjects.numbering;
`, context);
assert.equal(context.localNumberingResult.global, false);
assert.ok(context.localNumberingResult.teachers.includes("Мария Ивановна"));

// Выбор сворачивает список, а кнопка «Сменить» открывает его снова.
const classButton = {dataset: {cls: "6а"}};
const teacherButton = {dataset: {t: "Иванова ИИ"}};
element("classArea").querySelectorAll = selector => selector === "[data-cls]" ? [classButton] : [];
element("teacherChips").querySelectorAll = selector => selector === ".chip" ? [teacherButton] : [];
vm.runInContext(`state.teacherNames=["Иванова ИИ"]; renderClassArea(); renderTeacherArea();`, context);
classButton.onclick();
teacherButton.onclick();
assert.match(element("classArea").innerHTML, /mobile-selection "/);
assert.match(element("teacherArea").innerHTML, /mobile-selection "/);
assert.match(element("teacherArea").innerHTML, /Иванова ИИ/);
assert.match(element("classArea").innerHTML, /aria-expanded="false"/);
element("changeClass").onclick();
element("changeTeacher").onclick();
assert.match(element("classArea").innerHTML, /mobile-selection picker-open/);
assert.match(element("teacherArea").innerHTML, /mobile-selection picker-open/);
assert.match(element("teacherArea").innerHTML, /aria-expanded="true"/);

// Занятость кабинета зависит от фактического времени обеих смен.
vm.runInContext(`
  state.classes=["5а","6а","7а"];
  state.secondShiftClasses=["6а"];
  const cell=(name,rooms)=>({raw:name,names:[name],rooms});
  state.teachers={numbering:"local",grid:{Пн:{
    "1":{"5а":cell("Первая",["101","101"]),"6а":cell("Вторая",["101"])},
    "2":{"7а":cell("Пересечение",["101"])},
    "3":{"5а":cell("Без звонка",["102"])}
  }}};
  state.subjects={numbering:"local",grid:{Пн:{
    "1":{"5а":cell("Математика",["101"]),"6а":cell("История",["101"])},
    "2":{"7а":cell("Биология",["101"])},
    "3":{"5а":cell("Без звонка",["102"])}
  }}};
  state.bellSchedule={shifts:{"1":{"Пн":{"1":{"start":"08:00","end":"08:40"},"2":{"start":"13:50","end":"14:10"}}},"2":{"Пн":{"1":{"start":"13:45","end":"14:25"}}}}};
  state.rooms=["101","102"];
  globalThis.roomAt=(h,m)=>roomOccupancyAt(new Date(2026,10,9,h,m)).byRoom;
  globalThis.roomNow=[2026,10,9,8,40];
  Date=class extends FixedDate { constructor(...args){super(...(args.length?args:globalThis.roomNow));} };
  renderRooms();
`, context);
assert.equal(context.roomAt(7, 59)["101"].next.label, "08:00");
assert.deepEqual(Array.from(context.roomAt(8, 30)["101"].active, x=>x.cls), ["5а"]);
assert.equal(context.roomAt(8, 40)["101"].active.length, 0);
assert.equal(context.roomAt(8, 40)["101"].next.label, "13:45");
assert.deepEqual(Array.from(context.roomAt(13, 48)["101"].active, x=>x.cls), ["6а"]);
assert.deepEqual(Array.from(context.roomAt(13, 55)["101"].active, x=>x.cls), ["6а", "7а"]);
assert.equal(context.roomAt(14, 10)["101"].active.length, 1);
assert.equal(context.roomAt(14, 25)["101"].active.length, 0);
assert.equal(context.roomAt(14, 25)["101"].next, null);
assert.equal(context.roomAt(8, 30)["102"].unknown, true);
assert.match(element("roomsGrid").innerHTML, /Свободен до 13:45/);
assert.match(element("roomsGrid").innerHTML, /Нет данных о времени/);
vm.runInContext(`state.roomOnlyFree=true; renderRooms();`, context);
assert.doesNotMatch(element("roomsGrid").innerHTML, /Нет данных о времени/);
vm.runInContext(`state.roomOnlyFree=false; roomNow=[2026,10,9,14,25]; renderRooms();`, context);
assert.match(element("roomsGrid").innerHTML, /Свободен<\/div>/);
assert.doesNotMatch(element("roomsGrid").innerHTML, /Свободен до/);
vm.runInContext(`roomNow=[2026,10,15,10,0]; renderRooms();`, context);
assert.match(element("roomsSummary").innerHTML, /Воскресенье/);
assert.equal((element("roomsGrid").innerHTML.match(/Свободен<\/div>/g)||[]).length,2);

console.log("Frontend behavior OK: paired teachers, unique rooms, shift-specific times, live lesson countdown.");
