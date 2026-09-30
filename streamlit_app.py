import streamlit as st

from core.config import load_settings
from core.storage import prepare_database
from ui import dashboard_tab, review_tab, run_tab, setup_tab

TABS = ["Setup", "Run", "Dashboard", "Review"]

st.set_page_config(page_title="RFP Evaluation", layout="wide")
prepare_database()
settings = load_settings()

st.title("RFP Evaluation")

setup, run, dashboard, review = st.tabs(TABS, key="tab", on_change="rerun")
with setup:
    setup_tab.render(settings)
with run:
    run_tab.render(settings)
with dashboard:
    dashboard_tab.render()
with review:
    review_tab.render()
