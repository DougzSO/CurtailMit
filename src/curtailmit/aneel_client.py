"""Task 6 - ANEEL open data as a SECONDARY / FALLBACK source for generation-by-source. NOT the default path.

This module is not called by the default Stage 1 pipeline. It must be invoked explicitly, after a documented ONS failure
(CoverageError / ValidationError / schema mismatch in Task 3), and the caller must pass the reason, which is logged as a
WARNING ("fallback invoked") so the fallback is never silent. Do not re-probe ANEEL for curtailment: Task 2B already
searched it (13 queries) and found none.

What ANEEL can and cannot give (probed live 2026-10-21, see config/acquisition_targets.yaml `aneel.generation_fallback`):
ANEEL's CKAN publishes NO energy-generation (MWh) series by source for the SIN. The usable source-level data is the
plant registry SIGA (`siga-empreendimentos-geracao`): installed capacity by generation type with the date each plant entered
operation. The fallback therefore returns INSTALLED CAPACITY (MW) by source and year-end, and the capacity shares derived from
it. These are labelled `quantity = "installed_capacity_mw"` and `is_generation_energy = False` in every row: they are NOT a
drop-in for the ONS generation-based P(t) (that would need capacity factors, which this module deliberately does not invent).
SIGA lists only plants currently in operation, so past years are cumulative by `DatEntradaOperacao` and understate historical
capacity by whatever was retired since (survivorship); distributed micro/mini generation (MMGD) is a separate registry and is
not included.

Package choice uses a documented, deterministic heuristic (`score_candidate`): every candidate returned by package_search is
logged with its score and signals; the winner must also pass a schema check on the downloaded file, which is the real guard.
"""

from __future__ import annotations

import logging
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from curtailmit.acquisition import fetch_and_cache
from curtailmit.ons_client import CkanClient, ResourceInfo
from curtailmit.paths import get_interim_dir, get_raw_dir
from curtailmit.schemas import AneelFallbackChoice

logger = logging.getLogger(__name__)

OUTPUT_FILENAME = "aneel_fallback_capacity_by_source.parquet"
DEFAULT_QUERIES = ("geracao usina", "geracao fonte", "capacidade instalada geracao")
DEFAULT_HINT = "empreendimentos-geracao"
REQUIRED_COLUMNS = ("SigTipoGeracao", "DscFaseUsina", "DatEntradaOperacao", "MdaPotenciaFiscalizadaKw")
# SIGA generation-type codes -> the source_type names used by the ONS series (ons_generation.py).
TYPE_MAP = {"UFV": "solar", "EOL": "eolica", "UHE": "hidraulica", "PCH": "hidraulica", "CGH": "hidraulica", "UTE": "termica", "UTN": "termica"}
_RECENT_DAYS = 400


class AneelFallbackError(RuntimeError):
    """Raised when the ANEEL fallback cannot be discovered, parsed or validated."""


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode().lower()


def _data_resources(pkg: dict) -> list[ResourceInfo]:
    return [r for r in CkanClient.resources_from_package(pkg) if r.format.upper() in ("CSV", "PARQUET")]


def score_candidate(pkg: dict, resource_hint: str = DEFAULT_HINT, now: datetime | None = None) -> tuple[int, list[str]]:
    """Documented heuristic. Returns (score, signals); a package without a CSV/PARQUET data resource scores -100.

    +3 a data resource is named like the plant registry (`resource_hint`);  +2 'siga' in the package name/title;
    +1 'geracao' in the title;  +1 modified in the last ~400 days;  -5 flagged as discontinued ('descontinuado');
    -3 distributed micro/mini generation registry ('distribuida'/'mmgd': different scope, not the plant registry).
    """
    now = now or datetime.now(timezone.utc)
    signals: list[str] = []
    data = _data_resources(pkg)
    if not data:
        return -100, ["no CSV/PARQUET data resource"]
    score = 0
    haystack = _norm(f"{pkg.get('name', '')} {pkg.get('title', '')}")
    if any(resource_hint in _norm(r.name) for r in data):
        score += 3
        signals.append(f"+3 data resource named like '{resource_hint}'")
    if "siga" in haystack:
        score += 2
        signals.append("+2 'siga' in name/title")
    if "geracao" in _norm(pkg.get("title", "")):
        score += 1
        signals.append("+1 'geracao' in title")
    modified = pkg.get("metadata_modified")
    if modified:
        try:
            when = datetime.fromisoformat(str(modified).replace("Z", "+00:00"))
            when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
            if now - when <= timedelta(days=_RECENT_DAYS):
                score += 1
                signals.append("+1 modified recently")
        except ValueError:
            pass
    if "descontinuado" in haystack:
        score -= 5
        signals.append("-5 discontinued")
    if "distribuida" in haystack or "mmgd" in haystack:
        score -= 3
        signals.append("-3 distributed (MMGD) registry")
    return score, signals


