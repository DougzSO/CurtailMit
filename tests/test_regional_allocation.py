"""Task 17-3: regional allocation validation (D37). Synthetic inputs only; the real numbers are in docs/task17_design.md."""

import pandas as pd
import pytest

from curtailmit import regional_allocation as ra


def _state_year(rows):
    return pd.DataFrame(
        [{"id_estado": s, "technology": t, "year": y, "curtailed_energy_twh": e, "months_covered": m} for s, t, y, e, m in rows]
    )


def test_every_state_has_one_region_and_regions_cover_27_states():
    assert len(ra.STATE_REGION) == 27 and set(ra.STATE_REGION.values()) == set(ra.REGIONS)


def test_shares_sum_to_100_and_regions_without_plants_are_zero():
    d = _state_year([("BA", "wind", 2024, 6.0, 12), ("RS", "wind", 2024, 2.0, 12), ("MG", "solar", 2024, 1.0, 12)])
    s = ra.regional_shares(d)
    assert s.groupby(["technology", "year"])["share_pct"].sum().tolist() == pytest.approx([100.0, 100.0])
    w = s[(s.technology == "wind") & (s.year == 2024)].set_index("region")["share_pct"]
    assert w["NE"] == pytest.approx(75.0) and w["S"] == pytest.approx(25.0) and w["N"] == 0.0


def test_unknown_state_stops():
    with pytest.raises(ValueError, match="without a macro-region"):
        ra.regional_energy(_state_year([("XX", "wind", 2024, 1.0, 12)]))


def test_leave_one_year_out_is_exact_for_a_stable_pattern_and_flags_a_swing():
    stable = [(s, "wind", y, e, 12) for y in (2022, 2023, 2024) for s, e in (("BA", 9.0), ("RS", 1.0))]
    sh = ra.regional_shares(_state_year(stable))
    assert ra.leave_one_year_out(sh, "wind")["error_pp"].abs().max() == pytest.approx(0.0)
    swing = [("BA", "solar", 2024, 5.0, 12), ("MG", "solar", 2024, 5.0, 12), ("BA", "solar", 2025, 8.0, 12), ("MG", "solar", 2025, 2.0, 12)]
    sh2 = ra.regional_shares(_state_year(swing))
    fw = ra.forward_persistence(sh2, "solar")
    assert fw[fw.region == "NE"]["error_pp"].iloc[0] == pytest.approx(-30.0)
    v = ra.judge(ra.leave_one_year_out(sh2, "solar"), fw, sh2, "solar")
    assert v["verdict"] == "poor" and not v["checks"]["adjacent_swing"]


def test_judge_accepts_a_stable_technology():
    stable = [(s, "wind", y, e, 12) for y in (2022, 2023, 2024) for s, e in (("BA", 9.0), ("RS", 1.0))]
    res = ra.validate(_state_year(stable))
    assert res["verdicts"]["wind"]["verdict"] == "reasonable"


def test_partial_year_is_not_used_for_training_but_is_checked_forward():
    rows = [("BA", "wind", 2024, 9.0, 12), ("RS", "wind", 2024, 1.0, 12), ("BA", "wind", 2025, 5.0, 6), ("RS", "wind", 2025, 5.0, 6)]
    sh = ra.regional_shares(_state_year(rows))
    assert ra.leave_one_year_out(sh, "wind").empty  # one complete year: nothing to train on
    fw = ra.forward_persistence(sh, "wind")
    assert not fw["to_year_complete"].any()
