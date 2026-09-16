"""Check that the committed outputs match the claims made in the README.

Run from the repository root:

    python tests/test_reproducibility.py

This deliberately validates only what is committed -- the two CSVs and the GADM
boundary file -- so it runs on a fresh clone without downloading the ~300 MB of
rasters first. Checks that need the raster cache are skipped with a note when it is
absent, rather than failing.

Exits 0 if every check passes, 1 otherwise.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import config  # noqa: E402

RESULTS: list[tuple[str, str, str]] = []  # (status, name, detail)


def record(name: str, passed: bool, detail: str = "") -> None:
    """Record one check's outcome.

    Args:
        name: Short description of the check.
        passed: Whether it held.
        detail: Optional supporting numbers.
    """
    RESULTS.append(("PASS" if passed else "FAIL", name, detail))


def skip(name: str, reason: str) -> None:
    """Record a check that could not run.

    Args:
        name: Short description of the check.
        reason: Why it was skipped.
    """
    RESULTS.append(("SKIP", name, reason))


def check_schema(wide: pd.DataFrame) -> None:
    """The required CSV has the spec's exact columns, in order, with no gaps."""
    record("CSV columns match the spec exactly, in order",
           list(wide.columns) == list(config.CSV_COLUMNS),
           f"{len(wide.columns)} columns")
    record("235 rows: 47 counties x 5 years",
           len(wide) == 235 and wide["county"].nunique() == 47 and wide["year"].nunique() == 5,
           f"{len(wide)} rows, {wide['county'].nunique()} counties, {wide['year'].nunique()} years")
    record("No missing values anywhere in the required CSV",
           int(wide.isna().sum().sum()) == 0,
           f"{int(wide.isna().sum().sum())} nulls")
    numeric = wide.drop(columns=["county"])
    record("No negative values in any indicator",
           bool((numeric >= 0).all().all()))


def check_long_table(long: pd.DataFrame) -> None:
    """The long-format companion file is complete and evenly shaped."""
    expected = 47 * 5 * 2 * 20
    record("Long CSV has 9,400 rows (47 x 5 x 2 sexes x 20 bands)",
           len(long) == expected, f"{len(long)} rows, expected {expected}")
    record("Long CSV holds all 20 WorldPop age bands",
           sorted(long["age_band"].unique()) == sorted(config.AGE_BANDS),
           f"{long['age_band'].nunique()} bands")
    record("Long CSV is evenly split male/female",
           long[long["sex"] == "m"].shape[0] == long[long["sex"] == "f"].shape[0])


def check_counties(wide: pd.DataFrame) -> None:
    """All 47 counties are present, named as GADM names them."""
    boundary_path = config.RAW_DIR / "gadm41_KEN_2.json"
    if not boundary_path.exists():
        skip("County names match the GADM boundary file", "boundary file not present")
        return

    import json

    with boundary_path.open(encoding="utf-8") as handle:
        features = json.load(handle)["features"]
    gadm_names = {f["properties"][config.COUNTY_NAME_FIELD] for f in features}

    record("GADM file holds 300 level-2 features", len(features) == 300, f"{len(features)}")
    record("GADM file holds 47 distinct counties", len(gadm_names) == 47, f"{len(gadm_names)}")
    record("Every county in the CSV exists in the boundary file",
           set(wide["county"]) == gadm_names,
           f"{len(set(wide['county']) ^ gadm_names)} mismatched")


def check_band_groupings() -> None:
    """The indicator age bands partition the population as the README describes."""
    grouped = set(config.CHILDREN_UNDER_5_BANDS) | set(config.WORKING_AGE_BANDS) | set(config.ELDERLY_65PLUS_BANDS)
    uncovered = sorted(set(config.AGE_BANDS) - grouped)
    record("Only ages 5-14 fall outside the three indicator groups",
           uncovered == ["05", "10"], f"uncovered bands: {uncovered}")
    overlap = (
        len(config.CHILDREN_UNDER_5_BANDS) + len(config.WORKING_AGE_BANDS)
        + len(config.ELDERLY_65PLUS_BANDS) != len(grouped)
    )
    record("The three indicator groups do not overlap", not overlap)


def check_identity(wide: pd.DataFrame, long: pd.DataFrame) -> None:
    """Children + working age + elderly + ages 5-14 reconstructs the total."""
    middle = (
        long[long["age_band"].isin(["05", "10"])]
        .groupby(["county", "year"])["population"].sum()
    )
    indexed = wide.set_index(["county", "year"])
    rebuilt = (
        indexed["children_under_5"] + indexed["working_age"]
        + indexed["elderly_65plus"] + middle
    )
    worst = float((rebuilt - indexed["total_population"]).abs().max())
    record("Age groups sum back to the total population (rounding only)",
           worst <= 5.0, f"worst discrepancy {worst:.1f} people across 235 county-years")


def check_cross_file_agreement(wide: pd.DataFrame, long: pd.DataFrame) -> None:
    """The two CSVs describe the same population."""
    from_long = long.groupby(["county", "year"])["population"].sum()
    from_wide = wide.set_index(["county", "year"])["total_population"]
    worst = float((from_long - from_wide).abs().max())
    record("Long CSV totals agree with the required CSV",
           worst <= 5.0, f"worst discrepancy {worst:.1f} people")


