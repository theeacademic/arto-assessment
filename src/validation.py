"""File, spatial and data-quality validation, and the validation log.

Responsibilities (Stage 2):
    - Parse each downloaded raster filename into (sex, age band, year) and check the
      parse against EXPECTED_COMBINATIONS, so missing or unexpected files are found.
    - Confirm the GADM boundaries are in TARGET_CRS and that the expected admin units
      are all present and named as GADM names them.
    - Confirm a sample raster's CRS, and report any mismatch with the boundaries
      rather than reprojecting on the quiet.
    - Screen raster values for negatives, for zeros where population is implausible,
      and for any other pattern worth a human's attention.
    - Write every finding to VALIDATION_LOG_PATH.

Nothing in this module repairs data. Each check reports what it found; the decision
about what to do with a finding is made by a person and recorded in the log.
"""
