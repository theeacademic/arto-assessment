"""Kenya population pipeline: WorldPop age-sex rasters aggregated to GADM boundaries.

Package layout:
    config       constants shared by every stage (URLs, age bands, file paths)
    data_access  programmatic discovery and cached download of source files
    validation   file, spatial and data-quality checks; writes the validation log
    aggregation  zonal sums per polygon, derived indicators, output CSV
    utils        small shared helpers
    pipeline     command-line entry point that runs the stages in order
"""
