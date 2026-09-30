import altair as alt
import pandas as pd
import streamlit as st

from core.math_rules import reweight
from core.reports import run_json, run_pdf, run_workbook, scores_csv
from core.storage import load_run
from ui.widgets import bullets, completed_runs, notes, ranked, ranking_table, run_label, short_time

ITEM_CONFIG = {
    "Criterion": st.column_config.TextColumn(width=200),
    "Weight %": st.column_config.NumberColumn(format="%.0f", width=80),
    "Points": st.column_config.TextColumn(width=80),
    "Benchmark": st.column_config.NumberColumn(format="%.2f", width=95),
    "Gap": st.column_config.NumberColumn(format="%.2f", width=70),
    "Relative %": st.column_config.NumberColumn(format="%.1f", width=90),
    "Confidence": st.column_config.TextColumn(width=95),
    "Status": st.column_config.TextColumn(width=110),
}


def _choose_run():
    runs = completed_runs()
    if not runs:
        return None
    ids = [row["run_id"] for row in runs]
    labels = {row["run_id"]: run_label(row) for row in runs}
    current = st.session_state.get("run_id")
    if st.session_state.get("dashboard_run") not in ids:
        st.session_state.pop("dashboard_run", None)
    if current in ids and current != st.session_state.get("dashboard_shown"):
        st.session_state["dashboard_run"] = current
    picked = st.selectbox("Run", ids, format_func=labels.get, key="dashboard_run")
    st.session_state["run_id"] = picked
    st.session_state["dashboard_shown"] = picked
    return load_run(picked)


def _facts(run):
    locked = f"locked {short_time(run.get('locked_at'))}" if run.get("locked") else "not locked"
    parts = [
        f"Run id `{run['run_id']}`",
        run["state"].lower(),
        f"{short_time(run.get('started_at'))} to {short_time(run.get('finished_at'))}",
        locked,
    ]
    st.caption(", ".join(parts))


def _cards(suppliers):
    columns = st.columns(len(suppliers))
    for column, supplier in zip(columns, suppliers, strict=True):
        with column.container(border=True):
            rank = supplier["rank"]
            badge = ":green-badge[Winner]" if rank == 1 else f":gray-badge[Rank {rank}]"
            st.markdown(f"{badge}  \n**{supplier['supplier']}**")
            st.markdown(f"PPI **{supplier['ppi']:.2f}**, absolute **{supplier['absolute']:.2f}**")


def _chart(suppliers):
    rows = [
        {"Criterion": item["title"], "Supplier": s["supplier"], "Points": item["points"]}
        for s in suppliers
        for item in s["items"]
    ]
    if not rows:
        return
    criteria = [item["title"] for item in suppliers[0]["items"]]
    names = [s["supplier"] for s in suppliers]
    chart = (
        alt.Chart(pd.DataFrame(rows))
        .mark_bar()
        .encode(
            x=alt.X("Criterion:N", sort=criteria, title=None, axis=alt.Axis(labelAngle=0, labelLimit=200)),
            xOffset=alt.XOffset("Supplier:N", sort=names),
            y=alt.Y("Points:Q"),
            color=alt.Color("Supplier:N", sort=names, legend=alt.Legend(orient="bottom", title=None)),
            tooltip=["Supplier", "Criterion", "Points"],
        )
        .properties(height=320)
    )
    st.altair_chart(chart, width="stretch")


def _confidence(value):
    if value is None:
        return "-"
    if isinstance(value, (int, float)):
        return f"{value:.0%}" if value <= 1 else f"{value:g}"
    return str(value)


def _item_frame(items):
    rows = [
        {
            "Criterion": item["title"],
            "Weight %": item["weight"],
            "Points": f"{item['points']:g} / {item['max_points']:g}",
            "Benchmark": item["benchmark"],
            "Gap": item["gap"],
            "Relative %": item["relative"],
            "Confidence": _confidence(item.get("confidence")),
            "Status": item.get("status") or "",
        }
        for item in items
    ]
    return pd.DataFrame(rows)


def _quote(item):
    quote = (item.get("quote") or "").strip()
    if not quote:
        st.caption("No quote given.")
        return
    st.markdown("\n".join(f"> {line}" for line in quote.splitlines()))
    if item.get("quote_ok"):
        page = item.get("quote_page")
        st.caption(f"Page {page}, found in the PDF" if page else "Found in the PDF")
    else:
        st.caption("Not found in the PDF")


