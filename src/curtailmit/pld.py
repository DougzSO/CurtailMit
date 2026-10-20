"""
PLD (Preco de Liquidacao das Diferencas) module - OPTIONAL, non-blocking.

Per decision D10, PLD/CCEE integration is disabled by default and must
never block the main pipeline. CCEE's Dados Abertos portal
(https://dadosabertos.ccee.org.br/) was probed twice (including with
browser-like headers) and consistently returned HTTP 403 ("Acesso
bloqueado"), a CDN/WAF-level block unrelated to request headers or CKAN
permissions. See docs/limitations.md for details.

This module exists so the pipeline architecture supports PLD if the CCEE
access issue is ever resolved, without requiring changes elsewhere.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class PldDisabledError(Exception):
    """Raised if PLD data is requested while pld.enabled is false."""


def fetch_pld(enabled: bool = False) -> None:
    """
    Entry point for PLD data acquisition.

    Parameters
    ----------
    enabled:
        Must be explicitly set True by the caller (normally sourced from
        config/scenarios.yaml pld.enabled). Defaults to False, matching
        decision D10.

    Raises
    ------
    PldDisabledError
        If enabled=False (the default).
    NotImplementedError
        If enabled=True. CCEE's Dados Abertos portal is not accessible
        via automated means as of this writing (see docs/limitations.md),
        so this function has no working implementation yet even when
        explicitly enabled. A manual_ingestion.py-based fallback would be
        required to proceed.
    """
    if not enabled:
        raise PldDisabledError(
            "PLD module is disabled by default (pld.enabled=false, decision D10). "
            "Set enabled=True explicitly and implement a working CCEE access path "
            "before calling this function."
        )
    raise NotImplementedError(
        "CCEE Dados Abertos is not accessible via automated means as of this "
        "writing (HTTP 403 WAF block, confirmed on two separate probes). "
        "See docs/limitations.md. A manual_ingestion.py-based fallback would be "
        "required to proceed."
    )