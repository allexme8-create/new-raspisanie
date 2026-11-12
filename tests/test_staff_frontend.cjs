const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('frontend/staff.html', 'utf8');
for (const id of ['forgotPassword','resetPasswordCard','resetRequestForm','resetConfirmForm','resetCode','resetEmail']) assert.ok(html.includes(`id="${id}"`));
const elements = new Map();
function element(id) {
  if (!elements.has(id)) {
    const classes = new Set();
    elements.set(id, {value:'',innerHTML:'',textContent:'',classList:{toggle(name,force){if(force)classes.add(name);else classes.delete(name)},contains(name){return classes.has(name)}},querySelector(){return {disabled:false}},querySelectorAll(){return []}});
  }
  return elements.get(id);
}
const requests=[];
const context={
  document:{getElementById:element,querySelectorAll:()=>[],hidden:false},
  location:{pathname:'/associate'},
  sessionStorage:{getItem:()=>null,setItem:()=>{},removeItem:()=>{}},
  fetch:async (url,options)=>{requests.push({url,body:JSON.parse(options.body)});return {ok:true,status:200,json:async()=>url.endsWith('/request')?{message:'Если учётная запись существует, письмо будет отправлено'}:{ok:true}}},
  setInterval:()=>{},console,
};
vm.createContext(context);
vm.runInContext(fs.readFileSync('frontend/js/staff.js','utf8'),context);
(async()=>{
  element('loginEmail').value='user@example.com';
  element('forgotPassword').onclick();
  assert.equal(element('resetEmail').value,'user@example.com');
  assert.equal(element('resetPasswordCard').classList.contains('hidden'),false);
  await element('resetRequestForm').onsubmit({preventDefault(){},currentTarget:element('resetRequestForm')});
  assert.equal(requests[0].url,'/api/staff/password-reset/request');
  assert.equal(requests[0].body.role,'associate');
  element('resetCode').value='code';
  element('resetNewPassword').value='long-password-value';
  element('resetRepeatPassword').value='different-value';
  await element('resetConfirmForm').onsubmit({preventDefault(){},currentTarget:element('resetConfirmForm')});
  assert.equal(requests.length,1);
  assert.match(element('resetMessage').innerHTML,/Пароли не совпадают/);
  element('resetRepeatPassword').value='long-password-value';
  await element('resetConfirmForm').onsubmit({preventDefault(){},currentTarget:element('resetConfirmForm')});
  assert.equal(requests[1].url,'/api/staff/password-reset/confirm');
  assert.equal(requests[1].body.code,'code');
  assert.equal(element('resetPasswordCard').classList.contains('hidden'),true);
  assert.equal(element('staffLoginCard').classList.contains('hidden'),false);
  assert.equal(element('resetCode').value,'');
  console.log('Staff password recovery UI OK');
})().catch(error=>{console.error(error);process.exitCode=1});
