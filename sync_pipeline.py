import sqlite3
import time
import datetime
import requests
import bs4
import json
import sys

DB_NAME = "habr_analytics.db"
OLLAMA_URL = "http://localhost:11434"

# Модель по умолчанию для ИИ-разметки
DEFAULT_AI_MODEL = "qwen2.5:7b"


# --------------------------------------------------------------------------
# 1. ИНИЦИАЛИЗАЦИЯ И МИГРАЦИЯ СХЕМЫ БАЗЫ ДАННЫХ
# --------------------------------------------------------------------------

def init_enhanced_db():
    """
    Создает или дополняет схему SQLite всеми служебными полями:
    - Жизненный цикл: status ('active'/'closed'), first_seen, last_seen
    - Версионирование ИИ: ai_version, ai_processed_at
    - Оценки ИИ: requirements_density, salary_score, competition_score, ai_grade
    """
    conn = sqlite3.connect(DB_NAME)
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


# --------------------------------------------------------------------------
# 2. ФАЗА 1: БЫСТРЫЙ СКАН ЛЕНТЫ ВАКАНСИЙ (БЕЗ ПАУЗ)
# --------------------------------------------------------------------------

def fetch_all_cards_from_site():
    """
    Бесконечный скан страниц Хабра до полного исчерпания ленты.
    Возвращает список базовых данных карточек.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    cards_data = []
    page = 1

    print("🌐 [ЭТАП 1/4] Быстрый скан ленты Хабр Карьеры (до конца списка)...")

    while True:
        url = f"[https://career.habr.com/vacancies?type=all&page=](https://career.habr.com/vacancies?type=all&page=){page}"
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                print(f"⚠️ Ответ сервера {response.status_code} на странице {page}. Остановка скана.")
                break

            soup = bs4.BeautifulSoup(response.text, "html.parser")
            cards = soup.find_all("div", class_="vacancy-card")
            if not cards:
                cards = soup.find_all("li", class_="vacancy-card")

            if not cards:
                print(f"🏁 Достигнут конец ленты на странице {page - 1}.")
                break

            for card in cards:
                title_elem = card.find(class_="vacancy-card__title")
                if not title_elem:
                    continue

                link_elem = title_elem.find("a") if title_elem.name != "a" else title_elem
                if not link_elem:
                    continue

                link = "[https://career.habr.com](https://career.habr.com)" + link_elem["href"]
                v_id = link.split("/")[-1].split("?")[0]
                title = title_elem.get_text().strip()

                company_elem = card.find(class_="vacancy-card__company") or card.find(
                    class_="vacancy-card__company-title")
                company = company_elem.get_text().strip() if company_elem else "Не указана"

                skills_elem = card.find(class_="vacancy-card__skills")
                skills = ", ".join(
                    [a.get_text().strip() for a in skills_elem.find_all(["a", "span"])]) if skills_elem else ""

                meta_elem = card.find(class_="vacancy-card__meta")
                experience = meta_elem.get_text().strip() if meta_elem else "Не указан"

                salary_elem = card.find(class_="vacancy-card__salary")
                salary = salary_elem.get_text().strip() if salary_elem else "ЗП не указана"

                cards_data.append({
                    "id": v_id,
                    "title": title,
                    "company": company,
                    "salary": salary,
                    "experience": experience,
                    "skills": skills,
                    "link": link
                })

            page += 1

        except Exception as e:
            print(f"⚠️ Ошибка сети при сканировании страницы {page}: {e}")
            break

    print(f"📊 Найдено активных карточек на сайте: {len(cards_data)} шт.")
    return cards_data


# --------------------------------------------------------------------------
# 3. ФАЗА 2: СИНХРОНИЗАЦИЯ С БД И СКАЧИВАНИЕ НОВЫХ/ИЗМЕНЕННЫХ
# --------------------------------------------------------------------------

def fetch_vacancy_description(link):
    """Точечно загружает подробный текст описания вакансии с Хабра."""
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


def sync_cards_with_db(cards_data):
    """
    Сравнивает список с сайта с базой SQLite:
    - Обновляет last_seen = today и status = 'active'.
    - Загружает описание только для новых вакансий.
    - Если заголовок или ЗП изменились у старой вакансии — сбрасывает разметку ИИ для повторного анализа.
    """
    today_str = datetime.date.today().isoformat()
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    print("\n💾 [ЭТАП 2/4] Синхронизация данных с SQLite...")

    new_count = 0
    updated_count = 0

    for card in cards_data:
        v_id = card["id"]

        cursor.execute("SELECT title, salary FROM vacancies WHERE id = ?", (v_id,))
        row = cursor.fetchone()

        if not row:
            # 1. Абсолютно новая вакансия
            time.sleep(0.8)
            desc = fetch_vacancy_description(card["link"])

            cursor.execute("""
                INSERT INTO vacancies 
                (id, title, company, salary, experience, skills, description, link, first_seen, last_seen, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
            """, (v_id, card["title"], card["company"], card["salary"],
                  card["experience"], card["skills"], desc, card["link"], today_str, today_str))

            new_count += 1
            print(f"  ✨ [НОВАЯ]: {card['title'][:45]}...")

        else:
            old_title, old_salary = row

            # 2. Проверка изменений в содержании
            if old_title != card["title"] or old_salary != card["salary"]:
                time.sleep(0.8)
                desc = fetch_vacancy_description(card["link"])

                cursor.execute("""
                    UPDATE vacancies 
                    SET title = ?, company = ?, salary = ?, experience = ?, skills = ?, description = ?,
                        last_seen = ?, status = 'active', 
                        ai_grade = NULL, requirements_density = NULL, salary_score = NULL, competition_score = NULL,
                        ai_version = NULL, ai_processed_at = NULL
                    WHERE id = ?
                """, (card["title"], card["company"], card["salary"], card["experience"],
                      card["skills"], desc, today_str, v_id))

                updated_count += 1
                print(f"  🔄 [ОБНОВЛЕНА]: {card['title'][:45]}... (Разметка ИИ сброшена)")
            else:
                # 3. Вакансия без изменений — обновляем штамп активности
                cursor.execute(
                    "UPDATE vacancies SET last_seen = ?, status = 'active' WHERE id = ?",
                    (today_str, v_id)
                )

    conn.commit()
    conn.close()
    print(f"✅ Добавлено новых: {new_count} шт. Обновлено существующих: {updated_count} шт.")


# --------------------------------------------------------------------------
# 4. ФАЗА 3: БЕЗОПАСНЫЙ SOFT DELETE (ПОРОГ 14 ДНЕЙ)
# --------------------------------------------------------------------------

def apply_soft_delete(days_threshold=14):
    """
    Переводит вакансию в статус 'closed' ТОЛЬКО если её не видели в выдаче более 14 дней.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    print(f"\n📦 [ЭТАП 3/4] Проверка устаревших вакансий (Порог: {days_threshold} дней незамеченности)...")

    cursor.execute("""
        UPDATE vacancies 
        SET status = 'closed' 
        WHERE status = 'active' 
          AND JULIANDAY('now') - JULIANDAY(last_seen) > ?
    """, (days_threshold,))

    closed_count = cursor.rowcount
    conn.commit()
    conn.close()

    if closed_count > 0:
        print(f"🔒 Переведено в архив ('closed'): {closed_count} вакансий.")
    else:
        print("✅ Все активные вакансии свежие, архив не пополнялся.")


# --------------------------------------------------------------------------
# 5. ФАЗА 4: ИИ-РАЗМЕТКА С ВЕРСИОНИРОВАНИЕМ И АВТОДОКАЧКОЙ ОПИСАНИЙ
# --------------------------------------------------------------------------

def get_active_ollama_model():
    """Проверяет доступность Ollama и возвращает целевую модель Qwen."""
    try:
        res = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        if res.status_code == 200:
            models = [m["name"] for m in res.json().get("models", [])]
            if models:
                matching = next((m for m in models if DEFAULT_AI_MODEL in m), None)
                return matching if matching else models[0]
    except Exception:
        pass
    return None


def run_ai_enrichment():
    """
    Размечает вакансии через Ollama с автодокачкой описаний при необходимости,
    записывая ai_version и ai_processed_at.
    """
    model_name = get_active_ollama_model()
    if not model_name:
        print("\n⚠️ Сервер Ollama недоступен или нет моделей. Этап ИИ-анализа пропущен.")
        return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Выбираем вакансии, у которых отсутствует хотя бы один параметр разметки
    cursor.execute("""
        SELECT id, title, description, link 
        FROM vacancies 
        WHERE (ai_grade IS NULL 
           OR salary_score IS NULL 
           OR requirements_density IS NULL 
           OR competition_score IS NULL
           OR ai_grade IN ('ERROR', 'SKIP'))
          AND status = 'active'
    """)
    unprocessed = cursor.fetchall()
    conn.close()

    if not unprocessed:
        print("\n🤖 [ЭТАП 4/4] Все активные вакансии уже полностью размечены ИИ!")
        return

    print(f"\n🤖 [ЭТАП 4/4] Запуск ИИ-анализа для {len(unprocessed)} вакансий...")
    print(f"🏷 Используемая модель: '{model_name}'")

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

    for idx, (v_id, title, desc, link) in enumerate(unprocessed, 1):
        # ⚡ АВТОДОКАЧКА: Если описание отсутствует или короткое — скачиваем его прямо сейчас
        if not desc or len(desc.strip()) < 15:
            print(f" [{idx}/{len(unprocessed)}] ⚡ Докачиваю описание: {title[:35]}...", end="", flush=True)
            time.sleep(0.8)
            desc = fetch_vacancy_description(link)

            if desc and len(desc.strip()) >= 15:
                conn_tmp = sqlite3.connect(DB_NAME)
                c_tmp = conn_tmp.cursor()
                c_tmp.execute("UPDATE vacancies SET description = ? WHERE id = ?", (desc, v_id))
                conn_tmp.commit()
                conn_tmp.close()
                print(" УСПЕШНО")
            else:
                conn_tmp = sqlite3.connect(DB_NAME)
                c_tmp = conn_tmp.cursor()
                c_tmp.execute("UPDATE vacancies SET ai_grade = 'EMPTY' WHERE id = ?", (v_id,))
                conn_tmp.commit()
                conn_tmp.close()
                print(" ❌ Не удалось скачать (пропуск)")
                continue

        print(f" [{idx}/{len(unprocessed)}] {model_name} анализирует: {title[:35]}...", end="", flush=True)

        user_content = f"Название вакансии: {title}\nОписание вакансии:\n{desc[:5000]}"

        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.0}
        }

        try:
            res = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=45)
            if res.status_code == 200:
                raw_json = res.json()["message"]["content"].strip()

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
                comp = int(data.get('competition_score', 5))
                grade = str(data.get('ai_grade', 'Middle'))
                if grade not in ['Junior', 'Middle', 'Senior']:
                    grade = 'Middle'

                now_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                conn_upd = sqlite3.connect(DB_NAME)
                c_upd = conn_upd.cursor()
                c_upd.execute("""
                    UPDATE vacancies 
                    SET requirements_density = ?, salary_score = ?, competition_score = ?, ai_grade = ?,
                        ai_version = ?, ai_processed_at = ?
                    WHERE id = ?
                """, (density, salary, comp, grade, model_name, now_ts, v_id))
                conn_upd.commit()
                conn_upd.close()
                print(" OK")
            else:
                print(" ❌ Ошибка API")
        except Exception as e:
            print(f" ❌ Ошибка: {e}")

    print("🎉 ИИ-разметка успешно завершена!")


