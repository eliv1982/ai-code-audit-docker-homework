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

## Финальное состояние API

Приложение слушает **`0.0.0.0:8091`** по умолчанию.

Порт можно переопределить переменной окружения `PORT`.

### Эндпоинты

| Метод | Путь | Описание | Успешный статус |
|-------|------|----------|-----------------|
| GET | `/health` | Проверка сервиса | `200` |
| POST | `/adduser` | Создание пользователя | `201` |
| GET | `/user/<uid>` | Получение пользователя | `200` |
| GET / POST | `/activate/<uid>` | Активация пользователя | `200` |
| GET | `/active` | Список active users | `200` |
| GET | `/slow` | Фоновая задача, немедленный ответ | `202` |
| GET | `/wrong` | Демонстрация контролируемой ошибки | `500` |

Подробная спецификация — в [`openapi.yaml`](openapi.yaml).

## Структура проекта

```
ai-code-audit-docker-homework/
├── app.py                          # Flask API (финальная версия)
├── test_endpoints.py               # Smoke-test запущенного API
├── requirements.txt                # Зависимости Python
├── openapi.yaml                    # OpenAPI 3.1 спецификация
├── README.md                       # Документация проекта
├── Dockerfile                      # Сборка Docker-образа
├── docs/
│   └── cursor_audit_result.docx    # Отчёт AI-аудита из Cursor
└── users.db                        # SQLite-база (создаётся автоматически)
```

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

## Smoke-test

Скрипт `test_endpoints.py` проверяет запущенный API и выводит отчёт:

```
[OK] GET /health
[OK] POST /adduser
[FAIL] GET /wrong
```

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

Образ настроен на порт **8091** (`EXPOSE 8091`, `ENV PORT=8091`).

## Docker run

Запуск контейнера:

```bash
docker run --rm -p 8091:8091 --name audit-api ai-code-audit-api
```

Проверка:

```bash
curl http://127.0.0.1:8091/health
```

Сохранение SQLite-базы между перезапусками:

```bash
docker run --rm -p 8091:8091 -v audit-data:/app ai-code-audit-api
```

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
| `API_BASE_URL` | Базовый URL для smoke-test | `http://127.0.0.1:8091` |

## Стек

- Python 3.12+
- Flask 3.0
- SQLite
- requests (smoke-test)
