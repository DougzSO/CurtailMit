# Known Limitations

This document tracks confirmed, non-obvious limitations discovered
during data source exploration, so they are not silently rediscovered
or endlessly re-probed by future work (human or Claude Code).

## CCEE Dados Abertos — not accessible via automated means (CLOSED)

- **Source**: https://dadosabertos.ccee.org.br/
- **Status**: Confirmed blocked.
- **Evidence**: Two independent probes returned HTTP 403 with a generic
  "Acesso bloqueado" WAF/CDN challenge page, on both the root URL and
  the `api/3/action/package_list` CKAN endpoint:
    1. Plain `requests.get()` with default headers.
    2. Retry with a realistic browser `User-Agent` and `Accept-Language`
       header.
- **Conclusion**: This is a CDN/WAF-level block, not a CKAN permission
  issue or a fixable request-header problem. No further automated
  access attempts are planned.
- **Impact**: PLD (Preco de Liquidacao das Diferencas) remains an
  optional, disabled-by-default module (`pld.enabled: false`, decision
  D10). See `src/curtailmit/pld.py`. If PLD is required in a future
  version, the only viable path is manual download, isolated in
  `manual_ingestion.py` and explicitly logged as a limitation — never
  silently mixed into the automated pipeline.