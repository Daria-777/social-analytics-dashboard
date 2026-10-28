// Poll saved collector state only; social API calls belong to the scheduler.
export function createCollectionWatcher({canRefresh,currentHealth,readHealth,refresh}) {
  let pending=false;
  return async function checkForUpdates() {
    if (pending || !canRefresh()) return;
    pending=true;
    try {
      const latest=await readHealth();
      if (canRefresh() && JSON.stringify(latest)!==JSON.stringify(currentHealth())) await refresh();
    } catch {
      // Keep the current view during a temporary connection failure.
    } finally {
      pending=false;
    }
  };
}
