"""Command-line entry point: runs access, validation and aggregation in order.

Run with:
    python src/pipeline.py

Sequence (Stage 2 and Stage 3 fill this in):
    1. data_access   fetch the WorldPop rasters and GADM boundaries into data/raw,
                     reusing anything already cached.
    2. validation    run the file, spatial and data-quality checks and write
                     data/processed/validation_log.txt.
    3. aggregation   zonal sums, derived indicators, and the output CSV at
                     data/processed/kenya_population_by_county.csv.
    4. figures       the three static plots the spec asks for, into outputs/figures.

The dashboard is launched separately and reads only the outputs of this pipeline.
"""
