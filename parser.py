import sqlite3
import xml.etree.ElementTree as ET
import html
import re
import requests

DB_NAME = "habr_analytics.db"


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """
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
    """
    )
    conn.commit()
    conn.close()


def clean_html(raw_html):
    """Очищает текст от HTML-тегов, которые приходят в RSS."""
    if not raw_html:
        return ""
    # Декодируем HTML-сущности (типа &lt; в <)
    cleantext = html.unescape(raw_html)
    # Вырезаем все теги <>
    cleanr = re.compile("<.*?>")
    return re.sub(cleanr, " ", cleantext).strip()


def deep_parse_habr(search_query):
    init_db()

    rss_url = "https://career.habr.com/vacancies/rss"
    params = {"q": search_query, "type": "all"}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    print(f"📡 Запрашиваю фид напрямую для: {search_query}...")
    response = requests.get(rss_url, params=params, headers=headers)

    if response.status_code != 200:
        print(f"Не удалось получить RSS-фид: {response.status_code}")
        return

    root = ET.fromstring(response.content)
    items = root.findall(".//item")

    print(f"Найдено {len(items)} вакансий в фиде. Начинаю импорт в БД...\n")

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    for idx, item in enumerate(items, 1):
        link = item.find("link").text
        v_id = link.split("/")[-1].split("?")[0]

        title = item.find("title").text

        # МЕГА-ФИЧА: забираем описание вакансии прямо из RSS!
        # Оно там лежит в HTML-верстке, мы его просто очищаем от тегов
        raw_description = item.find("description").text
        clean_description = clean_html(raw_description)

        print(f"[{idx}/{len(items)}] Записываю в базу: {title}")

        # Скиллы пока оставляем пустыми, так как аналитика теперь сама ищет их в description
        cursor.execute(
            """
            INSERT OR REPLACE INTO vacancies (id, title, salary, experience, skills, description, link)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                v_id,
                title,
                "Указана в описании",
                "См. в названии",
                "",
                clean_description,
                link,
            ),
        )

    conn.commit()
    conn.close()
    print("\n🎉 База данных habr_analytics.db заполнена НАСТОЯЩИМИ текстами!")


if __name__ == "__main__":
    # Список поисковых запросов для создания огромной и сочной базы данных
    tech_queries = [
        "Python",
        "C++",
        "Go",
        "Golang",
        "C#",
        "Java",
        "JavaScript",
        "Frontend",
        "DevOps",
        "QA"
    ]

    print("🚀 НАЧИНАЮ МАССОВЫЙ СБОР ВАКАНСИЙ ДЛЯ БАЗЫ ДАННЫХ 🚀")
    print("=" * 60)

    for query in tech_queries:
        deep_parse_habr(query)
        print("-" * 60)

    print("\n🔥 МАССОВЫЙ ИМПОРТ ЗАВЕРШЕН! База данных забита под завязку.")