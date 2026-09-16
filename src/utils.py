"""Small helpers shared across the pipeline.

Expected to hold (as the later stages need them):
    - directory creation for the cache and output paths
    - a logger that writes to both the console and the validation log
    - formatting helpers used by more than one module

Anything that belongs to one stage only lives in that stage's module instead.
"""
