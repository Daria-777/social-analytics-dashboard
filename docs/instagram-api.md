# Instagram connector contract — Phase 3

Проверено 03.10.2026 по официальной документации Meta. Используется Instagram API
with Instagram Login, явно versioned `v26.0`. Не используется Basic Display или
Facebook Login. Professional account (Business/Creator) не требует Facebook Page.

## Официальные источники

- [Business Login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login/)
- [Get started](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/get-started/)
- [Insights guide](https://developers.facebook.com/docs/instagram-platform/insights/)
- [Account Insights reference](https://developers.facebook.com/documentation/instagram-platform/api-reference/instagram-user/insights)
- [Media Insights reference](https://developers.facebook.com/docs/instagram-platform/reference/instagram-media/insights/)
- [Media reference](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media)
- [Graph changelog](https://developers.facebook.com/docs/graph-api/changelog/)

Веб-инструмент получал 429/login page, поэтому страницы прочитаны прямыми HTTPS
запросами. Reference подтверждает v26.0. Контракт не заимствован из блогов.
Guide Insights содержит устаревшие примеры impressions; endpoint reference
указывает их deprecation, поэтому connector их не запрашивает.

## Авторизация

Минимальные scopes: `instagram_business_basic`, `instagram_business_manage_insights`.
OAuth helper/connector не запрашивают publish/comments/messages permissions.
Это утверждение о коде, а не гарантия scope набора Meta **Generate token**.
Instagram App ID и Secret берутся из Instagram business login settings, не из
случайного Facebook app ID. Redirect URI должен точно совпадать с зарегистрированным
публичным HTTPS URI. State одноразовый, случайный, проверяется перед token exchange.

| Операция | Endpoint |
|---|---|
| Authorization code | `https://www.instagram.com/oauth/authorize` |
| Code exchange, POST form | `https://api.instagram.com/oauth/access_token` |
| Long-lived exchange, GET | `https://graph.instagram.com/access_token` |
| Refresh, GET | `https://graph.instagram.com/refresh_access_token` |
| Account identity/metadata | `GET https://graph.instagram.com/v26.0/me` |
| Media, cursor pagination | `GET /v26.0/{user_id}/media` |
| Media insights | `GET /v26.0/{media_id}/insights` |
| Account insights | `GET /v26.0/{user_id}/insights` |

Code действует один час и одноразовый. Business-login short-lived token действует
один час; long-lived — 60 дней. Refresh требует неистёкший long-lived token старше
24 часов и basic permission. Автоматического refresh scheduler нет. OAuth secrets
передаются только сервером, ответы token exchange не входят в analytics payload.

## Проверка запрошенных и выданных прав

Не смешивайте permissions в настройках Meta app, `scope` authorization URL,
права на consent screen и **фактически выданный grant**. Generate token — официальный
bootstrap, но Get Started не обещает минимальный read-only scope для каждого
приложения. В отчёте onboarding этого проекта зафиксирована ссылка с basic + insights +
messages + comments + publish; flow остановлен до входа/consent. Это наблюдение
конкретного onboarding, а не утверждение о всех Meta apps.

До выдачи доступа оставляйте только `instagram_business_basic` и
`instagram_business_manage_insights`. Если UI позволяет, отключите лишние права
и проверьте итоговый consent. Если исключить messages/comments/publish нельзя,
не завершайте Generate token: используйте существующий OAuth helper с двумя scopes
и точным зарегистрированным публичным HTTPS redirect. Не расширяйте app permissions
для устранения OAuth ошибки и не сохраняйте заведомо избыточный token в `.env`.

Подтверждённый официальный способ получить список grant **в code flow** — поле
`permissions` ответа POST `https://api.instagram.com/oauth/access_token` при обмене
authorization code. [Business Login](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/business-login)
описывает этот ответ как token, user_id и выданные пользователем permissions.
Текущий helper требует точного набора двух read permissions, отклоняет дополнительные
или некорректные permissions до long-lived exchange и записи `.env`. Успешный code
flow сохраняет проверенный список в `INSTAGRAM_GRANTED_SCOPES` вместе с токеном.
Refresh сохраняет этот список, но не выполняет повторную introspection. Метаданные
старого/manual token не становятся проверенными автоматически.
Новый OAuth запрос с двумя scopes сам по себе не доказывает отзыв ранее выданных прав.

Для **уже выданного manual/dashboard token** отдельный поддерживаемый Instagram-Login
endpoint introspection/scopes в изученных официальных references не подтверждён.
Это ограничение проверки, а не утверждение, что такого способа нигде не существует.
Не переносите Facebook Login `/debug_token`, `/me/permissions` или параметр
`fields=permissions` на graph.instagram.com без подходящей официальной reference.
Никакие предполагаемые endpoints в connector не добавлены и не вызывались.

[Get Started](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/get-started)
подтверждает dashboard bootstrap и срок 60 дней. [Access Token reference](https://developers.facebook.com/documentation/instagram-platform/reference/access_token)
для long-lived exchange перечисляет только access_token, token_type и expires_in —
эта операция не возвращает документированный grant inventory. [/me reference](https://developers.facebook.com/documentation/instagram-platform/reference/me)
описывает разрешение identity пользователя по token. `/me`/успешный dry run не доказывают
отсутствие прав публикации, сообщений или комментариев; opaque token не следует
считать локально проверяемым списком scopes. Manual bootstrap с неизвестным grant
остаётся непроверенным onboarding, scheduler/collection до его проверки не включают.

Официальные страницы перепроверены 03.10.2026: web reader возвращал login/429;
публичные HTML Business Login, Get Started, access_token и /me прочитаны напрямую,
без авторизации, .env или запросов к реальному Instagram API. Отдельная предполагаемая
permissions reference не предоставила подтверждения контракта. Реальный token
пока отсутствует; выданные scopes конкретного аккаунта не проверялись.

## Identity и media

`/me` запрашивает `user_id,username,account_type,followers_count,follows_count`.
`user_id` — authoritative Instagram professional account ID; `id` может быть
app-scoped и не подменяет его. Ответы flat и single-item `data` принимаются,
неоднозначные multi-item структуры отклоняются.

Media fields: `id,media_type,caption,permalink,timestamp`. Duration не запрашивается:
не найдена документированная длительность самого media для этого flow. Упомянутое
в reference `duration_in_seconds` относится к copyright match, а не длине ролика.
Caption и duration остаются nullable.

**Ограничение типов:** current Media reference помечает `media_product_type` как
Facebook-Login-only. Connector Instagram Login его не запрашивает. IMAGE → photo,
CAROUSEL_ALBUM → carousel, VIDEO → video. Если authoritative response сам содержит
REELS/STORY product type, mapper использует его. Caption/permalink не используются
для распознавания reels. Для VIDEO без product type запрашивается только общая
поддерживаемая группа FEED/REELS; follows/profile metrics и reel-only metrics не
угадываются.

## Metrics

| Metric | Account/media | Internal field | Policy |
|---|---|---|---|
| views | account range / media lifetime | views | Не равно impressions или plays; без fallback |
| reach | account range / media lifetime | reach (новое) | Estimated; unique_viewers остаётся NULL |
| followers_count / follows_count | account current | followers / following | Отдельный current snapshot |
| likes/comments/shares | account range / media lifetime | одноимённые | Без подмены metadata counters |
| saves | account range | saves | account API name |
| saved | media lifetime | saves | media API name |
| profile_activity | feed media | profile_activity (новое) | Не равно visits; aggregate, без breakdown |
| profile_visits | feed media | profile_visits | Отдельная metric |
| follows | feed media | followers_gained | Только явная media insight, не delta followers |
| ig_reels_avg_watch_time / ig_reels_video_view_total_time | REELS | raw-only | Reference не подтверждает единицу времени; conversion в seconds не включён |
| reels_skip_rate | REELS only | Не реализована / не запрашивается | Estimated, in development; доля initial views с пропуском первых 3 секунд. Требует достоверной API-идентификации REELS; доступность зависит от API и media product, одного VIDEO или вручную сохранённого REEL недостаточно. Не completion и не retention curve |
| profile_views | account | NULL | Не присутствует в текущей Interaction Metrics table, не запрашивается |
| completion / drop-off / retention curve | account/media | NULL | Не представлены в выбранном официальном контракте |
| total_views/total_likes/total_comments | media | NULL | Facebook-Login-only; не суммируются с organic metrics |
| impressions / plays | account/media | NULL | Не используются как alias views |

Account metrics запрашиваются отдельно с `period=day,metric_type=total_value`,
явным since/until (предыдущие завершённые UTC сутки, inclusive end 23:59:59).
Они образуют отдельный range snapshot. Media insights имеют lifetime semantics.
У каждого snapshot есть `metric_scope`; account current и account range не смешаны.
Для current подтверждаются только фактически возвращённые `/me` counters:
оба отсутствуют/NULL → `unavailable`, оба поля остаются NULL; одно доступно →
`confirmed` для доступного значения, второе NULL; реальные нули → `confirmed`.
`confirmed` не означает полноту всех nullable полей. Отсутствие optional counters
само по себе не является ошибкой collection и не переводит run в failed/partial.
Сохранённые ранее snapshots и их статусы не исправляются задним числом.

Неоднозначный VIDEO без известного API product сохраняет прежний REEL/STORY;
новый объект может иметь VIDEO. Явный REELS/STORY/FEED уточняет сохранённый тип.
Capability для запросов insights берётся из свежего API DTO, независимо от
сохранённого (в том числе ручного) content_type.
Raw хранит параметры диапазона и успешные ответы. Для reach в notes сохраняется
estimated semantics; статус снимка estimated при наличии reach.

Каждая metric запрашивается отдельно. Unsupported metric оставляет соответствующее
поле NULL, помечает run partial и не записывает error response в raw analytics.
Пустой data не превращается в 0. Несколько series values не суммируются произвольно.
Watch-time raw сохраняется только при authoritative REELS type; normalized seconds
не заполняются до подтверждения единиц. Completion не выводится из watch time.

## API ограничения

Insights могут запаздывать до 48 часов. Данные аккаунта ограничены историческим
окном, часть metrics требует minimum audience; follower_count/online_followers и
некоторые demographics требуют 100 followers/engagements. Media insights не
предназначены для carousel children. Stories не обнаруживаются через отдельный
stories endpoint в этой фазе. Insights webhook для Instagram Login не поддержан.
Media counters organic и account metrics с ad coverage имеют разные semantics.

Нет фиксированного предположения о rate limit. GET reads: максимум 2 retries,
exponential backoff, Retry-After (seconds/HTTP-date). Ожидание >60 секунд прекращает
текущий запрос безопасной ошибкой вместо раннего retry. Auth exchanges не retries.
Pagination использует cursors.after при наличии next; next URL не вызывается,
чтобы не передавать token произвольному хосту. Configurable max pages; достижение
лимита даёт partial run, а не молчаливое объявление полного discovery.

## Idempotency и partial collection

Run UUID задаёт job identity. Повтор с тем же UUID не создаёт новый набор снимков.
Completed run возвращает сохранённый summary. Failed/partial можно повторить,
успешные snapshots пропускаются. Уже сохранённые partial snapshots тоже immutable:
их отсутствующие поля остаются NULL, а прежние failures сохраняют статус partial.
Retry добирает только отсутствующие snapshots; новый UUID нужен для нового измерения. Running run не запускается конкурентно снова.
Новый UUID означает новое реальное измерение, даже при том же snapshot_at.
Snapshot uniqueness относится только к non-NULL collection_run_id и сохраняет
возможность ручных измерений из разных источников.

Run reservation и каждый успешный account/media объект фиксируются отдельными
транзакциями. Ошибка одной media не откатывает остальные. Metadata обновляется
без изменения tags; manually-created content не удаляется и не сливается по caption.
Случайный crash оставляет running run для явного operator recovery; time-based
автоматического сброса и scheduler нет. Dry run делает только API reads + mapping,
не открывает DB и не создаёт даже CollectorRun.

`Snapshot.snapshot_at` — время получения account metadata либо завершения insight
collection для объекта. Metrics читаются последовательно и не являются атомарным
одновременным измерением; их период и raw responses сохраняются явно.

## Временный локальный callback для Instagram

Подготовлен отдельный one-shot HTTP listener; HTTPS обеспечивает отдельно
согласованный tunnel. Сейчас tunnel не запускается. Это не обход отклонённого
Generate token consent с publish/comments/messages: helper запрашивает только
`instagram_business_basic,instagram_business_manage_insights` и отклоняет
дополнительные grants в code-exchange response.

Схема для последующей проверки и отдельного согласования:

1. Проверить свободный выделенный порт 8766. Не использовать API/dashboard 8000.
2. После разрешения на публичный временный callback установить официальный
   tunnel client и запустить tunnel **только** к `http://127.0.0.1:8766`.
   Кандидат команды для проверки по `cloudflared tunnel --help` установленной версии:

   ```sh
   cloudflared tunnel --url http://127.0.0.1:8766 --http-host-header 127.0.0.1:8766
   ```

   Tunnel должен переписывать origin Host в `127.0.0.1:8766`; другие Host receiver
   отклоняет. Не включать debug/access logging URL/query. CLI-флаги и отсутствие
   query logging у конкретного tunnel runtime пока не проверены запуском.
3. Полученный `https://<temporary-host>/instagram/callback/` зарегистрировать
   в Meta Business Login, проверить trailing slash. То же точное значение задать
   владельцем в private `INSTAGRAM_REDIRECT_URI`. Новый Quick Tunnel обычно меняет
   hostname; потребуется обновить registration. Без сохранённой настройки не входить.
4. Запустить на Mac (не в Docker):

   ```sh
   .venv/bin/python -m app.cli.instagram_auth --callback-port 8766 --timeout 300
   ```

   Helper bind только 127.0.0.1, принимает лишь зарегистрированный callback path;
   `/accounts`, `/dashboard` и остальные пути здесь не обслуживаются. State
   криптографический, одноразовый и с TTL; timeout 1–600 секунд ограничивает также
   медленного клиента. Порт занят — безопасный отказ без fallback. URL/код/state
   не отражаются в ответах или HTTP error pages. Listener закрывается до backend
   exchange; token+grant записываются атомарно 0600 только после успешной проверки.
5. После успеха, ошибки или timeout остановить tunnel (Ctrl+C). Ротация state
   требует нового запуска helper; приватный `.env` сохраняется при ошибке.

Прежний `.venv/bin/python -m app.cli.instagram_auth` с hidden HTTPS redirect input
и `--refresh` сохранены. Refresh не запускает listener и не переоценивает grants.
Новый code flow сохраняет `INSTAGRAM_GRANTED_SCOPES`; запись этого поля вручную
не становится доказательством permissions. Schema/analytics snapshots не меняются.

Оператор HTTPS relay технически видит callback URL с одноразовым кодом. Публичная
ссылка доступна другим людям: неправильный state не даёт токен, но чужой запрос
может сорвать попытку, после чего потребуется новый запуск. Tunnel не должен
вести к API, dashboard или PostgreSQL. Реальный relay/TLS, Meta registration,
consent, scopes и owner identity ещё не проверены.

Источники: [Meta Business Login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login/),
[Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/),
[origin Host header](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/origin-parameters/#httphostheader).

### Диагностика временного callback

Успех определяет безопасное сообщение helper о сохранённом token и проверка конфигурации,
а не только страница browser. Error 1033 Cloudflare сам по себе не доказывает причину
проблемы или отказ OAuth. При браузерной ошибке сначала проверить helper; если callback
уже принят, не отправлять одноразовый code повторно. После успеха, ошибки или TTL
обязательно остановить tunnel. Не печатать полный redirect/code и не обходить браузерные
предупреждения безопасности. Если callback не принят до TTL, начать новый flow с новым
state; expired state/code не переиспользовать.
