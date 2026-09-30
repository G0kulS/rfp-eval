import re
import secrets
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from core import evidence, groq_client, math_rules, pdf_text, prompt, reply, storage
from core.config import Settings

MAX_WORKERS = 4
MAX_TRIES = 2
MAX_ERROR_CHARS = 300
RATE_LIMIT_MESSAGE = "The model's free rate limit was reached. Wait a minute and run again."


@dataclass
class Submission:
    supplier: str
    submitted_on: str
    experience: float
    filename: str
    content: bytes = field(repr=False)


class RunFailed(Exception):
    pass


def new_run_id():
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"EV-{stamp}-{secrets.token_hex(2).upper()}"


def day_text(value):
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def short_error(error, settings):
    if type(error).__name__ == "RateLimitError":
        return RATE_LIMIT_MESSAGE
    text = f"{type(error).__name__}: {error}"
    text = re.sub(r"<[^>]+>", " ", text)
    if settings.api_key:
        text = text.replace(settings.api_key, "***")
    text = " ".join(text.split())
    if len(text) > MAX_ERROR_CHARS:
        text = text[: MAX_ERROR_CHARS - 3] + "..."
    return text


class SupplierState(TypedDict, total=False):
    submission: Submission
    criteria: list
    settings: Settings
    pages: list
    problem: str | None
    messages: list
    raw: str
    card: reply.SupplierCard
    tries: int
    rejected: list
    steps: list


def supplier_name(state):
    return state["submission"].supplier


def read_node(state):
    submission = state["submission"]
    pages, problem = pdf_text.page_texts(submission.content)
    step = f"{submission.supplier}: read {len(pages)} page(s) from {submission.filename}"
    messages = []
    if not problem:
        messages = prompt.build_messages(submission.supplier, state["criteria"], pages)
    return {"pages": pages, "problem": problem, "messages": messages, "steps": [step]}


def after_read(state):
    if state["problem"]:
        return "blank"
    return "ask"


def blank_node(state):
    name = supplier_name(state)
    problem = state["problem"]
    card = reply.blank_card(
        name,
        state["criteria"],
        "NO_TEXT",
        f"The file has {problem}.",
        f"{name}: {problem}; every criterion was set to 0.",
    )
    step = f"{name}: skipped the model because the file has {problem}"
    return {"card": card, "steps": state["steps"] + [step]}


def ask_node(state):
    settings = state["settings"]
    criteria = state["criteria"]
    if settings.live:
        raw = groq_client.ask(state["messages"], settings)
    else:
        raw = groq_client.offline_reply(supplier_name(state), state["pages"], criteria)
    tries = state.get("tries", 0) + 1
    step = f"{supplier_name(state)}: asking the model to score {len(criteria)} criteria (try {tries})"
    return {"raw": raw or "", "tries": tries, "steps": state["steps"] + [step]}


def check_node(state):
    name = supplier_name(state)
    card = reply.read_reply(state["raw"], state["criteria"], name)
    steps = state["steps"] + [f"{name}: checking the reply"]
    rejected = list(state.get("rejected", []))
    if rejected:
        note = " ".join(rejected)
        card.warnings.insert(0, f"{name}: the model was asked again because of the first reply. {note}")
    update = {"card": card, "steps": steps}
    if card.problems and state["tries"] < MAX_TRIES:
        update["rejected"] = list(card.problems)
        update["messages"] = state["messages"] + [
            {"role": "assistant", "content": state["raw"]},
            prompt.correction_message(card.problems),
        ]
        update["steps"] = steps + [f"{name}: reply had problems, asking once more"]
    return update


def after_check(state):
    if state["card"].problems and state["tries"] < MAX_TRIES:
        return "ask"
    return "evidence"


def evidence_node(state):
    card = state["card"]
    for item in card.items:
        item.quote_ok = False
        if not item.quote:
            continue
        found, page = evidence.quote_found(state["pages"], item.quote)
        item.quote_ok = found
        if found and page is not None:
            item.quote_page = page
    matched = sum(1 for item in card.items if item.quote_ok)
    step = f"{card.supplier}: {matched} of {len(card.items)} quotes found in the document"
    return {"card": card, "steps": state["steps"] + [step]}


