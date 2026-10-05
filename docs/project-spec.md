# PROJECT: SOCIAL ANALYTICS — SOCIAL ANALYTICS

## 1. Цель проекта

Создать read-only систему аналитики личного бренда `@demo.account`, которая автоматически собирает доступные данные из Instagram и TikTok, хранит историю показателей и позволяет анализировать эффективность контента во времени.

Система не должна публиковать контент, менять настройки аккаунтов, удалять публикации или выполнять любые write-actions в социальных сетях.

Главная задача — не просто показывать текущие счётчики, а сохранять исторические snapshots, чтобы понимать:

- как распространяется каждый ролик;
- где происходит отвал аудитории;
- какие hooks работают лучше;
- какие темы приводят к просмотрам;
- какие темы вызывают интерес к личности автора;
- какие публикации приводят к посещению профиля;
- какие публикации конвертируют зрителей в подписчиков;
- какие форматы стоит масштабировать;
- какие гипотезы необходимо прекратить тестировать.

---

# 2. Главный принцип архитектуры

НИКОГДА не смешивать автоматически данные из разных источников.

Например:

- Instagram API;
- Instagram Insights UI;
- TikTok API;
- TikTok Studio;
- ручной snapshot.

Если TikTok Studio показывает 887 просмотров в сводке, а карточки публикаций дают 856, оба значения необходимо сохранить.

Не пытаться «исправить» расхождение.

Источник является частью данных.

Архитектура:

```text
Instagram API ─────┐
                   │
TikTok API ────────┼──> RAW DATA
                   │
Manual/UI data ────┘
                         ↓
                  NORMALIZED DATA
                         ↓
                    SNAPSHOTS
                         ↓
                  DERIVED METRICS
                         ↓
                    ANALYTICS
                         ↓
                    DASHBOARD
```

---

# 3. Стек

Предпочтительный MVP:

```text
Backend: Python 3.12+
API: FastAPI
Database: PostgreSQL / Supabase
ORM: SQLAlchemy 2.x
Migrations: Alembic
HTTP: httpx
Validation: Pydantic
Scheduler: cron / GitHub Actions / Supabase scheduled job
Tests: pytest
Dashboard: Metabase или простой internal dashboard
```

Frontend на первом этапе НЕ является приоритетом.

Сначала необходимо добиться корректного хранения данных.

---

# 4. Безопасность

Обязательные требования.

Никогда:

- не коммитить access tokens;
- не хранить secrets в исходниках;
- не выводить access tokens в logs;
- не использовать production credentials в tests;
- не передавать secrets на frontend.

Использовать:

```text
.env
.env.example
```

В `.env.example` должны быть только названия переменных.

Например:

```env
DATABASE_URL=
INSTAGRAM_ACCESS_TOKEN=
INSTAGRAM_USER_ID=

TIKTOK_CLIENT_KEY=
TIKTOK_CLIENT_SECRET=
TIKTOK_ACCESS_TOKEN=
TIKTOK_OPEN_ID=
```

`.env` должен быть в `.gitignore`.

---

# 5. Принцип READ ONLY

На первом этапе приложение имеет только аналитические функции.

Запрещено реализовывать:

```text
publish
delete
edit
comment
follow
unfollow
DM
change account settings
```

Если API scope предоставляет write-доступ, приложение всё равно не должно его использовать.

---

# 6. База данных

## TABLE: social_accounts

```text
id
platform
username
platform_account_id
account_type
created_at
updated_at
```

platform:

```text
instagram
tiktok
```

Пример:

```text
platform = instagram
username = demo.account
```

---

# 7. TABLE: content

Единая сущность публикации.

```text
id
account_id

platform
platform_content_id

content_type

published_at
duration_seconds

caption
permalink

created_at
updated_at
```

`content_type`:

```text
video
reel
photo
carousel
story
other
```

---

# 8. Стратегические теги контента

Добавить поля:

```text
internal_title
concept
content_pillar
series
topic
hook_type
hook_text
story_structure
format
cta_type
production_version
experiment_id
notes
```

Эти поля задаются нами, а не социальной сетью.

Пример:

```text
internal_title:
ИИ запретил блог про маркетинг

concept:
Ivan Ivanych

content_pillar:
personality_expertise

series:
AI producer

topic:
marketing

hook_type:
conflict

hook_text:
ИИ запретил мне вести блог про маркетинг

format:
talking_head
```

