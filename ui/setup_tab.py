import math

import pandas as pd
import streamlit as st

from core.reply import criteria_errors
from core.storage import list_criteria, prepare_database, replace_criteria

FIELDS = ["id", "title", "guidance", "weight", "max_points", "active"]

CONFIG = {
    "id": st.column_config.NumberColumn("ID", min_value=1, step=1, width=60),
    "title": st.column_config.TextColumn("Criterion", width=200, required=True),
    "guidance": st.column_config.TextColumn("What to look for", width=440),
    "weight": st.column_config.NumberColumn("Weight %", min_value=0, max_value=100, step=1, width=90),
    "max_points": st.column_config.NumberColumn("Max points", min_value=1, step=1, width=100),
    "active": st.column_config.CheckboxColumn("Active", width=70),
}


def _version():
    return st.session_state.setdefault("criteria_version", 0)


def _bump():
    st.session_state["criteria_version"] = _version() + 1


def _clean(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _rows(frame):
    rows = []
    for record in frame.to_dict("records"):
        row = {field: _clean(record.get(field)) for field in FIELDS}
        if all(row[field] in (None, "") for field in FIELDS if field != "active"):
            continue
        row["active"] = bool(row["active"])
        rows.append(row)
    return rows


def _weights(rows):
    total = sum(float(row["weight"] or 0) for row in rows if row["active"])
    st.progress(min(total / 100, 1.0), text=f"Active weights: {total:g}% of 100%")


def _save(rows):
    replace_criteria(rows)
    _bump()
    st.session_state["criteria_notice"] = "Criteria saved."


def _restore():
    prepare_database(reset_criteria=True)
    _bump()
    st.session_state["criteria_notice"] = "Default criteria restored."


def render(settings):
    st.subheader("Evaluation criteria")
    frame = pd.DataFrame(list_criteria(), columns=FIELDS)
    edited = st.data_editor(
        frame,
        key=f"criteria_{_version()}",
        num_rows="dynamic",
        hide_index=True,
        column_config=CONFIG,
        column_order=FIELDS,
        width="stretch",
    )
    rows = _rows(edited)
    _weights(rows)
    problems = criteria_errors(rows)
    for problem in problems:
        st.warning(problem)
    save, restore, _ = st.columns([1, 1, 4])
    blocked = bool(problems)
    save.button("Save", type="primary", disabled=blocked, on_click=_save, args=(rows,), width="stretch")
    restore.button("Restore defaults", on_click=_restore, width="stretch")
    notice = st.session_state.pop("criteria_notice", None)
    if notice:
        st.success(notice)
