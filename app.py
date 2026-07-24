import sqlite3
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
from collections import Counter
import re

# --------------------------------------------------------
# НАСТРОЙКИ СТРАНИЦЫ
# --------------------------------------------------------

st.set_page_config(
    page_title="Аналитика IT-рынка",
    page_icon="📊",
    layout="wide"
)

st.title("📊 Анализ востребованности IT-специалистов")

st.markdown("""
Дашборд рассчитывает **интегральный коэффициент востребованности**
на основе данных вакансий Хабр Карьеры и результатов анализа ИИ.""")


# --------------------------------------------------------
# ФУНКЦИЯ ДЛЯ ПАРСИНГА РЕАЛЬНОЙ ЗАРПЛАТЫ
# --------------------------------------------------------
def parse_real_salary(val):
    """Вытаскивает из текста вакансии реальную среднюю зарплату в рублях."""
    if pd.isna(val) or not isinstance(
        val, str
    ):
        return None

    val = val.lower().strip()
    val = re.sub(r'\s+', '', val)
    val = val.replace('руб', '').replace('р', '').replace('₽', '').replace('бел', '')

    multiplier = 1
    if '$' in val or 'usd' in val:
        multiplier = 90
        val = val.replace('$', '').replace('usd', '')
    elif '€' in val or 'eur' in val:
        multiplier = 100
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


# --------------------------------------------------------
# ЗАГРУЗКА ДАННЫХ
# --------------------------------------------------------

@st.cache_data(ttl=600)  # Кешируем данные на 10 минут
def load_data():
    conn = sqlite3.connect("habr_analytics.db")

    query = """
    SELECT
        title,
        company,
        salary,
        skills,
        description,
        link,
        salary_score,
        competition_score,
        requirements_density,
        ai_grade
    FROM vacancies
    WHERE
        ai_grade IN ('Junior','Middle','Senior')
        AND requirements_density IS NOT NULL
    """

    df = pd.read_sql(query, conn)
    conn.close()

    # Парсим зарплату в рубли для качественной аналитики
    df["parsed_salary"] = df["salary"].apply(parse_real_salary)
    return df


df = load_data()

if df.empty:
    st.error("В базе нет размеченных вакансий.")
    st.stop()


# --------------------------------------------------------
# ОПРЕДЕЛЕНИЕ ТЕХНОЛОГИИ
# --------------------------------------------------------

def detect_technologies(title: str):
    title = str(title).lower().strip()

    patterns = {
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
            r'первая линия)\b'
        ),
        "Marketing / PM": (
            r'\b(маркетолог|маркетинг|менеджер|manager|project manager|'
            r'администратор проектов|cvm|digital)\b'
        )
    }

    matched = []
    for tech, pattern in patterns.items():
        if re.search(pattern, title, re.IGNORECASE):
            matched.append(tech)

    # Если ни один паттерн не подошел, определяем в категорию "Other"
    if not matched:
        return ["Other"]

    return matched


# Применяем классификацию
df["technology"] = df["title"].apply(detect_technologies)

# Распаковываем списки в строки перед группировкой
df_exploded = df.explode("technology")

# --------------------------------------------------------
# ГЛОБАЛЬНЫЙ РАСЧЕТ И НОРМАЛИЗАЦИЯ (ДЛЯ ВСЕГО РЫНКА)
# --------------------------------------------------------
grade_map = {"Junior": 1, "Middle": 2, "Senior": 3}
df_exploded['grade_num'] = df_exploded['ai_grade'].map(grade_map)

# Агрегируем данные по уникальным комбинациям технология + грейд
global_stats = df_exploded.groupby(['technology', 'ai_grade']).agg(
    count=('title', 'count'),
    avg_salary=('salary_score', lambda x: x.mean() if pd.notna(x.mean()) else 5.0),
    avg_density=('requirements_density', lambda x: x.mean() if pd.notna(x.mean()) else 5.0),
    avg_comp=('competition_score', lambda x: x.mean() if pd.notna(x.mean()) else 5.0),
    avg_real_salary=('parsed_salary', lambda x: x.mean() if pd.notna(x.mean()) else np.nan),
    grade_num=('grade_num', 'first')
).reset_index()

max_count = global_stats['count'].max()

# Нормированные переменные для формулы
global_stats['Nn'] = np.log(global_stats['count'] + 1) / np.log(max_count + 1)
global_stats['Sn'] = global_stats['avg_salary'] / 10
global_stats['Dn'] = global_stats['avg_density'] / 10
global_stats['Gn'] = global_stats['grade_num'] / 3  # Нормировка уровня квалификации
global_stats['Cn'] = global_stats['avg_comp'] / 10

