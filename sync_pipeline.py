import sqlite3
import time
import datetime
import requests
import bs4

from config import (
    DB_NAME, DEFAULT_AI_MODEL, SOFT_DELETE_THRESHOLD_DAYS,
    HABR_HEADERS, REQUEST_TIMEOUT, FETCH_DELAY
)
from database import init_db_schema, get_unprocessed_vacancies
from web_parser import fetch_description_from_url
from ollama_client import select_model
from ai_enricher import run_ai_labeling
from utils import with_file_log


# --------------------------------------------------------------------------
# 1. ИНИЦИАЛИЗАЦИЯ И МИГРАЦИЯ СХЕМЫ БАЗЫ ДАННЫХ
# --------------------------------------------------------------------------

# Инициализация БД теперь используется из модуля database.py
# init_enhanced_db() заменена на init_db_schema()


# --------------------------------------------------------------------------
# 2. ФАЗА 1: БЫСТРЫЙ СКАН ЛЕНТЫ ВАКАНСИЙ (БЕЗ ПАУЗ)
# --------------------------------------------------------------------------

def fetch_all_cards_from_site():
    """
    Бесконечный скан страниц Хабра до полного исчерпания ленты.
    Возвращает список базовых данных карточек.
    """

    cards_data = []
    page = 1

    print("🌐 [ЭТАП 1/4] Быстрый скан ленты Хабр Карьеры (до конца списка)...")

    while True:
        url = f"https://career.habr.com/vacancies?type=all&page={page}"
        try:
            response = None
            for attempt in range(3):
                response = requests.get(url, headers=HABR_HEADERS, timeout=REQUEST_TIMEOUT)
                if response.status_code == 200:
                    break
                if attempt < 2:
                    time.sleep(FETCH_DELAY)
            if response is None or response.status_code != 200:
                code = response.status_code if response is not None else 0
                print(f"⚠️ Страница {page}: сервер ответил {code} после повторов. Возможен лимит/блокировка. Остановка скана.")
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

                link = "https://career.habr.com" + link_elem["href"]
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

        except requests.RequestException as e:
            print(f"⚠️ Ошибка сети при сканировании страницы {page}: {e}")
            break

    print(f"📊 Найдено активных карточек на сайте: {len(cards_data)} шт.")
    return cards_data


# --------------------------------------------------------------------------
# 3. ФАЗА 2: СИНХРОНИЗАЦИЯ С БД И СКАЧИВАНИЕ НОВЫХ/ИЗМЕНЕННЫХ
# --------------------------------------------------------------------------
# 3. ФАЗА 2: СИНХРОНИЗАЦИЯ С БД И СКАЧИВАНИЕ НОВЫХ/ИЗМЕНЁННЫХ
# --------------------------------------------------------------------------

# fetch_vacancy_description() теперь импортирована из web_parser.py как fetch_description_from_url

