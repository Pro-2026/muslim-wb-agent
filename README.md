# WB AI Agent

AI-агент для управления внутренней рекламой на Wildberries.  
Стек: Python 3.11 · FastAPI · aiogram 3 · PostgreSQL · Gemini API · Railway

## Команды бота

| Команда | Описание |
|---------|----------|
| `/pull` | Синхронизировать кампании и кластеры из WB |
| `/classify` | Классифицировать новые кластеры через Gemini |
| `/review` | Просмотреть предложения AI с кнопками Удалить/Оставить |
| `/apply` | Применить подтверждённые удаления в WB |
| `/bids` | Рекомендации по ставкам (CTR/CPO-правила) |
| `/report` | Сгенерировать отчёт за вчера через Gemini |
| `/status` | Состояние сервиса и список клиентов |
| `/stop` | Пауза/возобновление планировщика |
| `/ping` | Проверка связи |

## Добавить клиента (когда есть WB-токен)

```bash
railway run --service Postgres psql $DATABASE_URL -c \
  "INSERT INTO clients (name, wb_token, telegram_chat_id) VALUES ('Имя', 'WB_TOKEN', CHAT_ID);"
```

После этого `/pull` начнёт тянуть данные.

## Переменные окружения

| Переменная | Описание |
|-----------|----------|
| `DATABASE_URL` | PostgreSQL (Railway подставляет автоматически) |
| `TELEGRAM_BOT_TOKEN` | Токен от BotFather |
| `ADMIN_USER_ID` | Telegram user ID администратора |
| `GEMINI_API_KEY` | Ключ Google Gemini API |
| `WB_TOKEN` | API-токен Wildberries (Продвижение) |
| `RAILWAY_PUBLIC_DOMAIN` | Домен для webhook (Railway подставляет автоматически) |
| `SENTRY_DSN` | Опционально, для мониторинга ошибок |

## Описание товара для классификатора

Создай файл `docs/products/<wb_campaign_id>.md` по шаблону из `docs/products/example.md`.  
Классификатор будет использовать его как контекст при анализе кластеров.

## Локальный запуск

```bash
pip install -r requirements.txt
cp .env.example .env   # заполни переменные
python -m uvicorn src.main:app --reload
```

## Деплой на Railway

1. Push в GitHub → Railway деплоит автоматически
2. Или вручную: `railway up --service wb-agent --detach`

## Автоматика (планировщик)

- Каждые 3 часа: синхронизация с WB + экспирация просроченных решений (TTL 24ч)
- Каждый день в 09:00 МСК: отчёт за вчера в Telegram
