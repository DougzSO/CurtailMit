# Pre-submission checklist (DeCarbon article)

Items that must be closed by a person before the article is submitted. Each one is something the code and tests cannot settle. Open items stay listed until someone ticks them with a date and a source.

## 1. ONS and MCTI terms of use / redistribution licensing - NOT VERIFIED

- [ ] **Verify manually, before submission, that publishing `data_snapshot_manifest.json` complies with the actual terms of the ONS open-data portal and of the MCTI / gov.br pages.**

**Status (Task 15, 2026-10-27).** The terms of use and redistribution licensing of the ONS and MCTI datasets were **not formally verified**. Two web searches (ONS open-data terms; MCTI emission-factor licence) returned no explicit terms and no explicit prohibition. That is absence of evidence, not evidence of absence: it does **not** show that the use is permitted.

**What exactly has to be checked.**
1. Whether a manifest that lists only the file path, source URL, retrieval time (UTC), byte size and SHA-256 of each file (no content) is compliant with the ONS and MCTI terms. This is what decision D33 (option 1) commits to the public repository (`data_snapshot_manifest.json`, 250 files at Task 15, 254 since Task 17 with the GADM boundary files).
2. Whether the data-availability statement planned for the article (code and hashes public, data re-downloadable from the cited sources, no copy hosted) is compliant.
3. Whether attribution or citation wording is required for ONS and MCTI data in the article.
4. If either body forbids even the manifest, D33 must be revisited (code-only is the fallback), and the manifest removed from the repository and its history as needed.

**Where this connects.** Decision D33 (`config/discovered_sources.yaml`); `docs/reproducibility.md` section 1 ("Data availability"); `data_snapshot_manifest.json`; the data-availability statement that the article still needs (not drafted).

## 2. Data-availability statement in the article

- [ ] Write the statement citing `data_snapshot_manifest.json` and the verification procedure (`python -m curtailmit.run_manifest verify`; `docs/reproducibility.md` section 3). Not drafted in Task 15.


## 3. GADM boundary licence (decision D36) - NOT VERIFIED

- [ ] **Verify manually, before submission, the GADM licence terms for the boundary geometry used by the context maps (C1, C1S).** To the project's reading, GADM permits academic and other non-commercial use and does not permit redistribution without permission; the licence page was not re-read by the tooling.

**Status (Task 17, 2026-10-28).** The shapefile `gadm41_BRA_1.shp` (GADM 4.1 level 1, with `.dbf` / `.prj` / `.cpg`) is kept **only** in `curtailmit_database/raw/boundaries/gadm/` and is **not** committed to the public repository; the repository holds only its SHA-256 and size in `data_snapshot_manifest.json` (decision D33 pattern) and a small synthetic geometry fixture for tests. What to settle: (1) whether publishing the figures drawn from the geometry (the maps) is within the terms, (2) the required attribution wording for GADM in the article, (3) that nothing derived from the geometry beyond the figures is redistributed.

**Where this connects.** Decision D36 (`config/discovered_sources.yaml`); `docs/task17_design.md`; the same treatment as the ONS / MCTI item of section 1.
