import copy

PLACES = 4


def rounded(value):
    return round(float(value), PLACES)


def benchmarks(suppliers):
    best = {}
    for supplier in suppliers:
        for item in supplier["items"]:
            points = rounded(item["points"])
            if item["id"] not in best or points > best[item["id"]]:
                best[item["id"]] = points
    return best


def add_peer_metrics(supplier, best):
    absolute = 0.0
    weighted_relative = 0.0
    total_weight = 0.0
    for item in supplier["items"]:
        points = rounded(item["points"])
        weight = float(item["weight"])
        benchmark = best[item["id"]]
        item["benchmark"] = benchmark
        item["gap"] = rounded(points - benchmark)
        item["relative"] = rounded(points / benchmark * 100) if benchmark > 0 else 0.0
        absolute += points / float(item["max_points"]) * weight
        weighted_relative += item["relative"] * weight
        total_weight += weight
    supplier["absolute"] = rounded(absolute)
    supplier["ppi"] = rounded(weighted_relative / total_weight) if total_weight > 0 else 0.0


def order_key(supplier):
    return (
        -rounded(supplier["ppi"]),
        str(supplier["submitted_on"]),
        -float(supplier["experience"]),
        supplier["supplier"].lower(),
        supplier["supplier"],
    )


def show(value, other):
    if round(value, 1) == round(other, 1):
        return f"{value:.4f}"
    return f"{value:.1f}"


def rank_reason(supplier, other):
    name = other["supplier"]
    ppi = supplier["ppi"]
    other_ppi = other["ppi"]
    if ppi != other_ppi:
        word = "Higher" if ppi > other_ppi else "Lower"
        return f"{word} PPI than {name} ({show(ppi, other_ppi)} vs {show(other_ppi, ppi)})"
    same = f"Same PPI as {name} ({ppi:.4f})"
    day = str(supplier["submitted_on"])
    other_day = str(other["submitted_on"])
    if day != other_day:
        word = "earlier" if day < other_day else "later"
        return f"{same}; submitted {word} ({day} vs {other_day})"
    same = f"Same PPI and submission date as {name}"
    rating = float(supplier["experience"])
    other_rating = float(other["experience"])
    if rating != other_rating:
        word = "higher" if rating > other_rating else "lower"
        return f"{same}; {word} experience rating ({rating:g} vs {other_rating:g})"
    return f"Same PPI, submission date and experience rating as {name}; ordered by supplier name (A-Z)"


def add_rank_notes(ranked):
    if len(ranked) == 1:
        ranked[0]["rank_note"] = f"Only supplier in the batch (PPI {ranked[0]['ppi']:.1f})"
        return
    for index, supplier in enumerate(ranked):
        if index == 0:
            reason = rank_reason(supplier, ranked[1])
            supplier["rank_note"] = f"Ranked first. {reason}"
        else:
            supplier["rank_note"] = rank_reason(supplier, ranked[index - 1])


def score_batch(cards):
    suppliers = copy.deepcopy(list(cards))
    if not suppliers:
        return []
    best = benchmarks(suppliers)
    for supplier in suppliers:
        add_peer_metrics(supplier, best)
    ranked = sorted(suppliers, key=order_key)
    for position, supplier in enumerate(ranked, start=1):
        supplier["rank"] = position
    add_rank_notes(ranked)
    return ranked


def reweight(suppliers, weights):
    changed = copy.deepcopy(list(suppliers))
    for supplier in changed:
        for item in supplier["items"]:
            if item["id"] in weights:
                item["weight"] = float(weights[item["id"]])
            elif str(item["id"]) in weights:
                item["weight"] = float(weights[str(item["id"])])
    return score_batch(changed)