def check_indicator_formulas(wide: pd.DataFrame, long: pd.DataFrame) -> None:
    """Every ratio recomputes from its own components."""
    tolerance = 0.05
    checks = {
        "dependency_ratio": (wide["children_under_5"] + wide["elderly_65plus"]) / wide["working_age"] * 100,
        "child_dependency_ratio": wide["children_under_5"] / wide["working_age"] * 100,
        "elderly_dependency_ratio": wide["elderly_65plus"] / wide["working_age"] * 100,
        "pct_children": wide["children_under_5"] / wide["total_population"] * 100,
        "pct_elderly": wide["elderly_65plus"] / wide["total_population"] * 100,
    }
    for column, recomputed in checks.items():
        worst = float((wide[column] - recomputed).abs().max())
        record(f"{column} recomputes from its components", worst <= tolerance,
               f"worst difference {worst:.4f}")

    male = long[long["sex"] == "m"].groupby(["county", "year"])["population"].sum()
    female = long[long["sex"] == "f"].groupby(["county", "year"])["population"].sum()
    recomputed = (male / female * 100)
    worst = float((wide.set_index(["county", "year"])["sex_ratio"] - recomputed).abs().max())
    record("sex_ratio recomputes from the long CSV's male and female totals",
           worst <= tolerance, f"worst difference {worst:.4f}")


def check_national_totals(wide: pd.DataFrame) -> None:
    """The national figures quoted in the README are what the CSV holds."""
    national = wide.groupby("year")["total_population"].sum() / 1e6
    record("2021 national total is 52.6M as stated in the README",
           abs(national.loc[2021] - 52.6) < 0.05, f"{national.loc[2021]:.2f}M")
    record("2025 national total is 56.9M as stated in the README",
           abs(national.loc[2025] - 56.9) < 0.05, f"{national.loc[2025]:.2f}M")
    record("Population increases every year 2021-2025",
           bool(national.is_monotonic_increasing),
           " -> ".join(f"{v:.1f}M" for v in national))


def check_crs() -> None:
    """Boundaries and rasters are both EPSG:4326, so no reprojection was needed."""
    boundary_path = config.RAW_DIR / "gadm41_KEN_2.json"
    if boundary_path.exists():
        import json

        with boundary_path.open(encoding="utf-8") as handle:
            crs = json.load(handle).get("crs", {}).get("properties", {}).get("name", "")
        record("Boundary file declares WGS84 (EPSG:4326 / CRS84)",
               "CRS84" in crs or "4326" in crs, crs or "no crs member")
    else:
        skip("Boundary CRS", "boundary file not present")

    rasters = sorted(config.RAW_DIR.glob("*.tif"))
    if not rasters:
        skip("Raster CRS is EPSG:4326", "raster cache empty; run python -m src.pipeline first")
        return
    import rasterio

    with rasterio.open(rasters[0]) as src:
        record("Raster CRS is EPSG:4326, matching the boundaries",
               src.crs.to_string() == config.TARGET_CRS, src.crs.to_string())
        record("Raster nodata marker is -99999, as documented",
               src.nodata == -99999.0, str(src.nodata))


def check_raster_completeness() -> None:
    """If the cache is populated, it holds the 200 files the pipeline downloads."""
    rasters = sorted(config.RAW_DIR.glob("*.tif"))
    if not rasters:
        skip("Raster cache holds 200 male/female files",
             "raster cache empty; run python -m src.pipeline first")
        return
    expected = len(config.YEARS) * len(config.DOWNLOAD_SEX_CODES) * len(config.AGE_BANDS)
    record("Raster cache holds the expected 200 male/female files",
           len(rasters) == expected, f"{len(rasters)} files, expected {expected}")


def main() -> int:
    """Run every check and print a report.

    Returns:
        ``0`` if all checks passed, ``1`` otherwise.
    """
    for path in (config.PROCESSED_CSV_PATH, config.LONG_FORMAT_CSV_PATH):
        if not path.exists():
            print(f"Missing {path}. Run: python -m src.pipeline")
            return 1

    wide = pd.read_csv(config.PROCESSED_CSV_PATH)
    long = pd.read_csv(config.LONG_FORMAT_CSV_PATH, dtype={"age_band": str})

    check_schema(wide)
    check_long_table(long)
    check_counties(wide)
    check_band_groupings()
    check_identity(wide, long)
    check_cross_file_agreement(wide, long)
    check_indicator_formulas(wide, long)
    check_national_totals(wide)
    check_crs()
    check_raster_completeness()

    print("Reproducibility checks against the committed outputs")
    print("=" * 78)
    for status, name, detail in RESULTS:
        suffix = f"  ({detail})" if detail else ""
        print(f"[{status}] {name}{suffix}")

    failed = sum(1 for status, _, _ in RESULTS if status == "FAIL")
    skipped = sum(1 for status, _, _ in RESULTS if status == "SKIP")
    passed = sum(1 for status, _, _ in RESULTS if status == "PASS")
    print("=" * 78)
    print(f"{passed} passed, {failed} failed, {skipped} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
