import sqlite3
import json
import os
import sys
import time
from google import genai
from google.genai import types

DB_NAME = "habr_analytics.db"

# Укажи свой API-ключ прямо здесь
GEMINI_API_KEY = "AQ.Ab8RN6LBI4az56h26BzhF-coIna0RXpF12EGqUizPXx-a-o27A"

client = genai.Client(api_key=GEMINI_API_KEY)


def init_ai_columns():
    """Добавляет новые столбцы в БД, если их еще нет"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Новые столбцы под нашу крутую математическую формулу
    columns = [
        ("requirements_density", "INTEGER"),
        ("salary_score", "INTEGER"),
        ("competition_score", "INTEGER"),
        ("ai_grade", "TEXT")
    ]
    for col_name, col_type in columns:
        try:
            cursor.execute(f"ALTER TABLE vacancies ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError:
            pass  # Если столбец уже существует, просто идем дальше
    conn.commit()
    conn.close()


def analyze_vacancy_with_gemini(title, description):
    """Отправляет вакансию в Google Gemini. Возвращает строго распарсенный JSON."""
    system_prompt = (
        f"""
Ты — строгий HR-аналитик. Проанализируй текст IT-вакансии:
Название: {title}
Описание: {description}

Верни результат СТРОГО в формате JSON с 4 ключами.
Оценивай параметры строго по шкале от 1 до 10:

1. "salary_score" (Заработная плата и финансовые условия):
   - 1-3: Зарплата ниже рынка, стажировка за копейки, либо жесткие штрафы.
   - 4-7: Средняя рыночная зарплата, стандартный соцпакет.
   - 8-10: Зарплата выше рынка, премии, акции компании, отличный ДМС.
   (Если зарплата не указана, оценивай косвенные признаки богатства компании и щедрости описания).

2. "requirements_density" (Плотность требований):
   - 1-3: Минимум требований (знание синтаксиса, желание развиваться).
   - 4-7: Стандартный стек технологий для одной роли.
   - 8-10: Ищут "человека-оркестр", гигантский список фреймворков и DevOps-инструментов.

3. "competition_score" (Индекс конкуренции):
   Оцени, насколько высока конкуренция соискателей на эту вакансию:
   - 1-3: Низкая конкуренция (очень узкая ниша, высокие требования, уровень Senior).
   - 4-7: Средняя конкуренция (стандартные Middle позиции).
   - 8-10: Огромная конкуренция (позиции Junior, стажировки, "войти в IT").

4. "ai_grade":
   Определи требуемый уровень: "Junior", "Middle" или "Senior".

Формат вывода СТРОГО валидный JSON:
{{
  "salary_score": 0,
  "requirements_density": 0,
  "competition_score": 0,
  "ai_grade": "Grade"
}}
"""
    )

    short_desc = description[:6000] if description else ""

    try:
        response = client.models.generate_content(
            model="gemini-flash-lite-latest",
            contents=f"Title: {title}\nDesc: {short_desc}",
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.0,
                response_mime_type="application/json"
            ),
        )

        raw_json = response.text.strip()
        data = json.loads(raw_json)

        # ИСПРАВЛЕНИЕ: Вытаскиваем именно те ключи, которые запросили в промпте
        salary = int(data.get('salary_score', 5))
        density = int(data.get('requirements_density', 5))
        competition = int(data.get('competition_score', 5))

        # Грейд нейросеть теперь возвращает текстом ("Junior", "Middle", "Senior")
        ai_grade = data.get('ai_grade', "Middle")
        if ai_grade not in ["Junior", "Middle", "Senior"]:
            ai_grade = "Middle"  # Защита от галлюцинаций ИИ

        return density, salary, competition, ai_grade

    except Exception as e:
        print(f"\n⚠️ Ошибка Gemini API на вакансии '{title}': {e}")
        return None


def save_batch_to_db(batch_updates):
    """Записывает пачку обновлений в базу данных одним запросом."""
    if not batch_updates:
        return
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # ИСПРАВЛЕНИЕ: Добавлены новые колонки для записи
    cursor.executemany(
        "UPDATE vacancies SET requirements_density = ?, salary_score = ?, competition_score = ?, ai_grade = ? WHERE id = ?",
        batch_updates
    )
    conn.commit()
    conn.close()
    print(f"\n💾 [ПАКЕТ ХРАНЕНИЯ]: {len(batch_updates)} вакансий успешно зафиксированы в БД!")


def enrich_data():
    init_ai_columns()

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, title, description FROM vacancies WHERE ai_grade IS NULL OR ai_grade = 'ERROR' OR ai_grade = 'SKIP'")
    vacancies = cursor.fetchall()
    conn.close()

    if not vacancies:
        print("✅ Все вакансии в базе уже успешно размечены!")
        return

    print(f"🚀 Запускаю ускоренную пакетную разметку через Google Gemini API. К обработке: {len(vacancies)}")

    batch_updates = []
    batch_size = 10

    for idx, (v_id, title, desc) in enumerate(vacancies, 1):
        if not desc or len(desc.strip()) < 15:
            # ИСПРАВЛЕНИЕ: Добавлен лишний None, так как теперь у нас 4 параметра + id
            batch_updates.append((None, None, None, 'EMPTY', v_id))
            print(f"[{idx}/{len(vacancies)}] Пропущено (пустое описание): {title}")
        else:
            print(f"[{idx}/{len(vacancies)}] Gemini обрабатывает: {title}...", end="", flush=True)

            ai_result = analyze_vacancy_with_gemini(title, desc)

            if ai_result is None:
                batch_updates.append((None, None, None, 'SKIP', v_id))
                print(" ❌ Ошибка API (Будет повторено при перезапуске)")
            else:
                # ИСПРАВЛЕНИЕ: Распаковываем 4 параметра
                density, salary, competition, grade_str = ai_result
                batch_updates.append((density, salary, competition, grade_str, v_id))
                print(" OK")

        if len(batch_updates) >= batch_size:
            save_batch_to_db(batch_updates)
            batch_updates = []

        time.sleep(4.5)

    if batch_updates:
        save_batch_to_db(batch_updates)

    print(f"\n🎉 Обработка успешно завершена! Можешь обновлять app.py и смотреть результат.")


if __name__ == "__main__":
    enrich_data()