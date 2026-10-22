"""Task 3 - ONS generation-by-source acquisition (package `balanco-energia-subsistema`).

Provides the historical P(t) = (wind + solar) / (hydro + thermal + wind + solar) series used as
calibration input (Task 9) and the observed 2020 baseline (decision D1).

Discovery is closed (config/acquisition_targets.yaml: ons.packages.generation_by_source); the package is
still re-confirmed at runtime via package_show, with package_search as the recovery path.
Only years >= `history_start_year` (config) are downloaded: earlier resources have unusable gaps
(wind blank 2000-2005, partially in 2006; 24 h missing in 2015), irrelevant to the 2020 baseline / 2021+ calibration.
Values in the source are average power (MW) per hourly sample; energy is power x the sampling interval
inferred from the timestamps (1 h in practice).

Solar basis (D20, Task 9): from `solar_basis.dispatched_from` (config; 2021-01) the solar term of P(t) - numerator AND the solar part of the
total-generation denominator - is the ONS-dispatched (centralized) solar summed from the per-plant capacity-factor dataset
(`ons_solar_gap`), not the balance `val_gersolar`, which includes an estimated MMGD component from 2023-04-29. The raw balance solar stays in the
outputs as `solar_gen_ons_balance_raw_mwh`, a diagnostic that is never used in P(t) or curtailment-rate math. Wind and the 2020 baseline are unchanged.
A month of the window missing from the dispatched series fails explicitly (no silent fallback to `val_gersolar`).

Output (all under DATABASE_ROOT):
- interim/ons_generation_by_source.parquet   tidy hourly series [timestamp, date, source_type, generation_mwh]
- processed/ons_penetration_monthly.parquet  monthly energy by source + wind/solar/P(t) percentages
- processed/ons_penetration_annual.parquet   same, annual
- processed/baseline_2020_generation.json    2020 totals in TWh (schemas.Baseline2020Generation)
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from curtailmit.acquisition import fetch_and_cache
from curtailmit.data_ingestion import _normalize, _read_table, load_acquisition_targets
from curtailmit.ons_client import CkanClient, ResourceInfo
from curtailmit.paths import get_interim_dir, get_processed_dir, get_raw_dir
from curtailmit.schemas import Baseline2020Generation, GenerationPackageDiscovery
from curtailmit.validation import ValidationError

logger = logging.getLogger(__name__)

INTERIM_FILENAME = "ons_generation_by_source.parquet"
BASELINE_FILENAME = "baseline_2020_generation.json"
MONTHLY_FILENAME = "ons_penetration_monthly.parquet"
ANNUAL_FILENAME = "ons_penetration_annual.parquet"
BASELINE_YEAR = 2020
SOLAR_RAW_COL = "solar_gen_ons_balance_raw_mwh"  # diagnostic only (D20)

YEARLY_NAME_PATTERN = re.compile(r"^(?P<prefix>.+)-(?P<year>\d{4})$")
_SEARCH_QUERIES = ("balanco energia subsistema", "geracao fonte subsistema")
_SOURCE_COLUMNS = {
    "hidraulica": "val_gerhidraulica",
    "termica": "val_gertermica",
    "eolica": "val_gereolica",
    "solar": "val_gersolar",
}
_TIMESTAMP_COL, _SUBSYSTEM_COL = "din_instante", "id_subsistema"
_OPTIONAL_COLS = ("nom_subsistema", "val_carga", "val_intercambio")
_NATIONAL_AGGREGATE = "SIN"


class GenerationDiscoveryError(RuntimeError):
    """Raised when the ONS generation-by-source package cannot be discovered, parsed or validated."""


def _search_fallback(client: CkanClient) -> str:
    candidates: dict[str, str] = {}
    for query in _SEARCH_QUERIES:
        results = client.package_search(query)
        logger.info("Fallback search q='%s' returned %d packages", query, len(results))
        for pkg in results:
            haystack = _normalize(f"{pkg.get('name', '')} {pkg.get('title', '')}")
            logger.info("  candidate: %s | %s", pkg.get("name", ""), pkg.get("title", ""))
            if "balanco" in haystack and "subsistema" in haystack:
                candidates.setdefault(pkg["name"], pkg.get("title", ""))
    if not candidates:
        msg = f"Fallback package_search found no generation-by-source package (queries={_SEARCH_QUERIES})."
        logger.error(msg)
        raise GenerationDiscoveryError(msg)
    chosen = next(iter(candidates))
    if len(candidates) > 1:
        logger.warning("Multiple fallback candidates: %s - choosing '%s'", list(candidates), chosen)
    logger.info("Fallback chose package '%s'", chosen)
    return chosen


def discover_generation_package(client: CkanClient, pkg_cfg: dict) -> tuple[GenerationPackageDiscovery, list[ResourceInfo]]:
    """Re-confirm the configured package via package_show; fall back to package_search if it fails outright."""
    configured_id = pkg_cfg["package_id"]
    resolved_id, used_fallback = configured_id, False
    try:
        package = client.package_show(configured_id)
        logger.info("package_show('%s') OK: title=%r", configured_id, package.get("title"))
    except (requests.RequestException, RuntimeError) as exc:
        logger.warning("static config is STALE: package_show('%s') failed (%s) - falling back to package_search", configured_id, exc)
        resolved_id, used_fallback = _search_fallback(client), True
        package = client.package_show(resolved_id)
    resources = CkanClient.resources_from_package(package)

    expected_title = pkg_cfg.get("title")
    if expected_title and _normalize(package.get("title", "")) != _normalize(expected_title):
        logger.warning("package title changed: config=%r live=%r", expected_title, package.get("title"))
    formats = sorted({r.format.upper() for r in resources if r.format})
    logger.info("resource formats seen: %s", formats)
    yearly = [r for r in resources if YEARLY_NAME_PATTERN.match(r.name)]
    if not yearly:
        logger.warning("no resource matches the yearly '<prefix>-YYYY' naming (expected %r)", pkg_cfg.get("resource_name_pattern"))
    if used_fallback:
        logger.warning("discovered package_id='%s' differs from config '%s' - pin manually if desired", resolved_id, configured_id)
    info = GenerationPackageDiscovery(
        configured_package_id=configured_id,
        resolved_package_id=resolved_id,
        used_fallback_search=used_fallback,
        n_resources=len(resources),
        formats_seen=formats,
    )
    return info, resources


def select_yearly_resources(resources: list[ResourceInfo], preferred_formats: list[str], min_year: int | None = None) -> list[ResourceInfo]:
    """One resource per year (>= min_year) in preferred-format order; docs/dictionaries are skipped. Sorted oldest-first."""
    preferred = [f.upper() for f in preferred_formats]
    by_year: dict[int, list[ResourceInfo]] = {}
    for r in resources:
        m = YEARLY_NAME_PATTERN.match(r.name)
        if not m:
            logger.info("Skipping non-yearly resource '%s' (%s)", r.name, r.format)
            continue
        if min_year is not None and int(m.group("year")) < min_year:
            continue
        by_year.setdefault(int(m.group("year")), []).append(r)
    selected: list[ResourceInfo] = []
    for year in sorted(by_year):
        best = next((r for fmt in preferred for r in by_year[year] if r.format.upper() == fmt), None)
        if best is None:
            logger.warning("Year %d has no resource in preferred formats %s (has %s)", year, preferred, [r.format for r in by_year[year]])
            continue
        selected.append(best)
    if not selected:
        msg = f"No yearly generation resources in preferred formats {preferred} among {len(resources)} resources."
        logger.error(msg)
        raise GenerationDiscoveryError(msg)
    logger.info("Selected %d yearly resources (first=%s, last=%s)", len(selected), selected[0].name, selected[-1].name)
    return selected


def parse_generation_frame(raw: pd.DataFrame, label: str = "") -> pd.DataFrame:
    """Normalise one yearly resource to the tidy [timestamp, date, source_type, generation_mwh] frame (SIN only)."""
    df = raw.copy()
    df.columns = [str(c).strip().lower() for c in raw.columns]
    required = [_TIMESTAMP_COL, _SUBSYSTEM_COL, *_SOURCE_COLUMNS.values()]
    missing = [c for c in required if c not in df.columns]
    if missing:
        msg = f"Cannot parse generation resource {label}: missing columns {missing}; found {list(df.columns)}"
        logger.error(msg)
        raise GenerationDiscoveryError(msg)
    absent_optional = [c for c in _OPTIONAL_COLS if c not in df.columns]
    if absent_optional:
        logger.warning("%s: optional columns missing (schema drift?): %s", label, absent_optional)

    sin = df[df[_SUBSYSTEM_COL].astype(str).str.strip().str.upper() == _NATIONAL_AGGREGATE].copy()
    if sin.empty:
        msg = f"{label}: no rows with {_SUBSYSTEM_COL} == '{_NATIONAL_AGGREGATE}' (found {sorted(df[_SUBSYSTEM_COL].astype(str).unique())})"
        logger.error(msg)
        raise GenerationDiscoveryError(msg)

    timestamp = pd.to_datetime(sin[_TIMESTAMP_COL])
    if timestamp.duplicated().any():
        raise GenerationDiscoveryError(f"{label}: duplicated SIN timestamps ({int(timestamp.duplicated().sum())}) - cannot aggregate unambiguously.")
    unique_ts = timestamp.sort_values()
    if len(unique_ts) < 2:
        raise GenerationDiscoveryError(f"{label}: fewer than 2 SIN timestamps - cannot infer the sampling interval.")
    interval_h = unique_ts.diff().dropna().median().total_seconds() / 3600

    frames = []
    for source_type, col in _SOURCE_COLUMNS.items():
        # ONS parquet/CSV publish decimals as text -> coerce explicitly, then check what was lost.
        power = pd.to_numeric(sin[col], errors="coerce")
        n_nan = int(power.isna().sum())
        if n_nan and source_type == "solar":
            logger.info("%s: %d of %d NaN solar values treated as 0 (documented: solar blank before ~2017; not a data-quality failure)", label, n_nan, len(power))
            power = power.fillna(0.0)
        elif n_nan:
            msg = f"{label}: {n_nan} of {len(power)} values missing/non-numeric in {col} - refusing to assume zero generation."
            logger.error(msg)
            raise GenerationDiscoveryError(msg)
        frames.append(pd.DataFrame({"timestamp": timestamp, "date": timestamp.dt.date, "source_type": source_type, "generation_mwh": power * interval_h}))
    out = pd.concat(frames, ignore_index=True)
    logger.info("%s: parsed %d SIN samples x %d sources (interval=%.2f h)", label, len(sin), len(_SOURCE_COLUMNS), interval_h)
    return out


def check_dispatched_coverage(tidy: pd.DataFrame, dispatched_monthly: pd.DataFrame, dispatched_from: str) -> None:
    """Every month of the balance series from `dispatched_from` on must be in the dispatched series, over the same hours.

    Raises GenerationDiscoveryError naming the months (missing, or with a different number of hours / different balance energy).
    """
    start = pd.Period(dispatched_from, freq="M")
    solar = tidy[tidy["source_type"] == "solar"]
    ts = pd.to_datetime(solar["timestamp"])
    bal = solar.groupby(ts.dt.to_period("M"))["generation_mwh"].agg(["size", "sum"])
    bal = bal[bal.index >= start]
    if bal.empty:
        raise GenerationDiscoveryError(f"No balance months from {dispatched_from} on - cannot apply the dispatched solar basis (D20).")
    missing = [str(p) for p in bal.index if p not in dispatched_monthly.index]
    if missing:
        msg = f"Dispatched solar series (D20) is missing {len(missing)} month(s) present in val_gersolar: {missing}. Not falling back to val_gersolar."
        logger.error(msg)
        raise GenerationDiscoveryError(msg)
    d = dispatched_monthly.loc[bal.index]
    bad = [f"{p} (hours balance={int(bal.loc[p, 'size'])} dispatched={int(d.loc[p, 'hours'])})" for p in bal.index if int(bal.loc[p, "size"]) != int(d.loc[p, "hours"])]
    drift = [str(p) for p in bal.index if abs(bal.loc[p, "sum"] - d.loc[p, "balanco_matched_mwh"]) > 1e-6 * max(1.0, abs(bal.loc[p, "sum"]))]
    if bad or drift:
        msg = f"Dispatched solar series (D20) does not cover the same hours as val_gersolar: hour-count mismatch {bad}; balance energy mismatch {drift}."
        logger.error(msg)
        raise GenerationDiscoveryError(msg)


def compute_penetration(tidy: pd.DataFrame, freq: str = "monthly", dispatched_monthly: pd.DataFrame | None = None, dispatched_from: str | None = None) -> pd.DataFrame:
    """Energy by source and P(t) = (wind + solar) / (hydro + thermal + wind + solar), computed from the data (never hardcoded).

    With `dispatched_monthly` + `dispatched_from` (D20) the solar energy of every month >= dispatched_from is the dispatched (centralized)
    series; `solar_basis` says which one each period uses and `solar_gen_ons_balance_raw_mwh` keeps the raw balance value (diagnostic only).
    Annual rows are the sum of the monthly rows, so both frequencies agree.
    """
    if freq not in ("monthly", "annual"):
        raise ValueError(f"freq must be 'monthly' or 'annual', got {freq!r}")
    if (dispatched_monthly is None) != (dispatched_from is None):
        raise ValueError("dispatched_monthly and dispatched_from must be given together.")
    ts = pd.to_datetime(tidy["timestamp"])
    wide = tidy.assign(year=ts.dt.year, month=ts.dt.month).pivot_table(index=["year", "month"], columns="source_type", values="generation_mwh", aggfunc="sum")
    missing = [s for s in _SOURCE_COLUMNS if s not in wide.columns]
    if missing:
        raise GenerationDiscoveryError(f"compute_penetration: source types missing from tidy frame: {missing}")
    wide = wide[list(_SOURCE_COLUMNS)].add_suffix("_mwh")
    wide[SOLAR_RAW_COL] = wide["solar_mwh"]
    wide["solar_basis"] = "balance"
    if dispatched_monthly is not None:
        check_dispatched_coverage(tidy, dispatched_monthly, dispatched_from)
        start = pd.Period(dispatched_from, freq="M")
        periods = pd.PeriodIndex([pd.Period(year=y, month=m, freq="M") for y, m in wide.index], freq="M")
        use = periods >= start
        wide.loc[use, "solar_mwh"] = dispatched_monthly.loc[periods[use], "dispatched_matched_mwh"].to_numpy()
        wide.loc[use, "solar_basis"] = "dispatched"
    if freq == "annual":
        basis = wide["solar_basis"].groupby(level="year").agg(lambda b: b.iloc[0] if b.nunique() == 1 else "mixed")
        wide = wide.drop(columns="solar_basis").groupby(level="year").sum()
        wide["solar_basis"] = basis
    total = wide[[f"{s}_mwh" for s in _SOURCE_COLUMNS]].sum(axis=1)
    if (total <= 0).any():
        raise GenerationDiscoveryError("compute_penetration: non-positive total generation in at least one period.")
    wide["total_mwh"] = total
    wide["wind_pct"] = 100 * wide["eolica_mwh"] / total
    wide["solar_pct"] = 100 * wide["solar_mwh"] / total
    wide["penetration_pct"] = wide["wind_pct"] + wide["solar_pct"]
    return wide.reset_index()


def extract_baseline_2020(tidy: pd.DataFrame) -> Baseline2020Generation:
    """2020 annual totals by source in TWh. Requires complete 2020 coverage (every hour of the year present)."""
    ts = pd.to_datetime(tidy["timestamp"])
    rows = tidy[ts.dt.year == BASELINE_YEAR]
    if rows.empty:
        raise GenerationDiscoveryError(f"No {BASELINE_YEAR} data in the generation series - cannot build the D1 baseline.")
    stamps = pd.to_datetime(rows["timestamp"]).drop_duplicates().sort_values()
    interval = stamps.diff().dropna().median()
    expected = pd.date_range(f"{BASELINE_YEAR}-01-01", f"{BASELINE_YEAR + 1}-01-01", freq=interval, inclusive="left")
    gaps = expected.difference(stamps)
    if len(gaps):
        msg = f"{BASELINE_YEAR} baseline incomplete: {len(gaps)} of {len(expected)} samples missing (first gap {gaps[0]}) - failing explicitly."
        logger.error(msg)
        raise GenerationDiscoveryError(msg)
    twh = rows.groupby("source_type")["generation_mwh"].sum() / 1e6
    baseline = Baseline2020Generation(solar_twh=float(twh["solar"]), wind_twh=float(twh["eolica"]), total_twh=float(twh.sum()))
    logger.info(
        "2020 baseline: solar=%.2f TWh wind=%.2f TWh total=%.2f TWh (hydro=%.2f thermal=%.2f) penetration=%.2f%%",
        baseline.solar_twh, baseline.wind_twh, baseline.total_twh, twh["hidraulica"], twh["termica"], baseline.penetration_pct,
    )
    return baseline


def write_baseline_json(baseline: Baseline2020Generation, path: Path, package_id: str) -> None:
    payload = {
        **baseline.model_dump(),
        "penetration_pct": baseline.penetration_pct,
        "units": "TWh",
        "package_id": package_id,
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("Wrote 2020 baseline to %s", path)


def acquire_ons_generation(targets: dict | None = None, client: CkanClient | None = None, use_cache: bool = False, dispatched_monthly: pd.DataFrame | None = None) -> dict:
    """Task 3 entry point: yearly SIN generation by source -> interim series, P(t) tables and the 2020 baseline.

    D20 (Task 9): P(t) tables use the dispatched solar series from `solar_basis.dispatched_from` on (config, required). `dispatched_monthly`
    is built from the ONS capacity-factor files (cached) unless the caller supplies it.
    """
    targets = targets or load_acquisition_targets()
    ons_cfg = targets["ons"]
    pkg_cfg = ons_cfg["packages"]["generation_by_source"]
    client = client or CkanClient(ons_cfg["ckan_base_url"])

    info, resources = discover_generation_package(client, pkg_cfg)
    floor = date.fromisoformat(str(pkg_cfg["min_coverage_start"]))
    history_start = int(pkg_cfg.get("history_start_year", floor.year))
    if history_start > floor.year:
        raise ValidationError(f"history_start_year ({history_start}) is later than the coverage floor year ({floor.year}).")
    selected = select_yearly_resources(resources, pkg_cfg.get("preferred_formats", ["PARQUET", "CSV", "XLSX"]), min_year=history_start)
    first_year = int(YEARLY_NAME_PATTERN.match(selected[0].name).group("year"))
    logger.info("generation coverage floor: %s; earliest yearly resource: %d", floor, first_year)
    CkanClient.enforce_min_coverage(date(first_year, 1, 1), floor)  # fail fast, before any download

    raw_dir = get_raw_dir("ons/generation_by_source")
    frames = []
    for res in selected:
        dest = fetch_and_cache(res.url, raw_dir / f"{res.name}.{res.format.lower()}", use_cache=use_cache)
        frames.append(parse_generation_frame(_read_table(dest, res.format), label=res.name))
    tidy = pd.concat(frames, ignore_index=True)

    earliest, latest = min(tidy["date"]), max(tidy["date"])
    logger.info("generation coverage found: %s -> %s (%d rows, %d resources)", earliest, latest, len(tidy), len(selected))
    CkanClient.enforce_min_coverage(earliest, floor)
    if BASELINE_YEAR >= latest.year + 1:
        raise ValidationError(f"Generation series ends {latest}, before the {BASELINE_YEAR} baseline year.")

    basis_cfg = pkg_cfg.get("solar_basis") or {}
    dispatched_from = basis_cfg.get("dispatched_from")
    if not dispatched_from:
        raise ValidationError("config ons.packages.generation_by_source.solar_basis.dispatched_from is required (D20: val_gersolar is never the calibration basis).")
    if dispatched_monthly is None:
        from curtailmit.ons_solar_gap import build_dispatched_monthly

        solar = tidy[tidy["source_type"] == "solar"]
        balance_solar_mw = solar.set_index(pd.to_datetime(solar["timestamp"]))["generation_mwh"]  # hourly samples: MWh == MW
        dispatched_monthly = build_dispatched_monthly(client, balance_solar_mw, first_year=pd.Period(dispatched_from, freq="M").year, use_cache=True)

    interim_path = get_interim_dir() / INTERIM_FILENAME
    tidy.to_parquet(interim_path, index=False)
    processed = get_processed_dir()
    monthly = compute_penetration(tidy, "monthly", dispatched_monthly, dispatched_from)
    annual = compute_penetration(tidy, "annual", dispatched_monthly, dispatched_from)
    monthly.to_parquet(processed / MONTHLY_FILENAME, index=False)
    annual.to_parquet(processed / ANNUAL_FILENAME, index=False)
    baseline = extract_baseline_2020(tidy)
    baseline_path = processed / BASELINE_FILENAME
    write_baseline_json(baseline, baseline_path, info.resolved_package_id)

    info.n_years_downloaded, info.n_rows = len(selected), len(tidy)
    info.earliest_date, info.latest_date = earliest.isoformat(), latest.isoformat()
    logger.info("FINAL package_id=%s (fallback=%s)", info.resolved_package_id, info.used_fallback_search)
    return {
        "interim_path": str(interim_path),
        "monthly_path": str(processed / MONTHLY_FILENAME),
        "annual_path": str(processed / ANNUAL_FILENAME),
        "baseline_path": str(baseline_path),
        "package": info.model_dump(),
    }
