from core.math_rules import reweight, score_batch


def item(criterion_id, points, weight, max_points=10):
    return {"id": criterion_id, "title": f"C{criterion_id}", "weight": weight, "max_points": max_points,
            "points": points}


def supplier(name, points, submitted_on="2026-09-10", experience=3.0, weights=(60, 40)):
    items = []
    for number, value in enumerate(points, start=1):
        items.append(item(number, value, weights[number - 1]))
    return {"supplier": name, "submitted_on": submitted_on, "experience": experience, "items": items}


def by_name(ranked):
    return {entry["supplier"]: entry for entry in ranked}


def test_hand_worked_example():
    ranked = score_batch([supplier("Alpha", [8, 5]), supplier("Beta", [6, 10])])
    rows = by_name(ranked)
    assert rows["Alpha"]["absolute"] == 68.0
    assert rows["Beta"]["absolute"] == 76.0
    alpha_items = rows["Alpha"]["items"]
    assert [entry["benchmark"] for entry in alpha_items] == [8.0, 10.0]
    assert [entry["gap"] for entry in alpha_items] == [0.0, -5.0]
    assert [entry["relative"] for entry in alpha_items] == [100.0, 50.0]
    assert rows["Alpha"]["ppi"] == 80.0
    assert rows["Beta"]["ppi"] == 85.0
    assert [entry["supplier"] for entry in ranked] == ["Beta", "Alpha"]
    assert [entry["rank"] for entry in ranked] == [1, 2]
    assert rows["Alpha"]["rank_note"] == "Lower PPI than Beta (80.0 vs 85.0)"


def test_zero_benchmark_gives_zero_relative():
    ranked = score_batch([supplier("Alpha", [0, 5]), supplier("Beta", [0, 4])])
    for entry in ranked:
        assert entry["items"][0]["benchmark"] == 0.0
        assert entry["items"][0]["relative"] == 0.0
    assert by_name(ranked)["Alpha"]["ppi"] == 40.0


def test_tie_break_earlier_submission_date():
    ranked = score_batch([
        supplier("Alpha", [8, 8], submitted_on="2026-09-12"),
        supplier("Beta", [8, 8], submitted_on="2026-09-09"),
    ])
    assert [entry["supplier"] for entry in ranked] == ["Beta", "Alpha"]
    assert "submitted later" in ranked[1]["rank_note"]


def test_tie_break_higher_experience():
    ranked = score_batch([
        supplier("Alpha", [8, 8], experience=3.0),
        supplier("Beta", [8, 8], experience=4.5),
    ])
    assert [entry["supplier"] for entry in ranked] == ["Beta", "Alpha"]
    assert "lower experience rating (3 vs 4.5)" in ranked[1]["rank_note"]


def test_tie_break_supplier_name():
    ranked = score_batch([supplier("zeta Corp", [8, 8]), supplier("Alpha", [8, 8])])
    assert [entry["supplier"] for entry in ranked] == ["Alpha", "zeta Corp"]
    assert "supplier name (A-Z)" in ranked[1]["rank_note"]


def test_values_are_rounded_before_comparing():
    first = supplier("Alpha", [1, 1], submitted_on="2026-09-12", weights=(1, 2))
    second = supplier("Beta", [1, 1], submitted_on="2026-09-09", weights=(1, 2))
    first["items"][0]["points"] = 1.00000001
    ranked = score_batch([first, second])
    assert ranked[0]["ppi"] == ranked[1]["ppi"]
    assert ranked[0]["supplier"] == "Beta"


def test_reweight_changes_order_without_touching_input():
    original = score_batch([supplier("Alpha", [8, 5]), supplier("Beta", [6, 10])])
    changed = reweight(original, {1: 90, 2: 10})
    assert [entry["supplier"] for entry in changed] == ["Alpha", "Beta"]
    assert original[0]["supplier"] == "Beta"
    assert original[0]["items"][0]["weight"] == 60
    assert by_name(changed)["Alpha"]["absolute"] == 77.0
