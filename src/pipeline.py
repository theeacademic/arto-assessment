"""Command-line entry point: runs access, validation and aggregation in order.

Run with:
    python -m src.pipeline

Stage 2 (implemented here) discovers the WorldPop rasters, proves every expected
age-sex-year combination exists, downloads the subset the analysis needs, fetches
the GADM boundaries, and runs the file and spatial checks. Everything it finds is
written to ``data/processed/validation_log.txt``.

The pipeline never repairs a problem on its own. If a file is missing or a CRS does
not line up, it says so, records it, and stops so that a person decides what to do.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from src import config, data_access, validation
from src.utils import build_logger, ensure_dir, log_section


def record_decisions(logger: logging.Logger) -> None:
    """Write the analysis decisions already taken into the validation log.

    The spec asks the log to document decisions as well as findings, so the
    choices that shape the run are stated up front rather than inferred from
    the code.

    Args:
        logger: Logger for the validation log.
    """
    log_section(logger, "decisions recorded before this run")
    logger.info("County unit: GADM field %s (%d counties). GADM level 2 holds "
                "constituencies, so level-2 polygons are dissolved to counties "
                "at the aggregation stage.", config.COUNTY_NAME_FIELD, config.EXPECTED_COUNTY_COUNT)
    logger.info("Total population source: %s. All three sex codes are checked for "
                "existence; only %s are downloaded.",
                config.TOTAL_POPULATION_SOURCE, " and ".join(config.DOWNLOAD_SEX_CODES))
    logger.info("Dataset: WorldPop Global 2015-2030 R2025A, 1km_ua/constrained, "
                "years %s.", ", ".join(str(y) for y in config.YEARS))
    logger.info("Pixel-value checks (negative, zero, implausible) are deferred to the "
                "aggregation stage, which already reads every raster once.")


def run_ingest(logger: logging.Logger) -> tuple[list[Path], Path]:
    """Discover, verify and download the source data.

    Args:
        logger: Logger for the validation log.

    Returns:
        A tuple of the local raster paths and the local boundary file path.

    Raises:
        SystemExit: If expected files are missing or a download failed, so that
            the run stops for a human decision instead of continuing on partial
            data.
    """
    log_section(logger, "data access")
    session = data_access.build_session()

    discovered = data_access.discover_raster_urls(session, logger)
    all_urls = sorted({url for urls in discovered.values() for url in urls})
    logger.info("Discovered %d candidate raster URLs across %d years", len(all_urls), len(discovered))

    present = data_access.check_urls_exist(all_urls, session, logger)

    parsed, missing, unparseable = validation.check_file_completeness(sorted(present), logger)
    if missing or unparseable:
        logger.error("Stopping: the file set is incomplete and nothing has been imputed.")
        raise SystemExit(1)

    wanted = {
        url: size
        for url, size in present.items()
        if (item := validation.parse_raster_filename(url)) is not None
        and item.sex in config.DOWNLOAD_SEX_CODES
    }
    log_section(logger, "download")
    logger.info("Downloading %d of %d confirmed files (%s only)",
                len(wanted), len(present), " and ".join(config.DOWNLOAD_SEX_CODES))

    raster_paths, failures = data_access.download_many(wanted, config.RAW_DIR, session, logger)
    if failures:
        logger.error("%d downloads failed and were not retried further:", len(failures))
        for url in failures:
            logger.error("  failed: %s", url)
        raise SystemExit(1)

    boundary_path = data_access.fetch_boundaries(session, logger)
    return raster_paths, boundary_path


def run_validation(raster_paths: list[Path], boundary_path: Path, logger: logging.Logger) -> None:
    """Run the spatial checks on the boundaries and a sample raster.

    Args:
        raster_paths: Local raster paths from :func:`run_ingest`.
        boundary_path: Local boundary file path from :func:`run_ingest`.
        logger: Logger for the validation log.
    """
    boundaries = validation.load_boundaries(boundary_path, logger)
    boundary_crs_ok = validation.check_boundary_crs(boundaries, logger)
    raster_crs = validation.check_raster_crs(sorted(raster_paths)[0], logger)
    validation.check_crs_alignment(boundary_crs_ok, raster_crs, logger)
    validation.check_counties(boundaries, logger)


def main() -> int:
    """Run the pipeline end to end.

    Returns:
        Process exit code: ``0`` on success.
    """
    ensure_dir(config.PROCESSED_DIR)
    # Start a fresh log each run, so the file describes this run rather than
    # every run that has ever happened.
    config.VALIDATION_LOG_PATH.unlink(missing_ok=True)
    logger = build_logger()

    logger.info("Kenya population pipeline: WorldPop %s rasters to GADM counties",
                ", ".join(str(y) for y in config.YEARS))
    record_decisions(logger)

    raster_paths, boundary_path = run_ingest(logger)
    run_validation(raster_paths, boundary_path, logger)

    log_section(logger, "stage 2 complete")
    logger.info("%d rasters cached in %s", len(raster_paths), config.RAW_DIR)
    logger.info("Validation log written to %s", config.VALIDATION_LOG_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
