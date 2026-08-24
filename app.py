import streamlit as st

from utils.loader import load_news
from utils.loader import load_news_payload
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
# Data
# ======================

payload = load_news_payload()
news = payload["items"]


# ======================
# Language
# ======================

if "lang" not in st.session_state:
    st.session_state.lang = "中文"


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
        [
            "Highlights",
            "Macro Policy & Regulatory Updates",
            "DBG Internal Updates",
            "Competitor News"
        ]
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
        """
        <div class="highlight-box">

        <h3>
        ━ 本期导读 · Highlights
        </h3>

        </div>
        """,
        unsafe_allow_html=True
    )


    for i,item in enumerate(news[:5],1):

        st.markdown(
            f"""
            <div class="highlight-item">

            <b>{i}. [{item['category']}] 
            {item.get('title_cn') if st.session_state.lang == "中文" else item.get('title_en') or item.get('title_original')}</b>

            <br><br>

            来源：
            {item['source']}

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
        if x["category"] == target
    ]


    st.markdown(
        f"""
        ## {section}

        """
    )


    if filtered:


        subcategories = sorted(
            list(
                set(
                    x["subcategory"]
                    for x in filtered
                )
            )
        )


        tabs = st.tabs(subcategories)



        for tab,subcategory in zip(
            tabs,
            subcategories
        ):


            with tab:


                items = [
                    x for x in filtered
                    if x["subcategory"] == subcategory
                ]


                for item in items:


                    st.markdown(
                        f"""

                        <div class="news-card">


                        <div class="date">
                        {item['date']}
                        </div>


                        <h3>
                        {item.get('title_cn') if st.session_state.lang == "中文" else item.get('title_en') or item.get('title_original')}
                        </h3>


                        <p>
                        {item.get('summary','')}
                        </p>


                        <div class="source">

                        🏢 {item['source']}

                        </div>


                        <br>


                        <a href="{item['url']}"
                        target="_blank">

                        阅读原文 →

                        </a>


                        </div>


                        """,
                        unsafe_allow_html=True
                    )


    else:


        st.info(
            """
            本周暂无更新

            No updates this week.
            """
        )
