from __future__ import annotations

WELCOME = (
    "Привет! Заказ принят ✅\n"
    "Пришли, пожалуйста, свой username одним сообщением "
    "в формате @ник — после этого сразу запущу выдачу."
)

USERNAME_CONFIRM = (
    "Принял {username}. Ищу лот и оформляю выдачу, обычно это пара минут."
)

FUNPAY_SELLER_MESSAGE = (
    "Здравствуйте! Оплатил заказ.\n"
    "Выдайте, пожалуйста, на: {username}\n"
    "Спасибо!"
)

COMPLETED_TO_BUYER = (
    "Готово: заказ у продавца, выдача запрошена на {username}. "
    "Если что-то не придёт — напиши сюда, разберём."
)

OPERATOR_NEW_SALE = "🛒 Playerok sale {sale_id}: {title} за {price}"
OPERATOR_NEED_USERNAME = "⏳ deal {deal_id}: ждём @username в чате Playerok"
OPERATOR_BOUGHT = "💳 deal {deal_id}: FunPay купили за {price}, шлём {username}"
OPERATOR_DONE = "✅ deal {deal_id}: completed → {username}"
OPERATOR_FAIL = "❌ deal {deal_id}: {error}"
