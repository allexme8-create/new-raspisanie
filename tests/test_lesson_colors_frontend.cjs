const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const ctx={};vm.createContext(ctx);vm.runInContext(fs.readFileSync('frontend/js/lesson-colors.js','utf8'),ctx);
const color=s=>{ctx.name=s;return vm.runInContext('lessonColorClass([name])',ctx)};
assert.equal(color(' Физика  '),color('физика'));assert.notEqual(color('Физика'),color('Математика'));assert.equal(color(''), '');
const css=fs.readFileSync('frontend/css/style.css','utf8');for(let i=0;i<14;i++)assert.match(css,new RegExp(`\\.lesson-color-${i}\\{--lesson-color:`));assert.match(css,/\.overview-lesson\.changed\{background:#ddf4df/);assert.match(css,/\.overview-lesson\.removed\{background:#f9e1e1/);
console.log('Subject colors and change colors OK');
