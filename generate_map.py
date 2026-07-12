import sqlite3
import json
import ollama
import os
import re

DB_NAME = "habr_analytics.db"


def generate_dynamic_map():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT title FROM vacancies")
    unique_titles = [row[0] for row in cursor.fetchall()]
    conn.close()

    print(f"📦 Всего уникальных вакансий: {len(unique_titles)}")

    # Разбиваем список на порции по 50 штук
    batch_size = 50
    final_data = {}

    for i in range(0, len(unique_titles), batch_size):
        batch = unique_titles[i:i + batch_size]
        print(f"🤖 Анализирую порцию {i // batch_size + 1}...")

        system_prompt = (
            "You are a strict data formatting API. "
            "Group the provided job titles into IT categories. "
            "Respond ONLY with a valid JSON object: {\"CategoryName\": \"regex|pattern\"}."
        )

        try:
            response = ollama.chat(
                model='llama3',
                messages=[
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': "\n".join(batch)}
                ],
                format='json',
                options={'temperature': 0.0}
            )

            chunk_data = json.loads(response['message']['content'])

            # Объединяем результаты в один словарь
            if isinstance(chunk_data, dict):
                final_data.update(chunk_data)
            elif isinstance(chunk_data, list):
                # Если ИИ опять начал делать списки, простейшая попытка слияния
                for item in chunk_data:
                    if isinstance(item, dict):
                        final_data.update(item)

        except Exception as e:
            print(f"⚠️ Ошибка на порции {i}: {e}. Пропускаем...")

    # Сохраняем итоговый JSON
    with open("dynamic_categories.json", "w", encoding="utf-8") as f:
        json.dump(final_data, f, ensure_ascii=False, indent=4)

    print(f"✅ Успех! Категории ИИ сохранены: {list(final_data.keys())}")


if __name__ == "__main__":
    generate_dynamic_map()