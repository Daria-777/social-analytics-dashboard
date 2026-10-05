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
