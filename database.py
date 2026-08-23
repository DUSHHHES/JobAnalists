"""
Модуль для работы с базой данных SQLite.
Содержит функции инициализации схемы и CRUD-операции.
"""

import sqlite3
from typing import List, Tuple, Optional, Dict, Any

from config import DB_NAME


def get_connection() -> sqlite3.Connection:
    """Возвращает подключение к базе данных."""
    return sqlite3.connect(DB_NAME)


def init_db_schema():
    """
    Создаёт или дополняет схему SQLite всеми служебными полями:
    - Жизненный цикл: status ('active'/'closed'), first_seen, last_seen
    - Версионирование ИИ: ai_version, ai_processed_at
    - Оценки ИИ: requirements_density, salary_score, competition_score, ai_grade
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vacancies (
            id TEXT PRIMARY KEY,
            title TEXT,
            company TEXT,
            salary TEXT,
            experience TEXT,
            skills TEXT,
            description TEXT,
            link TEXT
        )
    """)

    required_columns = [
        ("first_seen", "TEXT"),
        ("last_seen", "TEXT"),
        ("status", "TEXT DEFAULT 'active'"),
        ("requirements_density", "INTEGER"),
        ("salary_score", "INTEGER"),
        ("competition_score", "INTEGER"),
        ("ai_grade", "TEXT"),
        ("ai_version", "TEXT"),
        ("ai_processed_at", "TEXT")
    ]

    for col_name, col_type in required_columns:
        try:
            cursor.execute(f"ALTER TABLE vacancies ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError:
            pass  # Колонка уже существует

    conn.commit()
    conn.close()


def get_total_count() -> int:
    """Возвращает общее количество вакансий в базе."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM vacancies")
    total_count = cursor.fetchone()[0]
    conn.close()
    return total_count


def get_unprocessed_vacancies() -> List[Tuple]:
    """
    Возвращает список вакансий, которые требуют ИИ-разметки.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, title, description, link 
        FROM vacancies 
        WHERE ai_grade IS NULL 
           OR salary_score IS NULL 
           OR requirements_density IS NULL 
           OR competition_score IS NULL
           OR ai_grade IN ('ERROR', 'SKIP')
    """)
    vacancies = cursor.fetchall()
    conn.close()
    return vacancies


def save_batch_updates(batch_updates: List[Tuple]):
    """
    Сохраняет пакет обновлений в базу данных.
    
    Args:
        batch_updates: Список кортежей (density, salary, competition, grade_str, v_id)
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.executemany("""
        UPDATE vacancies 
        SET requirements_density = ?, 
            salary_score = ?, 
            competition_score = ?, 
            ai_grade = ?,
            ai_version = ?, 
            ai_processed_at = ?
        WHERE id = ?
    """, [(item[0], item[1], item[2], item[3], item[4], item[5], item[6]) for item in batch_updates])
    conn.commit()
    conn.close()


def update_vacancy_description(v_id: str, description: str):
    """
    Обновляет описание вакансии в базе данных.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE vacancies SET description = ? WHERE id = ?", (description, v_id))
    conn.commit()
    conn.close()


def update_ai_evaluation(v_id: str, density: int, salary: int, comp: int, grade: str, 
                         model_name: str, now_ts: str):
    """
    Обновляет оценки ИИ для конкретной вакансии.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE vacancies 
        SET requirements_density = ?, salary_score = ?, competition_score = ?, ai_grade = ?,
            ai_version = ?, ai_processed_at = ?
        WHERE id = ?
    """, (density, salary, comp, grade, model_name, now_ts, v_id))
    conn.commit()
    conn.close()


def reset_ai_columns():
    """
    Сбрасывает все колонки ИИ-разметки в базе данных.
    """
    conn = get_connection()
    cursor = conn.cursor()

    print("⏳ Сбрасываю старую ИИ-разметку в базе данных...")

    cursor.execute("""
        UPDATE vacancies 
        SET requirements_density = NULL, 
            salary_score = NULL,
            competition_score = NULL,
            ai_grade = NULL
    """)

    conn.commit()
    conn.close()
    print("✅ Все ИИ-колонки успешно очищены! База полностью готова к чистому анализу.")


def get_db_summary() -> Dict[str, Any]:
    """
    Возвращает сводку состояния базы данных.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM vacancies")
    total = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM vacancies WHERE status = 'active'")
    active = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM vacancies WHERE ai_grade IN ('Junior','Middle','Senior')")
    analyzed = cursor.fetchone()[0]

    cursor.execute("SELECT ai_version, COUNT(*) FROM vacancies WHERE ai_version IS NOT NULL GROUP BY ai_version")
    versions = cursor.fetchall()

    conn.close()

    return {
        'total': total,
        'active': active,
        'analyzed': analyzed,
        'versions': versions
    }


def get_annotated_sample(sample_size: int = 30):
    """
    Возвращает случайную выборку вакансий, которые уже размечены.
    """
    import pandas as pd
    
    conn = get_connection()
    try:
        query = """
            SELECT id, title, description, salary_score, requirements_density, competition_score, ai_grade
            FROM vacancies
            WHERE ai_grade IN ('Junior', 'Middle', 'Senior')
              AND salary_score IS NOT NULL
              AND requirements_density IS NOT NULL
              AND competition_score IS NOT NULL
        """
        df = pd.read_sql(query, conn)
    except Exception as e:
        print(f"❌ Ошибка чтения из БД: {e}")
        conn.close()
        return None
    conn.close()

    if len(df) == 0:
        print("❌ В базе нет размеченных вакансий для сравнения!")
        print("Сначала запусти ai_enricher.py, чтобы разметить вакансии основной моделью.")
        return None

    actual_sample_size = min(sample_size, len(df))
    sample_df = df.sample(n=actual_sample_size, random_state=42).copy()
    return sample_df