# Изолированный Compose smoke test

Не запускайте destructive migrations/tests против `social-analytics` или production DB.
Используйте отдельный project (`dash-smoke`), отдельный private test env с новыми
DB/key credentials, DB name `test_dash` и отдельный named volume. Provider tokens
должны быть пустыми. Для API нужен override порта, например `127.0.0.1:18000:8000`,
чтобы не остановить постоянный dashboard на 8000. Fixture HTTPTransport остаётся
заблокированным в pytest; тестовые API clients используют только MockTransport.

Порядок проверки:

1. `compose config -q`, build, DB health, migrate upgrade head, API health.
2. Проверить anonymous 401, owner login, пустые accounts/content/snapshots/runs.
3. Записать синтетическую marker account/snapshot **только в test_dash**.
4. Restart, затем down без `-v` / up: marker и Alembic version сохраняются.
5. `pg_dump -Fc` test_dash; восстановить в ещё один пустой project/volume,
   сравнить marker/immutable snapshot/version и выполнить Alembic check.
6. Выполнить integration suite и upgrade/downgrade preservation checks на test_dash.
7. Очистить только явно названные smoke projects и их test volumes. Не применять
   общие `docker system prune` или команды к `social-analytics`.

Наличие этого плана не является результатом проверки. Фактические результаты
и невыполненные пункты фиксируются в [system-verification.md](system-verification.md).
