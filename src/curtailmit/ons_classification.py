"""Task 4 - curtailment classification (D5/D6): ONS restriction-reason codes -> DEB / REB / EUB.

The ONS COFF resources carry `cod_razaorestricao`; the official ONS data dictionary (a JSON resource of the same
CKAN package) defines the codes in free text, e.g. "REL - Razao de indisponibilidade externa (eletrica). CNF - Razao de
atendimento a requisitos de confiabilidade. ENE - Razao energetica. PAR - Restricao indicada no parecer de acesso".

Two documented steps, both config-driven (config/acquisition_targets.yaml, `classification`):
1. code -> D5 label: derived AT RUN TIME from the live dictionary text via `dictionary_keywords` (never hardcoded).
2. D5 label -> category: the existing `classification.mapping` (Razao Energetica -> DEB, Confiabilidade -> REB,
   Indisponibilidade Externa -> EUB; EUB is its own category and is never merged).

Documented codes that match no D5 label (e.g. PAR) are NOT forced into a category: those rows get a null
`deb_reb_eub` and stay in the aggregate. A code that is not in the dictionary at all is schema drift and raises.
If the classification cannot be established (no dictionary, no code column, nothing mappable), D6 applies:
`classification_available = False`, no classified field is written, and the aggregate remains fully usable.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from curtailmit.acquisition import fetch_and_cache
from curtailmit.ons_client import CkanClient
from curtailmit.paths import get_interim_dir, get_processed_dir, get_raw_dir
from curtailmit.validation import ClassificationFlag, attach_classification_flag, validate_classification_propagation

logger = logging.getLogger(__name__)

CLASSIFIED_FILENAME = "ons_curtailment_classified.parquet"
FLAG_FILENAME = "classification_available.json"
REASON_FIELD = "cod_razaorestricao"
CLASSIFIED_COLUMN = "deb_reb_eub"
_CATEGORIES = ("DEB", "REB", "EUB")
_SOURCE_KEYS = {"wind": "curtailment_wind", "solar": "curtailment_solar"}
# ONS dictionary text is partly published with replacement characters (U+FFFD) where dashes/accents should be.
_CODE_PATTERN = re.compile(r"\b([A-Z]{3})\s*[-–—�]\s+")


class ClassificationError(RuntimeError):
    """Raised on schema drift that must not be silently absorbed (e.g. a reason code missing from the dictionary)."""


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def parse_reason_code_dictionary(description: str) -> dict[str, str]:
    """Split a dictionary description such as '... REL - texto. CNF - texto.' into {code: text}."""
    matches = list(_CODE_PATTERN.finditer(description))
    codes: dict[str, str] = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(description)
        codes[m.group(1)] = description[m.end():end].strip(" .;\r\n\t")
    return codes


def derive_code_crosswalk(codes: dict[str, str], classification_cfg: dict) -> dict[str, str | None]:
    """{code: D5 label or None}, matching each code's dictionary text against `dictionary_keywords`."""
    keywords = classification_cfg["dictionary_keywords"]
    labels = set(classification_cfg["mapping"])
    unknown_labels = set(keywords) - labels
    if unknown_labels:
        raise ClassificationError(f"dictionary_keywords labels {sorted(unknown_labels)} are not in classification.mapping {sorted(labels)}")
    crosswalk: dict[str, str | None] = {}
    for code, text in codes.items():
        haystack = _normalize(text)
        hits = [label for label, stems in keywords.items() if any(_normalize(s) in haystack for s in stems)]
        if len(hits) > 1:
            raise ClassificationError(f"Dictionary text for code {code} matches several D5 labels {hits}: {text!r}")
        crosswalk[code] = hits[0] if hits else None
        logger.info("crosswalk %s -> %s  (dictionary: %r)", code, crosswalk[code] or "UNMAPPED (no D5 label)", text)
    return crosswalk


def fetch_data_dictionary(client: CkanClient, package_id: str, raw_subdir: str, label: str = "") -> tuple[list[dict], str] | None:
    """Download a package's JSON data dictionary (via fetch_and_cache, so a retrieval manifest is written) and return
    (entries, source_url), where entries are the `dicionario_simplificado` items {codigo, descricao}.

    Returns None if the package has no JSON dictionary resource. Network/HTTP errors propagate.
    """
    resources = CkanClient.resources_from_package(client.package_show(package_id))
    candidates = [r for r in resources if r.format.upper() == "JSON" and "dicion" in _normalize(r.name)]
    if not candidates:
        logger.warning("[%s] package '%s' has no JSON data-dictionary resource (resources: %s)", label or package_id, package_id, [r.name for r in resources])
        return None
    dest = fetch_and_cache(candidates[0].url, get_raw_dir(raw_subdir) / "data_dictionary.json")
    payload = json.loads(Path(dest).read_text(encoding="utf-8-sig", errors="replace"))
    return list(payload.get("dicionario_simplificado", [])), candidates[0].url


