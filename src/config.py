"""Constants shared by every stage of the pipeline.

Values here are facts about the source data and the required outputs. Anything that
is still an open decision is left as None with the question written next to it, so
that the choice is made deliberately in one place rather than implied by code.
"""

from pathlib import Path
from typing import Final

# --- Paths -------------------------------------------------------------------
# Resolved from this file so the pipeline runs from any working directory.
PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
RAW_DIR: Final[Path] = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR: Final[Path] = PROJECT_ROOT / "data" / "processed"
FIGURES_DIR: Final[Path] = PROJECT_ROOT / "outputs" / "figures"

PROCESSED_CSV_PATH: Final[Path] = PROCESSED_DIR / "kenya_population_by_county.csv"
VALIDATION_LOG_PATH: Final[Path] = PROCESSED_DIR / "validation_log.txt"

# --- Source data -------------------------------------------------------------
COUNTRY_ISO3: Final[str] = "KEN"
YEARS: Final[tuple[int, ...]] = (2021, 2022, 2023, 2024, 2025)

# WorldPop "Individual countries 2015-2030 (1km resolution) R2025A v1". This is the
# dataset whose path matches the "(1km_ua/constrained)" hint in the spec; note that
# the spec's prose says "unconstrained", which is the contradiction still open below.
WORLDPOP_REST_URL: Final[str] = (
    "https://hub.worldpop.org/rest/data/age_structures/G2_CN_Age_R25A_1km"
)
WORLDPOP_URL_TEMPLATE: Final[str] = (
    "https://data.worldpop.org/GIS/AgeSex_structures/Global_2015_2030/R2025A"
    "/{year}/{iso3_upper}/v1/1km_ua/constrained"
    "/{iso3_lower}_{sex}_{age}_{year}_CN_1km_R2025A_UA_v1.tif"
)

# Filename fields. WorldPop publishes 20 age bands x 3 sex codes = 60 files per year.
# Band "00" is ages 0-1 and band "01" is ages 1-4; "90" is the open-ended 90+ band.
AGE_BANDS: Final[tuple[str, ...]] = (
    "00", "01", "05", "10", "15", "20", "25", "30", "35", "40",
    "45", "50", "55", "60", "65", "70", "75", "80", "85", "90",
)
SEX_CODES: Final[tuple[str, ...]] = ("f", "m", "t")  # female, male, total

# Every combination above is checked for existence, but only these are downloaded.
DOWNLOAD_SEX_CODES: Final[tuple[str, ...]] = ("f", "m")

# Parallel transfer settings. Measured single-stream throughput to data.worldpop.org
# was ~89 KB/s; eight concurrent streams reached ~562 KB/s, so the download is
# parallelised. Without this, 200 files would take roughly an hour.
MAX_DOWNLOAD_WORKERS: Final[int] = 8
REQUEST_TIMEOUT_SECONDS: Final[int] = 60

GADM_URL: Final[str] = (
    "https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_KEN_2.json.zip"
)
TARGET_CRS: Final[str] = "EPSG:4326"

# --- Required output schema --------------------------------------------------
# Column order is fixed by the spec and must not be changed.
CSV_COLUMNS: Final[tuple[str, ...]] = (
    "county",
    "year",
    "total_population",
    "children_under_5",
    "working_age",
    "elderly_65plus",
    "sex_ratio",
    "dependency_ratio",
    "child_dependency_ratio",
    "elderly_dependency_ratio",
    "pct_children",
    "pct_elderly",
)

# --- Open decisions ----------------------------------------------------------
# These are unset on purpose. Each one changes what the pipeline produces, so each
# is a decision for the author to make before Stage 2 writes any real code.

# DECIDED (Stage 2): the output CSV reports the 47 counties, which are GADM's NAME_1
# field. The bundled gadm41_KEN_2.json holds 300 features of TYPE_2 "Constituency",
# so aggregation dissolves level-2 polygons up to NAME_1. This follows the spec's
# "all 47 counties" and its "county" column name rather than its "Level 2 (Counties)"
# label, which is wrong about what GADM level 2 contains.
COUNTY_NAME_FIELD: Final[str] = "NAME_1"
EXPECTED_COUNTY_COUNT: Final[int] = 47

# Which age bands make up each summary indicator, given the band codes above.
CHILDREN_UNDER_5_BANDS: Final[tuple[str, ...] | None] = None
WORKING_AGE_BANDS: Final[tuple[str, ...] | None] = None
ELDERLY_65PLUS_BANDS: Final[tuple[str, ...] | None] = None

# DECIDED (Stage 2): totals are summed from the "m" and "f" rasters. The published
# "t" rasters are still checked for existence (see DOWNLOAD_SEX_CODES) but are not
# downloaded, which saves 100 files of transfer on a slow connection.
TOTAL_POPULATION_SOURCE: Final[str] = "m+f"

# Does the dashboard get a second long-format CSV (county x year x sex x age band)?
# The required schema above carries neither sex nor age band, so the sex toggle and
# the age pyramid cannot be built from it alone.
LONG_FORMAT_CSV_PATH: Final[Path | None] = None
