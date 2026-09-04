"""
Модуль с утилитами для парсинга и обработки данных о вакансиях.
"""

import os
import re
import sys
import functools
from contextlib import contextmanager
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd

from config import SCORE_MIN, SCORE_MAX, USD_TO_RUB, EUR_TO_RUB

# --------------------------------------------------------
# ПАТТЕРНЫ ДЛЯ ОПРЕДЕЛЕНИЯ ТЕХНОЛОГИЙ
# --------------------------------------------------------

TECH_PATTERNS = {
    "DevOps": r'\b(devops|sre|dev-ops)\b',
    "QA": r'\b(qa|tester|test|testing|тестировщик|тестирования|manual|automation)\b',
    "Data Scientist": r'\b(data scientist|data science|ds|data engineer)\b',
    "ML": r'\b(machine learning|ml|nlp)\b',
    "Python": r'\bpython\b',
    "Java": r'\bjava\b',  # Благодаря \b "java" не совпадет с "javascript"
    "JavaScript": r'\b(javascript|js|frontend|фронтенд)\b',
    "TypeScript": r'\b(typescript|ts)\b',
    "Go": r'\b(go|golang)\b',  # Совпадет с "go", "golang", "go-разработчик"
    "C#": r'c#|\b\.?net\b|asp\.net',
    "C++": r'c\+\+',
    "PHP": r'\bphp\b',
    "Kotlin": r'\bkotlin\b',
    "Swift": r'\bswift\b',
    "Rust": r'\brust\b',
    "Scala": r'\bscala\b',
    "Ruby": r'\bruby\b',
    "Dart": r'\b(dart|flutter)\b',
    "1C": r'\b1с\b|\b1c\b',
    "Android": r'\bandroid\b',
    "iOS": r'\bios\b',
        "Analyst": r'\b(аналитик|analyst|analysis|analytics)\b',
    "Sysadmin / Support": (
        r'\b(sysadmin|системный администратор|администратор linux|'
        r'сисадмин|сервисный инженер|'
        r'инженер технической поддержки|'
        r'инженер проактивного мониторинга|support|поддержка|дежурный|'
        r'первая линия|эксплуатация)\b'
    ),
    "Marketing / PM": (
        r'\b(маркетолог|маркетинг|менеджер|manager|project manager|'
        r'администратор проектов|cvm|digital)\b'
    ),
}


def detect_technologies(title: str) -> List[str]:
    """
    Определяет технологии по названию вакансии.
    Возвращает список найденных технологий или список с 'Other', если ничего не найдено.
    """
    title_lower = str(title).lower().strip()
    
    matched = []
    for tech_name, pattern in TECH_PATTERNS.items():
        if re.search(pattern, title_lower):
            matched.append(tech_name)
    
    # Если ни один паттерн не подошёл, определяем в категорию "Other"
    if not matched:
        return ["Other"]
    
    return matched


def parse_real_salary(val) -> Optional[float]:
    """
    Вытаскивает из текста вакансии реальную среднюю зарплату в рублях.
    
    Args:
        val: строка с описанием зарплаты
        
    Returns:
        Средняя зарплата в рублях или None, если не удалось распарсить
    """
    if pd.isna(val) or not isinstance(val, str):
        return None

    val = val.lower().strip()
    val = re.sub(r'\s+', '', val)
    val = val.replace('руб', '').replace('р', '').replace('₽', '').replace('бел', '')

    multiplier = 1
    if '$' in val or 'usd' in val:
        multiplier = USD_TO_RUB
        val = val.replace('$', '').replace('usd', '')
    elif '€' in val or 'eur' in val:
        multiplier = EUR_TO_RUB
        val = val.replace('€', '').replace('eur', '')

    numbers = [int(n) for n in re.findall(r'\d+', val)]
    if not numbers:
        return None

    avg_num = sum(numbers) / len(numbers)

    if avg_num < 1000:
        avg_num = avg_num * 1000

    avg_num = avg_num * multiplier

    if avg_num < 15000 or avg_num > 1500000:
        return None

    return avg_num


def extract_skills(skills_str) -> List[str]:
    """
    Извлекает навыки из строки с навыками вакансии.
    
    Args:
        skills_str: строка с навыками (может быть в JSON-формате или разделённая запятыми)
        
    Returns:
        Список навыков
    """
    if pd.isna(skills_str) or not skills_str:
        return []
    
    # Попытка распарсить как JSON
    try:
        import json
        skills_list = json.loads(skills_str)
        if isinstance(skills_list, list):
            return [
                s.strip()
                for s in skills_list
                if isinstance(s, str) and s.strip()
            ]
    except (json.JSONDecodeError, TypeError):
        pass
    
    # Если не JSON, разбиваем по запятой
    if isinstance(skills_str, str):
        return [s.strip() for s in skills_str.split(',') if s.strip()]
    
    return []


