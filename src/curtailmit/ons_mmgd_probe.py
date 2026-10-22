"""Task 6B - does the ONS balance solar series (`val_gersolar`) include distributed generation (MMGD)?

Discovery and verification only: nothing here is wired into data_ingestion / calibration / projection.

Three things live here, all reusing existing building blocks (CkanClient, acquisition.fetch_and_cache,
ons_classification.fetch_data_dictionary - no new HTTP logic apart from the ONS load API, which also goes through fetch_and_cache):
1. `check_package_dictionary`: reads a package's JSON data dictionary and package notes and returns the VERBATIM definitions and
   any sentence mentioning MMGD / "geracao distribuida" / estimad / centralizad / usina. `states_mmgd_included` is True only if the
   definition of a requested field or the package notes literally mention MMGD / geracao distribuida - silence is reported as silence.
2. `discover_candidates`: package_search over candidate queries, one assessment per package with a documented, deterministic
   accept/reject reason (not a time series at source or plant level, nothing about wind/solar/capacity/distributed generation, ...).
3. Acquisition of the two usable series found (only small, schema-verified windows): the plant-level hourly capacity factor of
   ONS-dispatched wind/solar plants (`fator-capacidade-2`) and the verified-load API with the estimated MMGD component
   (`carga-energia-verificada`), plus `dispatched_vs_balanco` to compare dispatched (centralized) solar with the balance series.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from curtailmit.acquisition import fetch_and_cache
from curtailmit.ons_classification import fetch_data_dictionary
from curtailmit.ons_client import CkanClient, ResourceInfo
from curtailmit.paths import get_raw_dir
from curtailmit.schemas import DictionaryCheck

logger = logging.getLogger(__name__)

KEYWORDS = ("mmgd", "geracao distribuida", "estimad", "centralizad", "usina")
MMGD_TERMS = ("mmgd", "geracao distribuida", "micro e minigeracao", "mini e micro")
DEFAULT_QUERIES = ("fator de capacidade", "geracao distribuida", "MMGD", "geracao solar distribuida", "capacidade instalada usina", "geracao eolica solar fator")
CF_PACKAGE = "fator-capacidade-2"
CF_REQUIRED_COLUMNS = ("din_instante", "nom_tipousina", "nom_usina_conjunto", "id_ons", "val_geracaoverificada", "val_capacidadeinstalada", "val_fatorcapacidade")
MMGD_API_URL = "https://apicarga.ons.org.br/prd/cargaverificada"
MMGD_REQUIRED_FIELDS = ("cod_areacarga", "dat_referencia", "din_referenciautc", "val_cargaglobal", "val_cargammgd")
_TIME_FIELDS = ("din_instante", "dat_referencia", "din_referencia", "din_referenciautc", "dat_programacao")  # registry dates such as dat_entradaoperacao do not count
_ENTITY_TOKENS = ("usina", "id_ons", "ceg", "areacarga", "subsistema", "conjunto")
_TOPIC_TERMS = ("fator de capacidade", "capacidade instalada", "fotovolt", "solar", "eolic", "mmgd", "geracao distribuida", "distribuida")
_DATA_FORMATS = ("PARQUET", "CSV", "XLSX", "API")


class ProbeError(RuntimeError):
    """Raised when a probed dataset does not have the expected schema."""


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode().lower()


# ------------------------------------------------------------------ Part A: dictionary check


def scan_keywords(text: str, keywords: tuple[str, ...] = KEYWORDS) -> list[str]:
    haystack = _norm(text)
    return [k for k in keywords if k in haystack]


def check_package_dictionary(client: CkanClient, package_id: str, fields: list[str], raw_subdir: str, keywords: tuple[str, ...] = KEYWORDS) -> DictionaryCheck:
    """Verbatim definitions of `fields` plus every dictionary entry / note sentence matching `keywords`."""
    package = client.package_show(package_id)
    notes = str(package.get("notes") or "")
    resources = CkanClient.resources_from_package(package)
    modified = {r.name: (r.last_modified or "") for r in resources if r.format.upper() == "PARQUET" and r.last_modified}
    fetched = fetch_data_dictionary(client, package_id, raw_subdir, label=package_id)
    entries, url = fetched if fetched else ([], None)
    by_code = {str(e.get("codigo", "")): str(e.get("descricao", "")) for e in entries}
    definitions = {f: by_code[f] for f in fields if f in by_code}
    for name, text in definitions.items():
        logger.info("[%s] %s (verbatim): %s  <- %s", package_id, name, text, url)
    for f in fields:
        if f not in by_code:
            logger.warning("[%s] field %s is not described in the dictionary", package_id, f)

    hits: list[dict[str, str]] = []
    for code, text in by_code.items():
        matched = scan_keywords(f"{code} {text}", keywords)
        if matched:
            hits.append({"where": f"dictionary field {code}", "text": text, "keywords": ",".join(matched)})
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", notes):
        matched = scan_keywords(sentence, keywords) if sentence.strip() else []
        if matched:
            hits.append({"where": "package notes", "text": sentence.strip(), "keywords": ",".join(matched)})
    for h in hits:
        logger.info("[%s] keyword hit in %s (%s): %s", package_id, h["where"], h["keywords"], h["text"])

    scope_text = " ".join(list(definitions.values()) + [notes])
    states_mmgd = any(term in _norm(scope_text) for term in MMGD_TERMS)
    states_centralized = "centralizad" in _norm(" ".join(definitions.values()))
    return DictionaryCheck(
        package_id=package_id, dictionary_url=url, package_notes=notes, field_definitions=definitions, keyword_hits=hits,
        resource_last_modified=modified, states_mmgd_included=states_mmgd, states_centralized_only=states_centralized,
    )


# ------------------------------------------------------------------ Part B: candidate discovery


@dataclass
class CandidateAssessment:
    package_id: str
    title: str
    formats: list[str]
    apparent_range: str
    fields: list[str] = field(default_factory=list)
    sample_schema: list[str] = field(default_factory=list)
    accepted: bool = False
    reason: str = ""


def _apparent_range(resources: list[ResourceInfo]) -> str:
    stamps = sorted(m.group(0) for r in resources if (m := re.search(r"(19|20)\d{2}(?:[-_](0[1-9]|1[0-2]))?", r.name)))
    return f"{stamps[0]}..{stamps[-1]}" if stamps else "n/a (single/undated resources)"


def assess_candidate(package: dict, fields: list[str]) -> tuple[bool, str]:
    """Documented rules: needs a data resource; a time column AND an entity (plant/area/subsystem) column; a topic match."""
    resources = CkanClient.resources_from_package(package)
    if not any(r.format.upper() in _DATA_FORMATS for r in resources):
        return False, "no data resource (only documents)"
    lowered = [f.lower() for f in fields]
    if not fields:
        return False, "no machine-readable data dictionary: schema cannot be verified"
    if not any(f in lowered for f in _TIME_FIELDS):
        return False, "not a time series: no timestamp column (static registry or table)"
    if not any(token in f for f in lowered for token in _ENTITY_TOKENS):
        return False, "not at source or plant level: no plant/area/subsystem identifier"
    topical = _norm(f"{package.get('title', '')} {package.get('notes', '')} {' '.join(lowered)}")
    if not any(t in topical for t in _TOPIC_TERMS):
        return False, "off-topic: nothing about capacity factor, wind/solar generation, capacity or distributed generation"
    return True, "time series with entity ids and a wind/solar/capacity/distributed-generation topic"


def discover_candidates(client: CkanClient, queries: tuple[str, ...] = DEFAULT_QUERIES, read_samples: bool = True) -> list[CandidateAssessment]:
    """package_search over `queries`; one logged assessment (accept/reject + reason) per distinct package."""
    packages: dict[str, dict] = {}
    for query in queries:
        found = client.package_search(query)
        logger.info("ONS package_search q='%s' -> %d packages", query, len(found))
        for pkg in found:
            packages.setdefault(pkg["name"], pkg)
    out: list[CandidateAssessment] = []
    for name, pkg in sorted(packages.items()):
        resources = CkanClient.resources_from_package(pkg)
        fetched = fetch_data_dictionary(client, name, f"ons/probe_dictionaries/{name}", label=name)
        fields = [str(e.get("codigo", "")) for e in fetched[0]] if fetched else []
        accepted, reason = assess_candidate(pkg, fields)
        item = CandidateAssessment(
            package_id=name, title=str(pkg.get("title", "")), formats=sorted({r.format.upper() for r in resources if r.format}),
            apparent_range=_apparent_range(resources), fields=fields, accepted=accepted, reason=reason,
        )
        if accepted and read_samples:
            item.sample_schema = _sample_schema(resources, name)
        out.append(item)
        logger.info("%s candidate %s | %s | formats=%s | range=%s | %d fields | %s", "ACCEPT" if accepted else "REJECT", name, item.title, item.formats, item.apparent_range, len(fields), reason)
        if item.sample_schema:
            logger.info("   sample schema: %s", item.sample_schema)
    return out


def _sample_schema(resources: list[ResourceInfo], package_id: str) -> list[str]:
    """Column names of the latest PARQUET resource (downloaded via fetch_and_cache); API-only packages report their request URL."""
    parquet = [r for r in resources if r.format.upper() == "PARQUET"]
    if not parquet:
        api = [r for r in resources if r.format.upper() == "API"]
        return [f"API only (no bulk files): {api[0].name}"] if api else []
    latest = max(parquet, key=lambda r: r.last_modified or "")
    dest = fetch_and_cache(latest.url, get_raw_dir(f"ons/probe_samples/{package_id}") / f"{latest.name}.parquet", use_cache=True)
    return list(pq.read_schema(dest).names)


# ------------------------------------------------------------------ Part C: acquisition (schema-verified windows only)


def verify_capacity_factor_schema(columns: list[str]) -> None:
    missing = [c for c in CF_REQUIRED_COLUMNS if c not in columns]
    if missing:
        msg = f"Capacity-factor resource schema changed: missing {missing}; found {columns}"
        logger.error(msg)
        raise ProbeError(msg)


def verify_mmgd_api_schema(records: list[dict]) -> None:
    if not records:
        raise ProbeError("ONS verified-load API returned no records.")
    missing = [f for f in MMGD_REQUIRED_FIELDS if f not in records[0]]
    if missing:
        msg = f"Verified-load API schema changed: missing {missing}; found {sorted(records[0])}"
        logger.error(msg)
        raise ProbeError(msg)


def acquire_capacity_factor_months(client: CkanClient, months: list[str], use_cache: bool = False) -> dict[str, Path]:
    """Download the plant-level hourly capacity-factor file of each 'YYYY-MM' into raw/ons/capacity_factor (schema verified)."""
    resources = CkanClient.resources_from_package(client.package_show(CF_PACKAGE))
    out: dict[str, Path] = {}
    for month in months:
        match = [r for r in resources if r.name.endswith(f"-{month}") and r.format.upper() == "PARQUET"]
        if len(match) != 1:
            raise ProbeError(f"Expected exactly one PARQUET resource for {month} in '{CF_PACKAGE}', found {len(match)}.")
        dest = fetch_and_cache(match[0].url, get_raw_dir("ons/capacity_factor") / f"{match[0].name}.parquet", use_cache=use_cache)
        verify_capacity_factor_schema(pq.read_schema(dest).names)
        out[month] = Path(dest)
        logger.info("capacity factor %s -> %s", month, dest)
    return out


def acquire_mmgd_load(areas: list[str], start: str, end: str, use_cache: bool = False) -> dict[str, Path]:
    """Verified-load API (semi-hourly) per load area into raw/ons/mmgd. Note: area 'SIN' returns zeros (probed); use N/NE/S/SE."""
    import json

    out: dict[str, Path] = {}
    for area in areas:
        dest = fetch_and_cache(
            MMGD_API_URL, get_raw_dir("ons/mmgd") / f"cargaverificada_{area}_{start}_{end}.json",
            params={"dat_inicio": start, "dat_fim": end, "cod_areacarga": area}, use_cache=use_cache,
        )
        records = json.loads(Path(dest).read_text(encoding="utf-8-sig"))
        verify_mmgd_api_schema(records)
        out[area] = Path(dest)
        logger.info("MMGD/load API %s %s..%s -> %d records", area, start, end, len(records))
    return out


# ------------------------------------------------------------------ comparison


def dispatched_vs_balanco(cf: pd.DataFrame, balanco_solar_mw: pd.Series, source: str = "solar") -> pd.DataFrame:
    """Daily mean MWmed of ONS-dispatched plants (capacity-factor file) vs the balance series, and their difference."""
    verify_capacity_factor_schema(list(cf.columns))
    tipo = cf["nom_tipousina"].map(_norm)
    mask = tipo.str.startswith("solar") if source == "solar" else tipo.str.startswith("eol")
    dispatched = pd.to_numeric(cf.loc[mask, "val_geracaoverificada"], errors="coerce").groupby(cf.loc[mask, "din_instante"]).sum()
    balance = balanco_solar_mw.reindex(dispatched.index)
    frame = pd.DataFrame({"dispatched_mwmed": dispatched, "balanco_mwmed": balance})
    frame["difference_mwmed"] = frame["balanco_mwmed"] - frame["dispatched_mwmed"]
    return frame.resample("D").mean()
