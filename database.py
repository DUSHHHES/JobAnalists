"""
Модуль для работы с базой данных SQLite.
Содержит функции инициализации схемы и CRUD-операции.
"""

import sqlite3
from typing import List, Tuple, Optional, Dict, Any

from config import DB_NAME


def get_connection() -> sqlite3.Connection:
    """
    Возвращает подключение к базе данных в WAL-режиме
    с таймаутом ожидания блокировки.
    """
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout = 3000")
    return conn


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

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_vacancies_status_last_seen
        ON vacancies(status, last_seen)
    """)

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


def get_unprocessed_vacancies(active_only=False) -> List[Tuple]:
    """
    Возвращает список вакансий, которые требуют ИИ-разметки.

    active_only=True ограничивает выборку вакансиями в статусе 'active'.
    """
    query = """
        SELECT id, title, description, link, last_seen
        FROM vacancies
        WHERE ai_grade IS NULL
           OR salary_score IS NULL
           OR requirements_density IS NULL
           OR competition_score IS NULL
           OR ai_grade IN ('ERROR', 'SKIP')
    """
    if active_only:
        query += "  AND status = 'active'"
    query += "  ORDER BY last_seen DESC"

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(query)
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


def save_k_snapshots(rows):
    """
    Сохраняет дневные снимки коэффициента востребованности.

    rows: iterable кортежей (snapshot_date, technology, ai_grade,
    vacancies_count, k_score). Повторный снимок той же пары
    технология/грейд за ту же дату заменяет прежнее значение.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS k_snapshots (
            snapshot_date TEXT,
            technology TEXT,
            ai_grade TEXT,
            vacancies_count INTEGER,
            k_score REAL,
            PRIMARY KEY (snapshot_date, technology, ai_grade)
        )
    """)
    cursor.executemany(
        "INSERT OR REPLACE INTO k_snapshots VALUES (?, ?, ?, ?, ?)",
        list(rows)
    )
    conn.commit()
    conn.close()


def get_k_history(technology, ai_grade):
    """
    Возвращает историю коэффициента по паре технология/грейд
    как список кортежей (snapshot_date, k_score), упорядоченный по дате.
    Если таблица ещё не создана, возвращает пустой список.
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT snapshot_date, k_score FROM k_snapshots "
            "WHERE technology = ? AND ai_grade = ? "
            "ORDER BY snapshot_date",
            (technology, ai_grade)
        )
        history = cursor.fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        if 'conn' in locals():
            conn.close()
    return history