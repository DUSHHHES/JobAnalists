import os
import sqlite3
from collections import Counter
import pandas as pd


def analyze_data():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if " .venv" in current_dir or "venv" in current_dir:
        base_dir = os.path.dirname(current_dir)
    else:
        base_dir = current_dir

    db_path = os.path.join(base_dir, "habr_analytics.db")

    if not os.path.exists(db_path):
        print(f"❌ Файл базы данных НЕ найден по пути: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    # ВАЖНО: забираем еще и колонку description (описание)
    query = "SELECT title, experience, description FROM vacancies"

    try:
        df = pd.read_sql_query(query, conn)
    except Exception as e:
        print(f"❌ Ошибка при чтении таблицы 'vacancies': {e}")
        return
    finally:
        conn.close()

    if df.empty:
        print("⚠️ Таблица вакансий пуста!")
        return

    print(f"📊 Успешно загружено вакансий для анализа: {len(df)}\n")

    # === РАЗДЕЛ 1: Контекстный анализ хард-скиллов из описания ===
    print("🔥 ТОП-10 САМЫХ ВОСТРЕБОВАННЫХ НАВЫКОВ (Контекстный анализ):")

    # Словарь технологий, которые мы ищем в тексте (можешь дополнять его)
    tech_keywords = [
        "Osi model",
        "python",
        "django",
        "flask",
        "fastapi",
        "postgresql",
        "docker",
        "Linux",
        "git",
        "asyncio",
        "celery",
        "redis",
        "kubernetes",
        "pandas",
        "pytest",
        "rest api",
        "graphql",
        "nosql",
        "mongodb",
        "aws",
        "cicd",
    ]

    detected_skills = []

    for desc in df["description"].dropna():
        desc_lower = desc.lower()
        # Проверяем, какие технологии упоминаются в описании этой вакансии
        for tech in tech_keywords:
            if tech in desc_lower:
                detected_skills.append(tech)

    skills_counter = Counter(detected_skills)

    top_skills = []
    for count, (skill, freq) in enumerate(skills_counter.most_common(10), 1):
        percentage = (freq / len(df)) * 100
        print(
            f"{count}. {skill.upper() if len(skill)<5 else skill.capitalize()} — встречается в {percentage:.1f}% вакансий"
        )
        top_skills.append(skill)

    if not detected_skills:
        print(
            "ℹ️ В описаниях не найдено ключевых слов. Проверь, заполнено ли поле description в БД."
        )

    print("-" * 50)

    # === РАЗДЕЛ 2: Анализ грейдов ===
    print("📈 РАСПРЕДЕЛЕНИЕ ПО ГРЕЙДАМ (ТРЕБУЕМЫЙ ОПЫТ):")

    def categorize_grade(row):
        title = str(row["title"]).lower()
        exp = str(row["experience"]).lower()

        is_junior = any(
            x in title or x in exp
            for x in ["junior", "младший", "стажер", "intern"]
        )
        is_senior = any(
            x in title or x in exp
            for x in [
                "senior",
                "старший",
                "ведущий",
                "lead",
                "teamlead",
                "тимлид",
            ]
        )
        is_middle = any(
            x in title or x in exp for x in ["middle", "средний"]
        )

        if is_junior:
            return "Junior"
        elif is_senior:
            return "Senior"
        else:
            return "Middle"

    df["grade"] = df.apply(categorize_grade, axis=1)
    grade_counts = df["grade"].value_counts()

    for grade, count_val in grade_counts.items():
        pct = (count_val / len(df)) * 100
        print(f"• {grade}: {count_val} вак. ({pct:.1f}%)")

    print("-" * 50)

    return df, top_skills


if __name__ == "__main__":
    analyze_data()