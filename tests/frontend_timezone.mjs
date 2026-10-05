// Entire browser surface is fixture-backed; no DB, credentials, collection or external HTTP.
import fs from 'node:fs';
import assert from 'node:assert/strict';
import path from 'node:path';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root=new URL('../app/web/',import.meta.url);
const policy=fs.readFileSync(new URL('../app/main.py',import.meta.url),'utf8').match(/Content-Security-Policy'\]="([^"]+)"/)[1];
const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHANNEL?{channel:process.env.PLAYWRIGHT_CHANNEL}:{})});
try {
 const page=await browser.newPage({viewport:{width:1200,height:850},hasTouch:true,timezoneId:process.env.TIMEZONE_TEST_ID||"America/New_York"}), errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 const contents=[
  {id:'one',platform:'instagram',content_type:'reel',published_at:'2026-10-01T10:00:00Z',caption:'Первый ролик: длинное название для проверки переноса и двух строк в списке публикаций без потери текста в истории',preview_url:'https://s.cdninstagram.com/one.svg',platform_content_id:'1'},
  {id:'two',platform:'instagram',content_type:'photo',published_at:'2026-10-02T10:00:00Z',caption:'Второй ролик',platform_content_id:'2'},
  {id:'three',platform:'tiktok',content_type:'video',published_at:'2026-10-03T10:00:00Z',caption:'Третий ролик',platform_content_id:'3'},
 ];
 const rows=contents.map((content,i)=>({content,snapshot:{id:'s'+i,source:i===2?'tiktok_api':'instagram_api',metric_scope:'lifetime',snapshot_status:'confirmed',snapshot_at:'2026-10-05T16:00:00Z',views:[25,0,null][i],likes:[2,null,1][i],shares:0},derived:{average_watch_pct:null}}));
 const account={id:'account',platform:'instagram',username:'fixture'};
 const posted=[]; let experiments=[]; let connected=true; let history=[rows[0].snapshot]; let retention=[];
 const summaries=Object.fromEntries(['views','average_watch_pct','completion_rate','share_rate','save_rate','profile_visit_rate','follow_conversion'].map(k=>[k,{n:k==='views'?2:0,mean:k==='views'?12.5:null,median:k==='views'?12.5:null,guardrail:'insufficient_sample'}]));
 await page.route('**/*',async route=>{
  const req=route.request(),url=new URL(req.url()),p=url.pathname;
  if(url.hostname==='s.cdninstagram.com') return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800"><rect width="600" height="800" fill="#067462"/></svg>'});
  assert.equal(url.hostname,'127.0.0.1','Unexpected external request');
  if(p.startsWith('/content/') && p.endsWith('/preview')) return route.fulfill({status:404,body:''});
  if(p==='/dashboard'||p.startsWith('/dashboard/assets/')) {
   const name=p==='/dashboard'?'dashboard.html':p.split('/').at(-1);
   return route.fulfill({headers:{'Content-Security-Policy':policy},contentType:name.endsWith('.html')?'text/html':name.endsWith('.css')?'text/css':name.endsWith('.svg')?'image/svg+xml':'text/javascript',body:fs.readFileSync(new URL(name,root))});
  }
  let payload;
  if(req.method()==='POST') {
   assert.ok(['/experiments','/manual-snapshots/import'].includes(p),'Unexpected mutation '+p);
   const body=req.postDataJSON(); posted.push({path:p,body});
   if(p==='/experiments') {payload={...body,id:'experiment',status:'draft'};experiments=[payload];} else payload={};
  } else if(p==='/dashboard/config') payload={display_timezone:'Europe/Moscow',instagram_ready:connected,tiktok_ready:connected};
  else if(p==='/accounts') payload=connected?[account]:[];
  else if(p==='/content') payload=contents;
  else if(p==='/experiments') payload=experiments;
  else if(p==='/accounts/account/history') payload=[{source:'instagram_api',metric_scope:'current',snapshot_status:'confirmed',snapshot_at:'2026-10-05T16:00:00Z',followers:0,following:2}];
  else if(p==='/collectors/status') payload={instagram:{last_success_at:'2026-10-05T16:00:00Z',last_status:'success'},tiktok:{last_status:'failed'}};
  else if(p==='/collectors/runs') payload=[];
  else if(p==='/analytics/content-comparison') {
   const selected=rows.filter(r=>contents.some(c=>c.id===r.content.id)&&(!url.searchParams.has('series'))&&(!url.searchParams.has('platform')||r.content.platform===url.searchParams.get('platform'))&&(!url.searchParams.has('source')||r.snapshot.source===url.searchParams.get('source')));
   payload={rows:selected,groups:selected.length?[{group:null,platform:'instagram',source:'instagram_api',metric_scope:'lifetime',snapshot_status:'confirmed',metrics:summaries,sample_size:2,comparable_period:true}]:[]};
  } else if(p==='/analytics/content/one') payload={content:contents[0],latest:[rows[0]]};
  else if(p==='/content/one/history') payload=history;
  else if(p==='/content/one/retention') payload=retention;
  else if(p==='/content/one/experiments') payload={links:[]};
  else if(p==='/analytics/content/one/velocity') payload={source:'instagram_api',points:[1,6,24,48,72].map(age=>({requested_age_hours:age,actual_age_hours:102,deviation_hours:102-age,views:25,snapshot_at:'2026-10-05T16:00:00Z'}))};
  else assert.fail('Unexpected fixture request '+p);
  await route.fulfill({json:payload});
 });

 await page.goto('http://127.0.0.1:8770/dashboard');
 await page.locator('#recent-content .publication-card').first().waitFor();
 const tz=process.env.TIMEZONE_TEST_ID||'America/New_York';
 const expected=tz==='Asia/Tokyo'?'06.10.2026, 01:00':'05.10.2026, 12:00';
 await page.locator('#last-update > p').getByText(expected,{exact:false}).waitFor();
 console.log('Automatic browser timezone verified: '+tz+' (server fixture remains Moscow)');
} finally {await browser.close();}
