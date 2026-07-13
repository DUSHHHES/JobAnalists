import sqlite3
import json
import ollama
import sys

DB_NAME = "habr_analytics.db"


def init_ai_columns():
    """Добавляем новые колонки в базу, если их еще нет."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Добавляем колонки по одной (try/except защищает, если они уже созданы)
    columns = [
        ("requirements_density", "INTEGER"),
        ("sentiment_score", "INTEGER"),
        ("ai_grade", "TEXT")  # Сюда будем писать строгий текст 'Junior', 'Middle', 'Senior'
    ]

    for col_name, col_type in columns:
        try:
            cursor.execute(f"ALTER TABLE vacancies ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError:
            pass  # Колонка уже существует

    conn.commit()
    conn.close()


def analyze_vacancy_with_ai(title, description):
    """
    Отправляет вакансию в Ollama.
    Использует цифры 1, 2, 3 для грейдов, чтобы избежать проблем с токенами ИИ.
    """
    system_prompt = (
        "You are an IT Recruiter API. Analyze the job description and return ONLY a valid JSON object.\n"
        "Keys to return:\n"
        "1. 'density': Requirements complexity (integer from 1 to 10).\n"
        "2. 'sentiment': Company's willingness to mentor/train (integer from 1 to 10).\n"
        "3. 'grade_code': Candidate level. Return ONLY integer: 1 for Junior, 2 for Middle, 3 for Senior.\n\n"
        "Example output:\n"
        '{"density": 5, "sentiment": 8, "grade_code": 2}'
    )

    user_content = f"Job Title: {title}\nDescription:\n{description}"

    try:
        response = ollama.chat(
            model='llama3',
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_content}
            ],
            format='json',
            options={'temperature': 0.0}
        )

        raw_json = response['message']['content'].strip()
        data = json.loads(raw_json)

        # Строгая валидация полей из JSON
        density = int(data['density'])
        sentiment = int(data['sentiment'])
        grade_code = int(data['grade_code'])

        # Проверяем диапазоны, чтобы ИИ не выдал "15 из 10"
        if not (1 <= density <= 10) or not (1 <= sentiment <= 10):
            raise ValueError("Метрики вышли за пределы диапазона 1-10")

        # Мапим цифровые коды обратно в понятные сайту строки
        grade_map = {1: "Junior", 2: "Middle", 3: "Senior"}
        grade_str = grade_map.get(grade_code, "Middle")

        return density, sentiment, grade_str

    except (json.JSONDecodeError, KeyError, ValueError) as e:
        # Не жрем ошибку молча, а возвращаем None, чтобы забраковать запись
        print(f"⚠️ Ошибка парсинга ИИ для '{title}': {e}", file=sys.stderr)
        return None


def enrich_data():
    init_ai_columns()

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Вытаскиваем записи, где разметка еще не проводилась
    cursor.execute("SELECT id, title, description FROM vacancies WHERE ai_grade IS NULL")
    vacancies = cursor.fetchall()

    if not vacancies:
        print("✅ Все вакансии в базе уже успешно обработаны ИИ!")
        conn.close()
        return

    print(f"🤖 Начинаю пакетный ИИ-анализ вакансий. Всего к обработке: {len(vacancies)}")

    # Кэш в оперативной памяти для пакетной вставки
    db_update_cache = []
    broken_records_count = 0

    for idx, (v_id, title, desc) in enumerate(vacancies, 1):
        # Критика друга: Бракуем записи без описания сразу, они срут в статистику
        if not desc or len(desc.strip()) < 10:
            print(f"[{idx}/{len(vacancies)}] ❌ Забраковано (нет описания): {title}")
            # Помечаем в базе как ERROR, чтобы скрипт не мучал её при следующем запуске
            db_update_cache.append((-1, -1, "ERROR", v_id))
            broken_records_count += 1
            continue

        print(f"[{idx}/{len(vacancies)}] Llama 3 анализирует: {title}")

        ai_result = analyze_vacancy_with_ai(title, desc)

        if ai_result is None:
            # Если ИИ прислал битый JSON — бракуем запись, пишем ERROR
            db_update_cache.append((-1, -1, "ERROR", v_id))
            broken_records_count += 1
        else:
            density, sentiment, grade_str = ai_result
            # Складываем данные в кэш
            db_update_cache.append((density, sentiment, grade_str, v_id))

    # Критика друга: Пушим все данные в БД ОДНИМ ПАКЕТОМ (транзакцией)
    if db_update_cache:
        print(f"\n📦 Записываю пакет из {len(db_update_cache)} обновлений в базу данных...")
        cursor.executemany(
            "UPDATE vacancies SET requirements_density = ?, sentiment_score = ?, ai_grade = ? WHERE id = ?",
            db_update_cache
        )
        conn.commit()

    conn.close()
    print(
        f"🎉 Разметка завершена! Успешно обработано: {len(db_update_cache) - broken_records_count}, забраковано: {broken_records_count}")


if __name__ == "__main__":
    enrich_data()