def plan_sync_actions(cards_data, existing):
    """
    Сравнивает карточки сайта с текущим состоянием базы.

    existing: dict {id: (title, salary)}.
    Возвращает кортеж (new_cards, changed_cards) — новые вакансии и вакансии,
    изменившие title или salary. Без обращений к БД и сети.
    """
    new_cards = []
    changed_cards = []

    for card in cards_data:
        row = existing.get(card["id"])
        if not row:
            new_cards.append(card)
        elif row[0] != card["title"] or row[1] != card["salary"]:
            changed_cards.append(card)

    return new_cards, changed_cards


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

    cursor.execute("SELECT id, title, salary FROM vacancies")
    existing = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}

    new_cards, changed_cards = plan_sync_actions(cards_data, existing)
    planned_ids = {card["id"] for card in new_cards} | {card["id"] for card in changed_cards}

    for card in new_cards:
        time.sleep(FETCH_DELAY)
        desc = fetch_description_from_url(card["link"])

        cursor.execute("""
            INSERT INTO vacancies
            (id, title, company, salary, experience, skills, description, link, first_seen, last_seen, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
        """, (card["id"], card["title"], card["company"], card["salary"],
              card["experience"], card["skills"], desc, card["link"], today_str, today_str))

        new_count += 1
        print(f"  ✨ [НОВАЯ]: {card['title'][:45]}...")

    for card in changed_cards:
        time.sleep(FETCH_DELAY)
        desc = fetch_description_from_url(card["link"])

        cursor.execute("""
            UPDATE vacancies
            SET title = ?, company = ?, salary = ?, experience = ?, skills = ?, description = ?,
                last_seen = ?, status = 'active',
                ai_grade = NULL, requirements_density = NULL, salary_score = NULL, competition_score = NULL,
                ai_version = NULL, ai_processed_at = NULL
            WHERE id = ?
        """, (card["title"], card["company"], card["salary"], card["experience"],
              card["skills"], desc, today_str, card["id"]))

        updated_count += 1
        print(f"  🔄 [ОБНОВЛЕНА]: {card['title'][:45]}... (Разметка ИИ сброшена)")

    touched_rows = [
        (today_str, card["id"])
        for card in cards_data
        if card["id"] not in planned_ids
    ]
    cursor.executemany(
        "UPDATE vacancies SET last_seen = ?, status = 'active' WHERE id = ?",
        touched_rows
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

# get_active_ollama_model() теперь заменена на select_model() из ollama_client.py

def run_ai_enrichment():
    """
    Размечает вакансии через Ollama/OpenVINO с автодокачкой описаний при необходимости,
    записывая ai_version и ai_processed_at.
    """
    from config import BACKEND
    if BACKEND == "ollama":
        try:
            model_name = select_model(DEFAULT_AI_MODEL)
        except SystemExit:
            print("\n⚠️ Сервер Ollama недоступен или нет моделей. Этап ИИ-анализа пропущен.")
            return
    else:
        model_name = "openvino"

    unprocessed = get_unprocessed_vacancies(active_only=True)

    if not unprocessed:
        print("\n🤖 [ЭТАП 4/4] Все активные вакансии уже полностью размечены ИИ!")
        return

    print(f"\n🤖 [ЭТАП 4/4] Запуск ИИ-анализа для {len(unprocessed)} вакансий...")
    print(f"🏷 Используемая модель: '{model_name}'")

    run_ai_labeling(unprocessed, model_name)


# --------------------------------------------------------------------------
# 6. ВАЛИДАЦИЯ И ВЫВОД ИТОГОВОЙ СТАТИСТИКИ
# --------------------------------------------------------------------------

def print_db_summary():
    """Выводит сводку состояния базы данных."""
    # Используем функцию из database.py
    from database import get_db_summary as get_summary
    stats = get_summary()

    total = stats['total']
    active = stats['active']
    analyzed = stats['analyzed']
    versions = stats['versions']

    print("\n📊 ИТОГОВАЯ СТАТИСТИКА БАЗЫ ДАННЫХ:")
    print(f"  • Всего вакансий в базе: {total}")
    print(f"  • Из них активных (открытых): {active}")
    print(f"  • Успешно размечено ИИ: {analyzed}")
    if versions:
        print("  • Использованные версии моделей:")
        for ver, cnt in versions:
            print(f"     - {ver}: {cnt} шт.")


@with_file_log
def update_database():
    print("==================================================================")
    print("🚀 ЕДИНЫЙ ПАЙПЛАЙН СИНХРОНИЗАЦИИ И АНАЛИЗА БАЗЫ ДАННЫХ")
    print("==================================================================\n")

    init_db_schema()
    cards = fetch_all_cards_from_site()

    if cards:
        sync_cards_with_db(cards)

    apply_soft_delete(days_threshold=SOFT_DELETE_THRESHOLD_DAYS)
    run_ai_enrichment()
    print_db_summary()

    print("\n==================================================================")
    print("✨ ПАЙПЛАЙН УСПЕШНО ВЫПОЛНЕН! БАЗА ДАННЫХ В АКТУАЛЬНОМ СОСТОЯНИИ.")
    print("==================================================================\n")


if __name__ == "__main__":
    update_database()