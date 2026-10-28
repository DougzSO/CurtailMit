"""State attribution and aggregation of observed curtailment (Task 17): the stop conditions, the reconciliation gate, the cache semantics."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from curtailmit import context_data as cd


def _raw(tmp_path, wind_rows, solar_rows):
    for d, rows in (("curtailment_wind", wind_rows), ("curtailment_solar", solar_rows)):
        folder = tmp_path / "raw" / "ons" / d
        folder.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows, columns=["nom_usina", "id_estado", "nom_estado"]).to_parquet(folder / "2025-01.parquet")
    return tmp_path / "raw"


WIND = [("W1", "RN", "Rio Grande do Norte"), ("W2", "BA", "Bahia"), ("W2", "BA", "Bahia"), ("W3", "RS", "Rio Grande do Sul")]
SOLAR = [("S1", "MG", "Minas Gerais"), ("S2", "BA", "Bahia")]


def _classified():
    rows = []
    for ts, plant, src, e in [("2025-01-15 10:00", "W1", "wind", 10.0), ("2025-02-15 10:00", "W1", "wind", 5.0), ("2025-01-15 11:00", "W2", "wind", 20.0), ("2025-03-01 00:00", "W3", "wind", 1.0),
                              ("2025-01-02 12:00", "S1", "solar", 8.0), ("2025-06-02 12:00", "S2", "solar", 2.0), ("2026-01-03 12:00", "S1", "solar", 4.0), ("2025-02-01 00:00", "W2", "wind", 4.0)]:
        rows.append({"usina": plant, "source": src, "timestamp": pd.Timestamp(ts), "curtailed_energy_mwh": e})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------ plant -> state map
def test_map_has_one_row_per_plant_with_its_state(tmp_path):
    m = cd.usina_state_map(_raw(tmp_path, WIND, SOLAR)).set_index("usina")
    assert list(m.index) == ["S1", "S2", "W1", "W2", "W3"] and m.loc["W2", "id_estado"] == "BA" and m.loc["S1", "nom_estado"] == "Minas Gerais"


def test_a_plant_in_two_states_stops_with_the_plant_and_both_states_named(tmp_path):
    raw = _raw(tmp_path, [*WIND, ("W2", "PI", "Piaui")], SOLAR)
    with pytest.raises(cd.PlantStateConflictError, match=r"'W2': BA, PI") as e:
        cd.usina_state_map(raw)
    assert "not split by energy share" in str(e.value)


def test_a_plant_name_shared_by_wind_and_solar_in_different_states_is_also_a_conflict(tmp_path):
    with pytest.raises(cd.PlantStateConflictError, match="more than one state"):
        cd.usina_state_map(_raw(tmp_path, WIND, [*SOLAR, ("W1", "CE", "Ceara")]))


def test_a_raw_row_without_a_state_and_a_missing_raw_folder_stop(tmp_path):
    with pytest.raises(cd.MissingStateError, match="without a state"):
        cd.usina_state_map(_raw(tmp_path, [*WIND, ("W9", None, None)], SOLAR))
    with pytest.raises(cd.MissingStateError, match="no raw ONS files"):
        cd.usina_state_map(tmp_path / "empty")


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------ aggregation
def test_aggregation_sums_by_state_technology_and_year_and_reconciles(tmp_path):
    m = cd.usina_state_map(_raw(tmp_path, WIND, SOLAR))
    t = cd.aggregate_by_state(_classified(), m)
    assert list(t.columns) == list(cd.COLUMNS)
    w25 = t[(t.technology == "wind") & (t.year == 2025)].set_index("id_estado")
    assert w25.loc["BA", "curtailed_energy_mwh"] == 24.0 and w25.loc["RN", "curtailed_energy_mwh"] == 15.0 and w25.loc["RS", "curtailed_energy_mwh"] == 1.0
    assert w25["national_total_mwh"].eq(40.0).all() and w25["share_of_national_pct"].sum() == pytest.approx(100.0)
    assert w25.loc["BA", "share_of_national_pct"] == pytest.approx(60.0) and w25.loc["BA", "curtailed_energy_twh"] == pytest.approx(24.0 / 1e6)
    for (_tech, _year), g in t.groupby(["technology", "year"]):
        assert g["share_of_national_pct"].sum() == pytest.approx(100.0, rel=1e-12)
    national = _classified().assign(y=lambda d: d.timestamp.dt.year).groupby(["source", "y"])["curtailed_energy_mwh"].sum()
    per = t.groupby(["technology", "year"])["curtailed_energy_mwh"].sum()
    assert np.allclose(per.to_numpy(), national.to_numpy(), rtol=1e-9, atol=0)
    cd.reconcile(t, _classified())


def test_months_covered_and_partial_year_flags_come_from_the_data(tmp_path):
    t = cd.aggregate_by_state(_classified(), cd.usina_state_map(_raw(tmp_path, WIND, SOLAR)))
    s25 = t[(t.technology == "solar") & (t.year == 2025)]
    assert s25["months_covered"].eq(2).all() and s25["is_partial_year"].all()  # January and June only
    w25 = t[(t.technology == "wind") & (t.year == 2025)]
    assert w25["months_covered"].eq(3).all()


def test_a_classified_plant_without_a_state_stops(tmp_path):
    m = cd.usina_state_map(_raw(tmp_path, WIND, SOLAR))
    extra = pd.concat([_classified(), pd.DataFrame([{"usina": "GHOST", "source": "wind", "timestamp": pd.Timestamp("2025-01-01"), "curtailed_energy_mwh": 1.0}])])
    with pytest.raises(cd.MissingStateError, match="GHOST"):
        cd.aggregate_by_state(extra, m)


def test_reconciliation_is_a_hard_gate_that_catches_a_tampered_table(tmp_path):
    t = cd.aggregate_by_state(_classified(), cd.usina_state_map(_raw(tmp_path, WIND, SOLAR)))
    cd.reconcile(t, _classified())
    bad = t.copy()
    bad.loc[0, "curtailed_energy_mwh"] *= 1.000001  # a relative error of 1e-6 is far above the 1e-9 tolerance
    with pytest.raises(cd.ReconciliationError):
        cd.reconcile(bad, _classified())
    lost = t.iloc[1:]
    with pytest.raises(cd.ReconciliationError):
        cd.reconcile(lost, _classified())


def test_the_gate_inside_the_aggregation_fires_if_rows_are_lost_in_the_join(tmp_path, monkeypatch):
    m = cd.usina_state_map(_raw(tmp_path, WIND, SOLAR))
    original = pd.DataFrame.merge

    def lossy(self, right, *a, **k):
        out = original(self, right, *a, **k)
        return out.iloc[1:] if "id_estado" in out.columns else out  # drop one classified row after the state join

    monkeypatch.setattr(pd.DataFrame, "merge", lossy)
    with pytest.raises(cd.ReconciliationError, match="sum over states differs"):
        cd.aggregate_by_state(_classified(), m)


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- cache
def _layout(tmp_path):
    processed = tmp_path / "processed"
    processed.mkdir(exist_ok=True)
    _classified().to_parquet(processed / cd.CLASSIFIED_NAME)
    return {"raw_root": _raw(tmp_path, WIND, SOLAR), "processed": processed, "interim": tmp_path / "interim", "tables": tmp_path / "tables"}


def test_build_writes_the_cache_and_the_csv_and_reuses_them_unless_forced(tmp_path, monkeypatch):
    kw = _layout(tmp_path)
    first = cd.build(**kw)
    assert (tmp_path / "interim" / cd.CACHE_NAME).is_file() and (tmp_path / "tables" / cd.CSV_NAME).is_file()
    csv = pd.read_csv(tmp_path / "tables" / cd.CSV_NAME)
    assert len(csv) == len(first) and np.allclose(csv["curtailed_energy_mwh"], first["curtailed_energy_mwh"])

    def boom(*a, **k):
        raise AssertionError("recomputed although the cache exists")

    monkeypatch.setattr(cd, "aggregate_by_state", boom)
    again = cd.build(**kw)  # served from the cache
    pd.testing.assert_frame_equal(first, again)
    (tmp_path / "tables" / cd.CSV_NAME).unlink()
    cd.build(**kw)
    assert (tmp_path / "tables" / cd.CSV_NAME).is_file()  # the csv is restored from the cache
    with pytest.raises(AssertionError, match="recomputed"):
        cd.build(force=True, **kw)


def test_build_needs_the_classified_table_and_the_cli_reports_a_conflict_as_a_stop(tmp_path, monkeypatch, capsys):
    with pytest.raises(cd.ContextDataError, match="not found"):
        cd.build(raw_root=_raw(tmp_path, WIND, SOLAR), processed=tmp_path / "none", interim=tmp_path / "i", tables=tmp_path / "t")

    def conflict(**k):
        raise cd.PlantStateConflictError("plant X in BA and PI")

    monkeypatch.setattr(cd, "build", conflict)
    assert cd.main(["--force"]) == 2
    assert "STOP: plant X in BA and PI" in capsys.readouterr().err


# ------------------------------------------------------------------------------------------------------------------------------------------------------- real tables (local database)
@pytest.mark.integration
def test_real_state_year_table_reconciles_with_the_classified_table_and_states_match_the_geometry():
    from curtailmit import paths
    from curtailmit import spatial as sp

    lay = paths.planned_layout()
    cache = lay["interim"] / cd.CACHE_NAME
    classified_path = lay["processed"] / cd.CLASSIFIED_NAME
    if not cache.is_file() or not classified_path.is_file() or not sp.default_shp().is_file():
        pytest.skip("no local database")
    table = pd.read_parquet(cache)
    cd.reconcile(table, pd.read_parquet(classified_path, columns=["source", "timestamp", "curtailed_energy_mwh"]))  # rtol 1e-9, every technology and year
    for _, g in table.groupby(["technology", "year"]):
        assert g["share_of_national_pct"].sum() == pytest.approx(100.0, rel=1e-9)
    assert set(table["id_estado"]) <= set(sp.read_states(sp.default_shp(), tol=None))  # every ONS state code exists in the GADM layer
    assert set(table["technology"]) == {"wind", "solar"} and set(table["year"]) == {2022, 2023, 2024, 2025, 2026}