ВАЖНО:

Не делать эти поля обязательными.

Контент может появиться в API до того, как мы его разметили.

---

# 9. TABLE: account_snapshots

Не обновлять предыдущие значения.

Каждый сбор создаёт новую строку.

```text
id
account_id

snapshot_at

source
source_period_start
source_period_end

followers
following

views
unique_viewers

profile_views

likes
comments
shares
saves

new_viewers

raw_payload

created_at
```

`source`:

```text
instagram_api
instagram_ui
tiktok_api
tiktok_studio
manual
```

Поле может быть расширено.

---

# 10. TABLE: content_snapshots

Это центральная таблица проекта.

Каждый новый сбор создаёт новую строку.

```text
id
content_id

snapshot_at
source

views
unique_viewers

likes
comments
shares
saves

followers_gained
profile_visits

watch_time_total_seconds
watch_time_avg_seconds

completion_rate

traffic_for_you_pct
traffic_profile_pct
traffic_search_pct
traffic_following_pct
traffic_other_pct

new_viewers_pct
returning_viewers_pct

female_pct
male_pct
other_gender_pct

age_18_24_pct
age_25_34_pct
age_35_44_pct
age_45_54_pct
age_55_plus_pct

raw_payload

created_at
```

Все поля должны поддерживать NULL.

NULL нельзя автоматически заменять на 0.

---

# 11. Data status

Некоторые значения в Instagram/TikTok могут быть:

```text
--
processing
N/A
```

или противоречить друг другу.

Поэтому создать:

```text
data_status
```

Варианты:

```text
confirmed
processing
unavailable
anomalous
estimated
manual
```

Желательно реализовать не только на уровне snapshot, но при необходимости и отдельной таблицей field_status.

MVP допускает:

```text
snapshot_status
notes
```

---

# 12. RAW PAYLOAD

Каждый API response сохранять полностью.

Использовать JSONB.

Например:

```text
raw_payload JSONB
```

Причина:

API социальных платформ меняются.

Если позже понадобится новая метрика, исторический payload может позволить восстановить её без повторного запроса.

---

# 13. Instagram connector

Создать отдельный модуль:

```text
app/connectors/instagram/
```

Структура:

```text
client.py
auth.py
account.py
media.py
insights.py
schemas.py
mapper.py
```

Client не должен содержать business logic.

Задача connector:

1. получить Instagram account;
2. получить список публикаций;
3. получить metadata публикации;
4. получить доступные insights;
5. вернуть normalized DTO.

---

# 14. TikTok connector

```text
app/connectors/tiktok/
```

Структура:

```text
client.py
auth.py
user.py
videos.py
schemas.py
mapper.py
```

Получать доступные данные:

```text
video id
create time
duration
caption/title
view count
like count
comment count
share count
```

Не придумывать отсутствующие API metrics.

Если TikTok API не отдаёт:

```text
average watch time
completion rate
drop-off
For You %
demographics
new vs returning
```

оставлять поля NULL.

---

# 15. UI-only analytics

Создать механизм ручного импорта данных из Instagram Insights / TikTok Studio.

MVP должен позволять добавлять такие данные без вмешательства в API snapshots.

Можно сделать:

```text
POST /manual-snapshots/content
POST /manual-snapshots/account
```

Пример:

```json
{
  "platform": "tiktok",
  "platform_content_id": "7690971928651369730",
  "snapshot_at": "2026-10-03T13:52:00+03:00",
  "source": "tiktok_studio",
  "views": 251,
  "unique_viewers": 251,
  "watch_time_avg_seconds": 3.17,
  "completion_rate": 4.1,
  "traffic_for_you_pct": 100,
  "notes": "Most viewers stopped watching at 0:02"
}
```

---

# 16. Отдельная модель retention

Создать:

```text
content_retention_snapshots
```

Минимальные поля:

```text
id
content_id
snapshot_at
source

drop_off_second
average_watch_seconds
completion_rate

notes
created_at
```

Позже можно расширить до кривой:

```text
second
retention_pct
```

Не моделировать curve, пока у нас нет стабильных данных.

---

# 17. География

Создать:

```text
content_geo_snapshots
```

```text
id
content_snapshot_id

country_code
country_name
percentage
```

Никогда не делать вывод:

```text
country = language
```

Например:

Латвия ≠ обязательно русскоязычный пользователь.

