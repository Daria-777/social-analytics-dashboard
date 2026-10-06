// Pure formatting/time regressions. No DOM mutations, HTTP or credentials.
import fs from "node:fs";
import assert from "node:assert/strict";
const source = fs.readFileSync(
  new URL("../app/web/dashboard-core.js", import.meta.url),
  "utf8",
);
const core = await import(
  "data:text/javascript;base64," + Buffer.from(source).toString("base64")
);
// The initial timezone follows the browser/runtime; fixed expectations below
// must set their fixture timezone explicitly instead of relying on the host.
assert.equal(
  core.state.config.display_timezone,
  Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
);
core.state.config.display_timezone = "Europe/Moscow";
assert.equal(core.metric(4.1, "completion_rate"), "4,1");
assert.equal(core.metric(0.041, "share_rate"), "4,1%");
assert.equal(core.metric(null, "completion_rate"), "—");
assert.equal(core.metric(0, "views"), "0");
assert.equal(core.fmt(null), "—");
assert.equal(core.utc("2026-10-03T12:00"), "2026-10-03T09:00:00.000Z");
core.state.config.display_timezone = "Europe/Berlin";
assert.equal(core.utc("2026-07-03T12:00"), "2026-07-03T10:00:00.000Z");
assert.throws(() => core.utc("2026-03-29T02:30"));
console.log(
  "Frontend: completion vs ratio, NULL vs zero, timezone and DST passed",
);

// Browser-independent input fixture, exercising the same active list used by
// dashboard count/recent/table. All timestamps represent authoritative UTC times.
core.state.config.display_timezone = "Europe/Moscow";
const inputs = Object.fromEntries(
  Object.keys(core.filterMap)
    .concat(["from", "to"])
    .map((key) => ["filter-" + key, { value: "" }]),
);
inputs["comparison-group"] = { value: "hook_type" };
inputs["filter-platform"].value = "tiktok";
inputs["filter-source"].value = "tiktok_api";
inputs["filter-from"].value = inputs["filter-to"].value = "2026-10-01";
globalThis.document = { getElementById: (id) => inputs[id] };
core.state.content = [
  { id: "start", platform: "tiktok", published_at: "2026-09-30T21:00:00Z" },
  {
    id: "middle",
    platform: "tiktok",
    published_at: "2026-10-01T09:00:00.000Z",
  },
  {
    id: "end-without-ms",
    platform: "tiktok",
    published_at: "2026-10-01T20:59:59Z",
  },
  {
    id: "end-with-ms",
    platform: "tiktok",
    published_at: "2026-10-01T20:59:59.999Z",
  },
  {
    id: "before",
    platform: "tiktok",
    published_at: "2026-09-30T20:59:59.999Z",
  },
  { id: "after", platform: "tiktok", published_at: "2026-10-01T21:00:00Z" },
  { id: "null", platform: "tiktok", published_at: null },
  { id: "missing", platform: "tiktok" },
  { id: "invalid", platform: "tiktok", published_at: "invalid-date" },
];
assert.equal(core.query().get("date_from"), "2026-09-30T21:00:00.000Z");
assert.equal(core.query().get("date_to"), "2026-10-01T20:59:59.999Z");
assert.deepEqual(
  core.activeContent().map((c) => c.id),
  ["start", "middle", "end-without-ms", "end-with-ms"],
);
// Both representations of the exact starting timestamp are included.
core.state.content[0].published_at = "2026-09-30T21:00:00.000Z";
assert.equal(core.activeContent().length, 4);
inputs["filter-from"].value = inputs["filter-to"].value = "";
assert.equal(core.activeContent().length, 9); // Unknown timestamps remain visible without a date filter.
console.log(
  "Frontend: exact local-day boundaries, timestamp precision, missing/invalid timestamps passed",
);

for (const source of ["instagram_api", "tiktok_api"]) assert.equal(core.collectionMode(source), "automatic");
for (const source of ["instagram_ui", "tiktok_studio", "manual"]) assert.equal(core.collectionMode(source), "manual");
for (const source of [null, undefined, "", "future_provider", "confirmed", "estimated"]) assert.equal(core.collectionMode(source), "unknown");
console.log("Collection mode: API, UI/manual and unknown sources remain distinct from quality statuses");
