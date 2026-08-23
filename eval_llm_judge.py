import sys
import pandas as pd
import numpy as np
import requests

from config import OLLAMA_URL, JUDGE_MODEL, SAMPLE_SIZE, VALID_GRADES
from database import get_annotated_sample
from ollama_client import query_ollama, parse_model_json


def get_judge_evaluation_ollama(title, description, model_name=JUDGE_MODEL):
    """
    Отправляет вакансию независимой модели-арбитру через Ollama.
    Использует функцию query_ollama из ollama_client.py
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

    raw_json = query_ollama(model_name, system_prompt, user_content)

    data = parse_model_json(raw_json)

    if data is None:
        return None

    salary = int(data.get('salary_score', 5))
    density = int(data.get('requirements_density', 5))
    comp = int(data.get('competition_score', 5))
    grade = str(data.get('ai_grade', 'Middle'))

    if grade not in VALID_GRADES:
        grade = 'Middle'

    return {
        "salary_score": salary,
        "requirements_density": density,
        "competition_score": comp,
        "ai_grade": grade
    }


def run_llm_cross_validation():
    print("==================================================================")
    print(f"⚖️ ЗАПУСК КРОСС-ВАЛИДАЦИИ ДАННЫХ (арбитр: {JUDGE_MODEL})")
    print("==================================================================\n")

    # 1. Проверяем доступность локального сервера Ollama
    try:
        requests.get(f"{OLLAMA_URL}/", timeout=3)
    except requests.exceptions.ConnectionError:
        print("❌ Сервер Ollama не запущен! Убедись, что выполняется 'ollama serve'.")
        sys.exit(1)

    # 2. Формируем тестовую выборку
    sample_df = get_annotated_sample(SAMPLE_SIZE)
    if sample_df is None:
        return

    print(f"🎯 Выбрана контрольная группа из {len(sample_df)} случайных вакансий.")
    print(f"🤖 В роли эксперта-судьи выступает: '{JUDGE_MODEL}'\n")

    results = []

    for idx, row in enumerate(sample_df.itertuples(), 1):
        print(f"[{idx}/{len(sample_df)}] {JUDGE_MODEL} проверяет: {row.title[:45]}...", end="", flush=True)

        judge_res = get_judge_evaluation_ollama(row.title, row.description)

        if judge_res is None:
            print(" ❌ Ошибка запроса")
            continue

        print(" OK")

        results.append({
            "v_id": row.id,
            "title": row.title,
            # Оценки основной модели (из БД)
            "m1_grade": row.ai_grade,
            "m1_salary": row.salary_score,
            "m1_density": row.requirements_density,
            "m1_comp": row.competition_score,
            # Оценки арбитра
            "m2_grade": judge_res["ai_grade"],
            "m2_salary": judge_res["salary_score"],
            "m2_density": judge_res["requirements_density"],
            "m2_comp": judge_res["competition_score"],
        })

    eval_df = pd.DataFrame(results)

    if eval_df.empty:
        print("\n❌ Не удалось получить ответы от модели-арбитра.")
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
            print(f"  • '{r.title}': основная = {r.m1_grade} | арбитр ({JUDGE_MODEL}) = {r.m2_grade}")
    else:
        print("🎉 Абсолютное 100% совпадение грейдов во всей выборке!")

    eval_df.to_csv("model_comparison_report.csv", index=False, encoding="utf-8-sig")
    print("\n📁 Подробный отчет со всеми оценками сохранен в файл 'model_comparison_report.csv'.")


if __name__ == "__main__":
    run_llm_cross_validation()