---

# 18. Derived metrics

Расчётные показатели никогда не сохранялять как исходные API значения.

Создать analytics service.

Например:

```text
like_rate =
likes / views

share_rate =
shares / views

save_rate =
saves / views

comment_rate =
comments / views

follow_conversion =
followers_gained / unique_viewers

profile_visit_rate =
profile_visits / unique_viewers

average_watch_pct =
average_watch_seconds / duration_seconds
```

При denominator = 0 возвращать NULL.

Не возвращать infinity.

---

# 19. View velocity

Для каждой публикации рассчитывать:

```text
views_1h
views_6h
views_24h
views_48h
views_72h
views_7d
```

ВАЖНО:

Если snapshot отсутствует точно в 24 часа, использовать ближайший snapshot и хранить отклонение.

Например:

```text
requested_age_hours = 24
actual_age_hours = 25.3
```

Не выдавать это за точный показатель 24h.

---

# 20. Growth curve

Необходимо иметь endpoint:

```text
GET /content/{id}/history
```

Ответ:

```json
[
  {
    "snapshot_at": "...",
    "views": 250
  },
  {
    "snapshot_at": "...",
    "views": 251
  }
]
```

Так мы можем строить distribution curve.

---

# 21. Account history

Endpoint:

```text
GET /accounts/{id}/history
```

С фильтрами:

```text
source
date_from
date_to
```

---

# 22. Content comparison

Endpoint:

```text
GET /analytics/content-comparison
```

Фильтры:

```text
platform
date_from
date_to
series
topic
hook_type
content_pillar
```

Не создавать composite ranking.

Возвращать метрики отдельно.

Например:

```json
{
  "views": 251,
  "avg_watch_pct": 18.6,
  "completion_rate": 4.1,
  "share_rate": 0,
  "follow_conversion": 0
}
```

---

# 23. Никакого универсального Content Score

На данном этапе НЕ создавать:

```text
overall_score
viral_score 0-100
content_quality_score
```

Причина:

одна цифра скроет реальные причины результата.

Вместо этого хранить отдельные блоки сигналов.

---

# 24. Аналитические группы

## ATTENTION

```text
initial_distribution
drop_off_second
average_watch_pct
completion_rate
```

## ENGAGEMENT

```text
like_rate
comment_rate
share_rate
save_rate
```

## INTEREST

```text
profile_visit_rate
returning_viewer_rate
```

## CONVERSION

```text
follow_conversion
```

---

# 25. Experiments

Создать таблицу:

```text
experiments
```

Поля:

```text
id
name
hypothesis
metric
status

started_at
ended_at

notes
```

Пример:

```text
name:
Concrete hook in first second

hypothesis:
If the viewer understands the conflict in the first second,
average watch time and completion rate will increase.

metric:
average_watch_pct
completion_rate
```

---

# 26. Связь content ↔ experiment

Создать:

```text
content_experiments
```

```text
content_id
experiment_id
variant
```

Например:

```text
A
B
control
```

---

# 27. Начальные публикации

После настройки БД внести существующие публикации `@demo.account`.

Необходимо сохранить как минимум текущие известные TikTok/Instagram content objects.

Названия:

```text
157 дублей
Взяла себе ИИ-продюсера / Учусь говорить нет
Первая тысяча
ИИ запретил блог про маркетинг
Опыт есть. Карьера есть…
```

Использовать реальные platform content IDs из API после подключения.

Не хардкодить ID из документа, если API может вернуть authoritative identifiers.

---

# 28. Import historical snapshots

Система должна позволить импортировать старые snapshots из ручных отчётов.

Необходимо сделать CLI:

```text
python -m app.cli.import_snapshot file.json
```

Формат JSON описать отдельной schema.

---

# 29. Snapshot scheduler

Первый режим:

```text
1 раз в сутки
```

При наличии публикации младше 72 часов:

```text
чаще
```

Предлагаемая схема:

```text
+1h
+6h
+24h
+48h
+72h
+7d
```

Но если API limits делают это неудобным:

приоритет:

```text
6h
24h
72h
7d
```

---

# 30. API rate limits

Нельзя предполагать фиксированные rate limits.

Connector должен:

- обрабатывать HTTP 429;
- учитывать Retry-After;
- использовать exponential backoff;
- логировать request failures;
- не выполнять бесконечные retries.

---

# 31. Idempotency

