# MAX Bot — Say Me Hello Today

Telegram-подобный бот для MAX через GREEN-API: утреннее приветствие,
ответы на сообщения, напоминания молчунам, афоризм дня, мост к Hermes.

## Возможности

- Утренний вопрос каждому чату по индивидуальному расписанию
- Ответ на первое сообщение после утреннего вопроса (ANSWER_MESSAGES)
- Напоминание молчунам (WARNING_MESSAGES) + сводка админу
- Интеграция с Hermes через `/hermes <вопрос>` или `❇ <вопрос>`
- Поддержка разделения по роду (мужской/женский)

## Архитектура

- **bot.py** — слушатель входящих + мост Hermes (systemd service, постоянный)
- **send_daily.py** — утренняя рассылка (systemd timer, раз в час)
- **send_alerts.py** — напоминания (systemd timer, раз в час)
- **send_aphorism.py** — афоризм дня (systemd timer, раз в день)
- **state.json** — состояние (создаётся автоматически)

## Установка на Ubuntu 24.04

### 1. Системные зависимости

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git
```

### 2. Клонировать репозиторий

```bash
cd ~
git clone git@github.com:USERNAME/max-bot.git
cd max-bot
```

### 3. Создать venv и установить зависимости

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Настроить config.py

```bash
cp config.py.example config.py
nano config.py
```

Заполнить:
- `ID_INSTANCE`, `API_TOKEN` — из GREEN-API
- `ALLOWED_CHATS` — свои chatId, имена, роды, время
- `ADMIN_CHAT_ID`, `ADMIN_NAME`

### 5. Проверить работу

```bash
# Dry-run — проверить, что тексты подставляются
python -c "import config; print('OK')"

# Запустить бота вручную
python bot.py
# Ctrl+C для выхода
```

### 6. Установить systemd-юниты

```bash
sudo cp systemd/*.service systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now max-bot.service
sudo systemctl enable --now max-send-daily.timer
sudo systemctl enable --now max-send-alerts.timer
sudo systemctl enable --now max-send-aphorism.timer
```

### 7. Проверить

```bash
sudo systemctl status max-bot
systemctl list-timers | grep max
journalctl -u max-bot -f -q
```

## Обновление

```bash
cd ~/max-bot
git pull
sudo systemctl restart max-bot
```

## Логи

```bash
# Бот — в реальном времени
journalctl -u max-bot -f -q

# Рассылка — последний запуск
journalctl -u max-send-daily -n 30 -q

# Все MAX-сервисы за сегодня
journalctl -u 'max-*' --since today -q
```

## Hermes

Команды `/hermes <вопрос>` или `❇ <вопрос>` принимаются от `ADMIN_CHAT_ID`.
Каждый чат получает свою сессию `max_<chat_id>`, контекст сохраняется.

Таймаут Hermes — 120 секунд. При превышении — сообщение об ошибке.

## Лицензия

MIT