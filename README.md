# Playerok → FunPay bot

Авто-выдача: входящая оплата на Playerok → ждём `@username` в чате → покупаем подходящий лот на FunPay → пишем продавцу ник.

По умолчанию бот в **DRY_RUN**: живые покупки и чаты заблокированы, пайплайн крутится на мок-данных.

## Локально

```bash
git clone https://github.com/VladIsLove1515/irgigs3.git
cd irgigs3
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Прогон без панели (мок-продажи → completed):

```bash
python -m src --once
```

Панель оператора:

```bash
python -m src
```

Открой [http://127.0.0.1:43147](http://127.0.0.1:43147).

Сделки пишутся в `data/deals.db`, события — туда же и в `logs/bot.log`.

## Что делает пайплайн

1. Poll новых оплат Playerok (фильтр по `PLAYEROK_LOT_IDS` или `WATCH_KEYWORDS`).
2. Если в чате нет `@username` — один раз (с кулдауном) шлёт приветствие.
3. Как только ник есть — ищет FunPay-лот, проверяет title / max price / маржу / slippage / баланс.
4. Покупает лот, пишет продавцу ник, сообщает покупателю на Playerok.
5. Застрявшие стадии (кроме ожидания ника) уходят в `needs_review`.

Live-режим не включится, пока `DRY_RUN=true`. Для live ещё нужен `LIVE_CONFIRM_TOKEN=I_ACCEPT_LIVE_RISK`. Сами live-клиенты Playerok/FunPay пока намеренно закрыты заглушками: без проверенного парсера бот не будет тратить деньги.

## Тесты

```bash
python -m pytest
```

## Структура

```
src/            код бота
src/templates/  панель
tests/          pytest
data/           SQLite (локально)
logs/           bot.log (локально)
```
