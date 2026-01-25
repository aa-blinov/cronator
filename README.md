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

### Production с Docker и PostgreSQL (рекомендуется)

```bash
# 1. Клонировать репозиторий
git clone https://github.com/yourusername/cronator.git
cd cronator

# 2. Создать .env из примера и настроить пароли
cp .env.example .env
nano .env  # Установить POSTGRES_PASSWORD, ADMIN_PASSWORD, SECRET_KEY

# 3. Запустить сервисы (PostgreSQL + Cronator + Backup)
docker compose up -d

# 4. Проверить логи
docker compose logs -f cronator

# 5. Открыть в браузере
open http://localhost:8080
```

По умолчанию: `admin` / `admin` (измените в .env!)

**Что включено:**
- PostgreSQL 16 с автоматическими миграциями
- Ежедневные бэкапы БД в 2 AM (хранятся 7 дней)
- Persistent volumes для данных
- Health checks для всех сервисов

### Локальная разработка с SQLite

```bash
# Установить uv если ещё не установлен
curl -LsSf https://astral.sh/uv/install.sh | sh

# Установить зависимости
uv sync

# Запустить миграции БД
uv run alembic upgrade head

# Запустить приложение
uv run python -m uvicorn app.main:app --reload --port 8080
```

### Docker (старый метод, только для разработки)

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
python: "3.12"
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
GIT_TOKEN=ghp_your_personal_access_token  # Для приватных репозиториев
GIT_SYNC_INTERVAL=300
```

**Для приватных репозиториев:**

- **GitHub**: создайте Personal Access Token в Settings → Developer settings → Personal access tokens
- **GitLab**: создайте Personal Access Token в User Settings → Access Tokens
- **Bitbucket**: создайте App Password в Personal settings → App passwords

Токен должен иметь права на чтение репозитория (`repo` scope для GitHub).

## Конфигурация

### Первый запуск

При первом запуске создайте `.env` файл с базовыми настройками:

```bash
cp .env.example .env
# Отредактировать .env, изменить ADMIN_PASSWORD и SECRET_KEY
```

**Важно:** `.env` нужен только для первого запуска и задает начальные значения. После первого запуска все настройки можно менять через веб-интерфейс в разделе Settings.

### Управление настройками

После первого запуска все настройки хранятся в базе данных и редактируются через UI:

1. Откройте <http://localhost:8080/settings>
2. Нажмите "Edit Settings"
3. Измените нужные настройки (SMTP, Git, таймауты)
4. Сохраните изменения

Настройки применяются немедленно без перезапуска контейнера.

### Основные настройки

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `ADMIN_USERNAME` | Логин администратора | `admin` |
| `ADMIN_PASSWORD` | Пароль администратора | `admin` |
| `SECRET_KEY` | Секретный ключ (для шифрования) | `change-me` |
| `DATABASE_URL` | URL базы данных | SQLite (локально) / PostgreSQL (Docker) |
| `POSTGRES_PASSWORD` | Пароль PostgreSQL (только Docker) | `cronator_dev_password` |
| `BACKUP_RETENTION_DAYS` | Срок хранения бэкапов (дни) | `7` |
| `SMTP_ENABLED` | Включить email-алерты | `false` |
| `GIT_ENABLED` | Включить Git sync | `false` |
| `DEFAULT_TIMEOUT` | Таймаут скриптов (сек) | `3600` |

См. `.env.example` для полного списка.

## База данных

### PostgreSQL (Production)

В Docker используется PostgreSQL 16 с автоматическими миграциями:

```bash
# Миграции применяются автоматически при старте контейнера
docker compose up -d

# Просмотр текущей версии БД
docker compose exec cronator uv run alembic current

# История миграций
docker compose exec cronator uv run alembic history
```

### SQLite (Development)

Для локальной разработки используется SQLite:

```bash
# Применить миграции
uv run alembic upgrade head

# Откатить последнюю миграцию
uv run alembic downgrade -1

# Создать новую миграцию после изменения моделей
uv run alembic revision --autogenerate -m "Description of changes"
```

### Миграции (Alembic)

Проект использует Alembic для управления схемой БД:

```bash
# Создать новую миграцию после изменения моделей
uv run alembic revision --autogenerate -m "Add new column"

# Применить все миграции
uv run alembic upgrade head

# Откатить последнюю миграцию
uv run alembic downgrade -1

# Откатить до конкретной версии
uv run alembic downgrade <revision_id>

# Показать текущую версию БД
uv run alembic current