Повторный запуск collector не должен создавать дубли одного и того же контента.

Content deduplication:

```text
platform
platform_content_id
```

Snapshot при новом времени создаётся новый.

---

# 32. Observability

Логи должны показывать:

```text
platform
operation
content_id
status
request_duration
error_type
```

Но НЕ показывать token.

---

# 33. Health endpoint

```text
GET /health
```

Ответ:

```json
{
  "status": "ok",
  "database": "ok"
}
```

Не делать внешний API request в health endpoint.

---

# 34. Collector status

Endpoint:

```text
GET /collectors/status
```

Показывает:

```text
instagram_last_success
instagram_last_error

tiktok_last_success
tiktok_last_error
```

---

# 35. Dashboard MVP

Первый экран:

## ACCOUNT

```text
followers
profile visits
account views
```

обязательно с указанием:

```text
source
period
snapshot time
```

---

# 36. CONTENT TABLE

Столбцы:

```text
Published
Platform
Title
Series
Hook

Views
Unique viewers

Avg watch
Avg watch %
Completion %

Likes
Shares
Saves
Comments

Profile visits
Followers gained
```

NULL отображать:

```text
—
```

а не:

```text
0
```

---

# 37. Content detail page

Для каждого ролика:

### Metadata

```text
platform
publication time
duration
hook
series
topic
experiment
```

### Distribution

```text
views curve
unique viewers
traffic source
```

### Retention

```text
average watch
average watch %
completion
drop-off second
```

### Engagement

```text
likes
comments
shares
saves
```

### Conversion

```text
profile visits
follows
```

---

# 38. Comparison page

Позволить сравнивать:

```text
TikTok vs Instagram

hook types

series

topics

formats

CTA types
```

Но показывать:

```text
median
mean
sample size
```

Обязательно sample size.

Не делать вывод типа:

> Conflict hook лучше

при:

```text
n = 1
```

---

# 39. Sample size guardrail

В analytics service добавить правило.

Если:

```text
n < 5
```

вывод:

```text
insufficient_sample
```

Если:

```text
5 <= n < 10
```

вывод:

```text
directional_only
```

Если:

```text
n >= 10
```

можно считать сигнал более устойчивым, но не автоматически причинным.

---

# 40. Не путать correlation и causation

Dashboard не должен автоматически писать:

```text
Hook X caused higher retention.
```

Допустимая формулировка:

```text
Posts tagged with Hook X currently show higher median retention.
```

---

# 41. Timezone

В БД хранить timestamps в UTC.

В UI показывать:

```text
Europe/Moscow
```

для исторических данных проекта по умолчанию.

Архитектура должна позволять менять display timezone.

---

# 42. Historical reports

Нужно импортировать уже существующие контрольные точки.

Минимально:

```text
29.09.2026
30.09.2026
01.10.2026
03.10.2026 TikTok
```

Instagram 03.10 НЕ существует как подтверждённый snapshot.

Не создавать его.

Последний подтверждённый Instagram snapshot на момент старта:

```text
01.10.2026 15:48–15:50 MSK
```

Последний подтверждённый TikTok snapshot:

```text
03.10.2026 13:52–13:55 MSK
```

---

# 43. Data provenance

Каждая цифра должна иметь возможность ответить:

```text
Откуда она появилась?
Когда была получена?
Какой период она описывает?
API это или интерфейс?
Исходное значение или расчёт?
```

Это критическое требование проекта.

---

# 44. Tests

Писать tests одновременно с реализацией.

Минимальные unit tests:

```text
normalization
rate calculations
division by zero
NULL handling
timezone conversion
snapshot history
deduplication
API mapping
anomaly preservation
```

Пример обязательного test case:

```text
views = 0
unique_viewers = 2
average_watch = 15.78
```

Система НЕ должна автоматически исправлять это на:

```text
unique_viewers = 0
average_watch = 0
```

---

# 45. Integration tests

Mock external APIs.

Не вызывать Instagram/TikTok production API в CI.

---

# 46. Development phases

## PHASE 1 — Foundation

Сделать:

```text
repo
FastAPI
PostgreSQL
SQLAlchemy
Alembic
models
tests
docker compose
.env.example
```

Acceptance:

```text
docker compose up
```

запускает API + database.

---

## PHASE 2 — Data model

Реализовать:

```text
accounts
content
account_snapshots
content_snapshots
experiments
strategic tags
```

