"""Task 6C - measure the `val_gersolar` vs dispatched-solar gap as a monthly time series.

Standalone analysis (NOT wired into ons_generation / data_ingestion / calibration / projection). It reuses:
- `ons_mmgd_probe` (package id, required schema, `solar_mask` filter shared with the Task 6B 4-month comparison),
- `CkanClient` + `acquisition.fetch_and_cache` for the plant-level hourly capacity-factor files (`fator-capacidade-2`).

Pieces:
1. `list_capacity_factor_resources` / `acquire_capacity_factor_range`: every PARQUET resource from 2021 on (2021 is one yearly
   file `Fator_Capacidade-2021`, 2022+ are monthly `Fator_Capacidade_2-YYYY-MM`); the schema of each is compared with the
   reference schema and every difference is logged and returned (never coerced, never silently skipped).
2. `aggregate_dispatched_solar`: hourly SIN-level sum of the solar plants -> monthly MWmed / GWh.
3. `compare_with_balanco`: gap = val_gersolar - dispatched solar, over the SAME hours present in the capacity-factor file.
4. `analyse_gap`: the quantities asked for in Task 6C (first non-trivial month, flat/growing/volatile, 2024 sum vs RT ONS 0189/2025).
"""

from __future__ import annotations

import calendar
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from curtailmit.acquisition import fetch_and_cache
from curtailmit.ons_client import CkanClient, ResourceInfo
from curtailmit.ons_mmgd_probe import CF_PACKAGE, CF_REQUIRED_COLUMNS, ProbeError, solar_mask
from curtailmit.paths import get_raw_dir

logger = logging.getLogger(__name__)

RT_MMGD_2024_GWH = 45_752.0  # RT ONS DGL 0189/2025, section 4.3 (p. 16)
_MONTHLY = re.compile(r"-(\d{4}-\d{2})$")
_YEARLY = re.compile(r"-(\d{4})$")


@dataclass
class SchemaFinding:
    label: str
    missing_required: list[str] = field(default_factory=list)
    columns_added: list[str] = field(default_factory=list)
    columns_removed: list[str] = field(default_factory=list)
    type_changes: dict[str, str] = field(default_factory=dict)

    @property
    def identical(self) -> bool:
        return not (self.missing_required or self.columns_added or self.columns_removed or self.type_changes)

    @property
    def usable(self) -> bool:
        return not self.missing_required


def label_of(resource_name: str) -> str:
    """'Fator_Capacidade_2-2024-06' -> '2024-06'; 'Fator_Capacidade-2021' -> '2021' (yearly file)."""
    m = _MONTHLY.search(resource_name)
    if m:
        return m.group(1)
    y = _YEARLY.search(resource_name)
    if y:
        return y.group(1)
    raise ProbeError(f"Cannot derive a period from capacity-factor resource name '{resource_name}'.")


def list_capacity_factor_resources(resources: list[ResourceInfo], first_year: int = 2021) -> dict[str, ResourceInfo]:
    """One PARQUET resource per period label (yearly 'YYYY' or monthly 'YYYY-MM') from `first_year`; duplicates are an error."""
    out: dict[str, ResourceInfo] = {}
    for r in resources:
        if r.format.upper() != "PARQUET" or not r.name.startswith("Fator_Capacidade"):
            continue
        label = label_of(r.name)
        if int(label[:4]) < first_year:
            continue
        if label in out:
            raise ProbeError(f"Two PARQUET resources for capacity-factor period {label}: {out[label].name} and {r.name}.")
        out[label] = r
    if not out:
        raise ProbeError(f"No PARQUET capacity-factor resources from {first_year} on in package '{CF_PACKAGE}'.")
    return dict(sorted(out.items()))


