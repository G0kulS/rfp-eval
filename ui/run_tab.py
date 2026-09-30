import datetime as dt
from pathlib import Path

import pandas as pd
import streamlit as st

from core.agent import RunFailed, Submission, evaluate_batch
from core.config import BROKEN_DIR, SAMPLE_DETAILS, SAMPLE_DIR
from core.reply import criteria_errors, submission_errors
from core.storage import list_criteria, load_run
from ui.widgets import notes, ranked, ranking_table, winner_card

DETAIL_CONFIG = {
    "filename": st.column_config.TextColumn("File", disabled=True, width=380),
    "supplier": st.column_config.TextColumn("Supplier", width=150),
    "submitted_on": st.column_config.DateColumn("Submitted", format="YYYY-MM-DD", width=110),
    "experience": st.column_config.NumberColumn(
        "Experience", min_value=1, max_value=5, step=0.5, width=90, help="Rating from 1 to 5"
    ),
}


def _files():
    return st.session_state.setdefault("files", {})


def _uploader_key():
    return f"uploads_{st.session_state.setdefault('uploader_version', 0)}"


def _add_folder(folder):
    for path in sorted(Path(folder).glob("*.pdf")):
        _files()[path.name] = path.read_bytes()


def _clear():
    st.session_state["files"] = {}
    st.session_state["details"] = {}
    st.session_state["uploader_version"] = st.session_state.get("uploader_version", 0) + 1
    st.session_state.pop("last_run", None)


def _defaults(filename):
    if filename in SAMPLE_DETAILS:
        supplier, day, experience = SAMPLE_DETAILS[filename]
        day = dt.date.fromisoformat(day)
        return {"supplier": supplier, "submitted_on": day, "experience": float(experience)}
    return {"supplier": Path(filename).stem, "submitted_on": dt.date.today(), "experience": 3.0}


def _pick_files():
    st.file_uploader("Supplier proposals (PDF)", type="pdf", accept_multiple_files=True, key=_uploader_key())
    with st.container(horizontal=True):
        st.button("Load sample proposals", on_click=_add_folder, args=(SAMPLE_DIR,))
        st.button("Add broken files", on_click=_add_folder, args=(BROKEN_DIR,))
        st.button("Clear", on_click=_clear)
    held = dict(_files())
    for upload in st.session_state.get(_uploader_key()) or []:
        held[upload.name] = upload.getvalue()
    return held


def _details(names):
    saved = st.session_state.setdefault("details", {})
    rows = [{"filename": name, **saved.get(name, _defaults(name))} for name in names]
    frame = pd.DataFrame(rows, columns=list(DETAIL_CONFIG))
    edited = st.data_editor(
        frame,
        key=f"details_{hash(tuple(names))}",
        hide_index=True,
        column_config=DETAIL_CONFIG,
        width="stretch",
    )
    for record in edited.to_dict("records"):
        saved[record["filename"]] = {
            "supplier": record["supplier"],
            "submitted_on": _day(record["submitted_on"]),
            "experience": record["experience"],
        }
    return [saved[name] | {"filename": name} for name in names]


def _day(value):
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _as_text(value):
    if isinstance(value, (dt.date, dt.datetime)):
        return value.strftime("%Y-%m-%d")
    if value is None or pd.isna(value):
        return ""
    return str(value)


def _submission(row, content):
    experience = row["experience"]
    experience = None if experience is None or pd.isna(experience) else float(experience)
    return Submission(
        supplier=str(row["supplier"] or "").strip(),
        submitted_on=_as_text(row["submitted_on"]),
        experience=experience,
        filename=row["filename"],
        content=content,
    )


def _evaluate(submissions, name, settings):
    failure = None
    with st.status("Evaluating proposals", expanded=True) as box:
        try:
            run = evaluate_batch(submissions, name, settings, on_step=box.write)
        except (RunFailed, ValueError) as exc:
            failure = str(exc)
            box.update(label="Run failed", state="error")
        else:
            box.update(label="Run complete", state="complete", expanded=False)
    if failure:
        st.error(failure)
        return
    st.session_state["last_run"] = run["run_id"]
    st.session_state["run_id"] = run["run_id"]


def _result():
    run_id = st.session_state.get("last_run")
    run = load_run(run_id) if run_id else None
    if not run or not run.get("suppliers"):
        return
    winner_card(ranked(run["suppliers"])[0])
    notes(run)
    ranking_table(run["suppliers"], with_note=False)


def render(settings):
    left, right = st.columns([5, 11], gap="medium")
    with left:
        files = _pick_files()
    names = sorted(files)
    with right:
        if not names:
            st.info("Upload proposals or load the samples to start.")
            return
        rows = _details(names)
        name = st.text_input("Run name", value=f"Evaluation {dt.date.today():%Y-%m-%d}")
    submissions = [_submission(row, files[row["filename"]]) for row in rows]
    problems = submission_errors(submissions) + criteria_errors(list_criteria())
    if not name.strip():
        problems.append("Give the run a name.")
    for problem in problems:
        st.warning(problem)
    if not settings.live:
        st.caption("Runs are scored offline by keyword matching.")
    if st.button("Run evaluation", type="primary", disabled=bool(problems)):
        _evaluate(submissions, name.strip(), settings)
    _result()
