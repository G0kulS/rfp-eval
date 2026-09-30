import json

import pytest
from pydantic import ValidationError

from core.agent import Submission
from core.reply import CriterionScore, criteria_errors, read_reply, submission_errors

CRITERIA = [
    {"id": 1, "title": "Technical", "guidance": "Scale", "weight": 60, "max_points": 10, "active": True},
    {"id": 2, "title": "Price", "guidance": "Total cost", "weight": 40, "max_points": 10, "active": True},
]


def entry(criterion_id, score, **extra):
    data = {"criterion_id": criterion_id, "score": score, "max_score": 10, "confidence": 0.7,
            "justification": "Clear.", "evidence": "Some text.", "evidence_page": 1}
    data.update(extra)
    return data


def reply_text(entries):
    return json.dumps({"supplier_name": "Acme", "criteria": entries, "risks": [], "overall_summary": "Fine."})


def test_json_inside_code_fence_is_read():
    raw = "Here you go:\n```json\n" + reply_text([entry(1, 7), entry(2, 6)]) + "\n```"
    card = read_reply(raw, CRITERIA, "Acme")
    assert [item.points for item in card.items] == [7.0, 6.0]
    assert [item.status for item in card.items] == ["OK", "OK"]
    assert card.problems == []


def test_reply_that_is_not_json_scores_zero():
    card = read_reply("I think they are great, 9 out of 10.", CRITERIA, "Acme")
    assert [item.points for item in card.items] == [0.0, 0.0]
    assert {item.status for item in card.items} == {"INVALID"}
    assert card.problems == ["The reply was not valid JSON."]
    assert "not valid JSON" in card.warnings[0]


def test_missing_and_unknown_criteria():
    card = read_reply(reply_text([entry(1, 7), entry(9, 5)]), CRITERIA, "Acme")
    assert card.items[1].status == "MISSING"
    assert card.items[1].points == 0.0
    assert any("unknown criterion 9" in warning for warning in card.warnings)
    assert card.problems == ["Criterion 2 (Price) was missing."]
    assert len(card.items) == 2


def test_score_repairs_and_list_trimming():
    long_list = [f"point {number}" for number in range(9)]
    entries = [entry(1, "8/10", confidence=85, strengths=long_list), entry(2, 14, confidence="40%")]
    card = read_reply(reply_text(entries), CRITERIA, "Acme")
    first, second = card.items
    assert (first.points, first.status, first.confidence) == (8.0, "COERCED", 0.85)
    assert (second.points, second.status, second.confidence) == (10.0, "CLIPPED", 0.4)
    assert len(first.strengths) == 5
    assert any("clipped" in warning or "set to 10" in warning for warning in card.warnings)


def submission(name, content=b"%PDF-1.4 one", day="2026-09-10", experience=3, filename="a.pdf"):
    return Submission(name, day, experience, filename, content)


def test_submission_errors():
    assert submission_errors([submission("Acme"), submission("Beta", b"%PDF-1.4 two")]) == []
    assert "at least two" in submission_errors([submission("Acme")])[0]
    errors = submission_errors([
        submission("Acme"),
        submission("acme ", b"%PDF-1.4 two"),
        submission("Gamma", b"%PDF-1.4 one", day="2999-01-01", experience=7),
        submission("Delta", b"hello", filename="notes.docx"),
        submission("Echo", b"", day="31/12/2026"),
    ])
    text = "\n".join(errors)
    assert "used more than once" in text
    assert "in the future" in text
    assert "between 1 and 5" in text
    assert "same as the one uploaded for Acme" in text
    assert "not a PDF file" in text
    assert "is empty" in text
    assert "valid date" in text


def test_criteria_errors():
    assert criteria_errors(CRITERIA) == []
    rows = [dict(row) for row in CRITERIA] + [
        {"id": 3, "title": "technical", "guidance": "", "weight": 120, "max_points": 0, "active": True},
    ]
    text = "\n".join(criteria_errors(rows))
    assert "used more than once" in text
    assert "greater than 0" in text
    assert "between 0 and 100" in text
    assert "add up to 100" in text
    inactive = [dict(row, active=False) for row in CRITERIA]
    assert criteria_errors(inactive) == ["At least one criterion must be active."]


def test_criterion_score_rejects_invalid_values():
    base = {"id": 1, "title": "Technical", "weight": 60, "max_points": 10}
    assert CriterionScore(**base, points=7, confidence=0.5).points == 7
    with pytest.raises(ValidationError):
        CriterionScore(**base, confidence=1.5)
    with pytest.raises(ValidationError):
        CriterionScore(**base, points=-1)
    with pytest.raises(ValidationError):
        CriterionScore(**base, status="GUESSED")
