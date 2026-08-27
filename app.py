import html

import streamlit as st

from utils.loader import list_published_reports
from utils.loader import load_news_payload
from utils.loader import report_label
from utils.style import load_style


# ======================
# Page config
# ======================

st.set_page_config(
    page_title="DBG Weekly Intelligence",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)


load_style()


# ======================
if "lang" not in st.session_state:
    st.session_state.lang = "中文"


NAVIGATION = [
    ("Highlights", "一、本期导读", "Highlights", None),
    ("Macro Policy & Regulatory Updates", "二、宏观政策与监管动态", "Macro Policy & Regulatory Updates", "Macro"),
    ("DBG Internal Updates", "三、德交所集团内部动态", "DBG Internal Updates", "DBG"),
    ("Competitor News", "四、竞争对手动态", "Competitor News", "Competitor"),
]


FALLBACK_SECTIONS = {
    "Macro": ["中国", "美国", "英国", "欧洲", "国际组织", "亚太", "其他地区"],
    "DBG": ["集团要闻", "交易与清算", "投资管理解决方案", "证券与基金服务", "信息技术"],
    "Competitor": [
        "Eurex",
        "EEX",
        "360T",
        "Crypto Finance",
        "SimCorp",
        "ISS STOXX",
        "STOXX",
        "Clearstream",
        "DBG Market Data",
        "7 Market Technology",
    ],
}


def current_language():
    return st.session_state.lang


def label(cn, en):
    return cn if current_language() == "中文" else en


def title_for_section(section_key):
    for key, cn, en, _ in NAVIGATION:
        if key == section_key:
            return label(cn, en)
    return section_key


def groups_for_category(payload, category):
    for section in payload.get("sections", []):
        if section.get("key") == category and section.get("groups"):
            return section.get("groups", [])
    return FALLBACK_SECTIONS.get(category, [])


def group_value(item, category):
    if category == "Competitor":
        return item.get("brand") or item.get("subcategory", "")
    return item.get("subcategory", "")


def localized_title(item):
    if current_language() == "中文":
        return item.get("title_cn") or item.get("title_original") or item.get("title_en")
    return item.get("title_en") or item.get("title_original") or item.get("title_cn")


def localized_summary(item):
    if current_language() == "中文":
        return item.get("summary_cn") or item.get("summary_original") or item.get("summary") or item.get("summary_en")
    return item.get("summary_en") or item.get("summary_original") or item.get("summary") or item.get("summary_cn")


def empty_message():
    return "本周暂无更新" if current_language() == "中文" else "No updates this week."


# ======================
# Data
# ======================

published_reports = list_published_reports()
selected_report = None
if published_reports:
    selected_report = st.sidebar.selectbox(
        "Published week",
        published_reports,
        index=0,
        format_func=report_label,
    )

payload = load_news_payload(selected_report)
news = payload.get("items", [])
highlights = payload.get("highlights", news[:5])


# ======================
# Sidebar
# ======================

with st.sidebar:

    st.markdown(
        """
        <div class="sidebar-title">
        📊 DBG Weekly<br>
        Intelligence
        </div>
        """,
        unsafe_allow_html=True
    )


    st.markdown(
        """
        <div class="sidebar-sub">
        Deutsche Börse Group<br>
        Beijing Representative Office
        <br><br>
        Weekly Information Dashboard
        </div>
        """,
        unsafe_allow_html=True
    )


    st.divider()


    section = st.radio(
        "Navigation",
        [item[0] for item in NAVIGATION],
        format_func=title_for_section,
    )


    st.divider()


    st.caption(
        f"""
        Data period: {payload.get("week_start", "")} - {payload.get("week_end", "")}
        
        Information Sources: {payload.get("source_count", "")}
        
        """
    )



# ======================
# Header
# ======================

if not news:
    st.info(
        """
        No published weekly report is available yet.

        Publish an already-generated weekly JSON before deploying or viewing this app.
        """
    )
    st.stop()


col1, col2 = st.columns([5,1])


with col1:

    st.markdown(
        """
        <div class="header-small">
        WEEKLY BRIEFING
        </div>
        """,
        unsafe_allow_html=True
    )


    st.markdown(
        """
        # 德交所集团北京代表处<br>
        Weekly Intelligence Dashboard
        """,
        unsafe_allow_html=True
    )


with col2:

    st.button(
        "中文",
        key="cn",
        on_click=lambda: st.session_state.update(lang="中文")
    )

    st.button(
        "English",
        key="en",
        on_click=lambda: st.session_state.update(lang="English")
    )



st.write("")



# ======================
# Highlights
# ======================


if section == "Highlights":

    st.markdown(
        f"""
        <div class="highlight-box">

        <h3>
        {title_for_section("Highlights")}
        </h3>

        </div>
        """,
        unsafe_allow_html=True
    )


    for i,item in enumerate(highlights,1):
        summary = (localized_summary(item) or "").strip()
        summary_html = f'<p class="highlight-summary">{html.escape(summary)}</p>' if summary else ""
        title = html.escape(localized_title(item) or "")

        st.markdown(
            f"""
            <div class="highlight-item">

            <b>{i}. [{item.get('category', '')}]
            {title}</b>

            <br><br>

            {summary_html}

            来源：
            {item.get('source', '')}

            <br><br>

            <a href="{item.get('url', '#')}" target="_blank">
            阅读原文 →
            </a>

            </div>

            """,
            unsafe_allow_html=True
        )



# ======================
# Sections
# ======================


else:


    category_map = {

        "Macro Policy & Regulatory Updates":
            "Macro",

        "DBG Internal Updates":
            "DBG",

        "Competitor News":
            "Competitor"

    }


    target = category_map[section]


    filtered = [
        x for x in news
        if x.get("category") == target
    ]


    st.markdown(f"## {title_for_section(section)}")


    subcategories = groups_for_category(payload, target)
    tabs = st.tabs(subcategories)



    for tab,subcategory in zip(
        tabs,
        subcategories
    ):


        with tab:


            items = [
                x for x in filtered
                if group_value(x, target) == subcategory
            ]


            if not items:
                st.info(empty_message())
                continue

            for item in items:
                title = html.escape(localized_title(item) or "")
                summary = html.escape((localized_summary(item) or "").strip())


                st.markdown(
                    f"""

                    <div class="news-card">


                    <div class="date">
                    {item.get('date', '')}
                    </div>


                    <h3>
                    {title}
                    </h3>


                    <p>
                    {summary}
                    </p>


                    <div class="source">

                    🏢 {item.get('source', '')}

                    </div>


                    <br>


                    <a href="{item.get('url', '#')}"
                    target="_blank">

                    阅读原文 →

                    </a>


                    </div>


                    """,
                    unsafe_allow_html=True
                )
