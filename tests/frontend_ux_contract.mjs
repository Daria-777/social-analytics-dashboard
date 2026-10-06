import assert from 'node:assert/strict';
import { sortObservations, exactWindow, metricAvailability } from '../app/web/dashboard-presentation.js';
const make = (id, views, source='instagram_api') => ({content:{id,published_at:'2026-10-01T10:00:00Z'},snapshot:{views,source,metric_scope:'lifetime',snapshot_status:'confirmed'},derived:{}});
const input=[make('zero',0),make('unknown',null),make('high',20),make('other',999,'tiktok_api')];
assert.deepEqual(sortObservations(input,'views').map(r=>r.content.id),['high','zero','unknown','other']);
assert.equal(input[0].content.id,'zero');
assert.equal(exactWindow({requested_age_hours:1,actual_age_hours:102}),false);
assert.equal(exactWindow({requested_age_hours:1,actual_age_hours:1}),true);
assert.equal(exactWindow({requested_age_hours:1,actual_age_hours:null}),false);
assert.deepEqual(metricAvailability(input,'instagram_api','views'),{available:2,total:3});
assert.deepEqual(metricAvailability(input,'tiktok_api','completion_rate'),{available:0,total:1});
console.log('UX contract: source/period grouping, zero vs unknown, exact windows and observed metric availability passed');

const differentPeriod=make('range',500); differentPeriod.snapshot.metric_scope='range'; differentPeriod.snapshot.source_period_start='2026-10-01'; differentPeriod.snapshot.source_period_end='2026-10-02';
assert.deepEqual(sortObservations([...input,differentPeriod],'views').map(r=>r.content.id),['high','zero','unknown','other','range']);

// Mixed update times are never described as all platforms being fresh.
const { updateTimes } = await import('../app/web/dashboard-presentation.js');
assert.deepEqual(updateTimes([{platform:'instagram',at:'2026-10-01T10:00:00Z'},{platform:'tiktok',at:'2026-10-02T10:00:00Z'}]), { latest:'2026-10-02T10:00:00Z',mixed:true,unknown:false });
assert.deepEqual(updateTimes([{platform:'instagram',at:null}]), {latest:null,mixed:false,unknown:true});
const { chartGroups, historyPoints } = await import('../app/web/dashboard-presentation.js');
const quality=make('estimate',5); quality.snapshot.snapshot_status='estimated';
assert.equal(chartGroups([...input,quality,differentPeriod]).length,4);
assert.equal(chartGroups(input)[0][1][0].snapshot.views,0);
assert.equal(historyPoints({published_at:'2026-10-01T10:00:00Z'},[{snapshot_at:'2026-10-01T11:00:00Z',views:0},{snapshot_at:'2026-10-01T12:00:00Z',views:null}]).length,1);
assert.deepEqual(historyPoints({published_at:'2026-10-01T10:00:00Z'},[
 {snapshot_at:'2026-10-01T09:00:00Z',views:10},
 {snapshot_at:'invalid',views:10},
 {snapshot_at:'2026-10-01T11:00:00Z',views:-1},
 {snapshot_at:'2026-10-01T12:00:00Z',views:'25'},
]).map(s=>[s.age,s.views]),[[2,'25']]);
console.log('Chart contract: separate quality/platform/period groups, real zero and invalid/missing history points passed');

const { previewURL } = await import('../app/web/dashboard-preview.js');
const cover = 'https://p16-common-sign.tiktokcdn-eu.com/a.image?refresh_token=ab12cd34&x-expires=4000000000&x-signature=a%2Fb';
assert.equal(previewURL(cover),cover);
for (const bad of [cover.replace('ab12cd34','rft.secret'),cover.replace('tiktokcdn-eu.com','cdninstagram.com'),cover+'&access_token=secret',cover+'&refresh_token=ab12cd34']) assert.equal(previewURL(bad),null);
console.log('TikTok CDN marker allowed only on signed provider URLs; OAuth query credentials rejected');

const {accountTrend}=await import('../app/web/dashboard-presentation.js');
const a=(snapshot_at,followers,extra={})=>({source:'instagram_api',metric_scope:'current',snapshot_status:'confirmed',snapshot_at,followers,...extra});
const early=a('2026-10-01T10:00:00Z',0), late=a('2026-10-02T10:00:00Z',2);
assert.equal(accountTrend([late,early],late).delta,2);
assert.equal(accountTrend([early],early).delta,null);
assert.equal(accountTrend([early,late,a('2026-10-03T10:00:00Z',null)],a('2026-10-03T10:00:00Z',null)).delta,null);
assert.equal(accountTrend([early,{...late,source:'instagram_ui'}],early).points.length,1);
assert.equal(accountTrend([early,{...late,snapshot_status:'estimated'}],early).points.length,1);
assert.equal(accountTrend([early,{...late,metric_scope:'range'}],early).points.length,1);
assert.equal(accountTrend([early,late,{...late,followers:3}],late).delta,null);
assert.equal(accountTrend([early,late,{...late,followers:2}],late).points.length,2);
assert.equal(accountTrend([late,early],early).delta,null);
assert.equal(accountTrend([late,{...early,followers:4}],late).delta,-2);
console.log('Account overview: actual comparable counts, zero/unknown, duplicate timestamps and distinct sources/quality verified');