def schema_findings(label: str, schema: dict[str, str], reference: dict[str, str]) -> SchemaFinding:
    f = SchemaFinding(label=label)
    f.missing_required = [c for c in CF_REQUIRED_COLUMNS if c not in schema]
    f.columns_added = sorted(set(schema) - set(reference))
    f.columns_removed = sorted(set(reference) - set(schema))
    f.type_changes = {c: f"{reference[c]} -> {schema[c]}" for c in schema if c in reference and schema[c] != reference[c]}
    if f.identical:
        logger.debug("schema %s identical to reference", label)
    else:
        logger.warning("SCHEMA DIFFERENCE %s: missing_required=%s added=%s removed=%s type_changes=%s", label, f.missing_required, f.columns_added, f.columns_removed, f.type_changes)
    return f


def read_schema(path: Path) -> dict[str, str]:
    s = pq.read_schema(path)
    return {n: str(s.field(n).type) for n in s.names}


def acquire_capacity_factor_range(client: CkanClient, first_year: int = 2021, reference_path: Path | None = None, use_cache: bool = True) -> tuple[dict[str, Path], list[SchemaFinding]]:
    """Download (or reuse the cached) capacity-factor files from `first_year` on; return {label: path} and one SchemaFinding per file.

    The reference schema is the Task 6B-verified one (the already-cached 2022-12 file unless `reference_path` is given).
    """
    resources = list_capacity_factor_resources(CkanClient.resources_from_package(client.package_show(CF_PACKAGE)), first_year)
    raw = get_raw_dir("ons/capacity_factor")
    ref_path = reference_path or raw / "Fator_Capacidade_2-2022-12.parquet"
    reference = read_schema(ref_path)
    paths: dict[str, Path] = {}
    findings: list[SchemaFinding] = []
    for label, res in resources.items():
        dest = Path(fetch_and_cache(res.url, raw / f"{res.name}.parquet", use_cache=use_cache))
        paths[label] = dest
        findings.append(schema_findings(label, read_schema(dest), reference))
        logger.info("capacity factor %s -> %s", label, dest.name)
    return paths, findings


def aggregate_dispatched_solar_file(path: Path) -> pd.Series:
    """Hourly SIN sum (MW) of solar plants of one capacity-factor file, indexed by timestamp. Same filter as Task 6B (`solar_mask`)."""
    cf = pd.read_parquet(path, columns=["din_instante", "nom_tipousina", "val_geracaoverificada"])
    cf["din_instante"] = pd.to_datetime(cf["din_instante"])
    mask = solar_mask(cf)
    gen = pd.to_numeric(cf.loc[mask, "val_geracaoverificada"], errors="coerce")
    return gen.groupby(cf.loc[mask, "din_instante"]).sum(min_count=1).rename("dispatched_mw")


def aggregate_dispatched_solar(paths: dict[str, Path]) -> pd.Series:
    """Hourly dispatched solar (MW) across all files (duplicated timestamps across files are an error, not silently summed)."""
    parts = [aggregate_dispatched_solar_file(p) for _label, p in sorted(paths.items())]
    hourly = pd.concat(parts)
    if hourly.index.duplicated().any():
        raise ProbeError(f"Duplicated hourly timestamps across capacity-factor files: {hourly.index[hourly.index.duplicated()][:5].tolist()}")
    return hourly.sort_index()


def compare_with_balanco(dispatched_hourly: pd.Series, balanco_solar_mw: pd.Series) -> pd.DataFrame:
    """Monthly table over the hours present in BOTH series.

    dispatched_mwmed / balanco_mwmed are means over the matched hours; *_gwh scale that mean to the full calendar month
    (mean MW x hours in month / 1000), so months with missing hours stay comparable. `coverage` = matched hours / hours in month.
    """
    both = pd.DataFrame({"dispatched_mw": dispatched_hourly, "balanco_mw": balanco_solar_mw.reindex(dispatched_hourly.index)})
    unmatched = both["balanco_mw"].isna().sum()
    if unmatched:
        logger.warning("%d dispatched hours have no val_gersolar value in the balance series and are excluded", unmatched)
    both = both.dropna()
    g = both.groupby(both.index.to_period("M"))
    m = pd.DataFrame({"dispatched_mwmed": g["dispatched_mw"].mean(), "balanco_mwmed": g["balanco_mw"].mean(), "hours": g.size()})
    m["hours_in_month"] = [calendar.monthrange(p.year, p.month)[1] * 24 for p in m.index]
    m["coverage"] = m["hours"] / m["hours_in_month"]
    m["dispatched_gwh"] = m["dispatched_mwmed"] * m["hours_in_month"] / 1000
    m["balanco_gwh"] = m["balanco_mwmed"] * m["hours_in_month"] / 1000
    m["gap_gwh"] = m["balanco_gwh"] - m["dispatched_gwh"]
    m["gap_mwmed"] = m["balanco_mwmed"] - m["dispatched_mwmed"]
    m["gap_pct_of_balanco"] = 100 * m["gap_gwh"] / m["balanco_gwh"]
    return m


