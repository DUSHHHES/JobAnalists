import sqlite3

conn = sqlite3.connect("habr_analytics.db")
cursor = conn.cursor()

# Сбрасываем старую ИИ-разметку в NULL, чтобы новый скрипт переразметил всё начисто
cursor.execute("UPDATE vacancies SET requirements_density = NULL, sentiment_score = NULL, ai_grade = NULL")

conn.commit()
conn.close()
print("✅ Старая ИИ-разметка успешно сброшена! База готова к чистому анализу.")