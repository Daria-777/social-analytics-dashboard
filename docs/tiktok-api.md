# TikTok Display API contract — checked 2026-10-03

Only official references below define the connector; Display API **v2**, not
Research API or Content Posting API. No publish/delete/follow/revoke endpoint.

## Reads and mapping

[User info](https://developers.tiktok.com/doc/tiktok-api-v2-get-user-info/):
GET https://open.tiktokapis.com/v2/user/info/. Identity is open_id (app-scoped),
not display_name. user.info.basic reads identity; user.info.profile reads username;
optional user.info.stats reads followers/following/likes/video_count. Username
validates the initial connection, configured open_id pins subsequent identity.
video_count stays raw: it is not a views counter.

[List videos](https://developers.tiktok.com/doc/tiktok-api-v2-video-list/):
POST https://open.tiktokapis.com/v2/video/list/ is a read, scope video.list.
Only public posts, descending create_time. max_count 20, has_more + integer cursor;
cursor is milliseconds, while publication timestamp is seconds. Repeated/missing
cursor aborts pagination; response URLs never drive requests.

[Video object](https://developers.tiktok.com/doc/tiktok-api-v2-video-object/):
id → platform_content_id; create_time → UTC published_at; duration → seconds;
video_description/title → caption; share_url → permalink. view_count/like_count/
comment_count/share_count → views/likes/comments/shares. Missing fields stay NULL.
Saves, unique viewers, profile visits, gained follows, watch time, completion,
retention, demographics and traffic shares are not supplied by this contract;
they require separate UI/manual observations. Do not promise creator retention.

## OAuth

[Login Kit Web](https://developers.tiktok.com/doc/login-kit-web/): register a web
app and exact static HTTPS redirect, no query/fragment. Authorization URL:
https://www.tiktok.com/v2/auth/authorize/, state is random/short-lived/single-use.
Requested read scopes: user.info.basic,user.info.profile,video.list,user.info.stats;
stats may be denied without losing the mandatory identity/video permissions.
Credentials remain server-side; no public callback server is created automatically.

[Token management](https://developers.tiktok.com/doc/oauth-user-access-token-management/):
POST https://open.tiktokapis.com/v2/oauth/token/, URL-encoded body; authorization_code
or refresh_token grants. Validate nonempty tokens, Bearer type, positive expiry,
identity and required scopes before atomic local storage. Access token initial
lifetime 24h, refresh 365d; honor returned expiries. Refresh token may rotate: save
both values together, never overwrite valid credentials on a bad response.
OAuth POST is not automatically retried. Legacy env mode requires manual refresh before expiry;
authorization loss requires owner login. Do not retry a single-use code.

## Errors/retries

[Errors](https://developers.tiktok.com/doc/tiktok-api-v2-error-handling/) identify
access_token_invalid, scope_not_authorized/scope_permission_missed,
rate_limit_exceeded and internal_error. Safe exceptions contain endpoint, operation,
status and allowlisted code; provider messages, URLs, token bodies are not logged.
Malformed successful envelopes are rejected. Analytics raw contains successful,
sanitzed source responses only, never OAuth/error responses.

[Rate limits](https://developers.tiktok.com/doc/tiktok-api-v2-rate-limit/):
limits depend on API/application. No assumed fixed throughput. Safe reads (including
video/list POST) retry at most twice on transport failure, 429 or 5xx, with
exponential backoff and Retry-After seconds/date. Delay above 60s aborts rather
than retrying too early. Authentication/permissions/invalid request do not retry.

## Owner setup: Web or Desktop

Web remains the default: register a static public HTTPS redirect, configure Web
Login Kit/Display API and read scopes, and run `.venv/bin/python -m
app.cli.tiktok_auth --mode web`. Paste the final redirect into the hidden prompt.
Web mode rejects HTTP and loopback redirects.

For the local Mac, configure **Desktop Login Kit** and the sandbox target user.
Register the exact callback, including port and trailing slash:

```dotenv
TIKTOK_OAUTH_MODE=desktop
TIKTOK_REDIRECT_URI=http://127.0.0.1:8765/tiktok/callback/
```

Save client key/secret privately in the ignored `.env`, then run on the **Mac host**:

```sh
.venv/bin/python -m app.cli.tiktok_auth --mode desktop --timeout 300
.venv/bin/python -m app.cli.tiktok_auth --mode desktop --refresh
```

The helper binds only IPv4 127.0.0.1 at the registered explicit port, before
printing the authorization URL. Open that URL and approve the owner account.
The callback must match the exact Host/path/state; it is consumed once and the
listener closes before token exchange. An occupied port aborts without fallback.
The absolute deadline also closes stalled connections. Cancellation, invalid
callback or token response leaves the previous `.env` unchanged. Retry starts a
fresh state/verifier. No code, verifier, token or callback query is logged.

This implementation supports HTTP loopback only, with a fixed explicit port;
localhost is accepted, but 127.0.0.1 avoids IPv6 resolution differences. TikTok's
reference also allows HTTPS and wildcard ports; this helper implements neither.
Do not run the Desktop helper inside Docker: its loopback would belong to the
container rather than the Mac browser.

Desktop PKCE uses a fresh cryptographic verifier (43–128 characters), SHA-256
**hex** challenge and S256; exchange sends `code_verifier`. The reference's Node
example incorrectly substitutes the verifier in `code_challenge`; the helper
follows the explicit hashing contract instead. Sources:
[Login Kit Desktop](https://developers.tiktok.com/doc/en/login-kit-desktop),
[access token management](https://developers.tiktok.com/doc/oauth-user-access-token-management).

Both modes request user.info.basic, user.info.profile, user.info.stats and
video.list. Basic/profile/video.list grants are required; stats is optional.
TikTok approval and availability of the requested products/scopes must be verified
in the actual developer UI. A filled form is not proof of saved/approved settings.
Successful exchange/refresh atomically saves tokens/open_id/scopes with mode 0600.
Refresh in legacy env mode is manual and may rotate both tokens; restart workers
afterward. The optional private-store mode below reloads tokens before collection.
No scheduler or collection is automatically started.

Public informational pages `/terms` and `/privacy` describe the current owner-only
read-only app. They are not legal certification or proof that TikTok accepts
localhost URLs; saving/approval in the developer UI remains a separate check.

## Read-only grant validation

Token responses contain a comma-separated `scope` string according to the official
[access token contract](https://developers.tiktok.com/docs/en/oauth-user-access-token-management).
Exchange, refresh and storage use the same guard: basic/profile/video.list are
required, stats is optional, and every grant must belong to these four read scopes.
Extra publish/unknown scopes, empty entries, duplicates and surrounding whitespace
are rejected, without trimming or silently discarding entries. Valid scope order
is preserved exactly in the recorded grant. Invalid responses never replace the
previous private env file; errors do not include credentials or provider messages.

## Opt-in private store and automatic renewal

Default remains legacy `.env` with manual refresh. Automatic renewal is implemented
but disabled. The official contract returns expiry seconds, verified scope string
and open_id; refresh may rotate the refresh token. The application uses returned
values rather than assuming fixed lifetimes.

After separately authorized owner OAuth, seed one ignored directory on the Mac:

```sh
.venv/bin/python -m app.cli.tiktok_auth --mode desktop \
  --credential-store .tiktok-credentials --confirm-owner
```

`--confirm-owner` explicitly confirms the account selected in consent is the
configured owner. The OAuth response supplies its open_id and verified read grants;
collection still compares the returned user open_id against that stored identity.
The token-only JSON contains both tokens, open_id, exact scopes, aware UTC issued_at,
returned expiry seconds, and verified owner/grant metadata. The helper never copies
`.env`, client secrets, API keys or DB credentials into this directory. The directory
is 0700 and files 0600, owned by the current process user; symlinks, permissive files,
malformed/unverified metadata and future issuance are rejected.

For host CLI workers, the selected private store and opt-in are explicit settings:

```dotenv
TIKTOK_CREDENTIAL_STORE=.tiktok-credentials
TIKTOK_AUTO_REFRESH_ENABLED=true
TIKTOK_REFRESH_SKEW_SECONDS=300
```

For containers a separate **unapplied opt-in** override is available (also with
compose.server.yaml). First approve a persistent private directory that Docker
can share, verify its guest-visible UID/GID, and agree the runtime permissions.
The actual local API remains UID 10001; this work does not activate the override.

```sh
# Configuration sketch; do not execute until directory/runtime choice is approved.
TIKTOK_CREDENTIAL_DIRECTORY=/absolute/approved/path/.tiktok-credentials \
TIKTOK_CREDENTIAL_UID='VERIFIED_GUEST_UID' TIKTOK_CREDENTIAL_GID='VERIFIED_GUEST_GID' \
  docker compose -p social-analytics -f compose.yaml -f compose.tiktok-credentials.yaml up -d
```

The override requires an already seeded directory and explicit directory/UID/GID
settings; missing values fail Compose validation. It mounts the entire private
directory into API/scheduler read-write, so atomic replacement is visible across
workers without recreate. A single-file bind mount would retain the old inode.
The isolated test directory under private temporary folders maps to UID/GID 0
inside this Docker Desktop guest. The Mac UID failed the private ownership check.
A separate Documents-directory bind probe timed out; its mapping/File Sharing has
not been verified. Do not extrapolate the temporary-directory result to every
persistent Mac path. On native Linux use the actual directory owner UID/GID.

UID 0 is only a separately approved container runtime option, not an automatic
fallback: root was used in isolated fake-token tests, never in the owner's API or
scheduler. The override drops capabilities, prevents new privileges, uses a
read-only root filesystem and a small noexec/nosuid tmpfs. Only the token directory
bind is writable. Do not relax 0700/0600 or the ownership check to make a mount work.
Client
key/secret remain in private runtime environment, not in the shared token store.
Selecting the override does not enable the scheduler or refresh by itself;
`TIKTOK_AUTO_REFRESH_ENABLED` defaults to false. These are setup examples, not
settings applied to the owner's deployment.

API, CLI and scheduled collection load the latest store before client creation.
With renewal enabled, expiry inside the configured skew window triggers one OAuth
POST under Unix flock. After acquiring the lock the worker reads again: another
worker may already have refreshed it. OAuth POST is not automatically retried.
Returned identity must match the stored owner, all grants must pass the same guard,
and rotated credentials replace the file atomically only after validation. Planner,
readiness and status do not invoke OAuth; dry-run collection does call provider APIs
and therefore can renew when explicitly enabled.

Explicit manual renewal of the store remains available with renewal disabled:

```sh
.venv/bin/python -m app.cli.tiktok_auth --credential-store .tiktok-credentials --refresh
```

A malformed/missing selected store does not silently fall back to `.env`. Invalid
refresh responses or a failed atomic write retain the previous file and fail safely.
TikTok renewal failure skips further TikTok jobs in that tick while Instagram jobs
continue; no token values/provider messages enter public status or run summaries.
Scheduled renewal failures record a failed CollectorRun with only a safe error
type and attempt/backoff metadata, so scheduler retry limits still apply. No
snapshot is created by renewal. Backend requests report a safe failure. Later
ticks may retry only after cooldown and below the configured attempt limit. The
latest renewal failure also gates other TikTok jobs, so a different daily/content
job cannot bypass the credential cooldown. At the limit the platform is paused
until new verified credentials are issued (manual renewal/owner reauthorization).
Failed jobs retain their own attempt limit; new jobs can proceed after recovery.

If the provider rotates successfully but persistence fails, the retained old refresh
token may no longer work: reauthorize the owner rather than assuming rollback at
the provider. Expired/revoked refresh tokens also require reauthorization. Actual
provider renewal and long-term unattended operation are not verified by mocked tests.

### Supported concurrency and Docker Desktop verification

Mac Darwin flock and this Docker Desktop Linux flock **did not coordinate** in an
actual simultaneous test. Mixed Mac + Docker renewal is unsupported. All concurrent
Docker renewal readers/writers (API, scheduler and manual refresh) must run inside
the same Docker kernel. Native host-only workers can share host flock.

When selecting Docker mode, set host-side `TIKTOK_RENEWAL_RUNTIME=docker` as well
as the private store path. The Compose override always sets this mode. The resolver rejects renewal of a Docker-selected store outside a Docker
container before any HTTP; Mac is always rejected for this mode. Mac OAuth
seed/reseed requires both `--confirm-owner` and `--confirm-workers-stopped`; stop
all credential workers before seeding, then start them. Those flags are operator
attestations; the helper does not automatically stop running services.

```sh
# Only after separately authorized OAuth; all Docker credential workers stopped.
.venv/bin/python -m app.cli.tiktok_auth --mode desktop \
  --credential-store /absolute/approved/path/.tiktok-credentials \
  --confirm-owner --confirm-workers-stopped
# Manual renewal from the same Docker kernel, after approved setup:
docker compose -p social-analytics -f compose.yaml -f compose.tiktok-credentials.yaml \
  exec -T api python -m app.cli.tiktok_auth --refresh
```

Isolated reproducible check (uses only fake credentials, network none, no database):

```sh
TEST_TIKTOK_DOCKER=1 .venv/bin/python -m pytest -q tests/test_tiktok_credentials_docker.py
```

It validates two independent Docker workers, one mocked refresh, directory bind
visibility after atomic replacement, and private file readability from the Mac
after rotation. Default suite skips this explicit Docker test. The real persistent
directory, provider OAuth/renewal and enabling a root opt-in runtime remain separate
owner decisions/checks. The prepared code does not change the owner's `.env`,
activate renewal/scheduler or launch a real collection.
