# Changelog

Все значимые изменения проекта MAX Bot.

## [3.1.0] - 2026-10-17

### ✨ Добавлено
- Редактирование вложений через `PUT /messages` с `attachments`
- Enrich url с retry (5 попыток × 1.5 сек) для новых картинок
- Контекстное меню по правой кнопке мыши (ПКМ)
- Долгое нажатие на мобиле (500 мс) для открытия меню
- Склонение по полу в алерте администратора (`ответил` / `ответила`)
- Современный стиль контекстного меню:
  - SVG-иконки (Feather-style)
  - Blur-фон (`backdrop-filter`)
  - Плавная анимация появления
  - Синий hover-акцент
  - Разделитель перед опасными действиями
- Множественные вложения:
  - Картинки/видео — пачкой (до 12)
  - Файлы/аудио — по одному
  - Текст отдельно при >1 документе
- `existing_tokens` + `is_edit` для сохранения вложений при редактировании
- `_send_text_message` для отправки текста отдельно

### 🔧 Изменено
- Textarea растёт вверх (align-self: flex-end)
- Кнопка отправки — SVG-стрелка вверх (не сбрасывается на ➤)
- Enter отправляет на десктопе, Shift+Enter — новая строка
- На мобиле Enter = новая строка (отправка только кнопкой)
- Вложения над текстом в сообщении
- `FORWARD_CHATS` обновляется при AJAX-навигации
- `edit_message` принимает `attachments_json` (опционально)
- `edit_message_route` принимает `existing_tokens` + `files`

### 🐛 Исправлено
- Удаление последней картинки при редактировании
- Удаление всех вложений (PUT с пустым `attachments=[]`)
- Ошибка `_attachedFile is not defined` (заменено на `_attachedFiles`)
- Ошибка `Identifier 'msgEl' has already been declared` (дубликат в contextmenu)
- `IndexError: list index out of range` в enrich при удалении вложений
- Синхронизация брейкпоинтов CSS (640) и JS (768) → 640
- `min-width` у sidebar на мобиле (окно не сжималось < 640)
- Горизонтальный скролл на body
- Прозрачность sidebar (потерян `background` при рефакторинге)
- `mid` меняется при редактировании вложений (было DELETE+POST, стало PUT)
- Паразитный Enter на мобиле
- Скрепка срабатывала только один раз

### 📟 Инфраструктура
- Swap увеличен до 1 GB (`/swapfile2`)
- Swappiness = 10
- VS Code Server лимит памяти `--max-old-space-size=512`
- Проверка безопасности: fail2ban, iptables, соединения — всё легитимно

## [3.0.0] — 2026-10-14

### ✨ Добавлено

**Веб-интерфейс (`web/`)**
- FastAPI + Jinja2 + uvicorn, порт `9118`
- Sidebar со списком чатов, шапка с синхронизацией
- Отправка текста, вложений (file/image/video/audio)
- Редактирование и удаление сообщений
- Двусторонняя синхронизация с MAX
- **Пересылка** сообщений (`↪️ Переслать` в меню)
- **Пометка админского чата** 👑
- Emoji-picker (`@emoji-mart`)

**Вложения**
- Upload + Retry на `attachment.not.ready` (0/1/2/4/8 сек)
- **Enrich `url`** через `GET /messages?message_ids=<mid>`
- Превью: `<img>` для image, `<a href>` для file/video/audio
- Сохранение `attachments` в БД для входящих и исходящих

**Бот (`bot.py`)**
- Извлечение `attachments` из `GET /updates`
- Сохранение вложений для `TYPE_HERMES_REQ`, `TYPE_ANSWER`, `TYPE_SERVICE`

**Скрипты**
- `setup_bot.py`: показ **модели LLM**, очистка БД под новую схему
- `hermes_session_model.py`, `import_history.py`, `logs.sh`, `test_attach.py`

**Инфраструктура**
- `systemd/max-web.service` — новый
- `config.py.example` — шаблон с заглушками
- `requirements.lock` — точные версии

### 🔧 Изменено

- `shared/repository.py`: `update_attachments`, `insert_message(attachments=...)`
- `web/app.py`: enrich + retry
- `index.html`: модалка пересылки, 👑, условный рендер `m.text`, `<a href>`
- `style.css`: `.forward-modal*`, `.admin-badge`, `.attachment-*`
- `systemd/max-bot.service`: `Restart=on-failure`, `After=network-online.target`, `LANG/LC_ALL`

### 🐛 Исправлено

- Дублирование `📎 [file]` + `📄 filename`
- Задвоение ответа Hermes (`_ans` в БД)
- Двойная отправка утреннего при `msg_id=None`
- `attachment.not.ready` при отправке файлов
- Пустые записи в БД для входящих с вложениями

### ⚠️ Известные ограничения

- **Пересылка** работает **только для текста**
- Free-модели OpenRouter нестабильны (`404`)
- `seen_ids` в `bot.py` растёт бесконечно

### 🗑 Удалено

- Старые скрипты: `migrate_db.py`, `send_alerts.py`, `send_daily.py`, `test_send.py`, `test_send1.py`
- Старые systemd-сервисы: `max-send-alerts`, `max-send-daily`, `max-send-aphorism`
- Корневой `db.py`, `chat_messages.py`, `test_db.py` (заменены на `shared/`)


## [2.1.0] — 2026-10-09

### 🎉 Новое

- **`weather.py`** — модуль погоды с Яндекс.Погоды через HTML-парсинг (без API и без Hermes).
  - Координаты города определяются через Nominatim (OpenStreetMap).
  - Slug/GeoID города — автоматически через Яндекс.Погоду по координатам.
  - Парсинг скрытых `<p class="A11Y_visuallyHidden">` — температура, ощущается, ветер, влажность, давление, почасовой, прогноз.
  - Дополнительные страницы `/allergies` (пыльца) и `/magnetic-storms` (магнитное поле).
  - `--resolve yandex.ru:443:77.88.44.55` — обход проблемы с systemd-resolved.
  - Почасовой прогноз: с 09:00 локального времени, 12 записей.
  - Эмодзи-иконки погоды, снег → 🌨️.
  - Debug-логи через `WEATHER_DEBUG=1`.
- **`wish_worker`** в `bot.py` — отправляет пожелание (TypeID=2) после ответа на утреннее, независимо от времени.

### 🔧 Изменено

- `_send_weather` в `bot.py` — теперь вызывает `weather.get_weather(city)` вместо Hermes.
- Удалена `get_weather_for_chat` — больше не нужна.
- `db.py` — единая схема `MessagesDB` / `MessagesRel` (удалены старые `messages` / `messages_rel`).

### 🐛 Исправлено

- Дубли утренних сообщений — отключены `max-send-*.timer` (остатки старой архитектуры).
- Пожелание не уходило после ответа — исправлено через `wish_worker`.
- Погода падала с `HTTP 400` от YandexGPT — теперь полностью без Hermes.
- `--resolve` для yandex.ru — работает при отсутствии DNS.

### ⚠️ Известные ограничения

- Nominatim требует User-Agent и имеет лимит 1 запрос/сек (у нас кэш в памяти).
- Если Яндекс изменит вёрстку — регулярки могут отвалиться.
- Для Nominatim нужен доступ в интернет (не только к yandex.ru).