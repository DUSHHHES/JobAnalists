"""
Модуль для взаимодействия с Ollama API.
Содержит функции для проверки доступности сервера и моделей,
а также для отправки запросов к ИИ-моделям.
"""

import json
import requests
import sys
from typing import Dict, List, Optional

from config import OLLAMA_URL, DEFAULT_AI_MODEL, OLLAMA_TIMEOUT, OLLAMA_NUM_CTX, BACKEND


def check_ollama_server() -> bool:
    """
    Проверяет доступность локального сервера Ollama.
    Возвращает True, если сервер доступен, иначе завершает программу.
    """
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if response.status_code == 200:
            return True
    except Exception:
        pass
    
    print(f"""
❌ ОШИБКА: Не удалось подключиться к Ollama по адресу {OLLAMA_URL}.

Убедитесь, что сервер Ollama запущен:
  ollama serve
""")
    sys.exit(1)


def get_installed_models() -> List[str]:
    """
    Возвращает список всех установленных моделей в локальной Ollama.
    """
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if response.status_code == 200:
            data = response.json()
            return [model["name"] for model in data.get("models", [])]
    except Exception:
        pass
    return []


def select_model(preferred_model: str = DEFAULT_AI_MODEL) -> str:
    """
    Выбирает доступную модель из предпочтительной.
    Если предпочтительная модель недоступна, выбирает первую доступную.
    """
    installed = get_installed_models()
    if not installed:
        print("\n❌ ОШИБКА: В Ollama нет ни одной скачанной модели!")
        sys.exit(1)
    
    matching_model = next((m for m in installed if preferred_model in m), None)
    if matching_model:
        return matching_model
    else:
        active_model = installed[0]
        print(f"🔄 Переключаюсь на доступную модель: '{active_model}'")
        return active_model


def query_ollama(model_name: str, system_prompt: str, user_content: str, 
                 temperature: float = 0.0) -> Optional[str]:
    """
    Отправляет запрос к Ollama и возвращает ответ модели.
    
    Args:
        model_name: Имя модели для запроса
        system_prompt: Системный промпт
        user_content: Содержание пользовательского запроса
        temperature: Температура модели
        
    Returns:
        Ответ модели или None в случае ошибки
    """
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": temperature, "num_ctx": OLLAMA_NUM_CTX}
    }
    
    try:
        response = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=OLLAMA_TIMEOUT)
        
        if response.status_code == 404:
            print(f"\n❌ Модель '{model_name}' не найдена в Ollama!")
            return None
        
        if response.status_code != 200:
            return None
        
        result_data = response.json()
        return result_data["message"]["content"].strip()
        
    except Exception as e:
        print(f" ❌ Ошибка: {e}")
        return None


def parse_model_json(raw_response) -> Optional[Dict]:
    """
    Разбирает ответ модели в JSON-объект, срезая Markdown-блоки кода.

    Args:
        raw_response: сырой текст ответа модели или None

    Returns:
        dict при успехе, иначе None
    """
    if raw_response is None:
        return None

    raw = raw_response.strip()

    if raw.startswith("```"):
        lines = raw.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None

    return data if isinstance(data, dict) else None


def query_llm(model_name: str, system_prompt: str, user_content: str,
              temperature: float = 0.0) -> Optional[str]:
    """
    Универсальный запрос к LLM. Автоматически выбирает бэкенд
    в зависимости от конфига BACKEND.
    """
    if BACKEND == "openvino_npu":
        from openvino_client import query_openvino
        return query_openvino(system_prompt, user_content, temperature)
    else:
        return query_ollama(model_name, system_prompt, user_content, temperature)