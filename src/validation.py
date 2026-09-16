"""File, spatial and data-quality validation, and the validation log.

Every function here reports what it found and changes nothing. Missing files are
listed, not imputed; a CRS mismatch is reported, not silently reprojected; an odd
county name is flagged, not corrected. The decision about what to do with a finding
belongs to a person and is recorded in the log alongside the finding itself.

Pixel-level checks for negative and implausible values are not run here. They are
folded into the single raster read that the aggregation stage already performs, so
that several hundred rasters are not read twice on a slow machine.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import rasterio

from src import config
from src.utils import log_section

# ken_f_00_2021_CN_1km_R2025A_UA_v1.tif -> iso3 "ken", sex "f", band "00", year 2021
RASTER_NAME_PATTERN = re.compile(
    r"^(?P<iso3>[a-z]{3})_(?P<sex>[fmt])_(?P<age_band>\d{2})_(?P<year>\d{4})_",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedRaster:
    """One WorldPop raster identified by the fields encoded in its filename.

    Attributes:
        filename: The file name the fields were read from.
        iso3: Three-letter country code, lowercase as published.
        sex: ``"f"``, ``"m"`` or ``"t"``.
        age_band: Two-digit lower bound of the age band, for example ``"05"``.
        year: Calendar year of the projection.
    """

    filename: str
    iso3: str
    sex: str
    age_band: str
    year: int


def parse_raster_filename(filename: str) -> ParsedRaster | None:
    """Extract country, sex, age band and year from a WorldPop filename.

    Args:
        filename: File name or URL basename, for example
            ``"ken_f_00_2021_CN_1km_R2025A_UA_v1.tif"``.

    Returns:
        A :class:`ParsedRaster`, or ``None`` if the name does not match the
        expected pattern. An unparseable name is a finding for the caller to log,
        not something to guess at.
    """
    match = RASTER_NAME_PATTERN.match(Path(filename).name)
    if match is None:
        return None
    return ParsedRaster(
        filename=Path(filename).name,
        iso3=match.group("iso3").lower(),
        sex=match.group("sex").lower(),
        age_band=match.group("age_band"),
        year=int(match.group("year")),
    )


def expected_combinations() -> set[tuple[int, str, str]]:
    """Return every age-sex-year combination the pipeline expects to exist.

    Returns:
        A set of ``(year, sex, age_band)`` tuples covering all configured years,
        all three sex codes and all twenty age bands.
    """
    return {
        (year, sex, band)
        for year in config.YEARS
        for sex in config.SEX_CODES
        for band in config.AGE_BANDS
    }


def check_file_completeness(
    available_urls: list[str], logger: logging.Logger
) -> tuple[list[ParsedRaster], list[tuple[int, str, str]], list[str]]:
    """Check that every expected age-sex-year combination is present.

    Args:
        available_urls: URLs confirmed to exist on the server.
        logger: Logger for the validation log.

    Returns:
        A tuple of the successfully parsed rasters, the expected combinations
        that are missing, and the file names that could not be parsed.
    """
    log_section(logger, "file validation")

    parsed: list[ParsedRaster] = []
    unparseable: list[str] = []
    for url in available_urls:
        result = parse_raster_filename(url)
        if result is None:
            unparseable.append(Path(url).name)
        else:
            parsed.append(result)

    logger.info("Files confirmed present on server: %d", len(available_urls))
    logger.info("Filenames parsed into year/sex/age band: %d", len(parsed))

    for name in sorted(unparseable):
        logger.warning("Could not parse filename, excluded from checks: %s", name)

    expected = expected_combinations()
    found = {(item.year, item.sex, item.age_band) for item in parsed}
    missing = sorted(expected - found)
    unexpected = sorted(found - expected)

    logger.info(
        "Expected %d combinations (%d years x %d sexes x %d age bands); found %d",
        len(expected), len(config.YEARS), len(config.SEX_CODES), len(config.AGE_BANDS), len(found),
    )

    if missing:
        logger.error("MISSING %d expected age-sex-year combinations:", len(missing))
        for year, sex, band in missing:
            logger.error("  missing: year=%d sex=%s age_band=%s", year, sex, band)
        logger.error("No imputation or substitution applied. Awaiting a decision.")
    else:
        logger.info("All expected age-sex-year combinations are present.")

    for year, sex, band in unexpected:
        logger.warning("Unexpected combination not in configuration: year=%d sex=%s age_band=%s", year, sex, band)

    for year in config.YEARS:
        per_year = sum(1 for item in parsed if item.year == year)
        logger.info("  %d: %d files", year, per_year)

    return parsed, missing, unparseable


def load_boundaries(path: Path, logger: logging.Logger) -> gpd.GeoDataFrame:
    """Read the GADM boundary file.

    Args:
        path: Path to the extracted GADM GeoJSON.
        logger: Logger for the validation log.

    Returns:
        The boundaries as a GeoDataFrame.
    """
    boundaries = gpd.read_file(path)
    logger.info("Loaded boundaries: %d features from %s", len(boundaries), path.name)
    return boundaries


def check_boundary_crs(boundaries: gpd.GeoDataFrame, logger: logging.Logger) -> bool:
    """Verify the boundaries are in the expected CRS.

    Args:
        boundaries: Boundary layer to check.
        logger: Logger for the validation log.

    Returns:
        ``True`` if the CRS matches ``config.TARGET_CRS``, otherwise ``False``.
        Nothing is reprojected here; a mismatch is reported to the caller.
    """
    log_section(logger, "spatial validation")

    if boundaries.crs is None:
        logger.error("Boundaries have no CRS defined; expected %s.", config.TARGET_CRS)
        return False

    matches = boundaries.crs.to_string().upper() == config.TARGET_CRS.upper()
    if matches:
        logger.info("Boundary CRS is %s, as expected.", boundaries.crs.to_string())
    else:
        logger.warning(
            "Boundary CRS is %s but %s was expected. Not reprojected here.",
            boundaries.crs.to_string(), config.TARGET_CRS,
        )
    return matches


def check_raster_crs(raster_path: Path, logger: logging.Logger) -> str | None:
    """Read and report a sample raster's CRS.

    Args:
        raster_path: A representative raster to open.
        logger: Logger for the validation log.

    Returns:
        The CRS as a string, or ``None`` if the raster declares none.
    """
    with rasterio.open(raster_path) as raster:
        crs = raster.crs
        logger.info(
            "Sample raster %s: CRS=%s, size=%dx%d, pixel=%.6f deg, nodata=%s",
            raster_path.name,
            crs.to_string() if crs else "undefined",
            raster.width, raster.height, abs(raster.transform.a), raster.nodata,
        )
    return crs.to_string() if crs else None


def check_crs_alignment(
    boundary_crs_ok: bool, raster_crs: str | None, logger: logging.Logger
) -> bool:
    """Report whether the rasters and boundaries share a CRS.

    Args:
        boundary_crs_ok: Result of :func:`check_boundary_crs`.
        raster_crs: Result of :func:`check_raster_crs`.
        logger: Logger for the validation log.

    Returns:
        ``True`` when both are in the target CRS and no reprojection is needed.
    """
    aligned = boundary_crs_ok and raster_crs is not None and raster_crs.upper() == config.TARGET_CRS.upper()
    if aligned:
        logger.info("Rasters and boundaries share %s. No reprojection required.", config.TARGET_CRS)
    else:
        logger.warning(
            "CRS mismatch between rasters (%s) and boundaries. A reprojection decision is needed.",
            raster_crs,
        )
    return aligned


def check_counties(boundaries: gpd.GeoDataFrame, logger: logging.Logger) -> list[str]:
    """Verify the expected counties are present and reasonably named.

    Args:
        boundaries: Boundary layer holding the configured county name field.
        logger: Logger for the validation log.

    Returns:
        The sorted list of distinct county names found.

    Raises:
        KeyError: If the configured county name field is absent from the layer.
    """
    field = config.COUNTY_NAME_FIELD
    if field not in boundaries.columns:
        raise KeyError(f"Boundary file has no column {field!r}; found {list(boundaries.columns)}")

    names = boundaries[field]
    blank = int(names.isna().sum() + (names.astype(str).str.strip() == "").sum())
    distinct = sorted(set(names.dropna().astype(str).str.strip()))

    logger.info("County name field: %s", field)
    logger.info("Distinct counties found: %d (expected %d)", len(distinct), config.EXPECTED_COUNTY_COUNT)
    logger.info("Sub-units in file: %d", len(boundaries))

    if blank:
        logger.error("%d features have a blank or null %s. Not filled in.", blank, field)

    if len(distinct) != config.EXPECTED_COUNTY_COUNT:
        logger.error(
            "County count is %d, not %d. No county has been added or removed.",
            len(distinct), config.EXPECTED_COUNTY_COUNT,
        )
    else:
        logger.info("All %d counties are present.", config.EXPECTED_COUNTY_COUNT)

    # GADM writes some multi-word county names without a space, for example
    # "HomaBay" and "TransNzoia". Flagged so the naming is a conscious choice,
    # and left exactly as published so joins against GADM keep working.
    run_together = [n for n in distinct if re.search(r"[a-z][A-Z]", n)]
    if run_together:
        logger.warning(
            "%d county names are run together as GADM publishes them (%s). Left unchanged.",
            len(run_together), ", ".join(run_together),
        )

    logger.info("Counties: %s", ", ".join(distinct))
    return distinct
