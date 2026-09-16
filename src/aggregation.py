"""Zonal aggregation of rasters to polygons, and the derived indicators.

Responsibilities (Stage 3):
    - Sum raster pixel values within each admin polygon, for every age band, sex and
      year, producing one population total per polygon-age-sex-year combination.
    - Build the ten indicators the spec names, using the band groupings agreed in
      config (children under 5, working age, elderly 65+, total, sex ratio, the three
      dependency ratios, and the two percentage shares).
    - Write the result to PROCESSED_CSV_PATH in the exact column order the spec
      specifies in CSV_COLUMNS.

Division-by-zero in the ratio indicators is reported, not silently coerced.
"""