def fetch_reason_code_dictionary(client: CkanClient, package_id: str, source: str) -> dict[str, str] | None:
    """Download the package's JSON data dictionary and return its parsed {code: text} for cod_razaorestricao.

    Returns None (classification unavailable, D6) if the package has no JSON dictionary or it does not describe the field.
    Network/HTTP errors propagate - they are not evidence that classification is unavailable.
    """
    fetched = fetch_data_dictionary(client, package_id, f"ons/curtailment_{source}", label=source)
    if fetched is None:
        return None
    entries, _url = fetched
    entry = next((e for e in entries if str(e.get("codigo", "")).lower() == REASON_FIELD), None)
    if entry is None:
        logger.warning("[%s] data dictionary does not describe %s", source, REASON_FIELD)
        return None
    codes = parse_reason_code_dictionary(str(entry.get("descricao", "")))
    logger.info("[%s] dictionary codes for %s: %s", source, REASON_FIELD, sorted(codes))
    return codes or None


def load_interim(path: Path) -> pd.DataFrame:
    """Read the interim series memory-safely (the real file has ~16M rows): strings as categoricals, dates as Arrow date32."""
    schema_names = pq.read_schema(path).names
    dict_cols = [c for c in ("usina", "reason_category", "source") if c in schema_names]
    table = pq.read_table(path, read_dictionary=dict_cols)
    return table.to_pandas(types_mapper={pa.date32(): pd.ArrowDtype(pa.date32())}.get)


def apply_classification(frame: pd.DataFrame, source_crosswalks: dict[str, dict[str, str | None]], classification_cfg: dict) -> pd.DataFrame:
    """Add `deb_reb_eub` (in place; returned for convenience) from the per-source code crosswalk.

    Raises on codes absent from the dictionary. `reason_category` and `source` are handled as categoricals so the
    work scales with the number of distinct values, not rows.
    """
    mapping = classification_cfg["mapping"]
    reason = frame["reason_category"].astype("category")
    reason = reason.cat.rename_categories(lambda c: str(c).strip().upper())
    frame["reason_category"] = reason
    source = frame["source"].astype("category")
    category_codes = np.full(len(frame), -1, dtype="int8")
    for src, crosswalk in source_crosswalks.items():
        rows = (source == src).to_numpy()
        present = set(reason[rows].dropna().unique())
        undocumented = sorted(present - set(crosswalk))
        if undocumented:
            msg = f"[{src}] reason codes {undocumented} are not described in the ONS data dictionary {sorted(crosswalk)} - schema drift, refusing to guess."
            logger.error(msg)
            raise ClassificationError(msg)
        for code, label in crosswalk.items():
            if label is not None:
                category_codes[rows & (reason == code).to_numpy()] = _CATEGORIES.index(mapping[label])
    frame[CLASSIFIED_COLUMN] = pd.Categorical.from_codes(category_codes, categories=list(_CATEGORIES))
    return frame


def _energy_breakdown(frame: pd.DataFrame, column: str) -> dict[str, float]:
    key = frame[column].astype("category")
    key = key.cat.add_categories("(none)").fillna("(none)")
    energy = frame["curtailed_energy_mwh"].groupby(key, observed=True).sum()
    return {str(k): round(float(v), 3) for k, v in energy.items()}