def daily_gap(dispatched_hourly: pd.Series, balanco_solar_mw: pd.Series) -> pd.Series:
    """Daily mean gap (MWmed) over the hours present in both series."""
    both = pd.DataFrame({"d": dispatched_hourly, "b": balanco_solar_mw.reindex(dispatched_hourly.index)}).dropna()
    return (both["b"] - both["d"]).resample("D").mean().dropna().rename("gap_mwmed")


def find_step_day(daily: pd.Series, month: str, margin_days: int = 31) -> tuple[pd.Timestamp, float, float]:
    """Day with the largest day-over-day increase of the daily gap inside `month` +/- `margin_days` -> (day, gap that day, gap the day before).

    The window is needed because isolated ONS data glitches elsewhere (e.g. 2024-11-09, see report) have larger one-day jumps.
    """
    start = pd.Period(month).start_time - pd.Timedelta(days=margin_days)
    end = pd.Period(month).end_time + pd.Timedelta(days=margin_days)
    window = daily[start:end]
    day = window.diff().idxmax()
    return day, float(daily.loc[day]), float(daily.shift(1).loc[day])


def glitch_days(daily: pd.Series, after: str, below_mwmed: float) -> pd.Series:
    """Days after `after` whose gap falls back below `below_mwmed` (i.e. the balance looks like dispatched-only)."""
    d = daily[pd.Timestamp(after):]
    return d[d < below_mwmed]


@dataclass
class GapAnalysis:
    first_pct_above_threshold_month: str | None  # absolute rule: gap > trivial_pct of val_gersolar for 4 months running
    first_nontrivial_month: str | None  # relative rule: gap_mwmed > 2x the mean of the previous 12 months, sustained 3 more months
    pre_step_baseline_mwmed: float  # median gap over the 12 months before the step
    pre_step_gap_pct_min: float  # over the months from the first absolute-rule month until the step
    pre_step_gap_pct_max: float
    pre_step_gap_mwmed_min: float
    pre_step_gap_mwmed_max: float
    post_step_gap_mwmed_first12: float
    post_gap_trend_mwmed_per_year: float
    post_gap_cv: float
    post_character: str
    gap_2024_gwh: float
    gap_2024_baseline_adjusted_gwh: float
    gap_2024_months: int
    rt_ratio_2024: float
    rt_ratio_2024_adjusted: float
    rt_tolerance_pct: float
    rt_consistent: bool


