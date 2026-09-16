"""The three static figures the spec asks for.

Each function builds one figure and returns where it wrote it, so the pipeline can
report the paths and nothing has to guess at filenames. Two presentation choices are
worth stating because they affect what the reader sees rather than what the numbers
are: the raster map uses a logarithmic colour scale, because population per square
kilometre spans several orders of magnitude and a linear scale renders everything
except Nairobi as empty; and the scatterplot uses a logarithmic area axis, because
Marsabit is roughly three hundred times the size of Mombasa. Both are flagged in the
figure captions and can be switched to linear by changing one argument.
"""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
import rasterio

matplotlib.use("Agg")  # No display on this machine; write straight to file.
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm

from src import config
from src.utils import ensure_dir, log_section

RASTER_MAP_YEAR = 2025
RASTER_MAP_SEX = "f"
RASTER_MAP_BANDS = config.CHILDREN_UNDER_5_BANDS
EQUAL_AREA_CRS = "EPSG:8857"  # Equal Earth: preserves area, so km2 are comparable.


def raster_path(sex: str, age_band: str, year: int) -> Path:
    """Return the cached local path of one WorldPop raster.

    Args:
        sex: ``"f"``, ``"m"`` or ``"t"``.
        age_band: Two-digit band code, for example ``"00"``.
        year: Calendar year.

    Returns:
        Path inside the raw data cache.
    """
    url = config.WORLDPOP_URL_TEMPLATE.format(
        year=year,
        iso3_upper=config.COUNTRY_ISO3.upper(),
        iso3_lower=config.COUNTRY_ISO3.lower(),
        sex=sex,
        age=age_band,
    )
    return config.RAW_DIR / url.rsplit("/", 1)[-1]


def plot_raster_map(counties: gpd.GeoDataFrame, logger: logging.Logger) -> Path:
    """Map the 2025 female under-five population at raster resolution.

    Sums the two WorldPop bands that make up ages 0-4 for females in 2025 and
    draws them at their native 1 km resolution, with county outlines for
    orientation. Nodata and zero pixels are left blank rather than drawn as the
    bottom of the colour scale, so empty land reads as empty.

    Args:
        counties: Dissolved county polygons, for the outlines.
        logger: Logger for the validation log.

    Returns:
        Path to the written PNG.
    """
    total: np.ndarray | None = None
    for band in RASTER_MAP_BANDS:
        path = raster_path(RASTER_MAP_SEX, band, RASTER_MAP_YEAR)
        with rasterio.open(path) as src:
            values = src.read(1)
            values = np.where(values == src.nodata, 0.0, values)
            bounds = src.bounds
        total = values if total is None else total + values

    assert total is not None, "RASTER_MAP_BANDS must not be empty"
    display = np.ma.masked_less_equal(total, 0)

    figure, axes = plt.subplots(figsize=(8, 9))
    image = axes.imshow(
        display,
        extent=(bounds.left, bounds.right, bounds.bottom, bounds.top),
        cmap="YlOrRd",
        norm=LogNorm(vmin=max(display.min(), 0.1), vmax=display.max()),
    )
    counties.boundary.plot(ax=axes, color="0.35", linewidth=0.4)
    axes.set_title(
        f"Female children under 5, {RASTER_MAP_YEAR}\n"
        "WorldPop 1 km constrained, UN-adjusted"
    )
    axes.set_xlabel("Longitude")
    axes.set_ylabel("Latitude")
    figure.colorbar(image, ax=axes, shrink=0.7, label="Population per 1 km cell (log scale)")
    figure.tight_layout()

    output = config.FIGURES_DIR / "raster_map_2025_female_under5.png"
    figure.savefig(output, dpi=150)
    plt.close(figure)
    logger.info("Figure 1: %s (bands %s, sex %s, %d)",
                output.name, "+".join(RASTER_MAP_BANDS), RASTER_MAP_SEX, RASTER_MAP_YEAR)
    return output


