// All data and downloads are intercepted; no messages, providers or real DB.
import fs from 'node:fs';
import assert from 'node:assert/strict';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const web=new URL('../app/web/',import.meta.url);
const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
try {
 const page=await browser.newPage({viewport:{width:1366,height:850},timezoneId:'Europe/Moscow'});
 const errors=[],requests=[]; page.on('pageerror',e=>errors.push(e.message));
 let failSummary=false,failExport=false;
 await page.route('**/*',async route=>{
  const r=route.request(),u=new URL(r.url()),p=u.pathname;
  assert.equal(u.hostname,'127.0.0.1'); assert.equal(r.method(),'GET'); requests.push(p+u.search);
  if(p==='/dashboard'||p.startsWith('/dashboard/assets/')) {
   const name=p==='/dashboard'?'dashboard.html':p.split('/').at(-1);
   return route.fulfill({contentType:name.endsWith('.html')?'text/html':name.endsWith('.css')?'text/css':name.endsWith('.svg')?'image/svg+xml':'text/javascript',body:fs.readFileSync(new URL(name,web))});
  }
  if(p.startsWith('/reports/')) {
   assert.equal(u.searchParams.get('timezone'),'Europe/Moscow');
   assert.ok(['7','30'].includes(u.searchParams.get('days')));
   if(p==='/reports/summary') return route.fulfill({status:failSummary?503:200,json:failSummary?{detail:'Сводка временно недоступна'}:{text:'DASH - отчёт\nНакопленные просмотры: 20\nПодписчики: 0',period:'30.09.2026 - 06.10.2026'}});
   return route.fulfill({status:failExport?401:200,headers:{'Content-Disposition':`attachment; filename="dash-report-test.${p.endsWith('pdf')?'pdf':'xlsx'}"`},contentType:'application/octet-stream',body:failExport?'{}':'fixture-file'});
  }
  const payload=p==='/dashboard/config'?{}:p==='/collectors/status'?{instagram:{},tiktok:{}}:p==='/analytics/content-comparison'?{rows:[],groups:[]}:[];
  return route.fulfill({json:payload});
 });
 await page.goto('http://127.0.0.1:8770/dashboard');
 await page.locator('#workspace').waitFor();
 assert.equal(requests.some(p=>p.startsWith('/reports/')),false,'Report requests only on explicit open');
 const opener=page.locator('#report-menu > summary');
 await opener.focus(); await page.keyboard.press('Enter');
 await page.locator('#report-preview').getByText('Измерения:').waitFor();
 for(const format of ['pdf','xlsx']) {
  const downloadPromise=page.waitForEvent('download');
  await page.locator(`[data-report-format=${format}]`).click();
  const download=await downloadPromise;
  assert.equal(download.suggestedFilename(),`dash-report-test.${format}`);
 }
 const recipient=page.locator('#report-recipient'),link=page.locator('#report-telegram');
 await recipient.fill('@sample_user');
 const url=new URL(await link.getAttribute('href'));
 assert.equal(url.hostname,'t.me'); assert.equal(url.pathname,'/sample_user');
 assert.ok(url.searchParams.get('text').includes('Подписчики: 0'));
 for(const name of ['javascript:alert(1)','https://evil.invalid','@sample_user?start=x','../user']) {
  await recipient.fill(name); assert.equal(await link.getAttribute('href'),null);
 }
 await recipient.fill('@sample_user');
 await page.locator('#report-period').selectOption('30');
 await page.waitForFunction(()=>document.querySelector('#report-telegram').hasAttribute('href'));
 await page.keyboard.press('Escape'); assert.equal(await page.locator('#report-menu').evaluate(e=>e.open),false);
 assert.equal(await opener.evaluate(e=>e===document.activeElement),true);
 await opener.click(); await page.locator('#report-preview').getByText('Измерения:').waitFor();
 failExport=true;
 await page.locator('[data-report-format=pdf]').click();
 await page.locator('#report-error').getByText('Войдите снова').waitFor();
 assert.equal(await page.locator('[data-report-format=pdf]').isDisabled(),false);
 await page.keyboard.press('Escape'); failSummary=true;
 await opener.click(); await page.locator('#report-error').getByText('Не удалось подготовить сводку.').waitFor();
 assert.equal(await link.getAttribute('href'),null);
 for(const width of [390,320]) {
  await page.setViewportSize({width,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  const panel=await page.locator('.report-panel').boundingBox();
  assert.ok(panel.x>=0&&panel.x+panel.width<=width,`Panel fits ${width}`);
  for(const selector of ['#report-period','#report-recipient','[data-report-format=pdf]']) assert.ok((await page.locator(selector).boundingBox()).height>=44);
 }
 assert.deepEqual(errors,[]);
 console.log('Report downloads, period, recipient validation, keyboard, errors and mobile layout passed');
} finally { await browser.close(); }