Acceptance:

Можно вручную создать account/content/snapshot.

---

## PHASE 3 — Instagram connector

Реализовать auth + read-only collector.

Acceptance:

Collector получает account + media + доступные insights и сохраняет snapshot.

---

## PHASE 4 — TikTok connector

Реализовать auth + Display API collector.

Acceptance:

Collector получает список видео и публичные счётчики.

---

## PHASE 5 — Manual Studio snapshots

Сделать endpoint + CLI import.

Acceptance:

Можно занести:

```text
avg watch
completion
drop-off
For You %
demographics
```

не меняя API snapshot.

---

## PHASE 6 — Historical import

Импортировать наши существующие snapshots.

Acceptance:

Можно открыть историю публикации и увидеть несколько контрольных точек.

---

## PHASE 7 — Analytics

Добавить:

```text
rates
view velocity
watch %
comparison queries
sample size guardrails
```

---

## PHASE 8 — Dashboard

Сделать минимальный dashboard.

Красивый UI вторичен.

Корректность данных первична.

---

# 47. Что НЕ делать в MVP

Не добавлять:

```text
AI content generation
auto posting
comment moderation
DM
social listening
competitor scraping
automatic caption generation
automatic video editing
universal content score
ML predictions
```

---

# 48. Будущая AI-функция

Архитектура должна позволять позже добавить endpoint:

```text
POST /analytics/insights
```

который получает структурированные данные и формирует:

```text
Observation
Hypothesis
Next experiment
Result
Decision
```

Но LLM не должна обращаться напрямую к raw social API.

LLM работает только с normalized analytics layer.

---

# 49. Главный аналитический цикл

Все дальнейшие решения строятся так:

```text
OBSERVATION
↓
HYPOTHESIS
↓
CONTENT TEST
↓
DATA
↓
INTERPRETATION
↓
NEXT TEST
```

Пример:

```text
Observation:
Most TikTok viewers leave in second 1–2.

Hypothesis:
The situation is not understandable immediately.

Test:
Start with a concrete conflict and visible action in the first second.

Primary metrics:
average_watch_pct
completion_rate

Secondary:
shares
profile_visit_rate
follow_conversion
```

---

# 50. Definition of Done MVP

MVP считается готовым, когда:

1. Instagram account авторизуется.
2. TikTok account авторизуется.
3. Collector автоматически получает доступные API metrics.
4. Новые публикации автоматически обнаруживаются.
5. Каждый сбор создаёт historical snapshot.
6. Старые данные не перезаписываются.
7. UI-only metrics можно добавить вручную.
8. NULL и 0 различаются.
9. Источник каждой цифры известен.
10. Можно посмотреть историю одного ролика.
11. Можно сравнить несколько роликов.
12. Можно отфильтровать ролики по hook/series/topic.
13. Рассчитываются основные derived metrics.
14. Есть automated tests.
15. В repository нет secrets.

---

# 51. Правило работы Codex

Не пытайся реализовать весь проект одним большим commit.

Работай фазами.

Для каждой фазы:

1. Опиши, что собираешься изменить.
2. Напиши/обнови tests.
3. Реализуй минимальный код.
4. Запусти tests.
5. Исправь ошибки.
6. Покажи список изменённых файлов.
7. Кратко сообщи:
   - что сделано;
   - что проверено;
   - какие ограничения остались.
8. Только потом переходи к следующей фазе.

Не скрывай failing tests.

Не заменяй реальные API ограничения предположениями.

Если API documentation противоречит реализации, зафиксируй это как limitation.

---

# ПЕРВАЯ ЗАДАЧА CODEX

Начни только с Phase 1 и Phase 2.

Создай production-ready skeleton проекта:

```text
FastAPI
PostgreSQL
SQLAlchemy 2
Alembic
pytest
Docker Compose
```

Реализуй модели:

```text
SocialAccount
Content
AccountSnapshot
ContentSnapshot
Experiment
ContentExperiment
```

Добавь enum/source/status структуры.

Особое внимание:

```text
NULL != 0
```

Все analytics fields nullable.

Добавь indexes:

```text
account_id
content_id
snapshot_at
platform_content_id
source
```

Добавь uniqueness:

```text
(platform, platform_content_id)
```

для Content.

Напиши tests.

Не подключай пока Instagram или TikTok API.

После завершения Phase 1–2 остановись и покажи результат.