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


def deep_mass_parse(target_total=2500):
    """Массовый бесшовный сборщик ВСЕХ вакансий с авто-исправлением пропущенных полей."""
    init_db()

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM vacancies")
    current_count = cursor.fetchone()[0]
    print(f"📊 Текущее количество вакансий в базе: {current_count}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    print(f"🚀 Запускаю сканирование ленты Хабра до упора (цель: {target_total})...")

    page = 1
    no_more_vacancies = False

    while current_count < target_total and not no_more_vacancies:
        search_url = f"https://career.habr.com/vacancies?type=all&page={page}"

        try:
            response = requests.get(search_url, headers=headers, timeout=10)

            if response.status_code == 403:
                print("⚠️ Хабр выдал 403 (Антифрод). Включаю защитную паузу 15 секунд...")
                time.sleep(15)
                continue
            elif response.status_code != 200:
                print(f"⚠️ Хабр ответил статусом {response.status_code}. Прекращаем сбор.")
                break

            soup = bs4.BeautifulSoup(response.text, "html.parser")

            # Ищем карточки вакансий
            vacancy_cards = soup.find_all("div", class_="vacancy-card")
            if not vacancy_cards:
                vacancy_cards = soup.find_all("li", class_="vacancy-card")

            if not vacancy_cards:
                print(f"\n🏁 Достигнут абсолютный конец ленты вакансий на странице {page}!")
                no_more_vacancies = True
                break

            print(f"📄 Страница {page}: найдено {len(vacancy_cards)} карточек.")

            for card in vacancy_cards:
                if current_count >= target_total:
                    break

                # Извлекаем заголовок и ссылку
                title_elem = card.find(class_="vacancy-card__title")
                if not title_elem:
                    title_elem = card.find(class_="vacancy-card__title-link")

                if not title_elem:
                    continue
                title = title_elem.get_text().strip()

                link_elem = title_elem.find("a") if title_elem.name != "a" else title_elem
                if not link_elem:
                    continue
                link = "https://career.habr.com" + link_elem["href"]
                v_id = link.split("/")[-1].split("?")[0]

                # ИСПРАВЛЕНИЕ: Бронированный и тего-независимый поиск компании
                company_elem = card.find(class_="vacancy-card__company")
                if not company_elem:
                    company_elem = card.find(class_="vacancy-card__company-title")

                if company_elem:
                    company = company_elem.get_text().strip()
                else:
                    # Резервный поиск ссылки на профиль компании
                    comp_link = card.find("a", href=lambda h: h and "/companies/" in h)
                    company = comp_link.get_text().strip() if comp_link else "Не указана"

                # Считываем навыки
                skills_elem = card.find(class_="vacancy-card__skills")
                if skills_elem:
                    skills_list = [el.get_text().strip() for el in skills_elem.find_all(["a", "span"])]
                    skills_list = list(dict.fromkeys([s for s in skills_list if s]))  # чистим дубли
                    skills = ", ".join(skills_list)
                else:
                    skills = ""

                # Считываем опыт работы
                meta_elem = card.find(class_="vacancy-card__meta")
                experience = meta_elem.get_text().strip() if meta_elem else "Не указан"

                # Считываем зарплату
                salary_elem = card.find(class_="vacancy-card__salary")
                salary = salary_elem.get_text().strip() if salary_elem else "ЗП не указана"

                # ПРОВЕРКА ДУБЛИКАТОВ И РЕЖИМ АВТО-ИСПРАВЛЕНИЯ КОМПАНИЙ
                cursor.execute("SELECT company, skills, experience FROM vacancies WHERE id = ?", (v_id,))
                db_row = cursor.fetchone()

                if db_row:
                    db_company, db_skills, db_experience = db_row

                    # Проверяем, нужно ли восстановить "Не указана" / пустые поля для уже скачанной вакансии
                    needs_repair = False
                    repair_fields = []
                    repair_params = []

                    if (db_company is None or db_company == "Не указана") and company != "Не указана":
                        repair_fields.append("company = ?")
                        repair_params.append(company)
                        needs_repair = True

                    if (db_skills is None or db_skills == "") and skills != "":
                        repair_fields.append("skills = ?")
                        repair_params.append(skills)
                        needs_repair = True

                    if (db_experience is None or db_experience == "Не указан") and experience != "Не указан":
                        repair_fields.append("experience = ?")
                        repair_params.append(experience)
                        needs_repair = True

                    if needs_repair:
                        repair_params.append(v_id)
                        cursor.execute(
                            f"UPDATE vacancies SET {', '.join(repair_fields)} WHERE id = ?",
                            tuple(repair_params)
                        )
                        conn.commit()
                        print(f"  ⚡ [АВТО-ИСПРАВЛЕНИЕ] Заполнено для '{title}': компания -> '{company}'")

                    # Переходим к следующей вакансии БЕЗ ожидания и загрузки страницы описания (экономит 100% времени)
                    continue

                # Если вакансия абсолютно новая — делаем бережную паузу и качаем описание
                time.sleep(1.5)
                description = parse_single_vacancy_page(link)

                # Пишем в БД полностью заполненную строку
                cursor.execute(
                    """INSERT OR IGNORE INTO vacancies (id, title, company, salary, experience, skills, description, link) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (v_id, title, company, salary, experience, skills, description, link)
                )
                conn.commit()

                current_count += 1
                print(f"  -> Успешно докачано [{current_count}]: {title}")

            page += 1

        except Exception as e:
            print(f"⚠️ Ошибка на странице {page}: {e}")
            time.sleep(5)
            break

    conn.close()
    print(f"\n🎉 Сбор и авто-исправление успешно завершены! Уникальных вакансий: {current_count}")


if __name__ == "__main__":
    deep_mass_parse(2500)