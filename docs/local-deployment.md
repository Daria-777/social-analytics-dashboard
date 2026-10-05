# Локальное развёртывание на Mac

Runtime: Docker Desktop Apple Silicon, PostgreSQL 16 в named volume, API/dashboard
на `http://127.0.0.1:8000/dashboard`. Compose project всегда **social-analytics**.
DB наружу не публикуется. Токены платформ пустые, scheduler по умолчанию выключен.
Пустой dashboard до настоящей авторизации — ожидаемый результат.

## Подготовка и запуск

Docker Desktop устанавливается из официального подписанного пакета. Его лицензию
и запрошенные macOS разрешения принимает владелец. Не нужен Docker account для
локального запуска. Не включайте Kubernetes или платные cloud features.

Из корня проекта:

```sh
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
.venv/bin/python -m app.cli.local_setup
.venv/bin/python -m app.cli.readiness
docker compose -p social-analytics --env-file .env config -q
docker compose -p social-analytics --env-file .env up --build -d
docker compose -p social-analytics ps
curl --fail http://127.0.0.1:8000/health
```

Setup создаёт `.env` только при отсутствии через exclusive create (0600), с новыми
случайными credentials и blank provider tokens. Существующий файл не меняет.
Readiness не подключается к БД/API; exit 0 означает базовую configuration, а не
работающий daemon/авторизацию. Не используйте `compose config` без `-q`: он может
напечатать секреты. Не экспортируйте provider credentials в shell перед Compose:
переменные shell имеют приоритет над `.env`.

## Вход

```sh
.venv/bin/python -m app.cli.local_setup --copy-key
```

Вставьте ключ из clipboard в поле входа dashboard. Не отправляйте его в чат и не
добавляйте в URL. После вставки очистите clipboard: `printf '' | pbcopy`.
Ключ хранится только в private `.env`; cookie сессии HttpOnly/SameSite=Strict.
При входе можно выбрать **«Запомнить этот браузер на 30 дней»**. Без галочки
сессия действует 8 часов (или DASHBOARD_SESSION_HOURS). Это signed HttpOnly cookie
с ограниченным сроком, а не сохранение ключа. «Выйти» удаляет текущую сессию; смена
INTERNAL_API_KEY отзывает все сессии. Выбирайте опцию только на личном устройстве.
Локальный HTTP допустим только на loopback. Для удалённого доступа нужен HTTPS.

## Остановка, повторный запуск и данные

```sh
docker compose -p social-analytics stop
docker compose -p social-analytics start
```

`restart: unless-stopped` восстанавливает ранее запущенные services после старта
Docker engine; он не запускает сам Docker Desktop. При необходимости включите
его запуск при входе в macOS. Во время сна/выключения Mac, выхода пользователя или
остановки Docker collection не работает. Это не постоянно доступный сервер.
Отключённый scheduler сам не включится после restart.

Named volume `social-analytics_postgres_data` переживает restart и `down` без `-v`.
**Не выполняйте `down -v`, volume rm или Docker factory reset для рабочей БД.**
После изменения `.env` используйте `up -d --force-recreate api` вместо restart.
Scheduler пересоздавайте отдельно только после проверки настоящих dry runs.

## Backup и будущий перенос

```sh
mkdir -p backups
chmod 700 backups
umask 077
docker compose -p social-analytics exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > backups/dash.dump
```

Backup содержит пользовательские данные; не коммитьте и не публикуйте его.
На будущем сервере переносите код, private `.env` по SSH/SFTP и `pg_dump` backup.
Замените только инфраструктурные настройки (hostname/domain), сохраняя IDs/history.
Поднимите **пустую новую БД**, остановите writers, затем `pg_restore --exit-on-error
--no-owner --no-privileges` в неё. Не используйте `--clean` против рабочей БД.
Сначала проверьте restore в отдельном project/volume и сравните записи/миграцию;
затем migrations/health/dashboard. Не копируйте Docker volume вслепую между Mac
и Linux. HTTPS/server template: [server-deployment.md](server-deployment.md).

Изолированная проверка инфраструктуры: [compose-smoke.md](compose-smoke.md).
Реальная OAuth и первый collection выполняются отдельным последующим шагом по
[first-connection.md](first-connection.md), не во время deployment smoke tests.

## Локальная авторизация TikTok

Desktop helper запускается в `.venv` на Mac, вне контейнера. Зарегистрируйте
`http://127.0.0.1:8765/tiktok/callback/`, установите локально
`TIKTOK_OAUTH_MODE=desktop` и `TIKTOK_REDIRECT_URI` с этим точным значением.
Запустите `.venv/bin/python -m app.cli.tiktok_auth --mode desktop --timeout 300`.
Подробнее: [контракт, ручной refresh и ограничения](tiktok-api.md#owner-setup-web-or-desktop).
Публичные `/terms` и `/privacy` доступны без API key, не раскрывают credentials.
Принятие localhost URLs в TikTok Sandbox подтверждается только сохранением
конфигурации в developer UI; наличие страниц само по себе этого не доказывает.

Opt-in TikTok renewal использует отдельный token-only каталог и Compose override:
[setup](tiktok-api.md#opt-in-private-store-and-automatic-renewal). По умолчанию
этот каталог не монтируется, refresh и scheduler выключены.

Для Mac/Docker без host UID mapping рекомендуется [token-only named volume](tiktok-volume.md).