def _item_detail(item):
    label = f"{item['title']}: {item['points']:g} / {item['max_points']:g}"
    with st.expander(label):
        st.markdown(item.get("reason") or "No reason given.")
        _quote(item)
        strengths, gaps, questions = st.columns(3)
        with strengths:
            st.markdown("**Strengths**")
            bullets(item.get("strengths"))
        with gaps:
            st.markdown("**Gaps**")
            bullets(item.get("gaps"))
        with questions:
            st.markdown("**Questions**")
            bullets(item.get("questions"))


def _drill_down(suppliers):
    st.subheader("Supplier detail")
    names = [s["supplier"] for s in suppliers]
    name = st.selectbox("Supplier", names, key="dashboard_supplier")
    supplier = next(s for s in suppliers if s["supplier"] == name)
    left, right = st.columns([3, 1], gap="large")
    with left:
        frame = _item_frame(supplier["items"])
        st.dataframe(frame, hide_index=True, column_config=ITEM_CONFIG, width="stretch")
        for item in supplier["items"]:
            _item_detail(item)
    with right:
        st.markdown("**Summary**")
        st.markdown(supplier.get("summary") or "No summary.")
        st.markdown("**Risks**")
        bullets(supplier.get("risks"))


def _what_if(run):
    suppliers = run["suppliers"]
    with st.expander("What if the weights were different?"):
        items = suppliers[0]["items"]
        columns = st.columns(min(len(items), 3))
        weights = {}
        for index, item in enumerate(items):
            key = f"what_if_{run['run_id']}_{item['id']}"
            weights[item["id"]] = columns[index % len(columns)].slider(
                item["title"], 0, 100, int(round(item["weight"])), step=5, key=key
            )
        _what_if_result(suppliers, weights)


def _what_if_result(suppliers, weights):
    total = sum(weights.values())
    if total == 0:
        st.warning("Give at least one criterion some weight.")
        return
    if total != 100:
        st.caption(f"Weights add up to {total}%.")
    before = {s["supplier"]: s["rank"] for s in suppliers}
    after = ranked(reweight(suppliers, weights))
    rows = [
        {
            "New rank": s["rank"],
            "Supplier": s["supplier"],
            "PPI": s["ppi"],
            "Absolute": s["absolute"],
            "Change": _change(before[s["supplier"]] - s["rank"]),
        }
        for s in after
    ]
    config = {
        "PPI": st.column_config.NumberColumn(format="%.2f"),
        "Absolute": st.column_config.NumberColumn(format="%.2f"),
    }
    st.dataframe(pd.DataFrame(rows), hide_index=True, column_config=config, width="stretch")
    winner = ranked(suppliers)[0]["supplier"]
    if after[0]["supplier"] != winner:
        st.info(f"With these weights {after[0]['supplier']} would win instead of {winner}.")


def _change(delta):
    if delta > 0:
        return f"up {delta}"
    if delta < 0:
        return f"down {-delta}"
    return "same"


@st.cache_data(max_entries=16, show_spinner=False)
def _exports(run_id, stamp):
    run = load_run(run_id)
    return run_pdf(run), run_workbook(run), scores_csv(run)


def _downloads(run):
    text = run_json(run)
    pdf, workbook, csv = _exports(run["run_id"], text)
    base = f"rfp_run_{run['run_id']}"
    one, two, three, four, _ = st.columns([1, 1, 1, 1, 2])
    one.download_button("JSON", text, f"{base}.json", "application/json", width="stretch")
    two.download_button("PDF report", pdf, f"{base}.pdf", "application/pdf", width="stretch")
    xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    three.download_button("Excel", workbook, f"{base}.xlsx", xlsx, width="stretch")
    four.download_button("Scores CSV", csv, f"{base}_scores.csv", "text/csv", width="stretch")


def render():
    run = _choose_run()
    if run is None:
        st.info("No completed runs yet. Start one in the Run tab.")
        return
    _facts(run)
    suppliers = ranked(run["suppliers"])
    notes(run)
    _cards(suppliers)
    st.subheader("Ranking")
    ranking_table(suppliers)
    st.subheader("Points by criterion")
    _chart(suppliers)
    _drill_down(suppliers)
    _what_if(run)
    st.subheader("Downloads")
    _downloads(run)
