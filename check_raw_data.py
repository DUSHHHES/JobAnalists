import os
import sqlite3

# Автоматически определяем путь к базе
current_dir = os.path.dirname(os.path.abspath(__file__))
if " .venv" in current_dir or "venv" in current_dir:
    base_dir = os.path.dirname(current_dir)
else:
    base_dir = current_dir

db_path = os.path.join(base_dir, "habr_analytics.db")

print(f"🔍 Проверяю файл базы по пути: {db_path}")

if not os.path.exists(db_path):
    print("❌ Файл базы данных физически отсутствует! Запусти парсер.")
else:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Считаем общее количество записей
    cursor.execute("SELECT COUNT(*) FROM vacancies")
    total_rows = cursor.fetchone()[0]
    print(f"📊 Всего строк в таблице vacancies: {total_rows}")

    # Вытаскиваем первые 3 вакансии для осмотра
    cursor.execute("SELECT id, title, description FROM vacancies LIMIT 3")
    vacancies = cursor.fetchall()

    print("\n🧐 СМОТРИМ НА ТЕКСТ ВНУТРИ БАЗЫ:")
    print("=" * 70)

    for idx, (v_id, title, desc) in enumerate(vacancies, 1):
        print(f"Вакансия №{idx}: ID {v_id} | Название: {title}")
        if desc:
            # Показываем первые 200 символов описания, чтобы не спамить консоль
            preview = desc[:200].replace('\n', ' ')
            print(f"Текст описания (первые 200 симв.): {preview}...")
        else:
            print("❌ ТЕКСТ ОПИСАНИЯ ПУСТОЙ! (Поле description равно None или пустой строке)")
        print("-" * 70)

    conn.close()
