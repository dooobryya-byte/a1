import sys
sys.path.insert(0, '.')
from bot import send, edit_message, HERMES_THINKING_MSG

chat_id = "8627605"

# 1. Отправляем "⏳ Думаю..."
ok, think_id = send(chat_id, HERMES_THINKING_MSG)
print(f"1. send: ok={ok}, idMessage={think_id!r}")

# 2. Пробуем заменить на текст
if ok and think_id:
    result = edit_message(chat_id, think_id, "✅ Тест: сообщение ⏳ было заменено")
    print(f"2. edit_message: {result}")
else:
    print("2. ❌ idMessage=None — edit_message не сработает")