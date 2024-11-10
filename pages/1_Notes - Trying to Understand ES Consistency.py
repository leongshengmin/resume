import streamlit as st

st.set_page_config(
    page_title="Notes to self - Trying to Understand How ES Does Consistency",
    page_icon="",
)

st.markdown(
    """
            # Notes to self - Trying to Understand How ES Does Consistency
            *Document is still a WIP*
"""
)
with open("pages/es_consistency_principles.md", "r") as f:
    data = f.read()

st.markdown(data)
st.sidebar.header("Notes to self - Trying to Understand How ES Does Consistency")
