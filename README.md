# Cronator

**Python Script Scheduler with Web UI**

Cronator — это self-hosted планировщик Python-скриптов с веб-интерфейсом, изолированными окружениями для каждого скрипта, email-алертами и синхронизацией с Git.

![Dashboard Preview](https://via.placeholder.com/800x400?text=Cronator+Dashboard)

## Особенности

- **Hot-reload** — новые скрипты подхватываются без перезапуска
- **Изоляция** — каждый скрипт работает в своём виртуальном окружении (uv)
- **Python версии** — выбор любой версии Python (uv автоматически скачает нужную)
- **Web UI** — современный интерфейс для управления скриптами
- **Алерты** — уведомления на почту при ошибках
- **Бэкапы** — все данные хранятся в папках-вольюмах, плюс есть кнопка выгрузки БД
- **Git Sync** — автоматическая синхронизация скриптов из репозитория
- **Docker** — простой деплой одной командой

## Быстрый старт

### Docker (рекомендуется)

```bash
# Клонировать репозиторий
git clone https://github.com/yourusername/cronator.git
cd cronator

# Скопировать конфигурацию
cp .env.example .env
# Отредактировать .env, изменить ADMIN_PASSWORD и SECRET_KEY

# Запустить
docker-compose up -d

# Открыть в браузере
open http://localhost:8080
```

### Локально (для разработки)

```bash
# Установить uv если ещё не установлен
curl -LsSf https://astral.sh/uv/install.sh | sh

# Установить зависимости
uv sync

# Запустить
uv run python -m uvicorn app.main:app --reload --port 8080
```

## Структура скриптов

### Через UI

1. Откройте <http://localhost:8080>
2. Нажмите "New Script"
3. Напишите код, укажите расписание и зависимости
4. Сохраните

### Через файловую систему

Создайте папку в `scripts/` с файлом `cronator.yaml`:

```
scripts/
└── my-task/
    ├── cronator.yaml
    ├── script.py
    └── requirements.txt (опционально)
```

**cronator.yaml:**

```yaml
name: my-task
description: Описание задачи
schedule: "0 * * * *"  # Каждый час
python: "3.11"
enabled: true
timeout: 3600
alert_on_failure: true
```

**script.py:**

```python
from cronator_lib import get_logger

log = get_logger()

def main():
    log.info("Starting task...")
    # Ваш код
    log.success("Task completed!")

if __name__ == "__main__":
    main()
```

### Через Git

Настройте Git sync в `.env`:

```env
GIT_ENABLED=true
GIT_REPO_URL=https://github.com/user/my-scripts.git
GIT_BRANCH=main
GIT_SYNC_INTERVAL=300
```

## Конфигурация

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `ADMIN_USERNAME` | Логин администратора | `admin` |
| `ADMIN_PASSWORD` | Пароль администратора | `admin` |
| `SECRET_KEY` | Секретный ключ | `change-me` |
| `DATABASE_URL` | URL базы данных | SQLite |
| `SMTP_ENABLED` | Включить email-алерты | `false` |
| `GIT_ENABLED` | Включить Git sync | `false` |
| `DEFAULT_TIMEOUT` | Таймаут скриптов (сек) | `3600` |

См. `.env.example` для полного списка.

## API

Cronator предоставляет REST API:

```bash
# Список скриптов
curl -u admin:password http://localhost:8080/api/scripts

# Запустить скрипт
curl -X POST -u admin:password http://localhost:8080/api/scripts/1/run

# Получить историю выполнений
curl -u admin:password http://localhost:8080/api/executions?script_id=1
```

## cronator_lib

Библиотека для удобного логирования в скриптах:

```python
from cronator_lib import get_logger

log = get_logger()

log.info("Информационное сообщение")
log.warning("Предупреждение")
log.error("Ошибка", exc_info=True)
log.success("Успешно!")

# Прогресс
for i, item in enumerate(items):
    log.progress(i + 1, len(items), "Processing items")

# Структурированные данные
log.with_data("Processed", count=100, duration_ms=1234)
```

## Безопасность

- Всегда меняйте `ADMIN_PASSWORD` и `SECRET_KEY` в production
- Используйте HTTPS (через reverse proxy)
- Ограничьте доступ к порту 8080

## Лицензия

MIT
