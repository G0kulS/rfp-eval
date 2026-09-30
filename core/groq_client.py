import json
import re

from groq import Groq

RELATED = {
    "architecture": ["architecture", "microservice", "kubernetes", "cloud", "saas", "platform", "uptime"],
    "integrations": ["integrat", "connector", "adapter", "api", "sap", "salesforce", "webhook", "sign-on"],
    "scalability": ["scal", "autoscal", "concurrent", "load-tested", "tickets per minute", "zones"],
    "technical fit": ["omnichannel", "email", "chat", "whatsapp", "voice", "phone", "order history"],
    "timeline": ["week", "timeline", "phase", "schedule", "go-live", "rollout", "roll-out"],
    "milestones": ["milestone", "pilot", "exit criteria", "sign-off", "uat", "hypercare", "wave"],
    "staffing": ["team", "manager", "consultant", "engineer", "architect", "developer", "analyst", "trainer"],
    "risk plan": ["risk", "raid", "rollback", "steering", "owner"],
    "pricing clarity": ["inr", "price", "pricing", "per seat", "subscription", "licence", "license"],
    "total cost": ["total", "three-year", "3 years", "cost"],
    "assumptions": ["assumption", "gst", "valid", "fixed", "excluding", "included", "capped"],
    "controls": ["encrypt", "aes", "tls", "access", "penetration", "role-based", "nda"],
    "certifications": ["iso", "27001", "soc 2", "certif"],
    "privacy": ["residency", "privacy", "dpdp", "data stays", "stored in", "gdpr"],
    "auditability": ["audit", "logs", "report"],
    "support model": ["support", "24x7", "response", "service desk", "success manager", "sla"],
    "similar projects": ["projects", "customers", "retailers", "clients", "delivered", "deployed"],
    "references": ["reference", "client", "contact"],
}

VAGUE_CUES = [
    "tbc",
    "to be confirmed",
    "working towards",
    "hope",
    "worked out",
    "as they come up",
    "extra cost",
    "on request",
    "in progress",
    "once we are shortlisted",
    "generic",
]

MAX_QUOTE_WORDS = 40
PENALTY_PER_CUE = 0.75
MAX_PENALTY = 3.0


def ask(messages, settings):
    client = Groq(api_key=settings.api_key, max_retries=3)
    reply = client.chat.completions.create(
        model=settings.model,
        messages=messages,
        temperature=0,
        response_format={"type": "json_object"},
        timeout=120,
    )
    return reply.choices[0].message.content or ""


def topics_for(criterion):
    topics = []
    for part in re.split(r"[,;/]| and ", criterion["guidance"] or ""):
        topic = part.strip().lower()
        if topic:
            topics.append(topic)
    if not topics:
        topics.append(criterion["title"].lower())
    return topics


def signals_for(topic):
    signals = [topic]
    signals.extend(RELATED.get(topic, []))
    for word in topic.split():
        if len(word) >= 4:
            signals.append(word[:6])
    return signals


def has_signal(text, signals):
    for signal in signals:
        if re.search(r"\b" + re.escape(signal), text):
            return True
    return False


def document_lines(pages):
    lines = []
    for number, text in enumerate(pages, start=1):
        for line in text.splitlines():
            clean = " ".join(line.split())
            if clean:
                lines.append((number, clean))
    return lines


def vague_cues(text):
    found = []
    for cue in VAGUE_CUES:
        if re.search(r"\b" + re.escape(cue) + r"\b", text):
            found.append(cue)
    return found


def judge_criterion(criterion, lines):
    topics = topics_for(criterion)
    topic_hits = {topic: 0 for topic in topics}
    line_hits = []
    cues = []
    for page, line in lines:
        lowered = line.lower()
        matched = [topic for topic in topics if has_signal(lowered, signals_for(topic))]
        for topic in matched:
            topic_hits[topic] += 1
        if matched:
            line_hits.append((len(matched), page, line))
            cues.extend(vague_cues(lowered))
    return topics, topic_hits, line_hits, sorted(set(cues))


def best_quote(line_hits):
    long_lines = [hit for hit in line_hits if len(hit[2].split()) >= 6]
    candidates = long_lines or line_hits
    if not candidates:
        return "", None
    best = candidates[0]
    for hit in candidates:
        if hit[0] > best[0]:
            best = hit
    words = best[2].split()[:MAX_QUOTE_WORDS]
    return " ".join(words), best[1]


def raw_score(topics, topic_hits, cues, max_points):
    coverage = sum(min(topic_hits[topic], 3) / 3 for topic in topics) / len(topics)
    penalty = min(len(cues) * PENALTY_PER_CUE, MAX_PENALTY)
    score = max_points * coverage - penalty
    score = max(0.0, min(float(max_points), score))
    return round(score * 2) / 2


def criterion_result(criterion, lines):
    topics, topic_hits, line_hits, cues = judge_criterion(criterion, lines)
    covered = [topic for topic in topics if topic_hits[topic] > 0]
    missing = [topic for topic in topics if topic_hits[topic] == 0]
    quote, page = best_quote(line_hits)
    reason = f"The proposal covers {len(covered)} of {len(topics)} topics for {criterion['title']}."
    if missing:
        reason += f" Little or nothing was found on {', '.join(missing)}."
    if cues:
        reason += f" Vague wording was noted: {', '.join(cues)}."
    return {
        "criterion_id": criterion["id"],
        "score": raw_score(topics, topic_hits, cues, float(criterion["max_points"])),
        "max_score": criterion["max_points"],
        "confidence": round(0.4 + 0.5 * len(covered) / len(topics), 2),
        "justification": reason,
        "evidence": quote,
        "evidence_page": page,
        "strengths": [f"Covers {topic}" for topic in covered],
        "weaknesses": [f"Vague wording: {cue}" for cue in cues],
        "missing_information": [f"No clear detail on {topic}" for topic in missing],
    }


def offline_reply(supplier, pages, criteria):
    lines = document_lines(pages)
    results = [criterion_result(criterion, lines) for criterion in criteria]
    risks = []
    for result in results:
        for weakness in result["weaknesses"]:
            if weakness not in risks:
                risks.append(weakness)
    average = sum(result["score"] / float(result["max_score"]) for result in results) / max(len(results), 1)
    summary = (
        f"{supplier} was scored offline by keyword matching against the criteria guidance. "
        f"Average coverage is {round(average * 100)}% of the maximum."
    )
    reply = {
        "supplier_name": supplier,
        "criteria": results,
        "risks": risks,
        "overall_summary": summary,
    }
    return json.dumps(reply)
