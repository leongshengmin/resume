import streamlit as st

st.set_page_config(
    page_title="Faster AMI replacement for Stateful Nodes",
    page_icon="",
)

st.markdown("# Faster AMI replacement for Stateful Nodes")
with open("pages/faster_ami_replacement.md", "r") as f:
    data = f.read()

st.markdown(data)
st.sidebar.header("Faster AMI replacement for Stateful Nodes")