def calculate_relevance_score(row) -> float:
    """
    Вычисляет интегральный коэффициент востребованности для вакансии.
    
    Используется аддитивная многокритериальная модель с Min-Max нормализацией:
    1. Сырой вес (K_raw) = 0.35·N + 0.25·S + 0.20·D + 0.05·G − 0.15·C
    2. Итоговый балл (K_score) = (K_raw - K_min) / (K_max - K_min) × 100
    
    где:
    - N — количество вакансий (логарифмически сглаженное);
    - S — нормированная оценка заработной платы (1-10);
    - D — плотность требований работодателя (1-10);
    - G — уровень квалификации (1-3);
    - C — уровень конкуренции на вакансию (1-10).
    
    Все показатели предварительно нормируются в диапазоне 0…1.
    Весовые коэффициенты определены методом анализа иерархий (AHP).
    """
    # Нормализация оценок в диапазон 0-1
    s_score = (row.get('salary_score', 5) - 1) / 9 if row.get('salary_score') else 0.5
    c_score = (row.get('competition_score', 5) - 1) / 9 if row.get('competition_score') else 0.5
    d_score = (row.get('requirements_density', 5) - 1) / 9 if row.get('requirements_density') else 0.5
    
    # Нормализация грейда
    grade_map = {'Junior': 1, 'Middle': 2, 'Senior': 3}
    grade_val = grade_map.get(row.get('ai_grade', 'Middle'), 2)
    g_score = (grade_val - 1) / 2
    
    # Вычисление сырого веса
    # Примечание: N будет подставлено на этапе расчёта в дашборде
    raw_weight = 0.25 * s_score + 0.20 * d_score + 0.05 * g_score - 0.15 * c_score

    return raw_weight


def build_salary_calibration(df, min_bucket: int = 3) -> Tuple[Dict[int, float], Optional[float]]:
    """
    Строит калибровочную таблицу «ИИ-оценка финансовой привлекательности -> медианная зарплата»
    по вакансиям с раскрытой зарплатой.

    Args:
        df: DataFrame с колонками salary_score и parsed_salary
        min_bucket: минимальное число наблюдений в бакете оценки

    Returns:
        Кортеж (dict {score: медианная зарплата}, медианная зарплата рынка или None)
    """
    if "salary_score" not in df.columns or "parsed_salary" not in df.columns:
        return {}, None

    revealed = df.loc[
        df["parsed_salary"].notna() & df["salary_score"].between(SCORE_MIN, SCORE_MAX)
    ]

    market_median = revealed["parsed_salary"].median()
    if pd.isna(market_median):
        return {}, None

    buckets = revealed.groupby("salary_score")["parsed_salary"].agg(["median", "count"])
    calibration = {
        int(score): float(row["median"])
        for score, row in buckets.iterrows()
        if row["count"] >= min_bucket
    }
    return calibration, float(market_median)


def estimate_hidden_salary(score, calibration: Dict[int, float], fallback: Optional[float] = None) -> Optional[float]:
    """
    Оценивает скрытую зарплату по калибровочной таблице.

    Порядок: точный бакет -> линейная интерполяция между ближайшими известными
    баллами (экстраполяция заменяется клампом к крайнему бакету) -> fallback.
    """
    if not calibration:
        return fallback

    score = float(score)
    if score in calibration:
        return calibration[score]

    lower = max((s for s in calibration if s < score), default=None)
    upper = min((s for s in calibration if s > score), default=None)

    if lower is not None and upper is not None:
        weight = (score - lower) / (upper - lower)
        return calibration[lower] + weight * (calibration[upper] - calibration[lower])

    if lower is not None:
        return calibration[lower]
    if upper is not None:
        return calibration[upper]

    return fallback


def clamp_score(value) -> int:
    """
    Приводит оценку ИИ к целому числу в диапазоне SCORE_MIN..SCORE_MAX.
    Нечисловые значения дают нейтральную середину шкалы.
    """
    try:
        value = int(round(float(value)))
    except (TypeError, ValueError):
        return 5
    return max(SCORE_MIN, min(SCORE_MAX, value))


class TeeStream:
    """
    Дублирует запись в исходный поток и в файл лога.
    Безопасен к уже закрытому файлу.
    """

    def __init__(self, stream, file):
        self._stream = stream
        self._file = file

    def write(self, data):
        self._stream.write(data)
        try:
            self._file.write(data)
        except ValueError:
            pass
        return len(data)

    def flush(self):
        self._stream.flush()
        try:
            self._file.flush()
        except ValueError:
            pass


@contextmanager
def file_log(directory="logs"):
    """
    На время блока дублирует stdout в logs/run_<timestamp>.log.
    """
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"run_{datetime.now():%Y%m%d_%H%M%S}.log")
    stream = open(path, "w", encoding="utf-8", errors="replace")
    original = sys.stdout
    sys.stdout = TeeStream(original, stream)
    try:
        yield path
    finally:
        sys.stdout = original
        stream.close()


def with_file_log(func):
    """Пишет вывод функции одновременно в консоль и в файл лога."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with file_log():
            return func(*args, **kwargs)
    return wrapper