# Показать историю миграций
uv run alembic history --verbose
```

**Структура миграций:**
```
alembic/
├── versions/
│   └── 7a45991c91e2_initial_schema_with_all_tables.py
├── env.py           # Конфигурация для async SQLAlchemy
└── script.py.mako   # Шаблон для новых миграций
```

### Бэкапы PostgreSQL

Бэкапы создаются автоматически сервисом `db-backup`:

**Расписание:** Ежедневно в 2:00 AM  
**Хранение:** 7 дней (настраивается через `BACKUP_RETENTION_DAYS`)  
**Формат:** `backups/cronator_YYYYMMDD_HHMMSS.sql.gz`

#### Ручной бэкап

```bash
# Создать бэкап
docker compose exec db pg_dump -U cronator cronator | gzip > backups/manual_$(date +%Y%m%d).sql.gz

# Список бэкапов
ls -lh backups/
```

#### Восстановление из бэкапа

```bash
# 1. Остановить приложение
docker compose stop cronator

# 2. Восстановить БД
gunzip < backups/cronator_20260125_020000.sql.gz | docker compose exec -T db psql -U cronator cronator

# 3. Запустить приложение
docker compose start cronator

# Или полная пересборка:
docker compose down
docker compose up -d
```

#### Миграция с SQLite на PostgreSQL

Если у вас есть данные в SQLite и вы хотите мигрировать на PostgreSQL:

```bash
# 1. Экспорт данных из SQLite (создайте скрипт)
# 2. Запустить PostgreSQL
docker compose up -d db

# 3. Применить миграции
docker compose run --rm cronator uv run alembic upgrade head

# 4. Импорт данных через SQL или Python скрипт
# 5. Запустить приложение
docker compose up -d cronator
```

**Примечание:** Миграция данных не включена в автоматический процесс. При переходе с SQLite на PostgreSQL данные не переносятся автоматически.

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

## Тестирование

Проект включает комплексный набор тестов: unit-тесты и интеграционные тесты API.

### Запуск тестов

Вы можете запускать тесты локально (SQLite) или в изолированном контейнере (PostgreSQL):

#### Локально (SQLite)
```bash
# Установить dev зависимости
uv sync --all-extras

# Запустить все тесты
uv run pytest tests/ -v
```

#### В Docker (PostgreSQL) — Рекомендуется
Этот метод гарантирует полную идентичность окружения с production и тестирует работу с реальной БД PostgreSQL.
```bash
npm run test:docker
```
Или вручную:
```bash
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from tests
```

### Структура тестов

```
tests/
├── conftest.py              # Фикстуры и настройка тестовой БД
├── unit/
│   ├── test_models.py       # Тесты моделей Script, Execution
│   └── services/
│       ├── test_scheduler.py    # Тесты SchedulerService
│       └── test_executor.py     # Тесты ExecutorService
└── integration/
    ├── test_api_scripts.py      # API /api/scripts
    ├── test_api_executions.py   # API /api/executions
    └── test_api_settings.py     # API /api/settings
```

**Важно:**
- При локальном запуске используется файл `test_app.db` (SQLite), который удаляется после тестов.
- При запуске в Docker используется отдельный контейнер `db-test` (PostgreSQL 16).
- Во всех тестах автоматически устанавливается `SKIP_ALEMBIC_MIGRATIONS=1`, схема БД создается напрямую из моделей SQLAlchemy для скорости.

## Безопасность

⚠️ **Важные рекомендации по безопасности:**

- **Всегда меняйте** `ADMIN_PASSWORD`, `POSTGRES_PASSWORD` и `SECRET_KEY` в production
- **Используйте сильный SECRET_KEY** (минимум 32 символа) - он используется для шифрования чувствительных данных
- **Используйте сильный POSTGRES_PASSWORD** для защиты базы данных
- **Не коммитьте `.env`** в систему контроля версий
- **Используйте HTTPS** через reverse proxy (nginx, Caddy, Traefik)
- **Ограничьте доступ** к порту 8080 файрволлом
- **Регулярные бэкапы** - бэкапы PostgreSQL создаются автоматически каждый день
- **Изолируйте БД** - PostgreSQL доступна только из Docker сети, не экспонируйте порт 5432 наружу

### Шифрование данных

Все чувствительные настройки (пароли SMTP, Git токены) **автоматически шифруются** перед сохранением в БД:

- Алгоритм: Fernet (симметричное шифрование)
- Ключ: производный от `SECRET_KEY` из `.env`
- Проверка: запустите `python check_db_security.py`

Подробнее см. [SECURITY.md](SECURITY.md)

## Лицензия

MIT
