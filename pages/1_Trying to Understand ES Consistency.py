import streamlit as st

st.set_page_config(
    page_title="Trying to Understand How ES Does Consistency",
    page_icon="",
)

st.markdown(
    """
            # Trying to Understand How Elasticsearch Does Consistency
            *Document is still a WIP*
"""
)
with open("pages/es_consistency_principles.md", "r") as f:
    data = f.read()

st.markdown(data)
st.sidebar.header("Trying to Understand How Elasticsearch Does Consistency")
