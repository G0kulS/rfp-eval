import re
from collections import Counter

MIN_PART_WORDS = 4
MATCH_SHARE = 0.85


def tokens(text):
    lowered = (text or "").lower()
    cleaned = re.sub(r"[^a-z0-9%$]+", " ", lowered)
    return cleaned.split()


def quote_parts(quote):
    pieces = re.split(r"\.\.\.|…", quote or "")
    parts = []
    for piece in pieces:
        for sentence in re.split(r"(?<=[.!?;])\s+", piece):
            words = tokens(sentence)
            if len(words) >= MIN_PART_WORDS:
                parts.append(words)
    return parts


def window_match(page_words, part):
    size = len(part)
    if size == 0 or len(page_words) < size:
        return False
    wanted = Counter(part)
    needed = MATCH_SHARE * size
    window = Counter(page_words[:size])
    if overlap(window, wanted) >= needed:
        return True
    for start in range(1, len(page_words) - size + 1):
        window[page_words[start - 1]] -= 1
        window[page_words[start + size - 1]] += 1
        if overlap(window, wanted) >= needed:
            return True
    return False


def overlap(window, wanted):
    return sum(min(count, window[word]) for word, count in wanted.items())


def exact_run(page_words, part):
    size = len(part)
    for start in range(len(page_words) - size + 1):
        if page_words[start : start + size] == part:
            return True
    return False


def part_page(page_tokens, part, strict):
    for number, words in enumerate(page_tokens, start=1):
        if strict and exact_run(words, part):
            return number
        if not strict and window_match(words, part):
            return number
    return None


def quote_found(pages, quote):
    page_tokens = [tokens(text) for text in pages]
    parts = quote_parts(quote)
    strict = False
    if not parts:
        whole = tokens(quote)
        if not whole:
            return False, None
        parts = [whole]
        strict = True
    first_page = None
    for part in parts:
        page = part_page(page_tokens, part, strict)
        if page is None:
            return False, None
        if first_page is None:
            first_page = page
    return True, first_page