# --------------------------------------------------------------------------
# 6. ВАЛИДАЦИЯ И ВЫВОД ИТОГОВОЙ СТАТИСТИКИ
# --------------------------------------------------------------------------

def print_db_summary():
    """Выводит сводку состояния базы данных."""
    conn = sqlite3.connect(DB_NAME)
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

    print("\n📊 ИТОГОВАЯ СТАТИСТИКА БАЗЫ ДАННЫХ:")
    print(f"  • Всего вакансий в базе: {total}")
    print(f"  • Из них активных (открытых): {active}")
    print(f"  • Успешно размечено ИИ: {analyzed}")
    if versions:
        print("  • Использованные версии моделей:")
        for ver, cnt in versions:
            print(f"     - {ver}: {cnt} шт.")


def update_database():
    print("==================================================================")
    print("🚀 ЕДИНЫЙ ПАЙПЛАЙН СИНХРОНИЗАЦИИ И АНАЛИЗА БАЗЫ ДАННЫХ")
    print("==================================================================\n")

    init_enhanced_db()
    cards = fetch_all_cards_from_site()

    if cards:
        sync_cards_with_db(cards)

    apply_soft_delete(days_threshold=14)
    run_ai_enrichment()
    print_db_summary()

    print("\n==================================================================")
    print("✨ ПАЙПЛАЙН УСПЕШНО ВЫПОЛНЕН! БАЗА ДАННЫХ В АКТУАЛЬНОМ СОСТОЯНИИ.")
    print("==================================================================\n")


if __name__ == "__main__":
    update_database()