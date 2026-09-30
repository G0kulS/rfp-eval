import json

import pytest

from core import agent, groq_client, reports, storage
from core.agent import RunFailed, Submission, adjust_score, evaluate_batch
from core.config import BROKEN_DIR, SAMPLE_DETAILS, SAMPLE_DIR


def sample_submissions():
    submissions = []
    for filename, (supplier, day, experience) in SAMPLE_DETAILS.items():
        content = (SAMPLE_DIR / filename).read_bytes()
        submissions.append(Submission(supplier, day, experience, filename, content))
    return submissions


def good_reply(messages, score=7):
    criteria = [{"criterion_id": number, "score": score, "max_score": 10, "confidence": 0.8,
                 "justification": "Stated in the proposal.", "evidence": "", "evidence_page": 1}
                for number in range(1, 6)]
    return json.dumps({"supplier_name": "x", "criteria": criteria, "risks": [], "overall_summary": "ok"})


def test_offline_run_of_the_four_samples(offline):
    steps = []
    run = evaluate_batch(sample_submissions(), "Sample batch", offline, on_step=steps.append)
    names = [entry["supplier"] for entry in run["suppliers"]]
    assert len(names) == 4
    assert names[0] == "Meridian Softworks"
    assert names[-1] == "QuickDesk Solutions"
    assert [entry["rank"] for entry in run["suppliers"]] == [1, 2, 3, 4]
    assert run["state"] == "COMPLETED"
    assert run["run_id"].startswith("EV-")
    assert any("quotes found" in step for step in steps)
    top = run["suppliers"][0]
    assert all(item["quote_ok"] for item in top["items"])
    overview = storage.runs_overview()
    assert overview[0]["top_supplier"] == "Meridian Softworks"
    assert overview[0]["supplier_count"] == 4


def test_broken_pdfs_score_zero_with_warnings(offline):
    submissions = [sample_submissions()[0]]
    for number, path in enumerate(sorted(BROKEN_DIR.glob("*.pdf")), start=1):
        submissions.append(Submission(f"Broken {number}", "2026-09-10", 3, path.name, path.read_bytes()))
    run = evaluate_batch(submissions, "Broken files", offline)
    broken = [entry for entry in run["suppliers"] if entry["supplier"].startswith("Broken")]
    assert len(broken) == 2
    for entry in broken:
        assert entry["absolute"] == 0.0
        assert {item["status"] for item in entry["items"]} == {"NO_TEXT"}
    notes = [note for note in run["notes"] if "no readable text" in note]
    assert len(notes) == 2


def test_retry_when_reply_is_not_json(monkeypatch, fake_live):
    calls = []

    def fake_ask(messages, settings):
        calls.append(messages)
        if len(calls) % 2 == 1:
            return "Sorry, here is my view in words."
        return good_reply(messages)

    monkeypatch.setattr(agent, "MAX_WORKERS", 1)
    monkeypatch.setattr(groq_client, "ask", fake_ask)
    run = evaluate_batch(sample_submissions()[:2], "Retry", fake_live)
    assert len(calls) == 4
    assert "not valid JSON" in calls[1][-1]["content"]
    assert all(item["points"] == 7.0 for entry in run["suppliers"] for item in entry["items"])
    assert any("asked again" in note for note in run["notes"])


def test_retry_when_a_criterion_is_missing(monkeypatch, fake_live):
    calls = []

    def fake_ask(messages, settings):
        calls.append(messages)
        data = json.loads(good_reply(messages, score=6))
        if len(calls) % 2 == 1:
            data["criteria"] = data["criteria"][:4]
        return json.dumps(data)

    monkeypatch.setattr(agent, "MAX_WORKERS", 1)
    monkeypatch.setattr(groq_client, "ask", fake_ask)
    run = evaluate_batch(sample_submissions()[:2], "Missing", fake_live)
    assert len(calls) == 4
    assert "Criterion 5" in calls[1][-1]["content"]
    for entry in run["suppliers"]:
        assert [item["status"] for item in entry["items"]] == ["OK"] * 5


