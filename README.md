# MONNEY v5 — Telegram Mini App

В комплекте 3 основных файла: `bot.py`, `webapp.py`, `requirements.txt`.

## Bothost
1. Загрузить эти файлы в корень репозитория.
2. В переменных окружения оставить `BOT_TOKEN` и `DATA_DIR=/app/data` (если используете).
3. В настройках Bothost включить домен и указать внутренний порт, который выдаёт Bothost через `PORT` (обычно 3000/8000).
4. Сделать новый deploy/redeploy.
5. Проверить, что в логах есть `MONNEY v5 + Mini App запущен.` и `[MONNEY WEB]`.
6. В BotFather открыть настройки Mini App и указать HTTPS-адрес домена Bothost.

Mini App использует Telegram `initData` для авторизации; токен бота не попадает в браузер.
