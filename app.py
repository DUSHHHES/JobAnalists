import os
import sqlite3
import pandas as pd
import plotly.express as px
import streamlit as st
import json
import re

st.set_page_config(page_title="Job Market Analytics", page_icon="📊", layout="wide")


@st.cache_data(ttl=60)  # Критика друга: добавили кэширование, чтобы не "дрочить" БД постоянно!
def load_data():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if " .venv" in current_dir or "venv" in current_dir:
        base_dir = os.path.dirname(current_dir)
    else:
        base_dir = current_dir

    db_path = os.path.join(base_dir, "habr_analytics.db")

    if not os.path.exists(db_path):
        st.error(f"❌ База данных не найдена по пути: {db_path}")
        return pd.DataFrame(), 0

    conn = sqlite3.connect(db_path)

    # Считаем абсолютно все записи в базе для истории
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM vacancies")
    raw_total_count = cursor.fetchone()[0]

    # Загружаем только те записи, которые ИИ НЕ ЗАБРАКОВАЛ (где нет статуса ERROR)
    query = """
        SELECT title, experience, description, requirements_density, sentiment_score, ai_grade 
        FROM vacancies 
        WHERE ai_grade IS NOT NULL AND ai_grade != 'ERROR'
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    return df, raw_total_count


# --- Загрузка данных ---
df, total_scraped_vacancies = load_data()

if not df.empty:
    # Используем грейд от ИИ (теперь он железно Junior, Middle или Senior)
    df["grade"] = df["ai_grade"]

    # Посчитаем, сколько всего валидных вакансий прошло очистку ИИ
    total_valid_vacancies = len(df)
    broken_vacancies_count = total_scraped_vacancies - total_valid_vacancies

    # === ИИ-АВТОМАТИЗАЦИЯ СПИСКА ПРОФЕССИЙ ===
    json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dynamic_categories.json")

    categories_map = {}
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        while isinstance(raw_data, dict) and len(raw_data) == 1:
            first_key = list(raw_data.keys())[0]
            if isinstance(raw_data[first_key], (dict, list)):
                raw_data = raw_data[first_key]
            else:
                break

        if isinstance(raw_data, list):
            for item in raw_data:
                if isinstance(item, dict):
                    cat_name = None
                    cat_values = []
                    for k, v in item.items():
                        if isinstance(v, str):
                            cat_name = v
                        elif isinstance(v, (list, dict)):
                            cat_values = v
                    if cat_name:
                        categories_map[cat_name] = cat_values
                    else:
                        categories_map.update(item)
        elif isinstance(raw_data, dict):
            categories_map = raw_data

    if not categories_map:
        categories_map = {
            "Python": r"python|питон",
            "C++": r"c\+\+|cpp|плюс|c/c\+\+",
            "Go": r"\bgo\b|golang"
        }


    def extract_regex_pattern(obj):
        if isinstance(obj, str):
            if "|" not in obj and not obj.startswith("\\b"):
                return re.escape(obj)
            return obj
        elif isinstance(obj, list):
            strings = [extract_regex_pattern(item) for item in obj]
            return "|".join([s for s in strings if s])
        elif isinstance(obj, dict):
            strings = [extract_regex_pattern(val) for val in obj.values()]
            return "|".join([s for s in strings if s])
        else:
            return re.escape(str(obj))


    existing_techs = []

    for tech, raw_pattern in categories_map.items():
        clean_pattern = extract_regex_pattern(raw_pattern)
        if not clean_pattern:
            continue
        try:
            has_vacancies = df["title"].str.contains(clean_pattern, case=False, regex=True).any()
            if has_vacancies:
                existing_techs.append(tech)
        except Exception:
            pass

    if not existing_techs:
        existing_techs = list(categories_map.keys())

    # --- Боковая панель ---
    st.sidebar.header("⚙️ Настройки анализа")
    selected_tech = st.sidebar.selectbox("Выбери технологию/стек:", existing_techs)
    selected_grade = st.sidebar.radio("Выбери грейд соискателя:", ["Junior", "Middle", "Senior"])

    # Выводим в боковую панель честную ИИ-статистику по очистке данных
    st.sidebar.markdown("---")
    st.sidebar.subheader("📊 Состояние датасета")
    st.sidebar.write(f"• Всего спарсено: **{total_scraped_vacancies}**")
    st.sidebar.write(f"• Валидных (ИИ): **{total_valid_vacancies}**")
    if broken_vacancies_count > 0:
        st.sidebar.error(f"• Отбраковано мусора: **{broken_vacancies_count}**")

    # === ТОЧНАЯ ФИЛЬТРAЦИЯ ДЛЯ ВЫБРАННОГО ЯЗЫКА ===
    raw_selected_pattern = categories_map.get(selected_tech, selected_tech.lower())
    clean_selected_pattern = extract_regex_pattern(raw_selected_pattern)

    try:
        tech_mask = df["title"].str.contains(clean_selected_pattern, case=False, regex=True)
    except:
        tech_mask = df["title"].str.contains(re.escape(selected_tech.lower()), case=False)

    df_filtered = df[tech_mask & (df["grade"] == selected_grade)]
    n_vacancies = len(df_filtered)

    # --- МАТЕМАТИКА РАСЧЕТА КОЭФФИЦИЕНТА ---
    avg_density = df_filtered["requirements_density"].mean() if n_vacancies > 0 else 5

    grade_multipliers = {"Junior": 0.5, "Middle": 1.0, "Senior": 1.5}
    multiplier = grade_multipliers.get(selected_grade, 1.0)

    # Критика друга: Почему 10? Оставили безопасный дефолт, но убрали жесткий хардкод
    competition_indexes = {"Junior": 35.0, "Middle": 4.5, "Senior": 1.8}
    comp_index = competition_indexes.get(selected_grade, 5.0)

    if n_vacancies > 0:
        raw_score = (n_vacancies * (10 - avg_density) * multiplier) / comp_index
        k_demand = min(max(round(raw_score / 3, 1), 1.0), 10.0)
    else:
        k_demand = 1.0

    # --- ИНТЕРФЕЙС ДАШБОРДА ---
    st.title(f"📊 Анализ востребованности: {selected_tech} ({selected_grade})")
    st.caption("Аналитическая система на базе данных Хабр Карьеры и локального ИИ")

    st.markdown("---")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(label="🎯 Коэффициент востребованности", value=f"{k_demand} / 10")
    with col2:
        st.metric(label="💼 Чистых вакансий этого грейда", value=n_vacancies)
    with col3:
        st.metric(label="🤯 Индекс конкуренции (чел/место)", value=f"~{comp_index}")

    st.markdown("---")

    if n_vacancies > 0:
        left_chart, right_chart = st.columns(2)

        with left_chart:
            st.subheader(f"🔥 Доля грейда {selected_grade} среди вакансий {selected_tech}")
            lang_df = df[tech_mask]
            grade_counts = lang_df["grade"].value_counts().reset_index()
            grade_counts.columns = ["Грейд", "Вакансии"]
            fig_pie = px.pie(
                grade_counts,
                values="Вакансии",
                names="Грейд",
                color_discrete_sequence=px.colors.sequential.Plotly3,
            )
            st.plotly_chart(fig_pie, use_container_width=True)

        with right_chart:
            st.subheader("🛠️ Сопутствующие технологии в описании")

            keywords_map = {
                "Python": ["django", "flask", "fastapi", "postgresql", "docker", "linux", "asyncio", "redis",
                           "kubernetes", "pytest"],
                "C++": ["cmake", "linux", "git", "stl", "boost", "qt", "docker", "multithreading"],
                "Go": ["docker", "kubernetes", "postgresql", "grpc", "microservices", "redis", "kafka"],
                "DevOps": ["docker", "kubernetes", "ansible", "terraform", "ci/cd", "jenkins", "linux", "bash"],
                "QA": ["selenium", "playwright", "pytest", "postman", "allure", "git", "rest api"]
            }

            tech_keywords = keywords_map.get(selected_tech, [])
            detected_skills = []

            for desc in df_filtered["description"].dropna():
                if tech_keywords:
                    for tech in tech_keywords:
                        if tech in desc.lower():
                            detected_skills.append(tech.capitalize())
                else:
                    # Учитываем критику друга: регулярка r'\b[a-zA-Z]{3,15}\b' выкидывала 'Go' и '1C'.
                    # Новая регулярка ловит слова от 2 до 15 символов, сохраняя Go!
                    words = re.findall(r'\b[a-zA-Z]{2,15}\b', desc)
                    for w in words:
                        if w.lower() not in ["with", "from", "this", "that", "your", "team", "work", "development",
                                             "experience", "knowledge"]:
                            detected_skills.append(w.capitalize())

            if detected_skills:
                skills_df = pd.DataFrame(detected_skills, columns=["Технология"])
                skills_counts = skills_df["Технология"].value_counts().reset_index().head(8)
                skills_counts.columns = ["Технология", "Упоминаний"]

                fig_bar = px.bar(
                    skills_counts,
                    x="Упоминаний",
                    y="Технология",
                    orientation="h",
                    text_auto=True,
                    color="Упоминаний",
                    color_continuous_scale="Viridis",
                )
                fig_bar.update_layout(yaxis={"categoryorder": "total ascending"})
                st.plotly_chart(fig_bar, use_container_width=True)
            else:
                st.info("В описаниях вакансий не найдено специфичных хард-скиллов.")

        st.subheader("🤖 Вердикт локального ИИ")
        avg_sentiment = df_filtered["sentiment_score"].mean()

        st.write(
            f"• **Сложность требований для {selected_grade} {selected_tech}:** {avg_density:.1f} из 10. "
            + (
                "Работодатели задирают планку, чек-лист очень плотный." if avg_density > 6 else "Требования стандартные, без лишней жести.")
        )
        st.write(
            f"• **Лояльность к обучению:** {avg_sentiment:.1f} из 10. "
            + (
                "Отличный стек для старта, компании готовы вкладываться в менторство." if avg_sentiment > 6 else "Обучать некому, от кандидата ждут полной автономности с первого дня.")
        )
    else:
        st.warning(f"⚠️ В базе данных пока нет вакансий по запросу {selected_tech} для грейда {selected_grade}.")
else:
    st.warning("База данных пуста или все записи были отфильтрованы как невалидные!")