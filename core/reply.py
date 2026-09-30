import hashlib
import json
import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_LIST_ITEMS = 5
MAX_RISKS = 8
MAX_ITEM_CHARS = 300
MAX_TEXT_CHARS = 1500
MAX_FILE_BYTES = 20 * 1024 * 1024


Status = Literal["OK", "COERCED", "CLIPPED", "MISSING", "INVALID", "OVERRIDDEN", "NO_TEXT"]


class CriterionScore(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    id: int
    title: str
    weight: float = Field(ge=0, le=100)
    max_points: float = Field(gt=0)
    points: float = Field(default=0.0, ge=0)
    status: Status = "OK"
    confidence: float | None = Field(default=0.0, ge=0, le=1)
    reason: str = ""
    quote: str = ""
    quote_page: int | None = Field(default=None, ge=1)
    quote_ok: bool = False
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)


class SupplierCard(BaseModel):
    supplier: str
    items: list[CriterionScore] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)


def blank_item(criterion, status, reason):
    return CriterionScore(
        id=int(criterion["id"]),
        title=criterion["title"],
        weight=float(criterion["weight"]),
        max_points=float(criterion["max_points"]),
        status=status,
        reason=reason,
    )


def blank_card(supplier, criteria, status, reason, warning):
    items = [blank_item(criterion, status, reason) for criterion in criteria]
    return SupplierCard(supplier=supplier, items=items, warnings=[warning])


def find_json(raw):
    text = (raw or "").strip()
    candidates = [text]
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        candidates.append(fence.group(1).strip())
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict):
            return data
    return None


def to_number(value):
    if isinstance(value, bool):
        return None, False
    if isinstance(value, (int, float)):
        return float(value), False
    if not isinstance(value, str):
        return None, False
    text = value.strip().replace(",", ".")
    fraction = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*(?:/|out of)\s*(\d+(?:\.\d+)?)", text)
    if fraction:
        return float(fraction.group(1)), True
    plain = re.search(r"-?\d+(?:\.\d+)?", text)
    if plain:
        return float(plain.group(0)), True
    return None, False


def fraction_scale(value, max_points):
    if not isinstance(value, str):
        return None
    fraction = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*(?:/|out of)\s*(\d+(?:\.\d+)?)\s*", value)
    if not fraction:
        return None
    top = float(fraction.group(1))
    bottom = float(fraction.group(2))
    if bottom <= 0 or bottom == max_points:
        return None
    return top / bottom * max_points


def read_confidence(value):
    number, _ = to_number(value)
    if number is None:
        return 0.0
    if isinstance(value, str) and "%" in value:
        number = number / 100
    elif number > 1:
        number = number / 100
    return round(max(0.0, min(1.0, number)), 4)


def text_list(value, limit=MAX_LIST_ITEMS):
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    items = []
    for entry in value:
        text = " ".join(str(entry).split())
        if text:
            items.append(text[:MAX_ITEM_CHARS])
    return items[:limit]


def plain_text(value, limit=MAX_TEXT_CHARS):
    if value is None:
        return ""
    if isinstance(value, list):
        value = " ".join(str(entry) for entry in value)
    return " ".join(str(value).split())[:limit]


def read_page_number(value):
    number, _ = to_number(value)
    if number is None or number < 1:
        return None
    return int(number)


def read_id(value):
    number, _ = to_number(value)
    if number is None:
        return None
    return int(number)


def repaired_points(raw_score, max_points, label, warnings):
    number, coerced = to_number(raw_score)
    if number is None:
        return None, "INVALID"
    status = "OK"
    scaled = fraction_scale(raw_score, max_points)
    if scaled is not None:
        number = scaled
    if coerced:
        status = "COERCED"
        warnings.append(f"{label} score {raw_score!r} was read as {round(number, 4)}.")
    if number < 0 or number > max_points:
        clipped = max(0.0, min(max_points, number))
        status = "CLIPPED"
        limits = f"0 to {max_points:g}"
        warnings.append(f"{label} score {round(number, 4)} was outside {limits} and set to {clipped:g}.")
        number = clipped
    return round(number, 4), status


def score_item(criterion, entry, supplier, warnings):
    max_points = float(criterion["max_points"])
    label = f"{supplier}: criterion {int(criterion['id'])} ({criterion['title']})"
    points, status = repaired_points(entry.get("score"), max_points, label, warnings)
    if points is None:
        warnings.append(f"{label} had no usable score and was set to 0.")
        return blank_item(criterion, "INVALID", "The model gave no usable score.")
    return CriterionScore(
        id=int(criterion["id"]),
        title=criterion["title"],
        weight=float(criterion["weight"]),
        max_points=max_points,
        points=points,
        status=status,
        confidence=read_confidence(entry.get("confidence")),
        reason=plain_text(entry.get("justification")),
        quote=plain_text(entry.get("evidence"), 600),
        quote_page=read_page_number(entry.get("evidence_page")),
        strengths=text_list(entry.get("strengths")),
        gaps=text_list(entry.get("weaknesses")),
        questions=text_list(entry.get("missing_information")),
    )