def _write_flag_file(path: Path, flag: ClassificationFlag, details: dict) -> None:
    payload = {
        "classification_available": flag.classification_available,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "reason": flag.reason or "Reason codes mapped to DEB/REB/EUB via the live ONS data dictionary and classification.mapping (D5).",
        **details,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Wrote %s (classification_available=%s)", path, flag.classification_available)


def _validate_records(frame: pd.DataFrame, flag: ClassificationFlag) -> None:
    """Hard propagation check (validation.py rules). The rules depend only on (classification_available, classified field),
    so the check runs on every distinct combination of those fields rather than on millions of identical dicts."""
    keys = ["source", CLASSIFIED_COLUMN] if CLASSIFIED_COLUMN in frame.columns else ["source"]
    combos = frame[keys].astype(object).drop_duplicates().astype(object).where(lambda d: d.notna(), None).to_dict("records")
    records = [attach_classification_flag(c, flag) for c in combos]
    validate_classification_propagation(records)  # a raise here is a real bug - deliberately not caught
    logger.info("classification propagation validated on %d distinct record shapes (%d rows)", len(records), len(frame))


def classify_ons_curtailment(
    targets: dict | None = None,
    client: CkanClient | None = None,
    interim_path: Path | None = None,
    package_ids: dict[str, str] | None = None,
) -> dict:
    """Task 4 entry point: classify interim/ons_curtailment_raw.parquet -> processed/ons_curtailment_classified.parquet."""
    from curtailmit.data_ingestion import load_acquisition_targets  # local import: data_ingestion lazily imports this module

    targets = targets or load_acquisition_targets()
    cls_cfg = targets["classification"]
    ons_cfg = targets["ons"]
    client = client or CkanClient(ons_cfg["ckan_base_url"])
    interim_path = interim_path or (get_interim_dir() / "ons_curtailment_raw.parquet")
    frame = load_interim(interim_path)
    logger.info("Loaded %d curtailment rows from %s; distinct reason_category per source: %s", len(frame), interim_path,
                {s: sorted(frame.loc[frame.source == s, "reason_category"].dropna().unique().tolist()) for s in frame.source.unique()})

    crosswalks: dict[str, dict[str, str | None]] = {}
    problems: list[str] = []
    for source in sorted(frame["source"].unique()):
        pkg_id = (package_ids or {}).get(source) or ons_cfg["packages"][_SOURCE_KEYS[source]]["package_id"]
        codes = fetch_reason_code_dictionary(client, pkg_id, source)
        if codes is None:
            problems.append(f"{source}: no usable ONS data-dictionary entry for {REASON_FIELD} in package '{pkg_id}'")
            continue
        crosswalk = derive_code_crosswalk(codes, cls_cfg)
        if not any(crosswalk.values()):
            problems.append(f"{source}: none of the dictionary codes {sorted(codes)} match a D5 label")
            continue
        crosswalks[source] = crosswalk

    processed = get_processed_dir()
    out_path = processed / CLASSIFIED_FILENAME
    details: dict = {"crosswalk": crosswalks, "rows": len(frame)}

    if problems or set(crosswalks) != set(frame["source"].unique()):
        reason = ("Classification unavailable (D6 fallback to the unclassified aggregate): " + "; ".join(problems)
                  + ". Checked: JSON data dictionary of each COFF package, field cod_razaorestricao, D5 label keywords.")
        logger.warning(reason)
        flag = ClassificationFlag(classification_available=False, reason=reason)
        result = frame
    else:
        flag = ClassificationFlag(classification_available=True)
        result = apply_classification(frame, crosswalks, cls_cfg)
        curtailed = result[result["curtailed_energy_mwh"] > 0]
        unmapped_mwh = float(curtailed.loc[curtailed[CLASSIFIED_COLUMN].isna(), "curtailed_energy_mwh"].sum())
        total_mwh = float(curtailed["curtailed_energy_mwh"].sum())
        details["energy_mwh_by_category"] = _energy_breakdown(curtailed, CLASSIFIED_COLUMN)
        details["energy_mwh_by_raw_code"] = _energy_breakdown(curtailed, "reason_category")
        details["unclassified_energy_share"] = round(unmapped_mwh / total_mwh, 6) if total_mwh else 0.0
        logger.info("%s value_counts (rows):\n%s", CLASSIFIED_COLUMN, result[CLASSIFIED_COLUMN].value_counts(dropna=False).to_string())
        logger.info("curtailed energy (MWh) by category: %s; unclassified share %.4f%%", details["energy_mwh_by_category"], 100 * details["unclassified_energy_share"])
        if unmapped_mwh:
            logger.warning("%.1f MWh (%.4f%%) of curtailed energy has no DEB/REB/EUB category (documented but unmapped code, or no code) - kept in the aggregate only",
                           unmapped_mwh, 100 * unmapped_mwh / total_mwh)

    result["classification_available"] = flag.classification_available
    if not flag.classification_available:
        result["classification_reason"] = flag.reason
    _validate_records(result, flag)
    result.to_parquet(out_path, index=False)
    flag_path = processed / FLAG_FILENAME
    _write_flag_file(flag_path, flag, details)
    return {"classification_available": flag.classification_available, "reason": flag.reason, "classified_path": str(out_path), "flag_path": str(flag_path), **details}