# Считаем сырой коэффициент K_raw для всех комбинаций
global_stats['k_raw'] = (
        0.35 * global_stats['Nn'] +
        0.25 * global_stats['Sn'] +
        0.20 * global_stats['Dn'] +
        0.05 * global_stats['Gn'] -
        0.15 * global_stats['Cn']
)

# Находим глобальные минимумы и максимумы
min_k = global_stats['k_raw'].min()
max_k = global_stats['k_raw'].max()

# Нормируем от 0 до 100
if max_k == min_k:
    global_stats['k_score'] = 100.0  # Защита от деления на ноль
else:
    global_stats['k_score'] = ((global_stats['k_raw'] - min_k) / (max_k - min_k)) * 100

global_stats['k_score'] = global_stats['k_score'].round(2)

# --------------------------------------------------------
# SIDEBAR И ФИЛЬТРАЦИЯ ДЛЯ ВЫВОДА
# --------------------------------------------------------

st.sidebar.header("Фильтры")

technology = st.sidebar.selectbox(
    "Технология",
    sorted(df_exploded["technology"].unique())
)

grade = st.sidebar.radio(
    "Грейд",
    ["Junior", "Middle", "Senior"]
)

# Фильтруем распакованные данные для графиков и таблиц
filtered = df_exploded[
    (df_exploded["technology"] == technology) & (df_exploded["ai_grade"] == grade)
    ].copy()

# Достаем уже посчитанные метрики для выбранной комбинации
selected_stat = global_stats[
    (global_stats['technology'] == technology) & (global_stats['ai_grade'] == grade)
    ]

if filtered.empty or selected_stat.empty:
    st.warning("По выбранным параметрам вакансии отсутствуют.")
    st.stop()

selected_stat = selected_stat.iloc[0]

st.subheader(f"{technology} • {grade}")

# --------------------------------------------------------
# ИНТЕРАКТИВНЫЙ БЛОК ROADMAP И ОПИСАНИЯ ПРОФЕССИЙ
# --------------------------------------------------------
DESCRIPTIONS = {
    "DevOps": "Специалист, объединяющий разработку (Dev) и ИТ-обслуживание (Ops). Настраивает CI/CD и автоматизирует процессы.",
    "QA": "Инженер по обеспечению качества. Занимается ручным или автоматизированным тестированием ПО.",
    "Data Scientist": "Специалист по работе с данными. Строит предсказательные модели, анализирует большие объемы информации.",
    "ML": "Инженер машинного обучения. Разрабатывает и обучает нейросети и алгоритмы ИИ.",
    "Python": "Python-разработчик. Создает backend, скрипты, работает с данными и автоматизацией.",
    "Java": "Java-разработчик. Пишет надежный backend для энтерпрайз-систем и банковского сектора.",
    "JavaScript": "JS-разработчик (чаще Frontend). Создает интерактивные веб-интерфейсы и SPA.",
    "TypeScript": "TS-разработчик. Пишет строго типизированный код для современных веб-приложений.",
    "Go": "Go-разработчик. Создает высоконагруженные, быстрые и масштабируемые микросервисы.",
    "C#": "C#/.NET-разработчик. Разрабатывает приложения под экосистему Microsoft, игры и backend.",
    "C++": "C++ разработчик. Создает высокопроизводительные системы, движки, системное ПО.",
    "PHP": "PHP-разработчик. Классический backend для веб-сайтов и CMS-систем.",
    "Kotlin": "Kotlin-разработчик. Пишет современные приложения для Android и backend-сервисы.",
    "Swift": "Swift-разработчик. Создает нативные мобильные приложения для iOS и экосистемы Apple.",
    "Rust": "Rust-разработчик. Пишет безопасный и быстрый системный код, микросервисы, Web3.",
    "Scala": "Scala-разработчик. Создает распределенные системы и работает с Big Data.",
    "Ruby": "Ruby (Ruby on Rails) разработчик. Быстро прототипирует и создает веб-приложения.",
    "Dart": "Dart/Flutter-разработчик. Создает кроссплатформенные мобильные приложения (iOS и Android).",
    "1C": "1С-разработчик. Автоматизирует бизнес-процессы и учет на базе платформы 1С:Предприятие.",
    "Android": "Android-разработчик. Разрабатывает мобильные приложения под ОС Android (обычно Java/Kotlin).",
    "iOS": "iOS-разработчик. Создает мобильные приложения для iPhone и iPad (Objective-C/Swift).",
    "Analyst": "Аналитик (системный, бизнес, данных). Собирает требования, проектирует архитектуру или анализирует метрики.",
    "Sysadmin / Support": "Системный администратор / Инженер поддержки. Обеспечивает работу инфраструктуры и помогает пользователям.",
    "Marketing / PM": "Маркетолог / Менеджер проектов. Управляет командой, продуктом, маркетингом и процессами разработки.",
    "Other": "Другие ИТ-специалисты, не вошедшие в основные категории."
}