const {accountWeeks}=await import('../app/web/dashboard-presentation.js');
const weekly=(rows,tz='Europe/Moscow',now='2026-10-06T12:00:00Z')=>accountWeeks(accountTrend(rows,rows.at(-1)).points,tz,new Date(now));
const weeklyInput=[a('2026-09-14T10:00:00Z',3),a('2026-09-21T10:00:00Z',0),a('2026-10-05T10:00:00Z',1),a('2026-10-06T10:00:00Z',2)];
assert.deepEqual(weekly(weeklyInput).map(w=>[w.start,w.end,w.value,w.current]),[
 ['2026-09-14','2026-09-20',3,false],['2026-09-21','2026-09-27',0,false],
 ['2026-09-28','2026-10-04',null,false],['2026-10-05','2026-10-11',2,true]
]);
assert.equal(weekly([a('2026-10-05T10:00:00Z',3),a('2026-10-06T10:00:00Z',null)])[0].value,3);
assert.equal(weekly([a('2026-10-04T22:30:00Z',1)])[0].start,'2026-10-05');
assert.equal(weekly([a('2026-10-04T22:30:00Z',1)],'America/New_York')[0].start,'2026-09-28');
assert.equal(weekly([a('2027-01-01T10:00:00Z',1)])[0].start,'2026-12-28');
const dst=[a('2026-03-02T10:00:00Z',5),a('2026-03-09T10:00:00Z',4)];
assert.deepEqual(weekly(dst,'America/New_York').map(w=>w.start),['2026-03-02','2026-03-09']);
const following=[a('2026-10-01T10:00:00Z',0,{following:10}),a('2026-10-02T10:00:00Z',2,{following:8})];
assert.equal(accountTrend(following,following.at(-1),'following').delta,-2);
assert.equal(accountWeeks(accountTrend(following,following.at(-1),'following').points,'UTC',new Date('2026-10-06'),'following')[0].value,8);
assert.deepEqual(accountWeeks([],'UTC'),[]);
console.log('Weekly account history: last actual observation, gaps vs zero, timezone, DST, year boundary and metric selection passed');

const {accountOverview}=await import('../app/web/dashboard-presentation.js');
const manual=a('2026-10-06T12:00:00Z',999,{source:'instagram_ui'});
const range=a('2026-10-06T13:00:00Z',null,{metric_scope:'range',source_period_start:'2026-10-01',source_period_end:'2026-10-02'});
const main=a('2026-10-06T10:00:00Z',2);
const compact=accountOverview([early,main,manual,range,{...range,snapshot_at:'2026-10-05T13:00:00Z'}],'instagram');
assert.equal(compact.primary,main);
assert.equal(compact.additional.length,2);
assert.equal(compact.additional[0],range);
assert.equal(accountOverview([manual],'instagram').primary,manual);
assert.equal(accountOverview([range],'instagram').primary,null);
assert.deepEqual(accountOverview([],'instagram'),{primary:null,additional:[]});
assert.deepEqual(weekly(weeklyInput).at(-1).change,{delta:1,from:'2026-10-05T10:00:00Z',to:'2026-10-06T10:00:00Z'});
assert.equal(weekly(weeklyInput)[0].change,null);
console.log('Compact overview: one API summary, other periods/sources preserved separately, observed change intervals verified');

const {accountDailyChanges}=await import('../app/web/dashboard-presentation.js');
const daily=(history,tz='Europe/Moscow')=>accountDailyChanges(history,history.at(-1),tz);
const day4=a('2026-10-04T16:00:00Z',10,{following:5}),day5=a('2026-10-05T16:00:00Z',13,{following:4}),day6=a('2026-10-06T16:00:00Z',12,{following:6});
assert.deepEqual(daily([day4,day5,day6]).map(r=>[r.start,r.end,r.values.followers,r.values.following]),[['2026-10-06','2026-10-06',-1,2],['2026-10-05','2026-10-05',3,-1],['2026-10-04','2026-10-04',undefined,undefined]]);
assert.equal(daily([day4,a('2026-10-05T10:00:00Z',11),a('2026-10-05T17:00:00Z',14)])[0].values.followers,4);
const gap=daily([day4,a('2026-10-07T16:00:00Z',13)])[0];
assert.deepEqual([gap.start,gap.end,gap.values.followers],['2026-10-05','2026-10-07',3]);
const missing=daily([day4,a('2026-10-05T16:00:00Z',null),a('2026-10-06T16:00:00Z',13)]);
assert.deepEqual([missing[0].start,missing[0].end,missing[0].values.followers],['2026-10-05','2026-10-06',3]);
assert.equal(daily([day4,a('2026-10-05T16:00:00Z',10)])[0].values.followers,0);
assert.equal(daily([a('2026-10-04T16:00:00Z',0),a('2026-10-05T16:00:00Z',3)])[0].values.followers,3);
assert.equal(daily([day4,day5,{...day5,followers:15}])[0].values.followers,undefined);
assert.equal(daily([day4,{...day5,followers:''}])[0].values.followers,undefined);
assert.equal(accountDailyChanges([day4,{...day5,source:'instagram_ui'},day6],day6,'UTC')[0].values.followers,2);
assert.deepEqual(accountDailyChanges([day4,{...day5,metric_scope:'range'}],{...day5,metric_scope:'range'},'UTC'),[]);
assert.equal(daily([a('2026-10-04T22:30:00Z',10),a('2026-10-05T22:30:00Z',13)])[0].end,'2026-10-06');
assert.equal(daily([a('2026-10-04T22:30:00Z',10),a('2026-10-05T22:30:00Z',13)],'America/New_York')[0].end,'2026-10-05');
const spring=daily([a('2026-03-07T17:00:00Z',10),a('2026-03-08T16:00:00Z',13)],'America/New_York')[0];
assert.equal(spring.start,spring.end);assert.equal(spring.values.followers,3);
console.log('Daily changes: signed day-end differences, intraday deduplication, baselines, unknown/zero, gaps, conflicts, source separation and DST passed');
