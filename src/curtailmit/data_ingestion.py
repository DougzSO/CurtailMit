"""Stage 1 - data ingestion, discovery, and validation.

Order of operations:
1. Load + validate config/scenarios.yaml against schemas.py.
2. ONS discovery (curtailment wind/solar + generation by source) via CKAN.
3. Classification availability check + fallback decision (logged, never silent).
4. MCTI discovery (average + marginal emission factors).
5. Load 2026-2029 validation_data, kept separate from calibration_data.
6. Produce data-quality report.

Step 2 (ONS curtailment wind+solar) is implemented; steps 3-4 are still TODO skeletons,
with control flow, logging, and fail-explicit behavior already structured.
"""

from __future__ import annotations

import logging
import unicodedata
from datetime import date
from pathlib import Path

import pandas as pd
import requests
import yaml

from curtailmit.acquisition import fetch_and_cache
from curtailmit.ckan import MONTHLY_NAME_PATTERN
from curtailmit.ons_client import CkanClient, ResourceInfo
from curtailmit.paths import get_interim_dir, get_raw_dir
from curtailmit.schemas import CurtailmentPackageDiscovery, PipelineConfig
from curtailmit.validation import resolve_ons_min_coverage

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "scenarios.yaml"
ACQUISITION_TARGETS_PATH = Path(__file__).resolve().parents[2] / "config" / "acquisition_targets.yaml"


def load_config(path: Path = CONFIG_PATH) -> PipelineConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    config = PipelineConfig(
        year_grid=raw["year_grid"],
        interpolation_method=raw["interpolation_method"],
        baseline_2020=raw["baseline_2020"],
        pte_scenarios=raw["pte_scenarios"],
    )
    if not config.pte_scenarios.all_valid():
        raise ValueError("PTE table failed sanity check: solar_pct + wind_pct > 100 somewhere.")
    logger.info(
        "Config loaded and validated: %d scenarios, year_grid=%s",
        len(raw["pte_scenarios"]), config.year_grid,
    )
    return config


class CurtailmentDiscoveryError(RuntimeError):
    """Raised when an ONS curtailment package/resource cannot be discovered or parsed."""


_SOURCE_KEYS = {"wind": "curtailment_wind", "solar": "curtailment_solar"}
_SEARCH_QUERIES = {
    "wind": ("restricao coff eolica", "constrained off eolica"),
    "solar": ("restricao coff fotovoltaica", "constrained off fotovoltaica"),
}
_SOURCE_KEYWORDS = {"wind": ("eolic",), "solar": ("fotovolt", "solar")}

# Candidate column names in ONS COFF resources (schema is inspected, never assumed).
_TIMESTAMP_COLS = ("din_instante", "din_referenciautc", "data_hora", "dat_referencia")
_USINA_COLS = ("nom_usina", "nom_usina_conjunto", "nom_usinaconjunto", "nom_conjuntousina", "ceg", "id_ons")
_CURTAILED_MW_COL = "val_geracaonaorealizadaapurada"  # ONS-reported curtailed power; only populated on restricted intervals
_REFERENCE_COLS = ("val_geracaoreferenciafinal", "val_geracaoreferencia")
_GENERATION_COL = "val_geracao"
_REASON_COLS = ("cod_razaorestricao", "cod_origemrestricao")
_DEFAULT_INTERVAL_HOURS = 0.5

INTERIM_FILENAME = "ons_curtailment_raw.parquet"


