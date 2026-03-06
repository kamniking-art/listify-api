# Listify API — FastAPI Backend

## Быстрый старт

```bash
# Поднять всё одной командой
docker compose up --build

# API будет на http://localhost:8000
# Swagger docs: http://localhost:8000/docs
```

## Структура

```
app/
├── main.py                  ✅ FastAPI app + CORS + routers
├── core/
│   ├── config.py            ✅ Settings (env vars)
│   ├── database.py          ✅ SQLAlchemy async engine
│   └── auth.py              ✅ JWT + bcrypt + depends
├── models/user.py           ✅ SQLAlchemy ORM models
├── schemas.py               ✅ Pydantic schemas (in/out)
├── routers/
│   ├── auth.py              ✅ Register, login, refresh, me
│   ├── lists.py             ✅ Lists CRUD + Items CRUD
│   ├── receipts.py          ✅ Upload, status poll, confirm
│   └── other.py             ✅ Prices, Expenses, Budget, Smart
├── services/
│   └── ocr.py               ✅ Tesseract/Vision + parser + matcher
└── workers/
    └── tasks.py             ✅ Celery OCR task + cron jobs
```

## Эндпоинты

### Auth
| Method | Path | Описание |
|--------|------|----------|
| POST | /api/v1/auth/register | Регистрация |
| POST | /api/v1/auth/login | Логин |
| POST | /api/v1/auth/anonymous | Анонимный вход |
| POST | /api/v1/auth/refresh | Обновить токен |
| GET  | /api/v1/auth/me | Текущий юзер |

### Lists & Items
| Method | Path | Описание |
|--------|------|----------|
| GET  | /api/v1/lists | Все списки |
| POST | /api/v1/lists | Создать список |
| PATCH | /api/v1/lists/{id} | Обновить список |
| DELETE | /api/v1/lists/{id} | Удалить список |
| POST | /api/v1/lists/{id}/items | Добавить товар |
| PATCH | /api/v1/lists/{id}/items/{item_id}/status | Обновить статус |
| POST | /api/v1/lists/{id}/items/batch-status | Пакетное обновление |
| POST | /api/v1/lists/{id}/items/reorder | Сортировка |

### Receipts
| Method | Path | Описание |
|--------|------|----------|
| POST | /api/v1/receipts/upload | Загрузить чек (multipart) |
| GET  | /api/v1/receipts | Список чеков |
| GET  | /api/v1/receipts/{id}/status | Статус OCR (polling) |
| POST | /api/v1/receipts/{id}/confirm | Подтвердить совпадения |
| POST | /api/v1/receipts/{id}/mark-all-bought | Отметить всё куплено |

### Prices & Smart
| Method | Path | Описание |
|--------|------|----------|
| GET  | /api/v1/prices/forecast/{list_id} | Прогноз цен |
| GET  | /api/v1/prices/compare?list_id= | Сравнение магазинов |
| GET  | /api/v1/expenses/summary?period= | Сводка расходов |
| GET  | /api/v1/budget | Бюджет на месяц |
| PATCH | /api/v1/budget | Установить лимит |
| PATCH | /api/v1/budget/categories/{name} | Лимит категории |
| GET  | /api/v1/smart/suggestions | Умные рекомендации |
| POST | /api/v1/smart/autolist | Сгенерировать список |

## Переменные окружения (.env)

```env
DATABASE_URL=postgresql+asyncpg://listify:listify@localhost:5432/listify
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=your-secret-key-here
USE_LOCAL_STORAGE=true
LOCAL_STORAGE_PATH=/tmp/listify

# Опционально — Google Vision вместо Tesseract
USE_GOOGLE_VISION=false
GOOGLE_VISION_API_KEY=
```

## OCR Pipeline

```
Фото → preprocess_image() → extract_text() → parse_receipt_text() → match_items_to_list()
         (grayscale,            (Tesseract или     (store, date,          (rapidfuzz ~70%
          contrast boost)        Google Vision)     total, items)          threshold)
```

## Запуск без Docker

```bash
# PostgreSQL + Redis через Homebrew или apt
pip install -r requirements.txt

# БД
createdb listify

# API
uvicorn app.main:app --reload --port 8000

# Worker (отдельный терминал)
celery -A app.workers.tasks worker --loglevel=info
```
