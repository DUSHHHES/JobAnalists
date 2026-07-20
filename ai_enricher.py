import sqlite3
import json
import os
import sys
import time
import requests

DB_NAME = "habr_analytics.db"

# Адрес локального сервера Ollama по умолчанию
OLLAMA_URL = "http://localhost:11434"

# Какую модель мы хотим использовать в идеале
OLLAMA_MODEL = "gemma2"


def init_ai_columns():
    """Добавляет новые столбцы в БД, если их еще нет"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

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
            pass  # Столбец уже существует
    conn.commit()
    conn.close()


def get_installed_models():
    """Запрашивает у локального сервера Ollama список всех скачанных моделей."""
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if response.status_code == 200:
            data = response.json()
            return [model["name"] for model in data.get("models", [])]
    except Exception:
        pass
    return []


def analyze_vacancy_with_ollama(title, description, active_model):
    """
    Отправляет вакансию в локальную Ollama.
    Использует встроенный в Ollama режим гарантированного форматирования JSON.
    """
    system_prompt = (
        """Ты — строгий HR-аналитик. Проанализируй текст IT-вакансии.
Оцени параметры строго по шкале от 1 до 10:

1. "salary_score" (Заработная плата и финансовые условия):
   - 1-3: Зарплата ниже рынка, стажировка за копейки, либо жесткие штрафы.
   - 4-7: Средняя рыночная зарплата, стандартный соцпакет.
   - 8-10: Зарплата выше рынка, премии, акции компании, отличный ДМС.
   (Если зарплата не указана, оценивай косвенные признаки богатства компании и щедрости описания).

2. "requirements_density" (Плотность требований):
   - 1-3:  Минимум требований (знание синтаксиса, желание развиваться).
   - 4-7: Стандартный стек технологий для одной роли.
   - 8-10: Ищут "человека-оркестр", гигантский список фреймворков и DevOps-инструментов.

3. "competition_score" (Индекс конкуренции):
   Оцени, насколько высока конкуренция соискателей на эту вакансию:
   - 1-3: Низкая конкуренция (очень узкая ниша, высокие требования, уровень Senior).
   - 4-7: Средняя конкуренция (стандартные Middle позиции).
   - 8-10: Огромная конкуренция (позиции Junior, стажировки, "войти в IT").

4. "ai_grade":
   Определи требуемый уровень: "Junior", "Middle" или "Senior".

Ты должен вернуть СТРОГО валидный JSON-объект без какого-либо лишнего текста вокруг следующего формата:
{
  "salary_score": 5,
  "requirements_density": 5,
  "competition_score": 5,
  "ai_grade": "Middle"
}"""
    )

    short_desc = description[:5000] if description else ""
    user_content = f"Название вакансии: {title}\nОписание вакансии:\n{short_desc}"

    payload = {
        "model": active_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        "stream": False,
        "format": "json",  # Флаг заставляет Ollama форматировать ответ строго в JSON
        "options": {
            "temperature": 0.0  # Убираем креативность для точности оценок
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

        data = json.loads(raw_json)

        salary = int(data.get('salary_score', 5))
        density = int(data.get('requirements_density', 5))
        competition = int(data.get('competition_score', 5))

        ai_grade = data.get('ai_grade', "Middle")
        if ai_grade not in ["Junior", "Middle", "Senior"]:
            ai_grade = "Middle"

        return density, salary, competition, ai_grade

    except Exception as e:
        print(f" ❌ Ошибка парсинга JSON: {e}")
        return None


def save_batch_to_db(batch_updates):
    """Записывает пачку обновлений в базу данных одним запросом."""
    if not batch_updates:
        return
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.executemany(
        "UPDATE vacancies SET requirements_density = ?, salary_score = ?, competition_score = ?, ai_grade = ? WHERE id = ?",
        batch_updates
    )
    conn.commit()
    conn.close()
    print(f"\n💾 [ПАКЕТ ХРАНЕНИЯ]: {len(batch_updates)} вакансий успешно зафиксированы в БД!")


def enrich_data():
    global OLLAMA_MODEL

    # 1. Проверяем, запущен ли сервер Ollama локально
    try:
        requests.get(f"{OLLAMA_URL}/", timeout=3)
    except requests.exceptions.ConnectionError:
        print("\n❌ ОШИБКА: Сервер Ollama не обнаружен!")
        print("1. Убедись, что Ollama запущена на твоем компьютере.")
        print("2. Запусти в PowerShell команду: ollama serve\n")
        sys.exit(1)

    # 2. Получаем список всех установленных моделей
    installed_models = get_installed_models()

    if not installed_models:
        print("\n❌ ОШИБКА: У тебя в Ollama не скачано ни одной модели!")
        print("Пожалуйста, открой еще одно окно PowerShell (не закрывая то, где запущен 'ollama serve')")
        print(f"и запусти команду скачивания:  ollama pull {OLLAMA_MODEL}\n")
        sys.exit(1)

    # 3. Выбираем модель: если gemma2 не установлена, берем ту, что есть в наличии
    active_model = OLLAMA_MODEL
    # Ищем точное или частичное совпадение
    matching_model = next((m for m in installed_models if OLLAMA_MODEL in m), None)

    if matching_model:
        active_model = matching_model
    else:
        # Если нашей gemma2 нет, берем самую первую из списка установленных у пользователя
        active_model = installed_models[0]
        print(f"⚠️ Модель '{OLLAMA_MODEL}' не найдена локально.")
        print(f"🔄 Автоматически переключаюсь на твою установленную модель: '{active_model}'!")

    init_ai_columns()

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, title, description 
        FROM vacancies 
        WHERE ai_grade IS NULL OR ai_grade = 'ERROR' OR ai_grade = 'SKIP'
    """)
    vacancies = cursor.fetchall()
    conn.close()

    if not vacancies:
        print("✅ Все вакансии в базе уже успешно размечены!")
        return

    print(
        f"🚀 Запускаю локальный анализ через Ollama (Активная модель: {active_model}). Осталось разметить: {len(vacancies)}")

    batch_updates = []
    batch_size = 10

    for idx, (v_id, title, desc) in enumerate(vacancies, 1):
        if not desc or len(desc.strip()) < 15:
            batch_updates.append((None, None, None, 'EMPTY', v_id))
            print(f"[{idx}/{len(vacancies)}] Пропущено (пустое описание): {title}")
        else:
            print(f"[{idx}/{len(vacancies)}] Ollama ({active_model}) обрабатывает: {title}...", end="", flush=True)

            ai_result = analyze_vacancy_with_ollama(title, desc, active_model)

            if ai_result == "MODEL_NOT_FOUND":
                print(f"\n\n❌ ОШИБКА 404: Модель '{active_model}' внезапно пропала из Ollama!")
                if batch_updates:
                    save_batch_to_db(batch_updates)
                sys.exit(1)

            elif ai_result is None:
                batch_updates.append((None, None, None, 'SKIP', v_id))
            else:
                density, salary, competition, grade_str = ai_result
                batch_updates.append((density, salary, competition, grade_str, v_id))
                print(" OK")

        if len(batch_updates) >= batch_size:
            save_batch_to_db(batch_updates)
            batch_updates = []

        time.sleep(0.05)

    if batch_updates:
        save_batch_to_db(batch_updates)

    print(f"\n🎉 Локальный анализ успешно завершен! Все новые данные зафиксированы в базе {DB_NAME}.")


if __name__ == "__main__":
    enrich_data()