const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source=fs.readFileSync('frontend/js/mail-oauth-callback.js','utf8');
async function scenario(search,token){
  const result={textContent:''};let sent=null,cleaned=false;
  const context={URLSearchParams,location:{search,pathname:'/mail-oauth/callback'},history:{replaceState(){cleaned=true}},localStorage:{getItem:()=>token},document:{getElementById:()=>result},fetch:async(url,options)=>{sent={url,options};return {ok:true,json:async()=>({sender:'sender@yandex.ru'})}}};
  await vm.runInNewContext(source,context);
  return {result,sent,cleaned};
}
(async()=>{
  const good=await scenario('?code=secret-code&state=state-value','admin-token');
  assert.equal(good.cleaned,true);
  assert.equal(good.sent.url,'/api/admin/mail-oauth/complete');
  assert.deepEqual(JSON.parse(good.sent.options.body),{code:'secret-code',state:'state-value'});
  assert.match(good.result.textContent,/почта|Почта/);
  const noToken=await scenario('?code=secret-code&state=state-value','');
  assert.equal(noToken.cleaned,true);assert.equal(noToken.sent,null);
  const rejected=await scenario('?error=access_denied','admin-token');
  assert.equal(rejected.sent,null);assert.match(rejected.result.textContent,/отклонил/);
  console.log('OAuth callback UI OK');
})().catch(e=>{console.error(e);process.exitCode=1});
