import pandas as pd
import streamlit as st

from core.agent import adjust_score
from core.storage import load_run, lock_decision, remove_run, runs_overview
from ui.widgets import completed_runs, run_label, short_date, short_time

AUDIT_FIELDS = {
    "When": ("at", "created_at"),
    "Action": ("action",),
    "Supplier": ("supplier",),
    "Criterion": ("criterion_id",),
    "Old": ("old_value", "old_points"),
    "New": ("new_value", "new_points"),
    "Note": ("note", "reason"),
}


def _current_run():
    runs = completed_runs()
    ids = [row["run_id"] for row in runs]
    run_id = st.session_state.get("run_id")
    if run_id not in ids:
        run_id = ids[0] if ids else None
    return load_run(run_id) if run_id else None


def _flash():
    kind, text = st.session_state.pop("review_notice", (None, None))
    if kind == "success":
        st.success(text)
    elif kind == "error":
        st.error(text)


def _adjust_form(run):
    suppliers = {s["supplier"]: s for s in run["suppliers"]}
    titles = {item["id"]: item["title"] for item in run["suppliers"][0]["items"]}
    with st.container(border=True):
        st.markdown("**Change a score**")
        supplier_col, criterion_col = st.columns(2)
        supplier = supplier_col.selectbox("Supplier", list(suppliers), key="adjust_supplier")
        criterion = criterion_col.selectbox("Criterion", list(titles), format_func=titles.get,
                                            key="adjust_criterion")
        item = next(i for i in suppliers[supplier]["items"] if i["id"] == criterion)
        with st.form(f"adjust_{supplier}_{criterion}", clear_on_submit=True, border=False):
            points_col, reason_col = st.columns([1, 3])
            top, current = float(item["max_points"]), float(item["points"])
            points = points_col.number_input("New points", 0.0, top, current, 0.5)
            reason = reason_col.text_input("Reason")
            if st.form_submit_button("Save change", type="primary"):
                _apply(run["run_id"], supplier, criterion, points, reason)


def _apply(run_id, supplier, criterion, points, reason):
    if not reason.strip():
        st.error("Give a reason for the change.")
        return
    try:
        adjust_score(run_id, supplier, criterion, points, reason.strip())
    except ValueError as exc:
        st.error(str(exc))
        return
    st.session_state["review_notice"] = ("success", f"Score updated for {supplier}.")
    st.rerun()


def _lock_form(run):
    with st.form("lock_decision", border=True):
        st.markdown("**Lock decision**")
        note = st.text_input("Approval note")
        if st.form_submit_button("Lock decision"):
            _lock(run["run_id"], note)


def _lock(run_id, note):
    if not note.strip():
        st.error("Add an approval note before locking.")
        return
    try:
        lock_decision(run_id, note.strip())
    except ValueError as exc:
        st.error(str(exc))
        return
    st.rerun()


def _pick(row, keys):
    return next((row[key] for key in keys if row.get(key) is not None), "")


def _audit_row(row, titles):
    shown = {label: _pick(row, keys) for label, keys in AUDIT_FIELDS.items()}
    shown["When"] = short_time(shown["When"])
    shown["Action"] = str(shown["Action"]).replace("_", " ").capitalize()
    shown["Criterion"] = titles.get(shown["Criterion"], shown["Criterion"])
    return {label: "" if value is None else str(value) for label, value in shown.items()}


def _audit(run):
    st.subheader("Audit log")
    rows = run.get("audit") or []
    if not rows:
        st.caption("No changes recorded for this run.")
        return
    titles = {item["id"]: item["title"] for item in run["suppliers"][0]["items"]} if run["suppliers"] else {}
    frame = pd.DataFrame([_audit_row(row, titles) for row in rows])
    config = {"Note": st.column_config.TextColumn(width="large")}
    st.dataframe(frame, hide_index=True, column_config=config, width="stretch")


def _open(run_id):
    st.session_state["run_id"] = run_id
    st.session_state["tab"] = "Dashboard"


def _delete(run_id):
    remove_run(run_id)
    if st.session_state.get("run_id") == run_id:
        st.session_state.pop("run_id")
    st.session_state["review_notice"] = ("success", "Run deleted.")


def _history_frame(runs):
    rows = [
        {
            "Name": row["name"],
            "Date": short_date(row["started_at"]),
            "Status": row["state"].title(),
            "Suppliers": row["supplier_count"],
            "Winner": row.get("top_supplier") or "-",
            "Locked": bool(row["locked"]),
        }
        for row in runs
    ]
    return pd.DataFrame(rows)


def _history():
    st.subheader("History")
    runs = runs_overview()
    if not runs:
        st.caption("No runs yet.")
        return
    st.dataframe(_history_frame(runs), hide_index=True, width="stretch")
    by_id = {row["run_id"]: row for row in runs}
    pick_col, open_col, confirm_col, delete_col = st.columns([3, 1, 1, 1], vertical_alignment="bottom")
    labels = {run_id: run_label(row) for run_id, row in by_id.items()}
    picked = pick_col.selectbox("Run", list(by_id), format_func=labels.get, key="history_run")
    row = by_id[picked]
    open_col.button(
        "Open in dashboard",
        on_click=_open,
        args=(picked,),
        disabled=row["state"] != "COMPLETED",
        width="stretch",
    )
    sure = confirm_col.checkbox("Confirm delete", key=f"confirm_{picked}", disabled=bool(row["locked"]))
    delete_col.button(
        "Delete",
        on_click=_delete,
        args=(picked,),
        disabled=bool(row["locked"]) or not sure,
        width="stretch",
    )
    if row["locked"]:
        st.caption("Locked runs cannot be deleted.")


def _review(run):
    st.markdown(f"Reviewing **{run['name']}** ({short_date(run['started_at'])})")
    if run.get("locked"):
        when = short_time(run.get("locked_at"))
        st.info(f"This decision was locked on {when}. Scores can no longer change.")
    else:
        _adjust_form(run)
        _lock_form(run)
    _audit(run)


def render():
    _flash()
    run = _current_run()
    if run is None:
        st.info("No completed runs yet. Start one in the Run tab.")
    else:
        _review(run)
    _history()