def discover_generation_package(client: CkanClient, cfg: dict | None = None, now: datetime | None = None) -> tuple[AneelFallbackChoice, ResourceInfo]:
    """package_search over the candidate queries, log every candidate, choose by score, log why the others lost."""
    cfg = cfg or {}
    queries = tuple(cfg.get("queries", DEFAULT_QUERIES))
    hint = cfg.get("resource_name_hint", DEFAULT_HINT)
    candidates: dict[str, dict] = {}
    for query in queries:
        results = client.package_search(query)
        logger.info("ANEEL package_search q='%s' -> %d packages", query, len(results))
        for pkg in results:
            candidates.setdefault(pkg["name"], pkg)
    if not candidates:
        msg = f"ANEEL package_search returned no candidates for queries {queries}."
        logger.error(msg)
        raise AneelFallbackError(msg)

    scored = {name: score_candidate(pkg, hint, now) for name, pkg in candidates.items()}
    ranked = sorted(scored, key=lambda n: (-scored[n][0], n))
    for name in ranked:
        score, signals = scored[name]
        logger.info("  candidate %-70s score=%4d  %s", name, score, "; ".join(signals) or "no signals")
    best = ranked[0]
    best_score = scored[best][0]
    if best_score < 3:
        msg = f"No ANEEL candidate looks like a generation registry (best '{best}' scored {best_score}); refusing to guess."
        logger.error(msg)
        raise AneelFallbackError(msg)
    tied = [n for n in ranked if scored[n][0] == best_score]
    if len(tied) > 1:
        logger.warning("Tie at score %d among %s - choosing '%s' (alphabetical)", best_score, tied, best)
    rejected = {n: f"score {scored[n][0]} < {best_score} ({'; '.join(scored[n][1]) or 'no signals'})" for n in ranked[1:]}
    resources = [r for r in _data_resources(candidates[best]) if hint in _norm(r.name)]
    if not resources:
        raise AneelFallbackError(f"Package '{best}' has no data resource matching '{hint}' (resources: {[r.name for r in candidates[best].get('resources', [])]}).")
    resource = max(resources, key=lambda r: r.last_modified or "")  # most current extract (e.g. the daily one) wins
    logger.info("ANEEL fallback package chosen: '%s' (score %d), resource '%s' (%s, modified %s)", best, best_score, resource.name, resource.format, resource.last_modified)
    for name, why in rejected.items():
        logger.info("  rejected %s: %s", name, why)
    choice = AneelFallbackChoice(
        queries=list(queries), package_id=best, title=candidates[best].get("title", ""), score=best_score, resource_name=resource.name,
        resource_format=resource.format.upper(), n_candidates=len(candidates), rejected=rejected,
    )
    return choice, resource