st.markdown(f"*{DESCRIPTIONS.get(technology, '')}*")

ROADMAPS = {
    "DevOps": "https://roadmap.sh/devops",
    "QA": "https://roadmap.sh/qa",
    "Data Scientist": "https://roadmap.sh/ai-data-scientist",
    "ML": "https://roadmap.sh/ai-data-scientist",
    "Python": "https://roadmap.sh/python",
    "Java": "https://roadmap.sh/java",
    "JavaScript": "https://roadmap.sh/javascript",
    "TypeScript": "https://roadmap.sh/typescript",
    "Go": "https://roadmap.sh/golang",
    "C++": "https://roadmap.sh/cpp",
    "Android": "https://roadmap.sh/android",
    "iOS": "https://roadmap.sh/ios",
    "PHP": "https://roadmap.sh/php",
    "Swift": "https://roadmap.sh/ios",
    "Ruby": "https://roadmap.sh/ruby",
    "C#": "https://roadmap.sh/aspnet-core",
    "Kotlin": "https://roadmap.sh/android",
    "Rust": "https://roadmap.sh/rust",
    "Dart": "https://roadmap.sh/flutter",
    "Analyst": "https://roadmap.sh/data-analyst"
}

roadmap_url = ROADMAPS.get(technology, "https://roadmap.sh")
st.info(
    f"🎓 **Хочешь прокачаться?** Посмотри [пошаговый Roadmap "
    f"(карту развития) для {technology}]({roadmap_url})"
)

# --------------------------------------------------------
# ИЗВЛЕЧЕНИЕ РАССЧИТАННЫХ ДАННЫХ
# --------------------------------------------------------

vacancies_count = int(selected_stat['count'])
avg_salary = selected_stat['avg_salary']
avg_density = selected_stat['avg_density']
avg_competition = selected_stat['avg_comp']
avg_real_salary = selected_stat['avg_real_salary']

Nn = selected_stat['Nn']
Sn = selected_stat['Sn']
Dn = selected_stat['Dn']
Gn = selected_stat['Gn']
Cn = selected_stat['Cn']
k_raw = selected_stat['k_raw']
k_score = selected_stat['k_score']

# --------------------------------------------------------
# ВЫВОД ЗАРПЛАТЫ И УМНОЕ ПРОГНОЗИРОВАНИЕ
# --------------------------------------------------------
is_estimated = False
if pd.notna(avg_real_salary) and avg_real_salary > 0:
    rounded_salary = int(round(avg_real_salary / 1000) * 1000)
    salary_display = f"{rounded_salary:,} ₽".replace(",", " ")
else:
    estimated_salary = int(30000 + (avg_salary - 1) * 45000)
    estimated_salary = int(round(estimated_salary / 5000) * 5000)
    salary_display = f"~ {estimated_salary:,} ₽ *".replace(",", " ")
    is_estimated = True

# --------------------------------------------------------
# ИНТЕРПРЕТАЦИЯ
# --------------------------------------------------------

if k_score < 35:
    demand = "🔴 Низкий спрос"
elif k_score < 60:
    demand = "🟡 Средний спрос"
elif k_score < 80:
    demand = "🟢 Высокий спрос"
else:
    demand = "🔥 Очень высокий спрос"

# --------------------------------------------------------
# KPI КАРТОЧКИ
# --------------------------------------------------------

c1, c2, c3, c4 = st.columns(4)

c1.metric(
    "📈 Коэффициент востребованности",
    f"{k_score}/100"
)

c2.metric(
    "💼 Кол-во вакансий",
    vacancies_count
)

c3.metric(
    "💰 Средняя зарплата",
    salary_display
)

c4.metric(
    "🏆 Спрос",
    demand
)

if is_estimated:
    st.caption("* Работодатели скрыли зарплату. Сумма спрогнозирована ИИ на основе требований вакансий.")

st.divider()

