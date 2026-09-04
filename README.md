# Анализ востребованности IT-специалистов

Дашборд рассчитывает интегральный коэффициент востребованности по данным
Хабр Карьеры. Вакансии собираются пайплайном, размечаются локальной LLM
через Ollama (оценки зарплаты, плотности требований, конкуренции, грейд),
после чего агрегируются в Streamlit-дашборде с калиброванным прогнозом
зарплаты.

## Установка

1. Python 3.12+ и Ollama. Запустить сервер и скачать модель по умолчанию:

   ```
   ollama serve
   ollama pull qwen2.5:7b
   ```
2. Создать окружение и поставить зависимости:

   ```
   python -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   ```

## Использование

| Команда | Что делает |
|---|---|
| `.venv\Scripts\python.exe sync_pipeline.py` | Полный цикл: скан ленты Хабра → синхронизация БД → архивация устаревших → ИИ-разметка активных вакансий |
| `streamlit run app.py` | Дашборд аналитики |
| `.venv\Scripts\python.exe ai_enricher.py` | Только ИИ-разметка всех неразмеченных вакансий (без сканирования сайта, включая архивные) |

При каждом открытии дашборд автоматически сохраняет дневной снимок k_score
по всем парам технология/грейд в таблицу `k_snapshots` — накопленная история
доступна в экспандере „📈 История коэффициента“.

## Проверки качества данных и кода

```
.venv\Scripts\python.exe -m unittest test_utils
.venv\Scripts\python.exe validate_data.py
```

## Полная переоценка базы

Если нужно переразметить всё заново (например, после смены модели или
промпта):

```
.venv\Scripts\python.exe -c "from database import reset_ai_columns; reset_ai_columns()"
.venv\Scripts\python.exe sync_pipeline.py
```

Пайплайн разметит активные вакансии; архивные догоняет отдельным запуском
`ai_enricher.py`.

## Настройка

Основные параметры — в `config.py`, переопределяются переменными окружения:
`OLLAMA_URL`, `DEFAULT_AI_MODEL`, `JUDGE_MODEL`, `REQUEST_TIMEOUT`,
`OLLAMA_TIMEOUT`, `FETCH_DELAY`, `BATCH_SIZE`, `SOFT_DELETE_THRESHOLD_DAYS`,
`USD_TO_RUB`, `EUR_TO_RUB`.
