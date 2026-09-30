import pandas as pd
import streamlit as st

from core.storage import runs_overview


def short_date(value):
    return str(value or "")[:10]


def short_time(value):
    return str(value or "").replace("T", " ")[:16]


def run_label(row):
    return f"{row['name']} ({short_time(row['started_at'])})"


def completed_runs():
    return [row for row in runs_overview() if row["state"] == "COMPLETED"]


def ranked(suppliers):
    return sorted(suppliers, key=lambda s: s["rank"])


def bullets(items, empty="None noted."):
    items = [str(item).strip() for item in items or [] if str(item).strip()]
    if not items:
        st.caption(empty)
        return
    st.markdown("\n".join(f"- {item}" for item in items))


def ranking_frame(suppliers):
    rows = [
        {
            "Rank": s["rank"],
            "Supplier": s["supplier"],
            "Absolute": s["absolute"],
            "PPI": s["ppi"],
            "Submitted": short_date(s["submitted_on"]),
            "Experience": s["experience"],
            "Rank note": s.get("rank_note") or "",
        }
        for s in ranked(suppliers)
    ]
    return pd.DataFrame(rows)


def ranking_table(suppliers, with_note=True):
    frame = ranking_frame(suppliers)
    if not with_note:
        frame = frame.drop(columns=["Rank note"])
    config = {
        "Rank": st.column_config.NumberColumn(width=60),
        "Supplier": st.column_config.TextColumn(width=200),
        "Absolute": st.column_config.NumberColumn(format="%.2f", width=90),
        "PPI": st.column_config.NumberColumn(format="%.2f", width=80),
        "Submitted": st.column_config.TextColumn(width=110),
        "Experience": st.column_config.NumberColumn(format="%.1f", width=100),
        "Rank note": st.column_config.TextColumn(width="large"),
    }
    st.dataframe(frame, hide_index=True, column_config=config, width="stretch")


def winner_card(supplier):
    with st.container(border=True):
        st.markdown(f":green-badge[Winner] **{supplier['supplier']}**")
        left, right = st.columns(2)
        left.metric("PPI", f"{supplier['ppi']:.2f}")
        right.metric("Absolute score", f"{supplier['absolute']:.2f}")


def notes(run):
    for note in run.get("notes") or []:
        st.warning(note)
