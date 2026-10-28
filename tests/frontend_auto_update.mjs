import assert from 'node:assert/strict';
import {createCollectionWatcher} from '../app/web/dashboard-auto-update.js';
let visible=true,health={instagram:{last_success_at:'old'}},latest=health,reads=0,refreshes=0;
const poll=createCollectionWatcher({
  canRefresh:()=>visible,
  currentHealth:()=>health,
  readHealth:async()=>{reads++;return latest;},
  refresh:async()=>{refreshes++;health=latest;},
});
await poll();assert.equal(refreshes,0);
latest={instagram:{last_success_at:'new'}};
visible=false;await poll();assert.equal(reads,1);
visible=true;await poll();assert.equal(refreshes,1);
await poll();assert.equal(refreshes,1);
let release;
const blocked=createCollectionWatcher({canRefresh:()=>visible,currentHealth:()=>health,
  readHealth:()=>new Promise(resolve=>{release=resolve;}),refresh:async()=>{refreshes++;}});
const inFlight=blocked();await blocked();visible=false;release({tiktok:{last_success_at:'changed'}});await inFlight;
assert.equal(refreshes,1); // Editing/hidden state can change while request is in flight.
visible=true;
const unavailable=createCollectionWatcher({canRefresh:()=>true,currentHealth:()=>health,
  readHealth:async()=>{throw new Error('offline');},refresh:async()=>{refreshes++;}});
await unavailable();await unavailable();assert.equal(refreshes,1);
console.log('Auto-update: detects changed collection, skips hidden/editing state, serializes polling and tolerates offline');
