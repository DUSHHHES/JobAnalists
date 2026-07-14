import sqlite3
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
from collections import Counter

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
на основе данных вакансий Хабр Карьеры и результатов анализа Google Gemini.

Используемая модель расчета сырого веса:
**K_raw = 0.35·N + 0.25·S + 0.20·D + 0.05·G − 0.15·C**

Итоговый индекс масштабируется относительно рынка (от 0 до 100):
**K_score = (K_raw - min_k) / (max_k - min_k) * 100**
""")

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
        sentiment_score,
        ai_grade
    FROM vacancies
    WHERE
        ai_grade IN ('Junior','Middle','Senior')
        AND requirements_density IS NOT NULL
    """

    df = pd.read_sql(query, conn)
    conn.close()

    return df


df = load_data()

if df.empty:
    st.error("В базе нет размеченных вакансий.")
    st.stop()


# --------------------------------------------------------
# ОПРЕДЕЛЕНИЕ ТЕХНОЛОГИИ
# --------------------------------------------------------

def detect_technology(title: str):
    title = str(title).lower()

    patterns = {
        "Python": ["python"],
        "Java": [" java ", "java developer", "java-разработчик"],
        "JavaScript": ["javascript", "js developer", "frontend", "фронтенд"],
        "TypeScript": ["typescript"],
        "Go": [" golang", "go developer", "go-разработчик"],
        "C#": ["c#", ".net", "asp.net"],
        "C++": ["c++"],
        "PHP": ["php"],
        "Kotlin": ["kotlin"],
        "Swift": ["swift"],
        "Rust": ["rust"],
        "Scala": ["scala"],
        "Ruby": ["ruby"],
        "Dart": ["dart", "flutter"],
        "1C": ["1с", "1c"],
        "DevOps": ["devops", "sre"],
        "QA": [" qa ", "qa engineer", "tester", "тестировщик", "qa-инженер"],
        "Data Scientist": ["data scientist", "data science"],
        "ML": ["machine learning", "ml engineer", " ml "],
        "Android": ["android"],
        "iOS": ["ios"]
    }

    for tech, words in patterns.items():
        for word in words:
            if word.lower() in title:
                return tech

    return "Other"


df["technology"] = df["title"].apply(detect_technology)

# --------------------------------------------------------
# ГЛОБАЛЬНЫЙ РАСЧЕТ И НОРМАЛИЗАЦИЯ (ДЛЯ ВСЕГО РЫНКА)
# --------------------------------------------------------
# Чтобы найти min и max, мы должны сначала просчитать k_raw для всех комбинаций
grade_map = {"Junior": 1, "Middle": 2, "Senior": 3}
df['grade_num'] = df['ai_grade'].map(grade_map)

# Агрегируем все данные глобально
global_stats = df.groupby(['technology', 'ai_grade']).agg(
    count=('title', 'count'),
    avg_salary=('salary_score', lambda x: x.mean() if pd.notna(x.mean()) else 5.0),
    avg_density=('requirements_density', lambda x: x.mean() if pd.notna(x.mean()) else 5.0),
    avg_comp=('competition_score', lambda x: x.mean() if pd.notna(x.mean()) else 5.0),
    grade_num=('grade_num', 'first')
).reset_index()

max_count = global_stats['count'].max()

# Нормированные переменные для формулы
global_stats['Nn'] = np.log(global_stats['count'] + 1) / np.log(max_count + 1)
global_stats['Sn'] = global_stats['avg_salary'] / 10
global_stats['Dn'] = global_stats['avg_density'] / 10
global_stats['Gn'] = global_stats['grade_num'] / 3
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
    sorted(df["technology"].unique())
)

grade = st.sidebar.radio(
    "Грейд",
    ["Junior", "Middle", "Senior"]
)