def parse_siga_plants(raw: pd.DataFrame) -> pd.DataFrame:
    """Operating plants with [source_type, capacity_mw, entry_year]; fails explicitly if the schema changed."""
    missing = [c for c in REQUIRED_COLUMNS if c not in raw.columns]
    if missing:
        msg = f"ANEEL registry schema changed: missing {missing}; found {list(raw.columns)}"
        logger.error(msg)
        raise AneelFallbackError(msg)
    operating = raw[raw["DscFaseUsina"].map(_norm).str.startswith("opera")].copy()
    unknown = sorted(set(operating["SigTipoGeracao"].dropna().astype(str)) - set(TYPE_MAP))
    if unknown:
        raise AneelFallbackError(f"Unmapped generation types in the ANEEL registry: {unknown} (known: {sorted(TYPE_MAP)}) - refusing to drop capacity silently.")
    entry = pd.to_datetime(operating["DatEntradaOperacao"], errors="coerce")
    if entry.isna().any():
        raise AneelFallbackError(f"{int(entry.isna().sum())} operating plants have no valid DatEntradaOperacao - cannot place them in time.")
    capacity_kw = pd.to_numeric(operating["MdaPotenciaFiscalizadaKw"], errors="coerce")
    if capacity_kw.isna().any():
        raise AneelFallbackError(f"{int(capacity_kw.isna().sum())} operating plants have a non-numeric MdaPotenciaFiscalizadaKw.")
    return pd.DataFrame({"source_type": operating["SigTipoGeracao"].astype(str).map(TYPE_MAP), "capacity_mw": capacity_kw / 1000.0, "entry_year": entry.dt.year})


def capacity_by_source(plants: pd.DataFrame, years: list[int]) -> pd.DataFrame:
    """Cumulative installed capacity (MW) per source at the end of each requested year, plus shares of the total."""
    first = int(plants["entry_year"].min())
    too_early = [y for y in years if y < first]
    if too_early:
        raise AneelFallbackError(f"Years {too_early} precede the first plant entering operation in the registry ({first}).")
    rows = []
    for year in sorted(set(years)):
        in_service = plants[plants["entry_year"] <= year]
        by_source = in_service.groupby("source_type")["capacity_mw"].sum()
        total = float(by_source.sum())
        for source_type in sorted(set(TYPE_MAP.values())):
            mw = float(by_source.get(source_type, 0.0))
            rows.append({"year": year, "source_type": source_type, "installed_capacity_mw": mw, "capacity_share_pct": 100 * mw / total if total else 0.0})
    out = pd.DataFrame(rows)
    out["quantity"] = "installed_capacity_mw"
    out["is_generation_energy"] = False
    out["source"] = "aneel_siga_operating_plants_cumulative"
    return out


def fetch_generation_fallback(
    years: list[int],
    reason: str,
    targets: dict | None = None,
    client: CkanClient | None = None,
    use_cache: bool = False,
    write: bool = False,
) -> tuple[pd.DataFrame, AneelFallbackChoice]:
    """Fallback entry point. `reason` (required) states which ONS step failed and is logged as a WARNING.

    Returns (capacity table, discovery record). The table is installed capacity, NOT generation energy (see module docstring).
    """
    if not reason or not reason.strip():
        raise ValueError("fetch_generation_fallback requires an explicit `reason` (the documented ONS failure); it must never run silently.")
    from curtailmit.data_ingestion import load_acquisition_targets  # local import: keeps this module independent of the default path

    logger.warning("ANEEL FALLBACK INVOKED (not the default path). Reason: %s", reason)
    targets = targets or load_acquisition_targets()
    aneel_cfg = targets["aneel"]
    client = client or CkanClient(aneel_cfg["ckan_base_url"])
    choice, resource = discover_generation_package(client, aneel_cfg.get("generation_fallback"))
    dest = fetch_and_cache(resource.url, get_raw_dir("aneel/generation_fallback") / f"{resource.name}", use_cache=use_cache)
    if choice.resource_format == "PARQUET":
        raw = pd.read_parquet(dest)
    else:
        raw = pd.read_csv(Path(dest), sep=";", encoding="utf-8-sig", decimal=",", low_memory=False)
    table = capacity_by_source(parse_siga_plants(raw), years)
    logger.warning("ANEEL fallback returned INSTALLED CAPACITY by source for %s - not generation energy; it cannot replace the ONS P(t) without a capacity-factor assumption.", sorted(set(years)))
    if write:
        path = get_interim_dir() / OUTPUT_FILENAME
        table.to_parquet(path, index=False)
        logger.info("Wrote %s", path)
    return table, choice
