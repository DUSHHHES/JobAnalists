import sqlite3
import json
import ollama
import re

DB_NAME = "habr_analytics.db"


def init_ai_columns():
    """Добавляем новые колонки, включая ИИ-грейд."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("ALTER TABLE vacancies ADD COLUMN requirements_density INTEGER")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE vacancies ADD COLUMN sentiment_score INTEGER")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE vacancies ADD COLUMN ai_grade TEXT")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()


def analyze_vacancy_with_ai(description):
    """Отправляет текст в Ollama и получает 3 метрики (включая грейд)."""
    system_prompt = (
        "Ты — опытный IT-рекрутер. Проанализируй текст вакансии и верни СТРОГО один валидный JSON-словарь с тремя ключами.\n"
        "1. requirements_density: Плотность требований (от 1 до 10).\n"
        "2. sentiment_score: Готовность обучать (от 1 до 10).\n"
        "3. grade: На основе текста определи уровень кандидата. Выбери СТРОГО одно из трех слов: Junior, Middle, Senior.\n\n"
        "Пример ответа:\n"
        '{"requirements_density": 5, "sentiment_score": 8, "grade": "Middle"}'
    )

    try:
        response = ollama.chat(
            model='llama3',
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': f"Текст вакансии:\n{description}"}
            ],
            format='json',  # Запрещаем ИИ писать лишний текст
            options={'temperature': 0.0}
        )

        result_text = response['message']['content'].strip()
        data = json.loads(result_text)

        grade = data.get("grade", "Middle")
        if grade not in ["Junior", "Middle", "Senior"]:
            grade = "Middle"

        return data.get("requirements_density", 5), data.get("sentiment_score", 5), grade
    except Exception as e:
        return 5, 5, "Middle"  # Дефолт при ошибке


def enrich_data():
    init_ai_columns()

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Ищем все вакансии, где ИИ еще не проставил свой грейд
    cursor.execute("SELECT id, title, description FROM vacancies WHERE ai_grade IS NULL")
    vacancies = cursor.fetchall()

    if not vacancies:
        print("✅ Все вакансии уже размечены ИИ!")
        conn.close()
        return

    print(f"🤖 Начинаю глубокий ИИ-анализ вакансий (осталось: {len(vacancies)})...")

    for idx, (v_id, title, desc) in enumerate(vacancies, 1):
        print(f"[{idx}/{len(vacancies)}] Llama 3 анализирует: {title}")

        if not desc:
            density, sentiment, grade = 5, 5, "Middle"
        else:
            density, sentiment, grade = analyze_vacancy_with_ai(desc)

        cursor.execute(
            "UPDATE vacancies SET requirements_density = ?, sentiment_score = ?, ai_grade = ? WHERE id = ?",
            (density, sentiment, grade, v_id)
        )
        conn.commit()

    conn.close()
    print("\n🎉 Разметка завершена! ИИ определил грейды для всех вакансий.")


if __name__ == "__main__":
    enrich_data()