# Opt-in snapshot scheduler

По умолчанию выключен. Один настроенный owner на platform; в MVP collectors
одной platform сериализуются, Instagram и TikTok могут работать независимо.
Постоянная БД должна быть PostgreSQL. SQLite locks — только in-process для tests.

- Daily: 09:00 UTC по умолчанию, одна детерминированная UUID/platform/UTC day.
- Young publications: 6h/24h/72h/7d. Milestone округляется **вверх** до часового
  bucket; postings одной platform/bucket обслуживаются одним full-account job.
  Это экономит запросы, но время измерения приблизительное. Velocity всегда
  показывает actual age/deviation, не выдаёт bucket за точную контрольную точку.
- Tick каждые 15min, не более 2 новых/повторных jobs за tick. Новые публикации
  обнаруживает daily/full-account collector; отдельного polling discovery нет.
- Age jobs допустимы только в пределах 2h lateness. Слишком старые milestones не
  backfill-ятся сегодняшними цифрами. Late discovery может пропустить milestone;
  следующий daily collection всё равно сохраняет реальный текущий observation.
- Plan выбирает только публикации configured owner (open_id/user_id или username
  до pinning). Manual objects другого аккаунта не вызывают его age jobs.

## Конкурентность и повтор

PostgreSQL session advisory lock platform держится весь collector job, включая
commits. API, CLI и scheduler с разными UUID не могут одновременно собирать одну
platform. Второй worker получает busy; его новый run не создаётся.
Same UUID дополнительно защищён PK и conditional failed/partial → running claim.
Scheduler держит отдельный job advisory lock от проверки attempts до записи metadata,
поэтому параллельные scheduler processes не обходят retry budget.

Success не запускается повторно. Failed/partial повторяются тем же UUID максимум
3 раза (включая первый запуск), с задержками 30min, 60min по умолчанию. Подробности
schedule/attempts/next_retry_at сохраняются в collector_runs.summary. Age job также
ограничен lateness window, поэтому число попыток может быть меньше максимума.
API client retries остаются отдельно ограниченными. Running никогда не сбрасывается
по таймеру: crash требует операторской процедуры README. Уже сохранённый partial
snapshot неизменяем; его NULL не заполняются retry. Следующий job даёт новое измерение.

При revocation/expired refresh token нужны OAuth владельца. Scheduler не пишет .env.
В legacy env mode TikTok renewal ручной и требует пересоздания containers.
Для Docker-only opt-in renewal используйте [token-only named volume](tiktok-volume.md):
workers читают rotated credentials перед сбором и координируют refresh через flock.
Пересоздание после каждой rotation тогда не требуется. Instagram renewal остаётся ручным.

## Запуск после авторизации и настройки постоянной БД

В локальном ignored .env установите SCHEDULER_ENABLED=true. Остальные env имеют
безопасные defaults; имена перечислены в .env.example. В Compose:

```sh
docker compose --profile scheduler up --build -d
```

Без profile запускаются только DB/migration/API. Scheduler не имеет опубликованного
порта; миграции должны завершиться до его запуска. Для отдельного Python process:

```sh
.venv/bin/python -m app.cli.scheduler --plan
.venv/bin/python -m app.cli.scheduler --once
.venv/bin/python -m app.cli.scheduler
```

--plan читает DB и показывает scheduled candidates, не вызывает социальный API и
не пишет DB. Это не offline config check и не подтверждение token validity.
CLI требует явный DATABASE_URL и наличие хотя бы одного token; иначе jobs не стартуют.
--once делает один tick. Continuous mode после трёх последовательных DB/config
ошибок завершает process; бесконечного database retry/restart policy не добавлено.

## Recovery

Остановите scheduler (`docker compose stop scheduler`), API и CLI workers всех хостов;
подтвердите отсутствие процессов. Затем условно переведите конкретный running run
в failed по процедуре README (для TikTok используйте platform='tiktok'). Не меняйте
snapshots. Повторите его UUID вручную; либо дождитесь допустимого schedule retry.
Expired age window/exhausted attempt budget сами не возобновляются. Новые измерения
создаются новым UUID, история прежних failures сохраняется.
