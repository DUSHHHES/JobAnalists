import sqlite3
import json
import os
import sys
import time
import datetime
import requests
import bs4

DB_NAME = "habr_analytics.db"

# Адрес локального сервера Ollama по умолчанию
OLLAMA_URL = "http://localhost:11434"

# Целевая модель по умолчанию
OLLAMA_MODEL = "qwen2.5:7b"


def init_ai_columns():
    """Добавляет необходимые столбцы в БД, если их еще нет."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    columns = [
        ("requirements_density", "INTEGER"),
        ("salary_score", "INTEGER"),
        ("competition_score", "INTEGER"),
        ("ai_grade", "TEXT"),
        ("ai_version", "TEXT"),
        ("ai_processed_at", "TEXT")
    ]
    for col_name, col_type in columns:
        try:
            cursor.execute(f"ALTER TABLE vacancies ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()


def get_installed_models():
    """Возвращает список всех установленных моделей в локальной Ollama."""
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if response.status_code == 200:
            data = response.json()
            return [model["name"] for model in data.get("models", [])]
    except Exception:
        pass
    return []


def fetch_missing_description(link):
    """Автоматически докачивает описание вакансии с Хабра, если оно отсутствует в БД."""
    if not link or not isinstance(link, str) or not link.startswith("http"):
        return ""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        res = requests.get(link, headers=headers, timeout=10)
        if res.status_code == 200:
            soup = bs4.BeautifulSoup(res.text, "html.parser")
            block = soup.find("div", class_="vacancy-description") or soup.find("div",
                                                                                class_="style-html") or soup.find("div",
                                                                                                                  class_="vacancy-description__text")
            return block.get_text(separator=" ").strip() if block else ""
    except Exception:
        pass
    return ""


def analyze_vacancy_with_ollama(title, description, active_model):
    """
    Отправляет вакансию в локальную Ollama с детальным и строгим промптом.
    """
    system_prompt = """
Ты — строгий HR-аналитик и эксперт по анализу IT-вакансий.

Проанализируй описание вакансии и оцени параметры строго по указанным критериям.

Используй только информацию, содержащуюся в тексте вакансии.
Не додумывай отсутствующие факты.
Если информации недостаточно, выставляй среднюю оценку (5), а не пытайся угадывать.

===========================================================
1. "salary_score" — Оценка заработной платы и условий труда
===========================================================

Оцени привлекательность финансовых условий по шкале от 1 до 10.

1–3
• зарплата ниже рынка;
• неоплачиваемая стажировка;
• минимальный соцпакет;
• штрафы;
• неблагоприятные условия.

4–7
• среднерыночная зарплата;
• стандартный социальный пакет;
• обычные условия труда.

8–10
• зарплата значительно выше рынка;
• бонусы;
• премии;
• опционы;
• расширенный ДМС;
• дополнительные льготы.

Если размер зарплаты отсутствует и нет достаточной информации для оценки,
верни значение 5.

===========================================================
2. "requirements_density" — Плотность требований
===========================================================

Оцени сложность вакансии и объём обязательных требований.

1–3
• минимальный стек технологий;
• небольшой список требований;
• одна область ответственности.

4–7
• типичный стек технологий;
• несколько обязательных навыков;
• стандартные требования к специалисту.

8–10
• очень широкий стек;
• большое количество обязательных технологий;
• DevOps, архитектура, CI/CD, облака;
• совмещение нескольких ролей;
• высокие требования к опыту.

===========================================================
3. "competition_score" — Предполагаемая конкуренция среди соискателей
===========================================================

Оцени вероятность того, что на данную вакансию будет большое количество подходящих кандидатов.

При оценке учитывай СОВОКУПНОСТЬ следующих факторов:

• уровень квалификации;
• распространённость используемых технологий;
• редкость специализации;
• сложность требований;
• количество обязательных навыков;
• широту технологического стека;
• предполагаемый порог входа.

Не определяй оценку только по уровню Junior/Middle/Senior.

Шкала:

1–3
• очень низкая конкуренция;
• редкая специализация;
• уникальный стек;
• высокий порог входа;
• сложные требования;
• мало потенциальных кандидатов.

4–7
• средняя конкуренция;
• типичная IT-вакансия;
• распространённые технологии;
• стандартные требования.

8–10
• высокая конкуренция;
• массовая позиция;
• распространённые технологии;
• невысокий порог входа;
• большое количество потенциальных кандидатов.

===========================================================
4. "ai_grade" — Уровень специалиста
===========================================================

Определи требуемый уровень квалификации:

• Junior
• Middle
• Senior

Используй совокупность требований вакансии, ожидаемого опыта,
самостоятельности и уровня ответственности.

===========================================================
ПРАВИЛА ОТВЕТА
===========================================================

Верни ТОЛЬКО один валидный JSON-объект.

