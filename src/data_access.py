"""Programmatic discovery and cached download of the source data.

Responsibilities (Stage 2):
    - Resolve the WorldPop GeoTIFF URLs for Kenya for each year in YEARS, either
      from the WorldPop REST API or by constructing them from WORLDPOP_URL_TEMPLATE.
      The spec forbids downloading files by hand.
    - Download each file to RAW_DIR only if it is not already cached there, so that
      re-running the pipeline during development costs no network time.
    - Fetch the GADM Kenya boundary file to RAW_DIR under the same caching rule.
    - Return the local paths of everything fetched, for validation to inspect.

No repair or substitution happens here: a file that cannot be fetched is reported
to the caller and recorded in the validation log, never silently skipped.
"""
