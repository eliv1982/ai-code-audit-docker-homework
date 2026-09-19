# ai-code-audit-docker-homework

Учебный REST API на **Python + Flask + SQLite** для домашнего задания по аудиту кода, рефакторингу и развёртыванию в Docker.

## О проекте

Это **учебный проект по AI-аудиту кода через Cursor**. Цель — пройти полный цикл работы с реальным, но учебным кодом:

1. Создать намеренно проблемную, но запускаемую версию Flask API.
2. Провести аудит кода с помощью Cursor.
3. Исправить найденные проблемы.
4. Проверить результат smoke-testом.
5. Подготовить проект к Docker-сборке и публикации.

Проект **не предназначен для production** — это демонстрация процесса AI-аудита и рефакторинга.

## История разработки

### Этап 1. Проблемная версия

В первой версии `app.py` были **намеренно оставлены** типичные ошибки:

- небезопасные SQL-запросы через конкатенацию строк;
- глобальное SQLite-соединение и общий cursor;
- слабая валидация входных данных;
- некорректные HTTP-статусы;
- неаккуратная обработка ошибок;
- глобальный список `active users` без блокировки;
- запуск на стандартном порту Flask.

### Этап 2. AI-аудит в Cursor

Cursor провёл полный аудит кода и сформировал подробный отчёт с перечнем рисков и рекомендаций.

Отчёт сохранён в файле:

```
docs/cursor_audit_result.docx
```

### Этап 3. Исправления после аудита

По результатам аудита были исправлены:

| Область | Что сделано |
|---------|-------------|
| **SQL injection** | Все запросы переведены на параметризованный SQL |
| **SQLite** | Убрано глобальное соединение; используется per-request connection через Flask `g` |
| **Валидация** | Проверка JSON, типов, email и `uid`; ответы `400` / `409` |
| **HTTP-статусы** | Корректные коды: `201`, `202`, `404`, `500` и др. |
| **Обработка ошибок** | Контролируемые исключения, логирование, без `bare except` |
| **Active users** | Потокобезопасное хранение через `threading.Lock` |
| **Порт** | Финальный API работает на **8091** (порт **8080** занят Open WebUI) |
| **Docker** | Добавлены `requirements.txt`, `openapi.yaml`, smoke-test, инструкции по контейнеризации |

### Этап 4. Корректирующий проход после независимого аудита

Независимый аудит исправленной версии нашёл небольшие расхождения. Они устранены отдельным проходом, без превращения проекта в production-сервис:

| Область | Что сделано |
|---------|-------------|
| **Артефакты в Git** | `users.db` и `__pycache__/*.pyc` удалены из репозитория; SQLite-файлы (включая `-journal` / `-wal` / `-shm`) и кэш Python в `.gitignore` |
| **Docker-данные** | Код (`/app`) отделён от данных (`/app/data`); путь к базе задаётся `DATABASE_PATH`; том монтируется только в `/app/data` |
| **Email** | Пробелы внутри адреса (`a @b.com`) отклоняются; email приводится к нижнему регистру до проверки уникальности |
| **`/activate`** | Оставлен только `POST` (раньше по ошибке работал и `GET`) |
| **Ошибки БД** | Неожиданные ошибки SQLite возвращают JSON `500` без SQL и деталей исключения |
| **ID пользователя** | Принимаются только цифры `0-9` и значения не больше `2^63 - 1` (раньше огромный ID давал HTML `500`) |
| **Тесты** | Добавлен изолированный набор `unittest` (`test_app.py`); `test_endpoints.py` остаётся live smoke-тестом |
| **Docker-образ** | Базовый образ `python:3.12-slim` (как заявлено в документации), добавлен `.dockerignore` |

## Финальное состояние API

Приложение слушает **`0.0.0.0:8091`** по умолчанию.

Порт можно переопределить переменной окружения `PORT`.

### Эндпоинты

| Метод | Путь | Описание | Успешный статус |
|-------|------|----------|-----------------|
| GET | `/health` | Проверка сервиса | `200` |
| POST | `/adduser` | Создание пользователя | `201` |
| GET | `/user/<uid>` | Получение пользователя | `200` |
| POST | `/activate/<uid>` | Активация пользователя (только `POST`, `GET` → `405`) | `200` |
| GET | `/active` | Список active users | `200` |
| GET | `/slow` | Фоновая задача, немедленный ответ | `202` |
| GET | `/wrong` | Демонстрация контролируемой ошибки | `500` |

Подробная спецификация — в [`openapi.yaml`](openapi.yaml).

### Валидация и нормализация