# Фильтруем сырые данные для таблиц
filtered = df[
    (df["technology"] == technology) & (df["ai_grade"] == grade)
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
# ИЗВЛЕЧЕНИЕ РАССЧИТАННЫХ ДАННЫХ
# --------------------------------------------------------

vacancies_count = int(selected_stat['count'])
avg_salary = selected_stat['avg_salary']
avg_density = selected_stat['avg_density']
avg_competition = selected_stat['avg_comp']

Nn = selected_stat['Nn']
Sn = selected_stat['Sn']
Dn = selected_stat['Dn']
Gn = selected_stat['Gn']
Cn = selected_stat['Cn']
k_raw = selected_stat['k_raw']
k_score = selected_stat['k_score']

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
# KPI
# --------------------------------------------------------

c1, c2, c3, c4 = st.columns(4)

c1.metric(
    "📈 Коэффициент востребованности",
    f"{k_score}/100"
)

c2.metric(
    "💼 Вакансий",
    vacancies_count
)

c3.metric(
    "💰 Средняя зарплата",
    f"{avg_salary:.2f}"
)

c4.metric(
    "🏆 Оценка",
    demand
)

st.divider()

# --------------------------------------------------------
# ПОКАЗАТЕЛИ МОДЕЛИ
# --------------------------------------------------------

left, right = st.columns([1, 1])

with left:
    st.subheader("Показатели модели")
    st.metric("Плотность требований", round(avg_density, 2))
    st.metric("Конкуренция", round(avg_competition, 2))
    st.metric("Грейд", grade)

with right:
    st.subheader("Нормированные значения")
    norm = pd.DataFrame({
        "Параметр": ["Nₙ", "Sₙ", "Dₙ", "Gₙ", "Cₙ"],
        "Значение": [round(Nn, 3), round(Sn, 3), round(Dn, 3), round(Gn, 3), round(Cn, 3)]
    })

    st.dataframe(
        norm,
        hide_index=True,
        use_container_width=True
    )

st.divider()

# --------------------------------------------------------
# РАСЧЕТ ФОРМУЛЫ
# --------------------------------------------------------

st.subheader("Расчет коэффициента")

st.latex(r"""
K_{raw} = 0.35N_n + 0.25S_n + 0.20D_n + 0.05G_n - 0.15C_n
""")
st.latex(r"""
K_{score} = \frac{K_{raw} - K_{min}}{K_{max} - K_{min}} \times 100
""")

st.code(f"""
[1] Подставляем нормированные значения в сырую формулу:
Nn = {Nn:.3f} | Sn = {Sn:.3f} | Dn = {Dn:.3f} | Gn = {Gn:.3f} | Cn = {Cn:.3f}

K_raw = (0.35 × {Nn:.3f}) + (0.25 × {Sn:.3f}) + (0.20 × {Dn:.3f}) + (0.05 × {Gn:.3f}) - (0.15 × {Cn:.3f})
K_raw = {k_raw:.4f}

[2] Применяем Min-Max нормализацию относительно всего рынка:
Абсолютный минимум рынка (K_min) = {min_k:.4f}
Абсолютный максимум рынка (K_max) = {max_k:.4f}

K_score = ({k_raw:.4f} - {min_k:.4f}) / ({max_k:.4f} - {min_k:.4f}) * 100
K_score = {k_score:.2f}
""")

# --------------------------------------------------------
# ГРАФИК ВКЛАДА КРИТЕРИЕВ В КОЭФФИЦИЕНТ
# --------------------------------------------------------

st.subheader("📊 Вклад каждого критерия (в сырой K_raw)")

contrib = pd.DataFrame({
    "Критерий": [
        "Количество",
        "Зарплата",
        "Требования",
        "Грейд",
        "Конкуренция"
    ],
    "Вклад": [
        0.35 * Nn,
        0.25 * Sn,
        0.20 * Dn,
        0.05 * Gn,
        -0.15 * Cn
    ]
})

fig = px.bar(
    contrib,
    x="Критерий",
    y="Вклад",
    text="Вклад",
    color="Вклад",
    color_continuous_scale="RdBu"
)

fig.update_traces(texttemplate="%{text:.3f}")
st.plotly_chart(fig, use_container_width=True)

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

company_df = (
    filtered["company"]
    .value_counts()
    .head(10)
    .reset_index()
)
company_df.columns = ["Компания", "Вакансий"]

fig = px.bar(
    company_df,
    x="Компания",
    y="Вакансий",
    text="Вакансий"
)
st.plotly_chart(fig, use_container_width=True)

st.divider()

# --------------------------------------------------------
# СПИСОК ВАКАНСИЙ
# --------------------------------------------------------

st.subheader("📄 Найденные вакансии")

table = filtered[[
    "title",
    "company",
    "salary",
    "salary_score",
    "competition_score",
    "requirements_density",
    "link"
]]

table.columns = [
    "Название",
    "Компания",
    "Зарплата (текст)",
    "Оценка ИИ: Зарплата",
    "Оценка ИИ: Конкуренция",
    "Оценка ИИ: Требования",
    "Ссылка"
]

st.dataframe(
    table,
    use_container_width=True,
    hide_index=True
)

st.divider()

# --------------------------------------------------------
# СТАТИСТИКА ПО ВСЕМ ГРЕЙДАМ ВЫБРАННОЙ ТЕХНОЛОГИИ
# --------------------------------------------------------

st.subheader(f"📈 Сравнение грейдов для {technology}")

# Вытаскиваем уже посчитанные глобальные данные для выбранной технологии
tech_grades = global_stats[global_stats['technology'] == technology].copy()
tech_grades = tech_grades.sort_values(by='grade_num')

if not tech_grades.empty:
    fig = px.bar(
        tech_grades,
        x="ai_grade",
        y="k_score",
        text="k_score",
        color="ai_grade",
        color_discrete_map={'Junior': '#1f77b4', 'Middle': '#2ca02c', 'Senior': '#ff7f0e'},
        labels={"ai_grade": "Грейд", "k_score": "Интегральный индекс (0-100)"}
    )
    fig.update_layout(yaxis_range=[0, 100], showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

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
от 🔴 **Низкого спроса (самая непривлекательная связка на рынке)** до 🔥 **Очень высокого спроса (самая востребованная)**.
""")

st.success("✅ Анализ завершён.")