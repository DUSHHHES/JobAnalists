import sqlite3
import re
import pandas as pd
import numpy as np

DB_NAME = "habr_analytics.db"

def run_data_validation():
    print("==================================================")
    print("🧪 АВТОМАТИЧЕСКАЯ ПРОВЕРКА КАЧЕСТВА ДАННЫХ (DQA)")
    print("==================================================\n")

    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql("SELECT * FROM vacancies", conn)
    conn.close()

    total_records = len(df)
    print(f"📊 Всего вакансий в базе: {total_records}")

    if total_records == 0:
        print("❌ База данных пуста!")
        return

    # ----------------------------------------------------
    # ТЕСТ 1: Полнота разметки (Completeness)
    # ----------------------------------------------------
    print("\n--- [Тест 1/4] Полнота разметки ИИ ---")
    analyzed_df = df[df['ai_grade'].isin(['Junior', 'Middle', 'Senior'])].copy()
    analyzed_count = len(analyzed_df)
    completeness_rate = (analyzed_count / total_records) * 100

    print(f"Размечено вакансий: {analyzed_count} из {total_records} ({completeness_rate:.1f}%)")

    if completeness_rate < 80:
        print("⚠️ ВНИМАНИЕ: Менее 80% базы размечено. Рекомендуется доразметить вакансии.")
    else:
        print("✅ Отличный уровень покрытия данными!")

    # ----------------------------------------------------
    # ТЕСТ 2: Валидность диапазонов (Range & Constraint Check)
    # ----------------------------------------------------
    print("\n--- [Тест 2/4] Проверка корректности диапазонов оценок ---")

    invalid_scores = 0
    score_columns = ['salary_score', 'requirements_density', 'competition_score']

    for col in score_columns:
        if col in analyzed_df.columns:
            out_of_bounds = analyzed_df[
                (analyzed_df[col] < 1) | (analyzed_df[col] > 10) | (analyzed_df[col].isna())
                ]
            count_invalid = len(out_of_bounds)
            if count_invalid > 0:
                print(f"❌ Колонка '{col}': найдено {count_invalid} некорректных значений!")
                invalid_scores += count_invalid
            else:
                print(f"✅ Колонка '{col}': все значения строго в диапазоне 1..10")

    # ----------------------------------------------------
    # ТЕСТ 3: Проверка смысловых противоречий (Consistency Checks)
    # ----------------------------------------------------
    print("\n--- [Тест 3/4] Поиск смысловых противоречий ---")

    contradictions = 0

    # 3.1. Заголовок обещает Junior/Стажера, но ИИ поставил Senior
    jun_mismatch = analyzed_df[
        analyzed_df['title'].str.contains(r'junior|стажер|интерн|начинающий', case=False, na=False) &
        (analyzed_df['ai_grade'] == 'Senior')
        ]
    if len(jun_mismatch) > 0:
        print(f"⚠️ Ложные Senior: {len(jun_mismatch)} вакансий со словами 'Junior/Стажер' размечены как 'Senior'.")
        contradictions += len(jun_mismatch)
    else:
        print("✅ Нет противоречий 'Junior в названии -> Senior в грейде'")

    # 3.2. Заголовок обещает Senior/Lead, но ИИ поставил Junior
    sen_mismatch = analyzed_df[
        analyzed_df['title'].str.contains(r'senior|lead|ведущий|главный|архитектор', case=False, na=False) &
        (analyzed_df['ai_grade'] == 'Junior')
        ]
    if len(sen_mismatch) > 0:
        print(f"⚠️ Ложные Junior: {len(sen_mismatch)} вакансий со словами 'Senior/Lead' размечены как 'Junior'.")
        contradictions += len(sen_mismatch)
    else:
        print("✅ Нет противоречий 'Senior в названии -> Junior в грейде'")

    # ----------------------------------------------------
    # ТЕСТ 4: Проверка «схлопывания» распределений (Variance Check)
    # ----------------------------------------------------
    print("\n--- [Тест 4/4] Статистический анализ распределений ---")

    for col in score_columns:
        if col in analyzed_df.columns and not analyzed_df[col].dropna().empty:
            std_val = analyzed_df[col].std()
            mean_val = analyzed_df[col].mean()
            print(f"📊 '{col}': Среднее = {mean_val:.2f}, Стд. отклонение = {std_val:.2f}")

            if std_val < 0.8:
                print(
                    f"⚠️ ВНИМАНИЕ: Слишком низкая дисперсия в '{col}'! ИИ ставит почти одинаковые оценки всем вакансиям.")
            else:
                print(f"✅ Дисперсия в норме, ИИ дифференцирует вакансии.")

    # ----------------------------------------------------
    # ИТОГОВЫЙ ОТЧЕТ
    # ----------------------------------------------------
    print("\n==================================================")
    print("📋 ИТОГОВЫЙ РЕЗУЛЬТАТ ПРОВЕРКИ:")
    if invalid_scores == 0 and contradictions == 0:
        print("🎉 ВСЕ АВТОТЕСТЫ ПРОЙДЕНЫ УСПЕШНО! Данные готовы к интеграции.")
    else:
        print(f"⚠️ НАЙДЕНЫ ЗАМЕЧАНИЯ: Ошибок диапазонов: {invalid_scores}, Противоречий: {contradictions}.")
    print("==================================================\n")


if __name__ == "__main__":
    run_data_validation()