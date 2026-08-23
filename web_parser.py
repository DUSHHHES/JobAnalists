"""
Модуль для веб-парсинга страниц вакансий с Хабра.
"""

import re
import requests
import bs4
from typing import Optional

from config import HABR_HEADERS, REQUEST_TIMEOUT


def fetch_description_from_url(link: str) -> str:
    """
    Загружает описание вакансии с Хабра по ссылке.
    """
    if not link or not isinstance(link, str) or not link.startswith("http"):
        return ""

    try:
        response = requests.get(link, headers=HABR_HEADERS, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            soup = bs4.BeautifulSoup(response.text, "html.parser")

            # 1. Ищем по любым вариациям классов описания (Хабр часто их меняет)
            block = (
                soup.find(class_=re.compile(r"vacancy-description", re.I)) or
                soup.find(class_="style-html") or
                soup.find(class_=re.compile(r"description", re.I))
            )

            if block:
                text = block.get_text(separator=" ").strip()
                if len(text) > 20:
                    return text

            # 2. ЖЕЛЕЗОБЕТОННЫЙ РЕЗЕРВ: если классы полностью сменились, берем основной блок <main>
            main_block = soup.find("main") or soup.find("body")
            if main_block:
                text = main_block.get_text(separator=" ").strip()
                if len(text) > 20:
                    return text

    except Exception as e:
        print(f"Ошибка парсера: {e}")

    return ""


def fetch_vacancy_page(link: str) -> Optional[bs4.BeautifulSoup]:
    """
    Загружает страницу вакансии и возвращает объект BeautifulSoup.
    """
    if not link or not isinstance(link, str) or not link.startswith("http"):
        return None
    
    try:
        response = requests.get(link, headers=HABR_HEADERS, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            return bs4.BeautifulSoup(response.text, "html.parser")
    except Exception:
        pass
    
    return None