import streamlit as st
import math
from app.constant import *
from app.utils import timeline, table


def setup_page():
    st.set_page_config(
        page_title="Leong Shengmin's Resume", layout="wide", page_icon="👨‍🔬"
    )

    st.sidebar.markdown(f"LinkedIn: {info['LinkedIn']}")
    st.sidebar.markdown(f"Email: {info['Email']}")
    pdfFileObj = open("pdfs/resume.pdf", "rb")
    st.sidebar.download_button(
        "Download Resume",
        pdfFileObj,
        file_name="resume.pdf",
        mime="pdf",
        key="sidebar_resume_download",
    )

    st.subheader("Hi :wave: I'm Shengmin")
    st.write(info["Brief"])
    st.markdown(DOWNLOAD_BUTTON_CSS, unsafe_allow_html=True)
    st.download_button(
        "Download Resume",
        pdfFileObj,
        file_name="resume.pdf",
        mime="pdf",
        key="subheader_resume_download",
        type="primary",
    )

    ####
    # Career section
    ####
    st.subheader("Career")
    with st.spinner(text="Building timeline"):
        with open("app/career.json", "r") as f:
            data = f.read()
            timeline.timeline(data, height=400, start_at_end=True)

    career_tab = table.create_table(info["career"])
    st.plotly_chart(career_tab)

    ####
    # Skills section
    ####
    st.subheader("Skills & Tools ⚒️")
    with st.spinner(text="Loading section..."):
        data_count = len(info["skills_or_tech"])
        columns = st.columns(data_count)
        for i in range(data_count):
            skill = info["skills_or_tech"][i]
            columns[i].button(label=skill)

    ####
    # Education section
    ####
    st.subheader("Education 📖")
    with st.spinner(text="Loading section..."):
        edu_tab = table.create_table(info["edu"])
        st.plotly_chart(edu_tab)

    ####
    # Projects section
    ####
    st.subheader("Projects")
    with st.spinner(text="Loading section..."):
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
