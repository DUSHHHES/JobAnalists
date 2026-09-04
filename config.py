"""
Конфигурационный модуль для проекта JobAnalists.
Содержит общие настройки, пути и параметры подключения к сервисам.
"""

import os
from dotenv import load_dotenv
load_dotenv()
# --------------------------------------------------------
# Настройки базы данных
# --------------------------------------------------------

# Абсолютный путь к БД, чтобы скрипт можно было запускать из любой директории
DB_NAME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "habr_analytics.db")

# --------------------------------------------------------
# Настройки Ollama
# --------------------------------------------------------

# Адрес локального сервера Ollama по умолчанию
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

# Модель по умолчанию для ИИ-разметки
DEFAULT_AI_MODEL = os.environ.get("DEFAULT_AI_MODEL", "qwen2.5:7b")

# Модель-Арбитр для кросс-валидации
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "qwen2.5:7b")

# --------------------------------------------------------
# Настройки HTTP-запросов
# --------------------------------------------------------

# Заголовки для запросов к Хабру
HABR_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Таймауты для HTTP-запросов (в секундах)
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "10"))
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "40"))
MAX_DESCRIPTION_CHARS = int(os.environ.get("MAX_DESCRIPTION_CHARS", "9000"))
OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "8192"))

BACKEND = os.environ.get("BACKEND", "ollama")
OPENVINO_MODEL_DIR = os.environ.get("OPENVINO_MODEL_DIR", "models/qwen2.5-7b-int4")
OPENVINO_DEVICE = os.environ.get("OPENVINO_DEVICE", "NPU")

# Курсы валют для приведения зарплат к рублям
USD_TO_RUB = float(os.environ.get("USD_TO_RUB", "90"))
EUR_TO_RUB = float(os.environ.get("EUR_TO_RUB", "100"))

# --------------------------------------------------------
# Настройки валидации данных
# --------------------------------------------------------

# Размер контрольной случайной выборки для проверки
SAMPLE_SIZE = int(os.environ.get("SAMPLE_SIZE", "30"))

# Минимальная длина описания для обработки
MIN_DESCRIPTION_LENGTH = 15

# Пороговое значение для проверки полноты разметки
COMPLETENESS_THRESHOLD = 80

# Пороговое значение для стандартного отклонения
VARIANCE_THRESHOLD = 0.8

# Диапазон корректных оценок
SCORE_MIN = 1
SCORE_MAX = 10

# Валидные грейды
VALID_GRADES = ['Junior', 'Middle', 'Senior']

# --------------------------------------------------------
# Настройки синхронизации
# --------------------------------------------------------

# Порог удаления вакансий (в днях)
SOFT_DELETE_THRESHOLD_DAYS = int(os.environ.get("SOFT_DELETE_THRESHOLD_DAYS", "14"))

# Размер пакета для массовых операций
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "10"))

# Пауза между запросами к Оllama (в секундах)
OLLAMA_DELAY = float(os.environ.get("OLLAMA_DELAY", "0.05"))

# Пауза между запросами к страницам Хабра (в секундах)
FETCH_DELAY = float(os.environ.get("FETCH_DELAY", "0.8"))