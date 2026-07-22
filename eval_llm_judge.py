import sqlite3
import json
import sys
import pandas as pd
import numpy as np
import requests

DB_NAME = "habr_analytics.db"

# Адрес локального сервера Ollama
OLLAMA_URL = "http://localhost:11434/api/chat"

# Модель-Арбитр из твоего списка скачанных моделей
JUDGE_MODEL = "qwen2.5:7b"

# Размер контрольной случайной выборки для проверки
SAMPLE_SIZE = 30


def fetch_annotated_sample(sample_size=30):
    """Выбирает из базы случайную выборку вакансий, которые уже размечены основной моделью."""
    conn = sqlite3.connect(DB_NAME)
    query = """
        SELECT id, title, description, salary_score, requirements_density, competition_score, ai_grade
        FROM vacancies
        WHERE ai_grade IN ('Junior', 'Middle', 'Senior')
          AND salary_score IS NOT NULL
          AND requirements_density IS NOT NULL
          AND competition_score IS NOT NULL
    """
    try:
        df = pd.read_sql(query, conn)
    except Exception as e:
        print(f"❌ Ошибка чтения из БД: {e}")
        conn.close()
        return None
    conn.close()

    if len(df) == 0:
        print("❌ В базе нет размеченных вакансий для сравнения!")
        print("Сначала запусти ai_enricher.py, чтобы раз разметить вакансии основной моделью.")
        return None

    actual_sample_size = min(sample_size, len(df))
    sample_df = df.sample(n=actual_sample_size, random_state=42).copy()
    return sample_df


def get_judge_evaluation_ollama(title, description, model_name=JUDGE_MODEL):
    """
    Отправляет вакансию независимой моделью-арбитру Qwen 2.5 7B через Ollama.
    """
    system_prompt = """Ты — независимый эксперт-аудитор HR-данных. Проанализируй текст IT-вакансии.
Оцени параметры строго по шкале от 1 до 10:

1. "salary_score": Заработная плата и финансовая привлекательность (1-10).
2. "requirements_density": Плотность и сложность требований (1-10).
3. "competition_score": Индекс конкуренции соискателей (1-10).
4. "ai_grade": Требуемый грейд строго из трёх вариантов: "Junior", "Middle" или "Senior".

Верни результат СТРОГО в формате JSON без какого-либо лишнего текста:
{
  "salary_score": 5,
  "requirements_density": 5,
  "competition_score": 5,
  "ai_grade": "Middle"
}"""

    short_desc = description[:5000] if description else ""
    user_content = f"Вакансия: {title}\nОписание:\n{short_desc}"

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
        response = requests.post(OLLAMA_URL, json=payload, timeout=40)

        if response.status_code == 404:
            print(f"\n❌ Модель '{model_name}' не найдена в Ollama!")
            return None

        if response.status_code != 200:
            return None

        result_data = response.json()
        raw_json = result_data["message"]["content"].strip()
        data = json.loads(raw_json)

        grade = str(data.get('ai_grade', 'Middle'))
        if grade not in ['Junior', 'Middle', 'Senior']:
            grade = 'Middle'

        return {
            "salary_score": int(data.get('salary_score', 5)),
            "requirements_density": int(data.get('requirements_density', 5)),
            "competition_score": int(data.get('competition_score', 5)),
            "ai_grade": grade
        }
    except Exception:
        return None