def analyse_gap(m: pd.DataFrame, trivial_pct: float = 5.0, rt_gwh: float = RT_MMGD_2024_GWH, rt_tolerance_pct: float = 10.0, min_coverage: float = 0.9) -> GapAnalysis:
    """Task 6C quantities, on months with coverage >= `min_coverage` (the last, partial month is excluded).

    Two definitions of 'non-trivial' are reported because the gap is not zero before the step (non-dispatched plants, see report):
    - absolute: gap > `trivial_pct` % of val_gersolar in 4 consecutive months;
    - relative (the one used for the step): gap_mwmed more than twice the mean of the previous 12 months AND still above that in the next 3 months
      (needs 12 months of history, so the first possible month is the 13th of the series).
    The 2024 sum is the mean MWmed x 8784 h (2024 is a leap year). `rt_tolerance_pct` is chosen by the caller: the known confounder is the
    pre-step baseline (~100 MWmed ~ 0.9 TWh ~ 2 % of 45.75 TWh) plus the model uncertainty of ONS's own estimate; 10 % is ~5x the known confounder.
    """
    m = m[m["coverage"] >= min_coverage]
    pct, gap = m["gap_pct_of_balanco"], m["gap_mwmed"]
    first_abs = next((str(p) for i, p in enumerate(m.index) if len(pct.iloc[i : i + 4]) == 4 and (pct.iloc[i : i + 4] > trivial_pct).all()), None)
    first_rel = None
    for i in range(12, len(m)):
        base = gap.iloc[i - 12 : i].mean()
        if (gap.iloc[i : i + 4] > 2 * base).all() and len(gap.iloc[i : i + 4]) == 4:
            first_rel = str(m.index[i])
            break
    step = pd.Period(first_rel) if first_rel else None
    pre = m[m.index < step] if step is not None else m
    post = m[m.index >= step] if step is not None else m.iloc[0:0]
    pre_abs = pre[pre.index >= pd.Period(first_abs)] if first_abs else pre
    baseline = float(pre.iloc[-12:]["gap_mwmed"].median()) if len(pre) else float("nan")
    y24 = m[m.index.year == 2024]
    gap24 = float(y24["gap_mwmed"].mean() * 8784 / 1000) if len(y24) else float("nan")
    gap24_adj = float((y24["gap_mwmed"].mean() - baseline) * 8784 / 1000) if len(y24) else float("nan")
    ratio, ratio_adj = gap24 / rt_gwh, gap24_adj / rt_gwh
    if len(post) >= 6:
        x = (post.index.year + (post.index.month - 1) / 12).to_numpy(dtype=float)
        slope = float(((x - x.mean()) * (post["gap_mwmed"].to_numpy() - post["gap_mwmed"].mean())).sum() / ((x - x.mean()) ** 2).sum())
        cv = float(post["gap_mwmed"].std() / post["gap_mwmed"].mean())
        first12 = float(post["gap_mwmed"].iloc[:12].mean())
        change_pct = 100 * slope * (len(post) / 12) / post["gap_mwmed"].mean()
        character = "growing" if change_pct > 25 else ("declining" if change_pct < -25 else ("volatile" if cv > 0.35 else "roughly flat"))
    else:
        slope = cv = first12 = float("nan")
        character = "insufficient post-step months"
    return GapAnalysis(
        first_pct_above_threshold_month=first_abs, first_nontrivial_month=first_rel, pre_step_baseline_mwmed=baseline,
        pre_step_gap_pct_min=float(pre_abs["gap_pct_of_balanco"].min()) if len(pre_abs) else float("nan"),
        pre_step_gap_pct_max=float(pre_abs["gap_pct_of_balanco"].max()) if len(pre_abs) else float("nan"),
        pre_step_gap_mwmed_min=float(pre_abs["gap_mwmed"].min()) if len(pre_abs) else float("nan"),
        pre_step_gap_mwmed_max=float(pre_abs["gap_mwmed"].max()) if len(pre_abs) else float("nan"),
        post_step_gap_mwmed_first12=first12, post_gap_trend_mwmed_per_year=slope, post_gap_cv=cv, post_character=character,
        gap_2024_gwh=gap24, gap_2024_baseline_adjusted_gwh=gap24_adj, gap_2024_months=len(y24),
        rt_ratio_2024=ratio, rt_ratio_2024_adjusted=ratio_adj, rt_tolerance_pct=rt_tolerance_pct,
        rt_consistent=bool(len(y24) == 12 and abs(ratio - 1) * 100 <= rt_tolerance_pct and abs(ratio_adj - 1) * 100 <= rt_tolerance_pct),
    )


def write_monthly(m: pd.DataFrame, path: Path) -> Path:
    """Persist the monthly dispatched-solar / val_gersolar / gap table (standalone analysis output, interim/)."""
    out = m.copy()
    out.index = out.index.astype(str)
    out.index.name = "month"
    out.reset_index().to_parquet(path, index=False)
    logger.info("Wrote %s (%d months)", path, len(out))
    return path