# --------------------------------------------------------
# ПОКАЗАТЕЛИ МОДЕЛИ
# --------------------------------------------------------

left, right = st.columns([1, 1])

with left:
    st.subheader("Показатели модели (оценки ИИ)")
    st.metric("Плотность требований (D)", round(avg_density, 2))
    st.metric("Конкуренция соискателей (C)", round(avg_competition, 2))
    st.metric("Финансовый уровень вакансий (S)", f"{round(avg_salary, 2)} / 10")

with right:
    st.subheader("Грейд")
    st.metric("Выбранный квалификационный уровень", grade)

st.divider()

# --------------------------------------------------------
# ТОП НАВЫКОВ
# --------------------------------------------------------

st.subheader("🛠 Наиболее востребованные навыки")

skills = []
for value in filtered["skills"].dropna():
    if isinstance(value, str):
        for skill in value.split(","):
            skill = skill.strip()
            if len(skill) > 1:
                skills.append(skill)

counter = Counter(skills)
top_skills = pd.DataFrame(
    counter.most_common(15),
    columns=["Навык", "Количество"]
)

if not top_skills.empty:
    fig = px.bar(
        top_skills,
        x="Количество",
        y="Навык",
        orientation="h",
        text="Количество"
    )
    fig.update_layout(height=500, yaxis={'categoryorder': 'total ascending'})
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Навыки для выбранных параметров отсутствуют.")

st.divider()

# --------------------------------------------------------
# ТОП КОМПАНИЙ
# --------------------------------------------------------

st.subheader("🏢 Компании, которые чаще всего ищут специалистов")

clean_companies = filtered[
    (filtered["company"].notna()) &
    (filtered["company"].str.strip() != "") &
    (filtered["company"] != "Не указана")
    ]

if not clean_companies.empty:
    company_df = (
        clean_companies["company"]
        .value_counts()
        .head(10)
        .reset_index()
    )
    company_df.columns = ["Компания", "Вакансий"]

    fig = px.bar(
        company_df,
        x="Компания",
        y="Вакансий",
        text="Вакансий",
        color="Вакансий",
        color_continuous_scale="Viridis"
    )
    fig.update_layout(showlegend=False, coloraxis_showscale=False)
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Данные о работодателях отсутствуют.")

st.divider()

# --------------------------------------------------------
# СПИСОК ВАКАНСИЙ
# --------------------------------------------------------

st.subheader("📄 Найденные вакансии")

filtered["mini_desc"] = filtered["description"].apply(
    lambda x: (str(x)[:120] + "...") if pd.notna(x) and len(str(x)) > 120 else str(x)
)

table = filtered[[
    "title",
    "company",
    "salary",
    "mini_desc",
    "salary_score",
    "competition_score",
    "requirements_density",
    "link"
]].drop_duplicates(subset=["link"])

table.columns = [
    "Название",
    "Компания",
    "Зарплата (текст)",
    "Краткое описание",
    "Оценка ИИ: Зарплата",
    "Оценка ИИ: Конкуренция",
    "Оценка ИИ: Требования",
    "Ссылка"
]

st.dataframe(
    table,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Ссылка": st.column_config.LinkColumn("Ссылка", display_text="Открыть на Хабре"),
        "Краткое описание": st.column_config.TextColumn("Краткое описание", width="large")
    }
)

st.divider()

# --------------------------------------------------------
# СПРАВКА
# --------------------------------------------------------

with st.expander("ℹ️ О методике расчета"):
    st.markdown("""
### Интегральный коэффициент востребованности

Используется аддитивная многокритериальная модель с Min-Max нормализацией:

1. **Сырой вес (K_raw) = 0.35·N + 0.25·S + 0.20·D + 0.05·G − 0.15·C**
2. **Итоговый балл (K_score) = (K_raw - K_min) / (K_max - K_min) × 100**

где:
- **N** — количество вакансий (логарифмически сглаженное);
- **S** — нормированная оценка заработной платы (1-10);
- **D** — плотность требований работодателя (1-10);
- **G** — уровень квалификации (1-3);
- **C** — уровень конкуренции на вакансию (1-10).

Все показатели предварительно нормируются в диапазоне 0…1.
Весовые коэффициенты определены методом анализа иерархий (AHP).
Приведение результата к шкале от 0 до 100 относительно всего рынка позволяет получить объективную оценку:
от 🔴 **Низкого спроса** до 🔥 **Очень высокого спроса**.
""")

st.success("✅ Анализ завершён.")