- Тело `POST /adduser` — JSON-объект, запрос с `Content-Type: application/json`.
- `name` и `email` — непустые строки; пробелы по краям обрезаются.
- Email дополнительно приводится к **нижнему регистру** до проверки уникальности и сохранения: `Case@Test.Example` и `case@test.example` — один и тот же адрес (повторное создание → `409`, в ответе и базе — `case@test.example`).
- Формат email проверяется простым шаблоном `local@domain.tld`: без пробелов, ровно один `@`, точка в домене. Это не полная проверка по RFC.
- `uid` — целое число от `1` до `9223372036854775807`, только цифры `0-9`; иначе `400`.
- Неожиданная ошибка базы данных возвращает JSON `{"error": "internal server error"}` со статусом `500`; SQL и детали исключения остаются только в логе сервера.

### Учебные ограничения

Проект учебный и **не предназначен для production**:

- **Active users** хранятся только в памяти процесса: после перезапуска приложения или контейнера список `/active` пуст. Пользователи в SQLite при этом сохраняются.
- **`/slow`** запускает фоновую задачу в **daemon-потоке внутри процесса** приложения. Такая задача не сохраняется (not durable), может быть потеряна при остановке процесса, а число одновременных задач не ограничено. Это демонстрация, а не решение для фоновых задач в production.
- API запускается встроенным сервером Flask (`app.run`), без аутентификации и без production WSGI-сервера.
- Ответы Flask по умолчанию (`404` для неизвестного пути, `405` для неподдерживаемого метода) приходят в HTML, а не в JSON.
- Миграций нет: `CREATE TABLE IF NOT EXISTS` не меняет уже существующую таблицу. Если остался `users.db` от ранней (уязвимой) версии, без `NOT NULL` / `UNIQUE`, удалите его, чтобы схема создалась заново. Email, сохранённые раньше в смешанном регистре, не переписываются.

## Структура проекта

```
ai-code-audit-docker-homework/
├── app.py                          # Flask API (финальная версия)
├── test_app.py                     # Изолированные unit-тесты (unittest, временная БД)
├── test_endpoints.py               # Live smoke-test запущенного API
├── requirements.txt                # Зависимости Python
├── openapi.yaml                    # OpenAPI 3.1 спецификация
├── README.md                       # Документация проекта
├── Dockerfile                      # Сборка Docker-образа
├── .dockerignore                   # Что не попадает в контекст сборки образа
├── .gitignore                      # Артефакты запуска (venv, кэш, SQLite-файлы)
└── docs/
    └── cursor_audit_result.docx    # Отчёт AI-аудита из Cursor
```

SQLite-база (по умолчанию `users.db`) создаётся при запуске приложения и в Git **не хранится**.

## Локальный запуск

### Установка зависимостей

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

### Запуск API

```bash
python app.py
```

API будет доступен по адресу:

```
http://127.0.0.1:8091
```

Переопределение порта:

```bash
# Linux / macOS
PORT=9000 python app.py

# Windows PowerShell
$env:PORT=9000; python app.py
```

### База данных

При запуске приложение создаёт SQLite-базу. По умолчанию это файл `users.db` в текущей директории. Путь можно изменить переменной окружения `DATABASE_PATH`; недостающие каталоги в пути создаются автоматически:

```bash
# Linux / macOS
DATABASE_PATH=data/users.db python app.py

# Windows PowerShell
$env:DATABASE_PATH="data\users.db"; python app.py
```

Файлы базы и служебные файлы SQLite (`-journal`, `-wal`, `-shm`) игнорируются Git.

### Примеры запросов

```bash
curl http://127.0.0.1:8091/health

curl -X POST http://127.0.0.1:8091/adduser \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"Alice\",\"email\":\"alice@example.com\"}"

curl http://127.0.0.1:8091/user/1
curl -X POST http://127.0.0.1:8091/activate/1
curl http://127.0.0.1:8091/active
curl http://127.0.0.1:8091/slow
curl http://127.0.0.1:8091/wrong
```

## Тесты

В проекте два разных вида проверок:

| | `test_app.py` | `test_endpoints.py` |
|---|---|---|
| Что это | Изолированные unit-тесты | Live smoke-test |
| Сервер | Не нужен (Flask test client) | Нужен запущенный API |
| База данных | Временная SQLite-БД на каждый тест | База запущенного сервера |
| Зависимости | Только стандартная библиотека (`unittest`) | `requests` |
| Побочные эффекты | Нет | Остаётся пользователь `smoke_<время>@example.com` |

### Unit-тесты

```bash
python -m unittest test_app -v
```

Тесты не требуют запущенного сервера и не трогают `users.db`: каждый тест получает собственную временную базу и пустой список active users. Они проверяют `/health`, `/adduser` (валидацию, нормализацию email, `409`), `/user/<uid>`, `/activate/<uid>` (только `POST`), `/active`, схему свежесозданной базы (`NOT NULL`, `UNIQUE` для email), JSON `500` при ошибках базы данных и создание каталога для базы.

### Smoke-test (live)

Скрипт `test_endpoints.py` проверяет запущенный API и выводит отчёт:

```
[OK] GET /health — status=200, body={'status': 'ok'}
[OK] POST /adduser — status=201, user_id=1
[OK] GET /user/1 — status=200, body={'email': 'smoke_1789841125774@example.com', 'id': 1, 'name': 'Smoke Test User'}
[OK] GET /user/999999 — status=404, body={'error': 'user not found'}
[OK] POST /activate/1 — status=200, body={'message': 'user activated', 'user': {...}}
[OK] GET /active — status=200, active_ids=[1]
[OK] GET /slow — status=202, body={'message': 'task accepted', 'status': 'processing'}
[OK] GET /wrong (expected 500) — status=500, body={'error': 'internal server error'}

8/8 checks passed
```

`/wrong` **намеренно** отвечает `500`, поэтому для теста это успех (`[OK]`). `[FAIL]` печатается только при неожиданном ответе или недоступном сервере. Код возврата — `0`, если все проверки прошли, иначе `1`. Каждый запрос ограничен таймаутом.

Тест создаёт пользователя с уникальным email и не удаляет его. Для чистой базы запускайте сервер с одноразовым `DATABASE_PATH`.

### Запуск

Терминал 1 — API:

```bash
python app.py
```

Терминал 2 — тесты:

```bash
python test_endpoints.py
```

По умолчанию тест обращается к `http://127.0.0.1:8091`.

Переопределение базового URL:

```bash
# Linux / macOS
API_BASE_URL=http://127.0.0.1:9000 python test_endpoints.py

# Windows PowerShell
$env:API_BASE_URL="http://127.0.0.1:9000"; python test_endpoints.py
```

## Docker build

Сборка образа из корня проекта:

```bash
docker build -t ai-code-audit-api .
```

Образ основан на `python:3.12-slim` (версия Python совпадает с указанной в разделе «Стек») и настроен на порт **8091** (`EXPOSE 8091`, `ENV PORT=8091`).

Код приложения лежит в `/app`, а SQLite-база — в отдельном каталоге данных: `ENV DATABASE_PATH=/app/data/users.db`. Файл `.dockerignore` не пускает в контекст сборки `.git`, `.venv`, кэш Python, локальные базы SQLite и служебные файлы редакторов.

## Docker run

Запуск контейнера:

```bash
docker run --rm -p 8091:8091 --name audit-api ai-code-audit-api
```

Проверка:

```bash
curl http://127.0.0.1:8091/health
```

Другой порт (переменная `PORT` меняет порт внутри контейнера, поэтому меняйте и `-p`):

```bash
docker run --rm -p 9000:9000 -e PORT=9000 ai-code-audit-api
```

### Сохранение данных

Без тома база живёт внутри контейнера и исчезает вместе с ним. Чтобы SQLite-база переживала перезапуск, смонтируйте именованный том **только в `/app/data`**:

```bash
docker run --rm -p 8091:8091 -v audit-data:/app/data ai-code-audit-api
```

- Том хранит только базу (`/app/data/users.db`); код приложения по-прежнему берётся из образа.
- **Не монтируйте том поверх `/app`**: он скроет код из образа, и после обновления образа контейнер продолжит работать со старым `app.py` из тома.
- Сохраняются только пользователи в SQLite. Список active users хранится в памяти процесса и после перезапуска контейнера пуст.
- Удалить сохранённые данные: `docker volume rm audit-data`.

## Публикация в Docker Hub

### 1. Вход

```bash
docker login
```

### 2. Тегирование

Замените `your-dockerhub-username` на свой логин:

```bash
docker tag ai-code-audit-api your-dockerhub-username/ai-code-audit-api:latest
```

### 3. Публикация

```bash
docker push your-dockerhub-username/ai-code-audit-api:latest
```

## Запуск на сервере

### Через Docker

```bash
docker pull your-dockerhub-username/ai-code-audit-api:latest

docker run -d \
  --name audit-api \
  --restart unless-stopped \
  -p 8091:8091 \
  -v audit-data:/app/data \
  your-dockerhub-username/ai-code-audit-api:latest
```

### Через Python

```bash
git clone <repository-url>
cd ai-code-audit-docker-homework
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

### Проверка на сервере

```bash
curl http://<server-ip>:8091/health
```

```bash
API_BASE_URL=http://<server-ip>:8091 python test_endpoints.py
```

## Переменные окружения

| Переменная | Назначение | Значение по умолчанию |
|------------|------------|------------------------|
| `PORT` | Порт Flask-приложения | `8091` |
| `DATABASE_PATH` | Путь к файлу SQLite-базы; недостающие каталоги создаются автоматически | `users.db` (в Docker-образе `/app/data/users.db`) |
| `API_BASE_URL` | Базовый URL для smoke-test | `http://127.0.0.1:8091` |

## Стек

- Python 3.12+ (Docker-образ: `python:3.12-slim`)
- Flask 3.0
- SQLite
- requests (только для live smoke-test)
- unittest из стандартной библиотеки (unit-тесты)
