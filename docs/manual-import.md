# UI/Studio и исторические observations

Schema: [import-schema.json](import-schema.json); актуальный вариант всегда можно
получить `python -m app.cli.import_snapshot --schema` без DB/HTTP.

`POST /manual-snapshots/content`, `/account`, `/retention`, `/import` защищены
существующим internal authentication. Родитель выбирается **по точной паре**
platform/platform_content_id (account — platform/platform_account_id).
Неизвестный ID → 404, ничего не создаётся. Переданный internal UUID обязан совпасть
с найденным родителем. Ручные IDs не переименовываются и не объединяются с API ID.

Допустимые источники: manual, instagram_ui, tiktok_studio. UI source должен совпадать
с platform; API источники через manual import запрещены. Snapshot timestamps
требуют timezone; хранятся UTC. Period задавайте по экрану источника, не придумывайте.
NULL означает отсутствующую метрику, 0 — реальное значение. Не суммируем источники,
не корректируем anomalous views=0/unique_viewers=2/watch=15.78.

## JSON batch

Ниже только пример формата с **тестовыми**, не реальными identifiers/observations:

```json
{
  "version": 1,
  "content_snapshots": [{
    "platform": "tiktok",
    "platform_content_id": "test-only-video",
    "snapshot_at": "2026-01-01T12:00:00+03:00",
    "source": "tiktok_studio",
    "snapshot_status": "anomalous",
    "views": 0,
    "unique_viewers": 2,
    "watch_time_avg_seconds": 15.78,
    "completion_rate": null,
    "geography": [{"country_code":"LV","country_name":"Латвия","percentage":25}]
  }],
  "retention_snapshots": [{
    "platform": "tiktok",
    "platform_content_id": "test-only-video",
    "snapshot_at": "2026-01-01T12:00:00+03:00",
    "source": "tiktok_studio",
    "drop_off_second": 2,
    "average_watch_seconds": 15.78,
    "completion_rate": null,
    "notes": "Только пример: перепишите реальные сведения экрана источника"
  }],
  "account_snapshots": []
}
```

```sh
.venv/bin/python -m app.cli.import_snapshot file.json
```

Все записи batch валидируются, сохраняются одной транзакцией. Ошибка любого parent,
source или DB constraint отменяет весь batch; прежние наблюдения остаются.
Import **append-only**, каждый успешный вызов добавляет observations. Повторная
загрузка файла не является исправлением и добавит отдельные наблюдения; не
повторяйте успешный импорт случайно. Для исправления добавьте новый observation с
notes о причине; UPDATE/DELETE blocked ORM и PostgreSQL triggers.

Retention — отдельная таблица/source, не curve: drop_off_second,
average_watch_seconds и completion_rate. Geographies принадлежат конкретному
content snapshot, страна не означает язык. Percentages валидируются по отдельности
0..100; сомнительные распределения сохраняйте с anomalous/notes, не нормализуйте.
История: GET /content/{id}/retention и /content-snapshots/{id}/geography.

## Исторические отчёты проекта

Даты 29.09, 30.09, 01.10 и 03.10 TikTok известны из ТЗ, но их фактические значения,
реальные content IDs и сами отчёты не предоставлены. Они **не импортированы**.
Instagram 03.10 не создаётся как подтверждённое историческое наблюдение.
Для реального импорта нужны сами отчёты и точные уже discovered/зарегистрированные
IDs. Код импорта готов; готовность кода не заменяет наличия исторических данных.
