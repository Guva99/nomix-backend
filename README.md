# Nomix — backend

Бэкенд сервиса учёта личных расходов по фото чеков. Пользователь отправляет фото чека в Telegram-бота или через мобильное приложение / Telegram Mini App, модель Gemini распознаёт позиции, сервис раскладывает траты по категориям и считает статистику.

Клиентская часть (Flutter-приложение и Mini App) живёт в отдельном репозитории.

## Стек

- Python 3, FastAPI, Pydantic Settings
- PostgreSQL 15, SQLAlchemy (async) + asyncpg, Alembic
- Google Gemini — распознавание чеков по фото
- Telegram: aiogram, python-telegram-bot, авторизация через Telegram + JWT
- Docker Compose, nginx

## Что умеет

- Вход через Telegram (Mini App), выдача JWT
- Распознавание чека по фото: ответ модели приводится к строгой схеме (позиции, цены, категории, итог)
- Черновик чека: пользователь проверяет и правит результат распознавания перед сохранением
- История сохранённых чеков
- Статистика расходов по категориям и по месяцам, статистика по конкретному товару, поиск товаров
- Telegram-бот: приём фото, карточка распознанного чека с кнопками, месячные сводки

## API

Swagger доступен на `/api/docs`, ReDoc — на `/api/redoc`.

| Метод | Путь | Назначение |
|---|---|---|
| POST | `/api/telegram/login` | Вход через Telegram |
| GET | `/api/data/user` | Профиль пользователя |
| POST | `/api/bot/process-check` | Распознать чек по фото |
| GET | `/api/receipts/last-check` | Последний распознанный чек |
| POST | `/api/receipts/save-check` | Сохранить чек |
| GET | `/api/receipts/edit-check` | Редактирование черновика |
| GET | `/api/receipts/edit-saved-check` | Редактирование сохранённого чека |
| GET | `/api/receipts/saved-checks` | История чеков |
| GET | `/api/products/{product_id}` | Товар |
| GET | `/api/products/{product_id}/stats` | Статистика по товару |
| GET | `/api/products/search/{product_name}` | Поиск товара |
| GET | `/api/statistics` | Статистика расходов |
| GET | `/api/statistics/month` | Помесячная статистика по категориям |
| GET | `/api/avatar/{file_path}` | Аватар пользователя |

## Структура

```
app/
├── core/       # настройки, подключение к БД
├── deps/       # зависимости FastAPI
├── models/     # ORM-модели и Pydantic-схемы
├── routers/    # HTTP-эндпоинты
├── schemas/
├── services/   # бизнес-логика: бот, распознавание чеков, JWT, статистика
├── utils/
└── main.py
```

## Запуск

```bash
cp .env.example .env   # заполнить токен бота, ключ Gemini, секреты
docker compose up --build
```

Поднимаются три контейнера: `backend` (FastAPI), `postgres` и `nginx`. После старта API доступен через nginx, документация — на `/api/docs`.
