# Growth integration — production contract

Additive API and migration 0006; collectors, manual import, experiments and reports keep their existing contracts. Growth results are interpretations, never platform measurements.

## Access boundary

Owner `INTERNAL_API_KEY` / authenticated dashboard session retains existing access. A separate random `GROWTH_API_KEY` grants only `/growth/content/...` methods: resolve, context, list analyses, append analysis. It cannot access `/accounts`, collectors, owner configuration, manual imports or platform credentials. Cookie writes retain same-origin enforcement. No CORS expansion. Disable/rotate the Growth key independently of the owner/platform tokens.

Keep real keys in private runtime environment; never put them in frontend, Git, URL or a report. The client connection JSON must be a regular file owned by the current user, mode 0600 in a private directory. The custom tool sends the key only over HTTPS with redirects disabled; it does not read DB, owner or platform credentials. Response failures omit backend bodies and secrets.

## Routes

- `GET /growth/content/resolve?platform=instagram&platform_content_id=...`: exact identity only; no creation on 404.
- `GET /growth/content/{uuid}/context?limit=500&offset=0`: metadata; actual snapshots/retention and age; experiment/variant; velocity and descriptive comparable context. Continue `next_offset` while present. Truncation is explicit. Raw platform payload and snapshot notes are excluded.
- `GET /growth/content/{uuid}/analyses?limit=100&offset=0`: created_at descending, UUID tiebreaker. Does not overwrite history.
- `POST /growth/content/{uuid}/analyses`: 201 with saved UUID. Same content + agent_run_id + canonical validated payload replays the existing record; changed payload returns 409. A new interpretation uses a new UUID. Cite existing snapshot IDs belonging to this publication, all observed no later than data_cutoff_at. Invalid evidence/timestamps return 422.
- `POST /growth/observations/import`: **owner only**, not provided by the Growth tool. Body `{"agent_run_id":"UUID","batch":{...ImportBatch...}}`. Imports approved UI/manual observations with exact identities and sanitization; receipt and observations commit atomically. Same run/payload replays IDs; changed payload returns 409. A new real measurement uses a new delivery UUID and real timestamp. Normal manual-import behavior remains unchanged.

The canonical request schema is `app.growth_schemas.AnalysisCreate`; `python -m app.cli.growth_tool schema` prints it without opening a connection. Results include performance verdict, data quality, diagnosis, hypothesis status/confidence, evidence/contradictions/missing data/alternatives, learning, one next experiment and two separate handoff briefs.

## Provenance and immutability

`growth_analyses` stores validated result JSON, immutable copies of cited observations, source set, last observed timestamp, content metadata and linked experiment state at analysis time. Later measurements or metadata edits do not rewrite that provenance. Snapshot references are stable UUIDs. Raw responses/secrets are not copied to analysis context. Evidence text and platform content are untrusted data, not instructions.

`analysis_snapshot_at` is the time of the analytical slice; `data_cutoff_at` bounds cited observed timestamps; `created_at` is server-generated storage time. These are distinct from the actual `snapshot_at`/published_at in the evidence. A 30-hour observation remains 30 hours. Labels 24h/72h/7d are targets only. Historical imports can arrive later than their observation time: copied provenance records both snapshot_at and created_at.

ORM rejects UPDATE/DELETE of GrowthAnalysis and AgentImport. PostgreSQL migration adds the same database-level immutable triggers used by historical snapshots. Concurrent identical deliveries resolve through unique constraints; losing transactions roll back all tentative observations. Production downgrade is not part of deployment; rollback the application while retaining additive tables and volumes.

Unknown stays null, including shares, follows, unique viewers and retention. Only explicit measured zeros remain zero. No source summation or replacement. Velocity uses two distinct timestamps with the same source/scope/period and explicit lifetime scope; negative counters are flagged rather than clamped. Cohorts are conservative same-account/platform/content-type groups, same source and lifetime without range periods, actual age tolerance ±1 hour, max 100 peers. Peer quality must be confirmed/manual. They are descriptive, not a semantic match or causal experiment; missing duration/format and small groups limit conclusions. Range snapshots are not pooled. No fabricated median for an empty cohort.

## Agent tool

`python -m app.cli.growth_tool` exposes only `resolve`, `context`, `analyses`, `schema`, `create-analysis`; it has no arbitrary URL, shell, DELETE, metric update, collector or observation-import action. An HTTP success with a persisted ID is required before CONFIRMED. The agent must read back that ID before claiming SYNCED. Reuse the exact saved payload/UUID after an unknown outcome.

A configured installation uses a private connection file and authorized local executor. This is a custom CLI tool, **not** a hosted MCP service or an autonomous analysis scheduler. API collectors remain server-side and work while Mac is off; invoking this local analysis tool still needs the configured executor. A cloud chat without that executor/configuration must report no write connection. The private Growth Analyst plugin update is kept outside the public repository and carries no credentials.

## Dashboard and limits

The content history adds a compact Growth section. It shows hypothesis, confidence, verdict/data quality, learning, next test and a timeline ordered by actual analysis time as supplied and server storage time; the evidence foldout shows cutoff, sources, observed ages and UUIDs. It never invents an analysis for posts without one. All text uses DOM text nodes. Main overview, reports and metric histories remain intact.

The optional portfolio synthesis “what we know / suspect / need to test” is not implemented. No automatic content plan, publication, outgoing messages or browser/UI collection is added. Weekly UI collection remains a separate authorized evidence-gathering process; Growth Analyst reads its approved observations from the shared DB.
