import sqlite3
import json
import re
import collections
from rapidfuzz import process, fuzz
import nltk
from nltk.corpus import stopwords
from nltk.stem import SnowballStemmer

# Скачиваем список стоп-слов (предлоги, союзы, которые нужно выкинуть)
try:
    nltk.data.find('corpora/stopwords')
except LookupError:
    nltk.download('stopwords')

DB_NAME = "habr_analytics.db"

# Стеммеры для очистки окончаний и букв Е/Ё
stemmer_ru = SnowballStemmer("russian")
stemmer_en = SnowballStemmer("english")


def clean_and_stem(word):
    """Приводит слово к морфологической основе и нижнему регистру."""
    word = word.lower().replace('ё', 'е')
    # Если слово английское
    if re.match(r'[a-z]', word):
        return stemmer_en.stem(word)
    # Если русское
    elif re.match(r'[а-я]', word):
        return stemmer_ru.stem(word)
    return word


def build_smart_categories():
    print("📦 Извлекаю данные из базы для контекстного анализа...")
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # Берем только валидные вакансии
    cursor.execute("SELECT title, description FROM vacancies WHERE ai_grade != 'ERROR' AND description IS NOT NULL")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print("❌ Нет валидных данных для анализа! Сначала запусти парсер и ai_enricher.py.")
        return

    # Наш жесткий эталонный список корневых ИТ-направлений
    core_categories = ["Python", "C++", "Go", "Java", "C#", "JavaScript", "Frontend", "DevOps", "QA"]

    # Сюда будем собирать синонимы для каждой категории
    # Изначально закидываем базовые паттерны
    synonyms_map = {
        "Python": ["python", "питон"],
        "C++": ["c++", "cpp", "плюс", "c/c++"],
        "Go": ["go", "golang"],
        "Java": ["java", "джава"],
        "C#": ["c#", "шарп", ".net"],
        "JavaScript": ["javascript", "js", "typescript", "ts"],
        "Frontend": ["frontend", "фронтенд", "react", "vue", "angular"],
        "DevOps": ["devops", "девопс", "sre", "infra", "sysadmin", "администратор"],
        "QA": ["qa", "тестировщик", "test", "testing", "manual", "automation"]
    }

    print("🧠 Запускаю Левенштейна и Стемминг для анализа заголовков вакансий...")

    # Проходим по всем реальным названиям вакансий из базы
    for title, desc in rows:
        title_clean = title.lower().replace('ё', 'е')

        # Токенизируем заголовок на отдельные слова
        words = re.findall(r'[a-zA-Zа-яА-Я#\++\.]+', title_clean)

        for word in words:
            if len(word) < 2:
                continue

            # Для каждого слова из заголовка ищем, к какому ИТ-направлению оно ближе всего математически
            for category, syn_list in synonyms_map.items():
                # RapidFuzz ищет наилучшее совпадение слова со списком синонимов категории
                best_match = process.extractOne(word, syn_list, scorer=fuzz.WRatio)

                if best_match:
                    match_text, score, _ = best_match
                    # Если совпадение символов выше 85% — это синоним! (поймает опечатки)
                    if score >= 85 and word not in syn_list:
                        synonyms_map[category].append(word)

    # Превращаем списки синонимов в строгие regex-паттерны для app.py
    final_categories_map = {}
    for category, syn_list in synonyms_map.items():
        # Убираем дубликаты синонимов, если они возникли
        unique_syns = list(set(syn_list))

        # Формируем паттерн. Если это короткое слово вроде Go, защищаем его границами слова \\b
        processed_syns = []
        for s in unique_syns:
            if s.lower() == 'go' or s.lower() == 'qa':
                processed_syns.append(f"\\b{re.escape(s)}\\b")
            else:
                processed_syns.append(re.escape(s))

        final_categories_map[category] = "|".join(processed_syns)

    # Сохраняем математически точный JSON
    with open("dynamic_categories.json", "w", encoding="utf-8") as f:
        json.dump(final_categories_map, f, ensure_ascii=False, indent=4)

    print(f"✅ Успех! Алгоритмы Левенштейна сформировали карту: {list(final_categories_map.keys())}")


if __name__ == "__main__":
    build_smart_categories()