import io
import logging

import pdfplumber
from pypdf import PdfReader

NO_TEXT = "no readable text (scanned, empty or damaged file)"
MIN_CHARS = 150
ROW_TOLERANCE = 3
EDGE = 4
TABLE_GAP = 15
MIN_COLUMN_WORDS = 3

logging.getLogger("pypdf").setLevel(logging.ERROR)
logging.getLogger("pdfminer").setLevel(logging.ERROR)


def page_texts(content):
    pages = plumber_pages(content)
    if char_count(pages) < MIN_CHARS:
        backup = pypdf_pages(content)
        if char_count(backup) > char_count(pages):
            pages = backup
    if char_count(pages) < MIN_CHARS:
        return pages, NO_TEXT
    return pages, None


def char_count(pages):
    return sum(len(text.strip()) for text in pages)


def plumber_pages(content):
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            return [read_page(page) for page in pdf.pages]
    except Exception:
        return []


def pypdf_pages(content):
    try:
        reader = PdfReader(io.BytesIO(content))
        return [(page.extract_text() or "").strip() for page in reader.pages]
    except Exception:
        return []


def read_page(page):
    words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
    if not words:
        return ""
    rows = group_rows(words)
    split = column_split(rows, page.width)
    if split is None:
        return "\n".join(row_text(row) for row in rows)
    return "\n".join(two_column_lines(rows, split))


def group_rows(words):
    rows = []
    for word in sorted(words, key=lambda item: (item["top"], item["x0"])):
        if rows and abs(rows[-1][0]["top"] - word["top"]) <= ROW_TOLERANCE:
            rows[-1].append(word)
        else:
            rows.append([word])
    return [sorted(row, key=lambda item: item["x0"]) for row in rows]


def row_text(row):
    return " ".join(word["text"] for word in row).strip()


def crosses(row, x):
    return any(word["x0"] - EDGE < x < word["x1"] + EDGE for word in row)


def column_block(flags):
    best = (0, 0)
    start = None
    for index, flag in enumerate(flags + [True]):
        if not flag and start is None:
            start = index
        if flag and start is not None:
            if index - start > best[1] - best[0]:
                best = (start, index)
            start = None
    return best


def looks_like_table(words):
    for before, after in zip(words, words[1:], strict=False):
        if after["x0"] - before["x1"] > TABLE_GAP:
            return True
    return False


def side_words(row, x):
    left = [word for word in row if word["x1"] <= x]
    right = [word for word in row if word["x0"] >= x]
    return left, right


def split_fits(rows, x):
    first, last = column_block([crosses(row, x) for row in rows])
    left_counts = []
    right_counts = []
    for row in rows[first:last]:
        left, right = side_words(row, x)
        if looks_like_table(left) or looks_like_table(right):
            return False
        if left:
            left_counts.append(len(left))
        if right:
            right_counts.append(len(right))
    if len(left_counts) < 2 or len(right_counts) < 2:
        return False
    left_average = sum(left_counts) / len(left_counts)
    right_average = sum(right_counts) / len(right_counts)
    return left_average >= MIN_COLUMN_WORDS and right_average >= MIN_COLUMN_WORDS


def column_split(rows, width):
    best = []
    run = []
    for x in range(int(width * 0.35), int(width * 0.65) + 1, 2):
        if split_fits(rows, x):
            run.append(x)
            continue
        if len(run) > len(best):
            best = run
        run = []
    if len(run) > len(best):
        best = run
    if not best:
        return None
    return best[len(best) // 2]


def two_column_lines(rows, split):
    first, last = column_block([crosses(row, split) for row in rows])
    left = []
    right = []
    for row in rows[first:last]:
        left_words, right_words = side_words(row, split)
        if left_words:
            left.append(row_text(left_words))
        if right_words:
            right.append(row_text(right_words))
    top = [row_text(row) for row in rows[:first]]
    bottom = [row_text(row) for row in rows[last:]]
    return top + left + right + bottom
