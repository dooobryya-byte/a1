import db

# 1. Пишем сообщение
rowid = db.insert_message(
    chat_id="8627605",
    id_message="test_msg_001",
    text="Привет, это тест",
    type_id=0,
)
print(f"insert_message → rowid={rowid}")

# 2. Читаем
m = db.get_message_by_id("8627605", "test_msg_001")
print(f"get_message_by_id → {m}")

# 3. Проверяем, что требует ответа (не answered)
unanswered = db.get_unanswered(chat_id="8627605", type_ids=[0, 1, 5, 7])
print(f"get_unanswered → {len(unanswered)} записей")

# 4. Создаём связку
db.insert_rel(
    chat_id="8627605",
    id_message_for="test_msg_001",
    id_message_back="test_msg_002",
)
print("insert_rel → OK")

# 5. Проверяем, что теперь сообщение отвечено
unanswered2 = db.get_unanswered(chat_id="8627605", type_ids=[0, 1, 5, 7])
print(f"После связки get_unanswered → {len(unanswered2)} записей")

# 6. Проверяем has_rel
print(f"has_rel_by_for → {db.has_rel_by_for('8627605', 'test_msg_001')}")

# 7. Читаем связки
rels = db.get_recent_rels(chat_id="8627605")
print(f"get_recent_rels → {len(rels)} записей")
for r in rels:
    print(f"  {r['id_message_for']} → {r['id_message_back']}")