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
  state.classes = ["5а","6а"];
  state.teachers = {grid:{Пн:{"1":{"5а":{
    raw:"Иванова ИИ, Петрова ПП (101, 102, 101)",
    names:["Иванова ИИ","Петрова ПП"], rooms:["101","102","101"]
  }}}}};
  state.subjects = {grid:{Пн:{"1":{"5а":{
    raw:"Алгебра, Геометрия (101, 102)",
    names:["Алгебра","Геометрия"], rooms:["101","102"]
  }}}}};
  state.secondShiftClasses = ["5а"];
  state.bellSchedule = {shifts:{
    "1":{"Пн":{"1":{"start":"08:25","end":"09:05"},"7":{"start":"13:45","end":"14:25"}}},
    "2":{"Пн":{"1":{"start":"13:45","end":"14:25"}}}
  }};

  const ivan = teacherDayRows("Иванова ИИ","Пн")[0];
  const petrova = teacherDayRows("Петрова ПП","Пн")[0];
  collectRooms();
  const roomSlots = slotInfo("Пн", "1");
  globalThis.testResult = {
    ivan:{subj:ivan.subj,rooms:ivan.rooms},
    petrova:{subj:petrova.subj,rooms:petrova.rooms},
    classCell:cellFor("5а","Пн","1"),
    rooms:state.rooms,
    occupancy:Object.values(roomSlots).map(items=>items.length),
    secondShiftTime:lessonTime("5а","Пн",1)
  };
  renderCurrentLesson();
`, context);

const result = context.testResult;
assert.equal(result.ivan.subj, "Алгебра");
assert.deepEqual(Array.from(result.ivan.rooms), ["101"]);
assert.equal(result.petrova.subj, "Геометрия");
assert.deepEqual(Array.from(result.petrova.rooms), ["102"]);
assert.equal((result.classCell.match(/class="room-badge"/g) || []).length, 2);
assert.deepEqual(Array.from(result.rooms), ["101", "102"]);
assert.deepEqual(Array.from(result.occupancy), [1, 1]);
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

console.log("Frontend behavior OK: paired teachers, unique rooms, shift-specific times, live lesson countdown.");