@lru_cache(maxsize=1)
def supplier_graph():
    graph = StateGraph(SupplierState)
    graph.add_node("read", read_node)
    graph.add_node("blank", blank_node)
    graph.add_node("ask", ask_node)
    graph.add_node("check", check_node)
    graph.add_node("evidence", evidence_node)
    graph.add_edge(START, "read")
    graph.add_conditional_edges("read", after_read, {"blank": "blank", "ask": "ask"})
    graph.add_edge("blank", END)
    graph.add_edge("ask", "check")
    graph.add_conditional_edges("check", after_check, {"ask": "ask", "evidence": "evidence"})
    graph.add_edge("evidence", END)
    return graph.compile()


def evaluate_one(submission, criteria, settings):
    start = {"submission": submission, "criteria": criteria, "settings": settings, "tries": 0, "steps": []}
    final = supplier_graph().invoke(start)
    return supplier_entry(submission, final["card"]), final["steps"]


def supplier_entry(submission, card):
    return {
        "supplier": card.supplier,
        "submitted_on": day_text(submission.submitted_on),
        "experience": float(submission.experience),
        "filename": submission.filename,
        "summary": card.summary,
        "risks": list(card.risks),
        "warnings": list(card.warnings),
        "items": [item.model_dump() for item in card.items],
    }


def evaluate_all(submissions, criteria, settings, report):
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = [pool.submit(evaluate_one, item, criteria, settings) for item in submissions]
        try:
            for future in as_completed(futures):
                entry, steps = future.result()
                for step in steps:
                    report(step)
                results.append(entry)
        except Exception:
            for future in futures:
                future.cancel()
            raise
    return results


def clean_submissions(submissions):
    cleaned = []
    for item in submissions:
        name = " ".join(str(item.supplier or "").split())
        cleaned.append(
            Submission(
                supplier=name,
                submitted_on=day_text(item.submitted_on),
                experience=item.experience,
                filename=item.filename,
                content=item.content,
            )
        )
    return cleaned


def check_inputs(submissions):
    errors = reply.submission_errors(submissions)
    errors.extend(reply.criteria_errors(storage.list_criteria()))
    if errors:
        raise ValueError("\n".join(errors))


def evaluate_batch(submissions, name, settings, on_step=None):
    report = on_step or (lambda text: None)
    submissions = clean_submissions(submissions)
    check_inputs(submissions)
    criteria = storage.list_criteria(active_only=True)
    run_id = new_run_id()
    run_name = " ".join(str(name or "").split()) or run_id
    storage.create_run(run_id, run_name, settings.label, criteria)
    report(f"Run {run_id} started with {len(submissions)} suppliers and {len(criteria)} criteria")
    try:
        entries = evaluate_all(submissions, criteria, settings, report)
    except Exception as error:
        message = short_error(error, settings)
        storage.finish_run(run_id, "FAILED", [message])
        report(f"Run {run_id} failed: {message}")
        raise RunFailed(message) from error
    report("Calculating scores, benchmarks, PPI and ranks")
    ranked = math_rules.score_batch(entries)
    notes = [warning for entry in ranked for warning in entry["warnings"]]
    storage.save_scores(run_id, ranked)
    storage.finish_run(run_id, "COMPLETED", notes)
    report(f"Run {run_id} saved")
    return storage.load_run(run_id)


def find_item(run, supplier, criterion_id):
    for entry in run["suppliers"]:
        if entry["supplier"] != supplier:
            continue
        for item in entry["items"]:
            if int(item["id"]) == int(criterion_id):
                return item
    return None


def adjust_score(run_id, supplier, criterion_id, points, reason):
    reason = " ".join(str(reason or "").split())
    if not reason:
        raise ValueError("A reason is required to change a score.")
    run = storage.load_run(run_id)
    if run is None:
        raise ValueError(f"Run {run_id} was not found.")
    if run["locked"]:
        raise ValueError(f"Run {run_id} is locked, so scores cannot be changed.")
    if run["state"] != "COMPLETED":
        raise ValueError("Only a completed run can be adjusted.")
    item = find_item(run, supplier, criterion_id)
    if item is None:
        raise ValueError(f"No score was found for {supplier}, criterion {criterion_id}.")
    old_points = float(item["points"])
    new_points = round(max(0.0, min(float(item["max_points"]), float(points))), 4)
    item["points"] = new_points
    item["status"] = "OVERRIDDEN"
    item["override_reason"] = reason
    ranked = math_rules.score_batch(run["suppliers"])
    storage.save_scores(run_id, ranked)
    storage.add_audit(run_id, "ADJUST_SCORE", supplier, int(criterion_id), old_points, new_points, reason)
    return storage.load_run(run_id)