Не добавляй:
- пояснений;
- комментариев;
- Markdown;
- ```json;
- любого текста до или после JSON.

Формат ответа:

{
  "salary_score": 5,
  "requirements_density": 5,
  "competition_score": 5,
  "ai_grade": "Middle"
}
"""

    short_desc = description[:5000] if description else ""
    user_content = f"Название вакансии: {title}\nОписание вакансии:\n{short_desc}"

    payload = {
        "model": active_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.0
        }
    }

    try:
        response = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=45)

        if response.status_code == 404:
            return "MODEL_NOT_FOUND"

        if response.status_code != 200:
            print(f" ❌ Ошибка сервера Ollama (Код {response.status_code})")
            return None

        result_data = response.json()
        raw_json = result_data["message"]["content"].strip()

        if raw_json.startswith("```"):
            lines = raw_json.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            raw_json = "\n".join(lines).strip()

        data = json.loads(raw_json)

        salary = int(data.get('salary_score', 5))
        density = int(data.get('requirements_density', 5))
        competition = int(data.get('competition_score', 5))

        ai_grade = data.get('ai_grade', "Middle")
        if ai_grade not in ["Junior", "Middle", "Senior"]:
            ai_grade = "Middle"

        return density, salary, competition, ai_grade

    except Exception as e:
        print(f" ❌ Ошибка обработки: {e}")
        return None


def save_batch_to_db(batch_updates, active_model):
    """Записывает батч обновлений в БД вместе с версией ИИ и датой."""
    if not batch_updates:
        return
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    now_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    full_batch = [
        (d, s, c, g, active_model, now_ts, v_id)
        for d, s, c, g, v_id in batch_updates
    ]

    cursor.executemany("""
        UPDATE vacancies 
        SET requirements_density = ?, salary_score = ?, competition_score = ?, ai_grade = ?,
            ai_version = ?, ai_processed_at = ?
        WHERE id = ?
    """, full_batch)

    conn.commit()
    conn.close()
    print(f"\n💾 [СОХРАНЕНИЕ]: {len(batch_updates)} вакансий зафиксированы в БД!")


def enrich_data():
    global OLLAMA_MODEL

    try:
        requests.get(f"{OLLAMA_URL}/", timeout=3)
    except requests.exceptions.ConnectionError:
        print("\n❌ ОШИБКА: Сервер Ollama не запущен!")
        print("Запусти в консоли: ollama serve\n")
        sys.exit(1)

    installed = get_installed_models()
    if not installed:
        print("\n❌ ОШИБКА: В Ollama нет ни одной скачанной модели!")
        sys.exit(1)

    active_model = OLLAMA_MODEL
    matching_model = next((m for m in installed if OLLAMA_MODEL in m), None)
    if matching_model:
        active_model = matching_model
    else:
        active_model = installed[0]
        print(f"🔄 Переключаюсь на доступную модель: '{active_model}'")

    init_ai_columns()

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM vacancies")
    total_count = cursor.fetchone()[0]

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

    already_done = total_count - len(vacancies)

    print(f"📊 Статистика базы: Всего вакансий: {total_count} | Уже размечено: {already_done}")

    if not vacancies:
        print("✅ Все вакансии в базе уже полностью размечены!")
        return

    print(f"🚀 Запускаю разметку через Ollama ({active_model}). Осталось разметить: {len(vacancies)}")

    batch_updates = []
    batch_size = 10

    for idx, (v_id, title, desc, link) in enumerate(vacancies, 1):
        # Если описание отсутствует или короткое — пробуем докачать прямо сейчас
        if not desc or len(desc.strip()) < 15:
            print(f"[{idx}/{len(vacancies)}] ⚡ Докачиваю описание для: {title[:35]}...", end="", flush=True)
            time.sleep(0.8)
            desc = fetch_missing_description(link)

            if desc and len(desc.strip()) >= 15:
                # Обновляем описание в БД
                conn = sqlite3.connect(DB_NAME)
                c = conn.cursor()
                c.execute("UPDATE vacancies SET description = ? WHERE id = ?", (desc, v_id))
                conn.commit()
                conn.close()
                print(" УСПЕШНО ДОКАЧАНО")
            else:
                batch_updates.append((None, None, None, 'EMPTY', v_id))
                print(" ❌ Не удалось скачать (вакансия удалена)")
                continue

        print(f"[{idx}/{len(vacancies)}] {active_model} обрабатывает: {title[:35]}...", end="", flush=True)

        ai_result = analyze_vacancy_with_ollama(title, desc, active_model)

        if ai_result == "MODEL_NOT_FOUND":
            print(f"\n❌ Модель '{active_model}' не найдена!")
            if batch_updates:
                save_batch_to_db(batch_updates, active_model)
            sys.exit(1)
        elif ai_result is None:
            batch_updates.append((None, None, None, 'SKIP', v_id))
        else:
            density, salary, competition, grade_str = ai_result
            batch_updates.append((density, salary, competition, grade_str, v_id))
            print(" OK")

        if len(batch_updates) >= batch_size:
            save_batch_to_db(batch_updates, active_model)
            batch_updates = []

        time.sleep(0.05)

    if batch_updates:
        save_batch_to_db(batch_updates, active_model)

    print(f"\n🎉 Анализ завершен! Все данные успешно обновлены в {DB_NAME}.")


if __name__ == "__main__":
    enrich_data()