"""
Модуль для парсинга HTML HH.ru.
Заменяет hh_api.py — работает без OAuth, через HTML.
"""

import os
import re
import time
import requests
import bs4
from typing import List, Dict

from config import HABR_HEADERS, REQUEST_TIMEOUT, FETCH_DELAY

HH_HEADERS = HABR_HEADERS.copy()

HH_IT_ROLES = [
    96, 104, 107, 112, 113, 116, 121, 122, 123, 124,
    125, 126, 127, 148, 155, 160, 167
]

HH_AREA_NAMES = {
    1: "Москва",
    2: "Санкт-Петербург",
    3: "Екатеринбург",
    4: "Новосибирск",
    66: "Казань",
}


def _fetch_page(url: str, retries: int = 3) -> bs4.BeautifulSoup:
    """Загружает страницу с повторными попытками."""
    for attempt in range(retries):
        try:
            response = requests.get(url, headers=HH_HEADERS, timeout=REQUEST_TIMEOUT)
            if response.status_code == 200:
                return bs4.BeautifulSoup(response.text, "html.parser")
            if response.status_code == 429:
                wait = (attempt + 1) * 3
                print(f"    HH.ru 429: пауза {wait}с...")
                time.sleep(wait)
                continue
            if response.status_code == 403:
                print(f"    HH.ru 403: попытка {attempt + 1}/{retries}")
                time.sleep(2)
                continue
            print(f"    Warning: HH.ru returned {response.status_code}")
            return None
        except requests.RequestException as e:
            print(f"    Warning: HH.ru request error: {e}")
            time.sleep(1)
    return None


def fetch_vacancy_description(url: str) -> str:
    """Скачивает описание вакансии по URL."""
    if not url or not isinstance(url, str) or not url.startswith("http"):
        return ""

    soup = _fetch_page(url)
    if not soup:
        return ""

    desc = soup.find(attrs={"data-qa": "vacancy-description"})
    if desc:
        text = desc.get_text(separator=" ").strip()
        if len(text) > 20:
            return text

    main = soup.find("main") or soup.find("body")
    if main:
        text = main.get_text(separator=" ").strip()
        if len(text) > 20:
            return text

    return ""


def fetch_all_it_vacancies(text: str = "", areas: List[int] = None, max_pages: int = 10) -> List[Dict]:
    """Сканирование IT-вакансий с HH.ru по нескольким регионам."""
    if areas is None:
        areas = [2]

    roles_param = "&".join([f"professional_role={r}" for r in HH_IT_ROLES])
    all_cards = []
    seen_ids = set()

    for area in areas:
        area_name = HH_AREA_NAMES.get(area, f"ID:{area}")
        print(f"\n  [HH.ru] Регион: {area_name}")

        area_cards = []
        skipped_dup = 0
        for page in range(max_pages):
            url = (
                f"https://hh.ru/search/vacancy?"
                f"text={text}&area={area}&{roles_param}&page={page}"
            )
            soup = _fetch_page(url)
            if not soup:
                break

            titles = soup.find_all(attrs={"data-qa": "serp-item__title"})
            employers = soup.find_all(attrs={"data-qa": "vacancy-serp__vacancy-employer-text"})
            salaries = soup.find_all(attrs={"data-qa": "vacancy-serp__compensation"})
            experiences = soup.find_all(
                attrs={"data-qa": lambda x: x and "vacancy-serp__vacancy-work-experience" in x}
            )

            if not titles:
                break

            page_new = 0
            for i, title_elem in enumerate(titles):
                href = title_elem.get("href", "")
                vacancy_id = href.split("/vacancy/")[-1].split("?")[0] if "/vacancy/" in href else ""
                card_id = f"hh_{vacancy_id}"

                if card_id in seen_ids:
                    skipped_dup += 1
                    continue
                seen_ids.add(card_id)

                company = employers[i].get_text(strip=True) if i < len(employers) else "Не указана"
                salary = salaries[i].get_text(strip=True) if i < len(salaries) else "ЗП не указана"
                experience = experiences[i].get_text(strip=True) if i < len(experiences) else "Не указан"

                full_link = href if href.startswith("http") else f"https://hh.ru{href}"

                area_cards.append({
                    "id": card_id,
                    "title": title_elem.get_text(strip=True),
                    "company": company,
                    "salary": salary,
                    "experience": experience,
                    "skills": "",
                    "link": full_link
                })
                page_new += 1

            print(f"    Страница {page + 1}: +{page_new} вакансий")

            if page < max_pages - 1:
                time.sleep(FETCH_DELAY)

        dup_info = f" (пропущено дублей: {skipped_dup})" if skipped_dup else ""
        print(f"  [HH.ru] {area_name}: собрано {len(area_cards)} вакансий{dup_info}")
        all_cards.extend(area_cards)

    print(f"\n  [HH.ru] ИТОГО: {len(all_cards)} вакансий из {len(areas)} регионов")
    return all_cards
