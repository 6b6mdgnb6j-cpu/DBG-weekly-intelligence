import streamlit as st


def load_style():

    st.markdown(
        """

<style>


/* 页面背景 */

.stApp {

    background-color:#F3F6FA;

}



/* sidebar */

section[data-testid="stSidebar"] {

    background-color:#062B4F;

}



section[data-testid="stSidebar"] * {

    color:white;

}


section[data-testid="stSidebar"] [data-baseweb="select"] *,
section[data-testid="stSidebar"] [data-baseweb="popover"] *,
section[data-testid="stSidebar"] input,
section[data-testid="stSidebar"] div[role="combobox"] * {

    color:#12304A !important;

}



.sidebar-title {

font-size:28px;
font-weight:800;
line-height:1.2;

}



.sidebar-sub {

font-size:14px;
line-height:1.8;
opacity:0.9;

}




/* header */


.header-small {

color:#D79A2B;

font-size:14px;

letter-spacing:4px;

font-weight:700;

}



/* 标题 */

h1 {

color:#12304A;

font-size:42px !important;

}



/* highlight */

.highlight-item {


background:white;

border-radius:12px;

padding:20px;

margin-bottom:15px;

border-left:5px solid #D79A2B;

box-shadow:
0 3px 12px rgba(0,0,0,0.05);


}



/* news card */


.news-card {


background:white;

border-radius:15px;

padding:25px;

margin-bottom:20px;

box-shadow:
0 4px 15px rgba(0,0,0,0.08);


}



.news-card h3 {

color:#12304A;

}



.date {


background:#EAF1FA;

display:inline-block;

padding:5px 12px;

border-radius:10px;

font-size:14px;

}



.source {

color:#667085;

font-size:14px;

}



a {

color:#0057A8 !important;

font-weight:600;

}




/* tab */

button[data-baseweb="tab"] {


border-radius:20px;


}




</style>


        """,
        unsafe_allow_html=True
    )