def entries_by_id(entries, criteria, supplier, warnings):
    known = {int(criterion["id"]) for criterion in criteria}
    found = {}
    for entry in entries:
        if not isinstance(entry, dict):
            warnings.append(f"{supplier}: a criterion entry that was not an object was ignored.")
            continue
        criterion_id = read_id(entry.get("criterion_id"))
        if criterion_id not in known:
            warnings.append(f"{supplier}: unknown criterion {entry.get('criterion_id')!r} was dropped.")
            continue
        if criterion_id in found:
            warnings.append(f"{supplier}: criterion {criterion_id} appeared twice; the first one was kept.")
            continue
        found[criterion_id] = entry
    return found


def read_reply(raw, criteria, supplier):
    data = find_json(raw)
    if data is None:
        card = blank_card(
            supplier,
            criteria,
            "INVALID",
            "The model reply was not valid JSON.",
            f"{supplier}: the model reply was not valid JSON, so every criterion was set to 0.",
        )
        card.problems = ["The reply was not valid JSON."]
        return card
    card = SupplierCard(supplier=supplier)
    entries = data.get("criteria")
    if not isinstance(entries, list):
        entries = []
    found = entries_by_id(entries, criteria, supplier, card.warnings)
    for criterion in criteria:
        criterion_id = int(criterion["id"])
        if criterion_id in found:
            card.items.append(score_item(criterion, found[criterion_id], supplier, card.warnings))
            continue
        card.items.append(blank_item(criterion, "MISSING", "The model gave no result for this criterion."))
        label = f"criterion {criterion_id} ({criterion['title']})"
        card.warnings.append(f"{supplier}: {label} was missing; set to 0.")
        card.problems.append(f"Criterion {criterion_id} ({criterion['title']}) was missing.")
    card.risks = text_list(data.get("risks"), MAX_RISKS)
    card.summary = plain_text(data.get("overall_summary"))
    return card


def parse_day(value):
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        return None


def number_or_none(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def file_errors(label, submission):
    errors = []
    filename = str(submission.filename or "")
    content = submission.content or b""
    if not filename.lower().endswith(".pdf"):
        errors.append(f"{label}: '{filename}' is not a PDF file.")
    elif content and not content[:1024].lstrip().startswith(b"%PDF"):
        errors.append(f"{label}: '{filename}' does not look like a PDF file.")
    if not content:
        errors.append(f"{label}: '{filename}' is empty.")
    if len(content) > MAX_FILE_BYTES:
        errors.append(f"{label}: '{filename}' is larger than 20 MB.")
    return errors


def detail_errors(label, submission):
    errors = []
    day = parse_day(submission.submitted_on)
    if day is None:
        errors.append(f"{label}: submission date must be a valid date (YYYY-MM-DD).")
    elif day > date.today():
        errors.append(f"{label}: submission date {day.isoformat()} is in the future.")
    rating = number_or_none(submission.experience)
    if rating is None or rating < 1 or rating > 5:
        errors.append(f"{label}: experience rating must be between 1 and 5.")
    return errors


def submission_errors(submissions):
    errors = []
    if len(submissions) < 2:
        errors.append("Upload at least two supplier proposals to compare.")
    names = {}
    hashes = {}
    for number, submission in enumerate(submissions, start=1):
        name = " ".join(str(submission.supplier or "").split())
        label = name or f"Supplier {number}"
        if not name:
            errors.append(f"Supplier {number}: supplier name is required.")
        elif name.lower() in names:
            errors.append(f"Supplier name '{name}' is used more than once.")
        else:
            names[name.lower()] = number
        errors.extend(detail_errors(label, submission))
        errors.extend(file_errors(label, submission))
        content = submission.content or b""
        if content:
            digest = hashlib.sha256(content).hexdigest()
            if digest in hashes:
                errors.append(f"{label}: the file is the same as the one uploaded for {hashes[digest]}.")
            else:
                hashes[digest] = label
    return errors


def criterion_row_errors(number, row):
    errors = []
    title = str(row.get("title") or "").strip()
    label = title or f"Criterion row {number}"
    if not title:
        errors.append(f"Criterion row {number}: name is required.")
    max_points = number_or_none(row.get("max_points"))
    if max_points is None or max_points <= 0:
        errors.append(f"{label}: maximum score must be greater than 0.")
    weight = number_or_none(row.get("weight"))
    if weight is None or weight < 0 or weight > 100:
        errors.append(f"{label}: weight must be between 0 and 100.")
    return errors


def criteria_errors(rows):
    errors = []
    seen = set()
    active_weight = 0.0
    active_count = 0
    for number, row in enumerate(rows, start=1):
        errors.extend(criterion_row_errors(number, row))
        title = str(row.get("title") or "").strip().lower()
        if title and title in seen:
            errors.append(f"Criterion name '{row.get('title')}' is used more than once.")
        seen.add(title)
        if bool(row.get("active")):
            active_count += 1
            active_weight += number_or_none(row.get("weight")) or 0.0
    if active_count == 0:
        errors.append("At least one criterion must be active.")
    elif abs(active_weight - 100) > 0.01:
        total = f"{round(active_weight, 2):g}"
        errors.append(f"Active criterion weights must add up to 100 (they add up to {total}).")
    return errors
