import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DIR = ROOT / "samples" / "proposals"
BROKEN_DIR = ROOT / "samples" / "broken"
DEFAULT_MODEL = "openai/gpt-oss-120b"

SAMPLE_DETAILS = {
    "Meridian_Softworks_Technical_and_Commercial_Proposal.pdf": ("Meridian Softworks", "2026-09-10", 4.5),
    "QuickDesk - Proposal for Sundaram Retail.pdf": ("QuickDesk Solutions", "2026-09-08", 2.0),
    "Tarang Systems_Response_SRL-IT-2026-014.pdf": ("Tarang Systems", "2026-09-09", 4.0),
    "NSCS_Proposal_Final (signed).pdf": ("Northstar Consulting", "2026-09-11", 5.0),
}


@dataclass
class Settings:
    api_key: str
    model: str
    live: bool

    @property
    def label(self):
        if self.live:
            return f"Groq {self.model}"
        return "Offline keyword scorer"


def database_path():
    return Path(os.environ.get("RFP_DB", str(ROOT / "database" / "rfp.sqlite")))


def read_secret(name):
    try:
        import streamlit as st

        value = st.secrets.get(name)
    except Exception:
        return None
    if value is None:
        return None
    return str(value).strip()


def read_value(name, default):
    value = read_secret(name)
    if value:
        return value
    value = os.environ.get(name, "").strip()
    if value:
        return value
    return default


def load_settings():
    load_dotenv(ROOT / ".env")
    api_key = read_value("GROQ_API_KEY", "")
    model = read_value("GROQ_MODEL", DEFAULT_MODEL)
    mode = read_value("LLM_MODE", "live").lower()
    live = bool(api_key) and mode == "live"
    return Settings(api_key=api_key, model=model, live=live)
