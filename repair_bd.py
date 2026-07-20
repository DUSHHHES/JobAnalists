import sqlite3

DB_NAME = "habr_analytics.db"

def reset_database():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    print("⏳ Сбрасываю старую ИИ-разметку в базе данных...")

    # Сбрасываем абсолютно все колонки разметки, включая новые метрики зарплаты и конкуренции
    cursor.execute("""
        UPDATE vacancies 
        SET requirements_density = NULL, 
            salary_score = NULL, 
            competition_score = NULL, 
            ai_grade = NULL
    """)

    conn.commit()
    conn.close()
    print("✅ Все ИИ-колонки успешно очищены! База полностью готова к чистому анализу через ai_enricher.py.")

if __name__ == "__main__":
    reset_database()