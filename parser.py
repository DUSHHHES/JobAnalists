import sqlite3
import time
import requests
import bs4

DB_NAME = "habr_analytics.db"


def init_db():
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
            link TEXT,
            requirements_density INTEGER,
            sentiment_score INTEGER,
            ai_grade TEXT
        )
    """)
    conn.commit()
    conn.close()


def parse_single_vacancy_page(url):
    """Заходит на страницу вакансии и забирает текст описания."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return ""
        soup = bs4.BeautifulSoup(response.text, "html.parser")

        # Проверяем разные варианты блоков описания для максимальной отказоустойчивости
        desc_block = soup.find("div", class_="vacancy-description")
        if not desc_block:
            desc_block = soup.find("div", class_="style-html")
        if not desc_block:
            desc_block = soup.find("div", class_="vacancy-description__text")

        return desc_block.get_text(separator=" ").strip() if desc_block else ""
    except Exception:
        return ""


def deep_mass_parse(target_total=1000):
    """Массовый постраничный сборщик с прямым поиском карточек."""
    init_db()

    # Расширенный список тегов для гарантированного набора 1000 вакансий
    tech_queries = ["Python", "C++", "Go", "Java", "JavaScript", "Frontend", "DevOps", "QA", "Data Engineering", "C#",
                    "Backend", "Разработчик"]

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM vacancies")
    current_count = cursor.fetchone()[0]
    print(f"📊 Текущее количество вакансий в базе: {current_count}")

    if current_count >= target_total:
        print(f"✅ Цель в {target_total} вакансий уже достигнута!")
        conn.close()
        return

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    print(f"🚀 Запускаю массовый постраничный сбор до цели в {target_total} позиций...")

    for query in tech_queries:
        if current_count >= target_total:
            break

        print(f"\n🔎 Сканирую направление: [{query}]")
        page = 1

        while current_count < target_total:
            search_url = f"https://career.habr.com/vacancies?q={query}&type=all&page={page}"

            try:
                response = requests.get(search_url, headers=headers, timeout=10)

                if response.status_code == 403:
                    print("⚠️ Хабр выдал 403 (Антифрод). Включаю защитную паузу 10 секунд...")
                    time.sleep(10)
                    break
                elif response.status_code != 200:
                    print(f"⚠️ Хабр ответил статусом {response.status_code}. Меняем стек.")
                    break

                soup = bs4.BeautifulSoup(response.text, "html.parser")

                # Трюк: ищем карточки напрямую по базовому классу 'vacancy-card'
                vacancy_cards = soup.find_all("div", class_="vacancy-card")

                if not vacancy_cards:
                    # Попробуем найти элементы списков, если Хабр перешел на теги li
                    vacancy_cards = soup.find_all("li", class_="vacancy-card")

                if not vacancy_cards:
                    print(f"Выкачаны все доступные страницы для стека {query} (или карточки не найдены).")
                    break

                print(f"📄 Пагинация: Направление [{query}], Страница {page}, Найдено карточек: {len(vacancy_cards)}")

                for card in vacancy_cards:
                    if current_count >= target_total:
                        break

                    # Извлекаем заголовок и ссылку
                    title_elem = card.find("div", class_="vacancy-card__title")
                    if not title_elem:
                        title_elem = card.find("a", class_="vacancy-card__title-link")  # Резервный поиск ссылки

                    if not title_elem: continue
                    title = title_elem.get_text().strip()

                    link_elem = title_elem.find("a") if title_elem.name != "a" else title_elem
                    if not link_elem: continue
                    link = "https://career.habr.com" + link_elem["href"]
                    v_id = link.split("/")[-1].split("?")[0]

                    # Проверяем дубликаты
                    cursor.execute("SELECT 1 FROM vacancies WHERE id = ?", (v_id,))
                    if cursor.fetchone():
                        continue

                    company_elem = card.find("div", class_="vacancy-card__company-title")
                    company = company_elem.get_text().strip() if company_elem else "Не указана"

                    salary_elem = card.find("div", class_="vacancy-card__salary")
                    salary = salary_elem.get_text().strip() if salary_elem else "ЗП не указана"

                    # Бережный тайм-аут, чтобы не перегружать сервер и обходить блокировки
                    time.sleep(1.5)

                    # Скачиваем описание
                    description = parse_single_vacancy_page(link)

                    # Пишем в БД
                    cursor.execute(
                        """INSERT INTO vacancies (id, title, company, salary, description, link) 
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (v_id, title, company, salary, description, link)
                    )
                    conn.commit()

                    current_count += 1
                    print(f"  -> Успешно скачано [{current_count}/{target_total}]: {title}")

                page += 1

            except Exception as e:
                print(f"⚠️ Ошибка на странице {page}: {e}")
                time.sleep(5)
                break

    conn.close()
    print(f"\n🎉 Миссия выполнена! База успешно расширена до {current_count} вакансий.")


if __name__ == "__main__":
    deep_mass_parse(1000)