def run_llm_cross_validation():
    print("==================================================================")
    print("⚖️ ЗАПУСК КРОСС-ВАЛИДАЦИИ ДАННЫХ (Gemma 2 vs Qwen 2.5)")
    print("==================================================================\n")

    # 1. Проверяем доступность локального сервера Ollama
    try:
        requests.get("http://localhost:11434/", timeout=3)
    except requests.exceptions.ConnectionError:
        print("❌ Сервер Ollama не запущен! Убедись, что выполняется 'ollama serve'.")
        sys.exit(1)

    # 2. Формируем тестовую выборку
    sample_df = fetch_annotated_sample(SAMPLE_SIZE)
    if sample_df is None:
        return

    print(f"🎯 Выбрана контрольная группа из {len(sample_df)} случайных вакансий.")
    print(f"🤖 В роли эксперта-судьи выступает: '{JUDGE_MODEL}'\n")

    results = []

    for idx, row in enumerate(sample_df.itertuples(), 1):
        print(f"[{idx}/{len(sample_df)}] Qwen 2.5 проверяет: {row.title[:45]}...", end="", flush=True)

        judge_res = get_judge_evaluation_ollama(row.title, row.description)

        if judge_res is None:
            print(" ❌ Ошибка запроса")
            continue

        print(" OK")

        results.append({
            "v_id": row.id,
            "title": row.title,
            # Оценки основной модели (Gemma 2 из БД)
            "m1_grade": row.ai_grade,
            "m1_salary": row.salary_score,
            "m1_density": row.requirements_density,
            "m1_comp": row.competition_score,
            # Оценки Арбитра (Qwen 2.5 7B)
            "m2_grade": judge_res["ai_grade"],
            "m2_salary": judge_res["salary_score"],
            "m2_density": judge_res["requirements_density"],
            "m2_comp": judge_res["competition_score"],
        })

    eval_df = pd.DataFrame(results)

    if eval_df.empty:
        print("\n❌ Не удалось получить ответы от модели Qwen 2.5.")
        return

    # --------------------------------------------------------------------------
    # РАСЧЕТ МЕТРИК ТОЧНОСТИ
    # --------------------------------------------------------------------------
    total_eval = len(eval_df)

    # 1. Совпадение грейдов (Accuracy)
    grade_matches = (eval_df["m1_grade"] == eval_df["m2_grade"]).sum()
    grade_accuracy = (grade_matches / total_eval) * 100

    # 2. Средняя ошибка по числовым шкалам (MAE)
    mae_salary = np.abs(eval_df["m1_salary"] - eval_df["m2_salary"]).mean()
    mae_density = np.abs(eval_df["m1_density"] - eval_df["m2_density"]).mean()
    mae_comp = np.abs(eval_df["m1_comp"] - eval_df["m2_comp"]).mean()

    avg_mae = (mae_salary + mae_density + mae_comp) / 3
    consistency_index = max(0, 100 - (avg_mae * 10))

    print("\n==================================================================")
    print("📊 ИТОГОВЫЙ ОТЧЕТ СОГЛАСОВАННОСТИ НЕЙРОСЕТЕЙ (LLM-as-a-Judge)")
    print("==================================================================")
    print(f"1. Точность совпадения Грейдов (Accuracy):   {grade_accuracy:.1f}% ({grade_matches}/{total_eval})")
    print(f"2. Среднее отклонение по Зарплатам (MAE):     {mae_salary:.2f} из 10 баллов")
    print(f"3. Среднее отклонение по Требованиям (MAE):   {mae_density:.2f} из 10 баллов")
    print(f"4. Среднее отклонение по Конкуренции (MAE):  {mae_comp:.2f} из 10 баллов")
    print("------------------------------------------------------------------")
    print(f"🎯 ИНДЕКС СХОДИМОСТИ МОДЕЛЕЙ: {consistency_index:.1f}%")
    print("==================================================================\n")

    mismatches = eval_df[eval_df["m1_grade"] != eval_df["m2_grade"]]
    if not mismatches.empty:
        print("🔍 Примеры спорных вакансий:")
        for r in mismatches.head(5).itertuples():
            print(f"  • '{r.title}': Gemma = {r.m1_grade} | Qwen = {r.m2_grade}")
    else:
        print("🎉 Абсолютное 100% совпадение грейдов во всей выборке!")

    eval_df.to_csv("model_comparison_report.csv", index=False, encoding="utf-8-sig")
    print("\n📁 Подробный отчет со всеми оценками сохранен в файл 'model_comparison_report.csv'.")


if __name__ == "__main__":
    run_llm_cross_validation()