def load_acquisition_targets(path: Path = ACQUISITION_TARGETS_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def _search_fallback(client: CkanClient, source: str) -> str:
    """Recovery path: package_search heuristic when the configured package_id no longer resolves."""
    keywords = _SOURCE_KEYWORDS[source]
    candidates: dict[str, str] = {}
    for query in _SEARCH_QUERIES[source]:
        results = client.package_search(query)
        logger.info("Fallback search q='%s' returned %d packages", query, len(results))
        for pkg in results:
            name = pkg.get("name", "")
            haystack = _normalize(f"{name} {pkg.get('title', '')}")
            logger.info("  candidate: %s | %s", name, pkg.get("title", ""))
            if "coff" in haystack and any(k in haystack for k in keywords):
                candidates.setdefault(name, pkg.get("title", ""))
    if not candidates:
        msg = f"Fallback package_search found no COFF {source} curtailment package (queries={_SEARCH_QUERIES[source]})."
        logger.error(msg)
        raise CurtailmentDiscoveryError(msg)
    chosen = next(iter(candidates))
    if len(candidates) > 1:
        logger.warning("Multiple fallback candidates for %s: %s - choosing '%s'", source, list(candidates), chosen)
    logger.info("Fallback chose package '%s' for %s curtailment", chosen, source)
    return chosen


def _warn_if_structure_changed(source: str, package: dict, resources: list[ResourceInfo], pkg_cfg: dict) -> None:
    """Defensive re-confirmation: WARN (never silently ignore) if the package drifted from the static config."""
    expected_title = pkg_cfg.get("title")
    if expected_title and package.get("title") != expected_title:
        logger.warning("[%s] package title changed: config=%r live=%r", source, expected_title, package.get("title"))
    preferred = [f.upper() for f in pkg_cfg.get("preferred_formats", [])]
    seen = sorted({r.format.upper() for r in resources if r.format})
    logger.info("[%s] resource formats seen: %s", source, seen)
    if preferred and not set(preferred) & set(seen):
        logger.warning("[%s] none of the preferred formats %s present (seen=%s)", source, preferred, seen)
    expected_prefix = pkg_cfg.get("resource_name_pattern", "").replace("-YYYY-MM", "")
    monthly = [m for m in (MONTHLY_NAME_PATTERN.match(r.name) for r in resources) if m]
    if not monthly:
        logger.warning("[%s] no resource matches the monthly '<prefix>-YYYY-MM' naming (expected prefix %r)", source, expected_prefix)
    elif expected_prefix and any(m.group("prefix") != expected_prefix for m in monthly):
        logger.warning("[%s] resource name prefix differs from configured %r", source, expected_prefix)


def discover_curtailment_package(client: CkanClient, source: str, pkg_cfg: dict) -> tuple[CurtailmentPackageDiscovery, list[ResourceInfo]]:
    """Re-confirm the configured package via package_show; fall back to package_search if it fails outright."""
    configured_id = pkg_cfg["package_id"]
    resolved_id, used_fallback = configured_id, False
    try:
        package = client.package_show(configured_id)
        logger.info("[%s] package_show('%s') OK: title=%r", source, configured_id, package.get("title"))
    except (requests.RequestException, RuntimeError) as exc:
        logger.warning("[%s] static config is STALE: package_show('%s') failed (%s) - falling back to package_search", source, configured_id, exc)
        resolved_id, used_fallback = _search_fallback(client, source), True
        package = client.package_show(resolved_id)
    resources = CkanClient.resources_from_package(package)
    _warn_if_structure_changed(source, package, resources, pkg_cfg)
    if used_fallback:
        logger.warning("[%s] discovered package_id='%s' differs from config '%s' - pin manually if desired", source, resolved_id, configured_id)
    info = CurtailmentPackageDiscovery(
        source=source,
        configured_package_id=configured_id,
        resolved_package_id=resolved_id,
        used_fallback_search=used_fallback,
        n_resources=len(resources),
        formats_seen=sorted({r.format.upper() for r in resources if r.format}),
    )
    return info, resources


def select_data_resources(resources: list[ResourceInfo], preferred_formats: list[str], min_month: tuple[int, int]) -> list[ResourceInfo]:
    """Pick one data resource per month (preferred format order), skipping docs and months before min_month.

    If no resource follows the monthly naming convention, falls back to the single most
    recently modified resource in a preferred format (logged as WARNING).
    """
    preferred = [f.upper() for f in preferred_formats]
    by_month: dict[tuple[int, int], list[ResourceInfo]] = {}
    for r in resources:
        m = MONTHLY_NAME_PATTERN.match(r.name)
        if not m:
            logger.info("Skipping non-monthly resource '%s' (%s)", r.name, r.format)
            continue
        by_month.setdefault((int(m.group("year")), int(m.group("month"))), []).append(r)

    selected: list[ResourceInfo] = []
    for key in sorted(by_month):
        if key < min_month:
            continue
        best = next((r for fmt in preferred for r in by_month[key] if r.format.upper() == fmt), None)
        if best is None:
            logger.warning("Month %04d-%02d has no resource in preferred formats %s (has %s)", key[0], key[1], preferred, [r.format for r in by_month[key]])
            continue
        selected.append(best)

    if not selected:
        usable = [r for r in resources if r.format.upper() in preferred]
        if not usable:
            msg = f"No data resources in preferred formats {preferred} among {len(resources)} resources."
            logger.error(msg)
            raise CurtailmentDiscoveryError(msg)
        newest = max(usable, key=lambda r: r.last_modified or "")
        logger.warning("No monthly-named resources; falling back to most recently modified: %s (%s)", newest.name, newest.last_modified)
        selected = [newest]
    logger.info("Selected %d data resources (first=%s, last=%s)", len(selected), selected[0].name, selected[-1].name)
    return selected


def _read_table(path: Path, fmt: str) -> pd.DataFrame:
    fmt = fmt.upper()
    if fmt == "PARQUET":
        return pd.read_parquet(path)
    if fmt in ("XLSX", "XLS"):
        return pd.read_excel(path)
    if fmt == "JSON":
        return pd.read_json(path)
    if fmt == "CSV":
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            header = f.readline()
        return pd.read_csv(path, sep=";" if header.count(";") > header.count(",") else ",", encoding="utf-8-sig", low_memory=False)
    raise CurtailmentDiscoveryError(f"Unsupported resource format '{fmt}' for {path}")


def _first_present(columns: list[str], candidates: tuple[str, ...]) -> str | None:
    return next((c for c in candidates if c in columns), None)


def parse_curtailment_frame(raw: pd.DataFrame, source: str) -> pd.DataFrame:
    """Normalise an ONS COFF resource to [timestamp, date, usina, curtailed_energy_mwh, reason_category, source].

    Curtailed power is ONS's own `val_geracaonaorealizadaapurada` (MW) when present - it is
    populated exactly on restricted intervals, so blanks mean "not curtailed" (verified
    against live 2022-01 data: non-null count == cod_razaorestricao non-null count). For
    schemas lacking it, it is derived as (reference generation - verified generation), clipped
    at 0 MW. Power is integrated to MWh using the sampling interval inferred from timestamps.
    """
    df = raw.copy()
    df.columns = [str(c).strip().lower() for c in raw.columns]
    cols = list(df.columns)
    ts_col, usina_col = _first_present(cols, _TIMESTAMP_COLS), _first_present(cols, _USINA_COLS)
    ref_col = _first_present(cols, _REFERENCE_COLS)
    has_direct = _CURTAILED_MW_COL in cols
    if not (ts_col and usina_col and (has_direct or (ref_col and _GENERATION_COL in cols))):
        msg = f"Cannot parse {source} curtailment: need timestamp/usina plus {_CURTAILED_MW_COL} or reference/{_GENERATION_COL} columns, found {cols}"
        logger.error(msg)
        raise CurtailmentDiscoveryError(msg)

    timestamp = pd.to_datetime(df[ts_col])
    if has_direct:
        curtailed_mw = pd.to_numeric(df[_CURTAILED_MW_COL], errors="coerce")
        logger.info("[%s] using %s; %d of %d intervals have no restriction reported (treated as 0 MWh)", source, _CURTAILED_MW_COL, int(curtailed_mw.isna().sum()), len(df))
        curtailed_mw = curtailed_mw.fillna(0.0)
    else:
        logger.warning("[%s] %s absent - deriving curtailment as %s - %s", source, _CURTAILED_MW_COL, ref_col, _GENERATION_COL)
        curtailed_mw = (pd.to_numeric(df[ref_col], errors="coerce") - pd.to_numeric(df[_GENERATION_COL], errors="coerce")).clip(lower=0)
    unique_ts = timestamp.drop_duplicates().sort_values()
    if len(unique_ts) >= 2:
        interval_h = unique_ts.diff().dropna().median().total_seconds() / 3600
    else:
        interval_h = _DEFAULT_INTERVAL_HOURS
        logger.warning("Only one timestamp in %s data - assuming %.1f h sampling interval", source, interval_h)

    reason_col = _first_present(cols, _REASON_COLS)
    out = pd.DataFrame(
        {
            "timestamp": timestamp,
            "date": timestamp.dt.date,
            "usina": df[usina_col].astype("string"),
            "curtailed_energy_mwh": curtailed_mw * interval_h,
            "reason_category": df[reason_col].astype("string") if reason_col else pd.Series(pd.NA, index=df.index, dtype="string"),
            "source": source,
        }
    )
    logger.info("[%s] parsed %d rows (interval=%.2f h, reason column=%s)", source, len(out), interval_h, reason_col)
    return out


def acquire_curtailment_source(client: CkanClient, source: str, pkg_cfg: dict, min_coverage: date, use_cache: bool = False) -> tuple[pd.DataFrame, CurtailmentPackageDiscovery]:
    """Discover, download, parse, and coverage-check one curtailment package."""
    info, resources = discover_curtailment_package(client, source, pkg_cfg)
    selected = select_data_resources(resources, pkg_cfg.get("preferred_formats", ["PARQUET", "CSV", "XLSX"]), (min_coverage.year, min_coverage.month))
    raw_dir = get_raw_dir(f"ons/curtailment_{source}")
    frames = []
    for res in selected:
        dest = fetch_and_cache(res.url, raw_dir / f"{res.name}.{res.format.lower()}", use_cache=use_cache)
        frames.append(parse_curtailment_frame(_read_table(dest, res.format), source))
        if len(frames) == 1:
            # Resources are sorted oldest-first: check coverage on the earliest file before downloading the rest (fail fast).
            first_date = min(frames[0]["date"])
            logger.info("[%s] earliest file %s starts at %s", source, res.name, first_date)
            CkanClient.enforce_min_coverage(first_date, min_coverage)
    data = pd.concat(frames, ignore_index=True)
    if data.empty:
        raise CurtailmentDiscoveryError(f"{source} curtailment resources parsed to zero rows.")

    earliest, latest = min(data["date"]), max(data["date"])
    logger.info("[%s] coverage found: %s -> %s (%d rows, %d resources)", source, earliest, latest, len(data), len(selected))
    CkanClient.enforce_min_coverage(earliest, min_coverage)  # CoverageError propagates by design
    info.n_months_downloaded, info.n_rows = len(selected), len(data)
    info.earliest_date, info.latest_date = earliest.isoformat(), latest.isoformat()
    return data, info


def acquire_ons_curtailment(targets: dict | None = None, client: CkanClient | None = None, use_cache: bool = False) -> dict:
    """Task 2 entry point: wind + solar curtailment -> DATABASE_ROOT/interim/ons_curtailment_raw.parquet."""
    targets = targets or load_acquisition_targets()
    ons_cfg = targets["ons"]
    client = client or CkanClient(ons_cfg["ckan_base_url"])

    frames, infos = [], []
    for source, key in _SOURCE_KEYS.items():
        pkg_cfg = ons_cfg["packages"][key]
        min_coverage = resolve_ons_min_coverage(source, pkg_cfg)  # per-package floor (D14)
        logger.info("[%s] coverage floor: %s", source, min_coverage)
        data, info = acquire_curtailment_source(client, source, pkg_cfg, min_coverage, use_cache=use_cache)
        frames.append(data)
        infos.append(info)
        logger.info("[%s] FINAL package_id=%s (fallback=%s)", source, info.resolved_package_id, info.used_fallback_search)

    combined = pd.concat(frames, ignore_index=True)
    out_path = get_interim_dir() / INTERIM_FILENAME
    combined.to_parquet(out_path, index=False)
    logger.info("Wrote %d rows (wind+solar) to %s", len(combined), out_path)
    return {"interim_path": str(out_path), "n_rows": len(combined), "packages": [i.model_dump() for i in infos]}


def discover_ons_resources(raw_config: dict | None = None) -> dict:
    """Run ONS curtailment discovery + acquisition (Task 2).

    `raw_config` is accepted for backward compatibility and ignored: acquisition_targets.yaml
    is the source of truth for confirmed package ids.
    """
    return acquire_ons_curtailment()


def check_classification_availability(raw_config: dict, discovered: dict) -> bool:
    """Task 4: classify the interim ONS curtailment series (see ons_classification.py) and return classification_available.

    Returns False (never raises) when the classified series is genuinely unavailable (D6 fallback, logged and written to
    processed/classification_available.json); schema drift such as undocumented reason codes does raise.
    """
    from curtailmit.ons_classification import classify_ons_curtailment

    package_ids = {p["source"]: p["resolved_package_id"] for p in discovered.get("packages", [])}
    interim = Path(discovered["interim_path"]) if discovered.get("interim_path") else None
    return classify_ons_curtailment(interim_path=interim, package_ids=package_ids)["classification_available"]


def discover_mcti_factors(raw_config: dict) -> dict:
    """Task 5: acquire MCTI average + margin (OM/BM/CM) emission factors (see mcti_client.py)."""
    from curtailmit.mcti_client import acquire_mcti_factors

    return acquire_mcti_factors()


def load_validation_data(raw_config: dict) -> dict:
    validation = raw_config.get("validation_data", {})
    if not validation.get("years"):
        logger.warning("validation_data is empty - fill from the v2 2026-2029 prospection table.")
    return validation


def run_stage1() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        raw_config = yaml.safe_load(f)

    config = load_config()
    discovered = discover_ons_resources(raw_config)
    classification_available = check_classification_availability(raw_config, discovered)
    mcti = discover_mcti_factors(raw_config)
    validation_data = load_validation_data(raw_config)

    report = {
        "config_valid": True,
        "classification_available": classification_available,
        "ons_discovered": discovered,
        "solar_curtailment_2020_baseline": "documented_zero_not_measured (D14: ONS solar curtailment starts 2024-04)",
        "mcti_discovered": mcti,
        "validation_data_loaded": bool(validation_data.get("years")),
    }
    logger.info("Stage 1 data-quality report: %s", report)
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_stage1()
