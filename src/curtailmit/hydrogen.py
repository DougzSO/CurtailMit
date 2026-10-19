"""Stage 5 - green hydrogen valorization potential.

Per docs/methodology.md Section 2.6:
    H2_potential(s,t) = E_curt(s,t) / SEC
with SEC in [50, 55] kWh/kg H2, central estimate 52.5 kWh/kg H2.
Always reported as a range (min/central/max), never a single point.
"""

from __future__ import annotations

import pandas as pd

from curtailmit.schemas import HydrogenRow

TWH_TO_KWH = 1e9


def compute_hydrogen_potential(
    mitigation_df: pd.DataFrame,
    sec_min: float,
    sec_central: float,
    sec_max: float,
) -> pd.DataFrame:
    """mitigation_df must contain [scenario, year, E_curt_twh].

    Note: SEC is inversely related to H2 output - a LOWER SEC (kWh/kg) yields
    MORE H2 per unit of energy, so h2_max corresponds to sec_min, and vice-versa.
    """
    for required_col in ("scenario", "year", "E_curt_twh"):
        if required_col not in mitigation_df.columns:
            raise ValueError(f"mitigation_df missing required column '{required_col}'")

    if not (sec_min <= sec_central <= sec_max):
        raise ValueError("Require sec_min <= sec_central <= sec_max.")

    df = mitigation_df.copy()
    energy_kwh = df["E_curt_twh"] * TWH_TO_KWH

    df["h2_potential_max_kg"] = energy_kwh / sec_min
    df["h2_potential_central_kg"] = energy_kwh / sec_central
    df["h2_potential_min_kg"] = energy_kwh / sec_max

    out_cols = ["scenario", "year", "h2_potential_min_kg", "h2_potential_central_kg", "h2_potential_max_kg"]
    result = df[out_cols].copy()

    for row in result.itertuples(index=False):
        HydrogenRow(**row._asdict())

    return result
