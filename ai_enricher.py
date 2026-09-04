"""
Скрипт для ИИ-разметки вакансий через Ollama.
"""

import time
import datetime

from config import (
    DEFAULT_AI_MODEL, MIN_DESCRIPTION_LENGTH, BATCH_SIZE,
    OLLAMA_DELAY, FETCH_DELAY, MAX_DESCRIPTION_CHARS
)
from database import (
    init_db_schema, get_total_count,
    get_unprocessed_vacancies, save_batch_updates, update_vacancy_description
)
from web_parser import fetch_description_from_url
from ollama_client import check_ollama_server, select_model, query_llm, parse_model_json
from utils import clamp_score, with_file_log
from prompts import ENRICHMENT_PROMPT


def analyze_vacancy_with_ollama(title, description, active_model):
    """
    Отправляет вакансию в локальную Ollama с единым промптом из prompts.py.
    """
    short_desc = description[:MAX_DESCRIPTION_CHARS] if description else ""
    user_content = f"Название вакансии: {title}\nОписание вакансии:\n{short_desc}"

    raw_json = query_llm(active_model, ENRICHMENT_PROMPT, user_content, temperature=0.0)

    data = parse_model_json(raw_json)
    if data is None:
        print(" ❌ Модель вернула невалидный JSON")
        return None

    salary = clamp_score(data.get('salary_score', 5))
    density = clamp_score(data.get('requirements_density', 5))
    competition = clamp_score(data.get('competition_score', 5))
    ai_grade = str(data.get('ai_grade', "Middle"))

    if ai_grade not in ["Junior", "Middle", "Senior"]:
        ai_grade = "Middle"

    return density, salary, competition, ai_grade


def run_ai_labeling(vacancies, model_name):
    """
    Размечает ровно переданный список вакансий (v_id, title, desc, link,
    last_seen).

    Автодокачивает описания, батчами пишет результаты через save_batch_updates.
    Фильтрацию по статусу/полноте выполняет вызывающий.
    """
    print(f"🚀 Запускаю разметку через Ollama ({model_name}). Осталось разметить: {len(vacancies)}")

    today_str = datetime.date.today().isoformat()
    fresh = sum(1 for row in vacancies if row[4] and row[4] >= today_str)
    print(f"📊 В очереди: {len(vacancies)} шт. Из них видены сегодня: {fresh}, ранее: {len(vacancies)-fresh}")

    started = time.monotonic()

    batch_updates = []

    for idx, (v_id, title, desc, link, last_seen) in enumerate(vacancies, 1):
        processed = idx - 1
        if processed and processed % 20 == 0:
            remaining = (time.monotonic() - started) / processed * (len(vacancies) - processed)
            print(f" ⏱ {processed}/{len(vacancies)} · осталось ≈ {remaining/60:.0f} мин", flush=True)

        if not desc or len(desc.strip()) < MIN_DESCRIPTION_LENGTH:
            print(f"[{idx}/{len(vacancies)}] ⚡ Докачиваю описание для: {title[:35]}...", end="", flush=True)
            time.sleep(FETCH_DELAY)
            desc = fetch_description_from_url(link)

            if desc and len(desc.strip()) >= MIN_DESCRIPTION_LENGTH:
                update_vacancy_description(v_id, desc)
                print(" УСПЕШНО ДОКАЧАНО")
            else:
                now_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                batch_updates.append((None, None, None, 'EMPTY', model_name, now_ts, v_id))
                print(" ❌ Не удалось скачать (пропускаем)")
                continue

        print(f"[{idx}/{len(vacancies)}] {model_name} обрабатывает: {title[:35]}...", end="", flush=True)
        ai_result = analyze_vacancy_with_ollama(title, desc, model_name)
        now_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if ai_result is None:
            batch_updates.append((None, None, None, 'SKIP', model_name, now_ts, v_id))
            print(" ❌ Ошибка сервера ИИ")
        else:
            density, salary, competition, grade_str = ai_result
            batch_updates.append((density, salary, competition, grade_str, model_name, now_ts, v_id))
            print(" OK")

        if len(batch_updates) >= BATCH_SIZE:
            save_batch_updates(batch_updates)
            print(f"\n💾 [СОХРАНЕНИЕ]: {len(batch_updates)} вакансий зафиксированы в БД!")
            batch_updates = []
            time.sleep(OLLAMA_DELAY)

    if batch_updates:
        save_batch_updates(batch_updates)
        print(f"\n💾 [СОХРАНЕНИЕ]: Последний батч ({len(batch_updates)}) зафиксирован в БД!")


@with_file_log
def enrich_data():
    from config import BACKEND
    if BACKEND == "ollama":
        check_ollama_server()
        active_model = select_model(DEFAULT_AI_MODEL)
    else:
        active_model = "openvino"

    init_db_schema()

    total_count = get_total_count()
    vacancies = get_unprocessed_vacancies()

    already_done = total_count - len(vacancies)
    print(f"📊 Статистика базы: Всего вакансий: {total_count} | Уже размечено: {already_done}")

    if not vacancies:
        print("✅ Все вакансии в базе уже полностью размечены!")
        return

    run_ai_labeling(vacancies, active_model)

    print(f"\n🎉 Анализ завершен! Все данные успешно обновлены.")


if __name__ == "__main__":
    enrich_data()