def plot_national_timeseries(indicators: pd.DataFrame, logger: logging.Logger) -> Path:
    """Plot Kenya's total population for each year in the study period.

    Args:
        indicators: The county-level indicator table.
        logger: Logger for the validation log.

    Returns:
        Path to the written PNG.
    """
    national = indicators.groupby("year")["total_population"].sum() / 1e6

    figure, axes = plt.subplots(figsize=(8, 5))
    axes.plot(national.index, national.values, marker="o", color="#1f4e79")
    for year, value in national.items():
        axes.annotate(f"{value:.1f}M", (year, value), textcoords="offset points",
                      xytext=(0, 8), ha="center", fontsize=9)
    axes.set_title("Kenya total population, 2021-2025")
    axes.set_xlabel("Year")
    axes.set_ylabel("Population (millions)")
    axes.set_xticks(list(national.index))
    axes.grid(axis="y", alpha=0.3)
    figure.tight_layout()

    output = config.FIGURES_DIR / "national_population_2021_2025.png"
    figure.savefig(output, dpi=150)
    plt.close(figure)
    logger.info("Figure 2: %s (%.1fM in %d rising to %.1fM in %d)",
                output.name, national.iloc[0], national.index[0],
                national.iloc[-1], national.index[-1])
    return output


def plot_children_vs_area(
    indicators: pd.DataFrame, counties: gpd.GeoDataFrame, logger: logging.Logger
) -> Path:
    """Scatter children under five against county area for 2025.

    County area is computed after reprojecting to an equal-area CRS, so that the
    figures are real square kilometres and comparable between counties rather
    than degrees, which shrink with latitude.

    Args:
        indicators: The county-level indicator table.
        counties: Dissolved county polygons.
        logger: Logger for the validation log.

    Returns:
        Path to the written PNG.
    """
    areas = counties.to_crs(EQUAL_AREA_CRS).area / 1e6
    area_by_county = pd.Series(areas.values, index=counties[config.COUNTY_NAME_FIELD])

    year_rows = indicators[indicators["year"] == RASTER_MAP_YEAR].copy()
    year_rows["area_km2"] = year_rows["county"].map(area_by_county)

    figure, axes = plt.subplots(figsize=(8, 6))
    axes.scatter(year_rows["area_km2"], year_rows["children_under_5"],
                 s=28, color="#c0504d", alpha=0.75, edgecolor="white", linewidth=0.5)

    # Label only the extremes, so the chart stays readable.
    notable = pd.concat([
        year_rows.nlargest(3, "children_under_5"),
        year_rows.nlargest(2, "area_km2"),
        year_rows.nsmallest(1, "area_km2"),
    ]).drop_duplicates(subset="county")
    for _, row in notable.iterrows():
        axes.annotate(row["county"], (row["area_km2"], row["children_under_5"]),
                      textcoords="offset points", xytext=(5, 4), fontsize=8)

    axes.set_xscale("log")
    axes.set_title(f"Children under 5 against county area, {RASTER_MAP_YEAR}")
    axes.set_xlabel(f"County area (km², {EQUAL_AREA_CRS} equal-area, log scale)")
    axes.set_ylabel("Children under 5")
    axes.grid(alpha=0.3)
    figure.tight_layout()

    output = config.FIGURES_DIR / "children_under5_vs_county_area_2025.png"
    figure.savefig(output, dpi=150)
    plt.close(figure)

    correlation = year_rows["area_km2"].corr(year_rows["children_under_5"])
    logger.info("Figure 3: %s (areas %.0f-%.0f km², Pearson r = %.3f between area and "
                "children under 5)", output.name, year_rows["area_km2"].min(),
                year_rows["area_km2"].max(), correlation)
    return output


def make_all_figures(
    indicators: pd.DataFrame, counties: gpd.GeoDataFrame, logger: logging.Logger
) -> list[Path]:
    """Build all three required figures.

    Args:
        indicators: The county-level indicator table.
        counties: Dissolved county polygons.
        logger: Logger for the validation log.

    Returns:
        Paths of the figures written, in spec order.
    """
    log_section(logger, "figures")
    ensure_dir(config.FIGURES_DIR)
    return [
        plot_raster_map(counties, logger),
        plot_national_timeseries(indicators, logger),
        plot_children_vs_area(indicators, counties, logger),
    ]