def test_rate_limit_gives_short_message(monkeypatch, fake_live):
    class RateLimitError(Exception):
        pass

    def fake_ask(messages, settings):
        raise RateLimitError("<html>429 Too Many Requests for gsk_test_secret_value</html>")

    monkeypatch.setattr(groq_client, "ask", fake_ask)
    with pytest.raises(RunFailed) as caught:
        evaluate_batch(sample_submissions(), "Limited", fake_live)
    assert str(caught.value) == "The model's free rate limit was reached. Wait a minute and run again."
    assert storage.runs_overview()[0]["state"] == "FAILED"


def test_other_model_error_hides_key_and_tags(monkeypatch, fake_live):
    def fake_ask(messages, settings):
        raise ConnectionError("<b>bad key gsk_test_secret_value</b> " + "x" * 500)

    monkeypatch.setattr(groq_client, "ask", fake_ask)
    with pytest.raises(RunFailed) as caught:
        evaluate_batch(sample_submissions(), "Broken link", fake_live)
    message = str(caught.value)
    assert message.startswith("ConnectionError: bad key ***")
    assert "gsk_test" not in message and "<b>" not in message
    assert len(message) <= 300


def test_bad_inputs_raise_value_error(offline):
    submissions = sample_submissions()
    submissions[1].supplier = submissions[0].supplier.upper()
    with pytest.raises(ValueError) as caught:
        evaluate_batch(submissions, "Bad", offline)
    assert "used more than once" in str(caught.value)
    assert storage.runs_overview() == []


def test_adjust_score_then_lock(offline):
    run = evaluate_batch(sample_submissions(), "Adjust", offline)
    last = run["suppliers"][-1]["supplier"]
    with pytest.raises(ValueError):
        adjust_score(run["run_id"], last, 1, 10, "  ")
    changed = adjust_score(run["run_id"], last, 1, 25, "Reference call confirmed the SAP work")
    entry = next(row for row in changed["suppliers"] if row["supplier"] == last)
    first = entry["items"][0]
    assert (first["points"], first["status"]) == (10.0, "OVERRIDDEN")
    assert changed["audit"][-1]["old_value"] != changed["audit"][-1]["new_value"]
    assert changed["audit"][-1]["action"] == "ADJUST_SCORE"
    locked = storage.lock_decision(run["run_id"], "Approved by the panel")
    assert locked["locked"] is True
    assert locked["audit"][-1]["action"] == "LOCK_DECISION"
    with pytest.raises(ValueError):
        adjust_score(run["run_id"], last, 1, 5, "Too late")
    storage.remove_run(run["run_id"])
    assert storage.load_run(run["run_id"]) is None


def test_exports_are_not_empty(offline):
    run = evaluate_batch(sample_submissions(), "Exports", offline)
    assert json.loads(reports.run_json(run))["run_id"] == run["run_id"]
    assert reports.run_pdf(run).startswith(b"%PDF")
    assert reports.run_workbook(run)[:2] == b"PK"
    csv_text = reports.scores_csv(run)
    assert csv_text.count("\n") == 21


def test_graph_retries_only_once_on_a_missing_criterion(monkeypatch, fake_live):
    calls = []

    def fake_ask(messages, settings):
        calls.append(messages)
        data = json.loads(good_reply(messages, score=5))
        data["criteria"] = data["criteria"][:4]
        return json.dumps(data)

    monkeypatch.setattr(groq_client, "ask", fake_ask)
    criteria = storage.list_criteria(active_only=True)
    entry, steps = agent.evaluate_one(sample_submissions()[0], criteria, fake_live)
    assert len(calls) == 2
    assert calls[1][-1]["role"] == "user" and "Criterion 5" in calls[1][-1]["content"]
    assert [item["status"] for item in entry["items"]][-1] == "MISSING"
    assert sum(1 for step in steps if "asking once more" in step) == 1
    assert any("asked again" in warning for warning in entry["warnings"])
    assert set(agent.supplier_graph().get_graph().nodes) >= {"read", "blank", "ask", "check", "evidence"}
