import streamlit as st
from constant import *
from utils import timeline, table
import plotly.graph_objects as go


st.set_page_config(
    page_title="Leong Shengmin's Resume", layout="wide", page_icon="👨‍🔬"
)

st.sidebar.markdown(f"LinkedIn: {info['LinkedIn']}", unsafe_allow_html=True)
st.sidebar.markdown(f"Email: {info['Email']}")
pdfFileObj = open("pdfs/resume.pdf", "rb")
st.sidebar.download_button(
    "Download Resume", pdfFileObj, file_name="resume.pdf", mime="pdf"
)


st.subheader("Hi :wave: I'm Shengmin")
st.write(info["Brief"])

####
# Career section
####
st.subheader("Career")
with st.spinner(text="Building timeline"):
    with open("career.json", "r") as f:
        data = f.read()
        timeline.timeline(data, height=600, start_at_end=True)

career_tab = table.create_table(info["career"], height=400)
st.plotly_chart(career_tab)

####
# Skills section
####
st.subheader("Skills & Tools ⚒️")
with st.spinner(text="Loading section..."):
    rows = len(info["skills_or_tech"])
    for i in range(rows):
        columns = st.columns(SKILLS_NUM_COLUMNS)
        skill = info["skills_or_tech"][i]
        columns[SKILLS_NUM_COLUMNS - 1].button(label=skill)

####
# Education section
####
st.subheader("Education 📖")
edu_tab = table.create_table(info["edu"], height=250)
st.plotly_chart(edu_tab)

####
# Projects section
####
st.subheader("Projects")
st.markdown(
    "\n".join(
        [
            f"""
**{item['title']}**
- {item['description']}
"""
            for item in info["projects"]
        ]
    )
)
