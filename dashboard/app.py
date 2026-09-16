"""Streamlit dashboard for exploring the processed Kenya population data.

Run with:
    streamlit run dashboard/app.py

Reads only the pipeline's outputs -- the two processed CSVs and the GADM boundaries --
so the dashboard never opens a raster and never recomputes an indicator that the
pipeline already wrote.

Two visualisations: a choropleth of the selected indicator, and an age pyramid.
Counties can be chosen from the sidebar or by clicking the map; the two stay in step.
The sex toggle applies to the three count indicators, which can genuinely be split by
sex, and is disabled for the four ratio indicators, which cannot: a sex ratio is
defined as males divided by females, so there is no such thing as one for males alone.
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import config  # noqa: E402

# The spec asks for an interpretation section. It is written by the author, not
# generated: put the Markdown here and it will render at the foot of the page.
INTERPRETATION_MARKDOWN = ""

SEX_OPTIONS = {"Total": ("f", "m"), "Male": ("m",), "Female": ("f",)}


@st.cache_data
def load_indicators() -> pd.DataFrame:
    """Load the required county indicator CSV.

    Returns:
        One row per county and year, with the spec's twelve columns.
    """
    return pd.read_csv(config.PROCESSED_CSV_PATH)


@st.cache_data
def load_long_table() -> pd.DataFrame:
    """Load the long-format population file used by the pyramid and the sex toggle.

    Returns:
        One row per county, year, sex and age band. The age band is kept as a
        zero-padded string so it matches the configured band codes.
    """
    return pd.read_csv(config.LONG_FORMAT_CSV_PATH, dtype={"age_band": str})


@st.cache_data
def load_counties() -> gpd.GeoDataFrame:
    """Load the GADM boundaries and dissolve them to counties.

    Returns:
        One row per county, holding only the county name and its geometry.
    """
    boundaries = gpd.read_file(config.RAW_DIR / "gadm41_KEN_2.json")
    return (
        boundaries.dissolve(by=config.COUNTY_NAME_FIELD, as_index=False)
        [[config.COUNTY_NAME_FIELD, "geometry"]]
        .sort_values(config.COUNTY_NAME_FIELD)
        .reset_index(drop=True)
    )


def county_values(
    indicator: str, year: int, sex_label: str, indicators: pd.DataFrame, long_table: pd.DataFrame
) -> pd.DataFrame:
    """Return the per-county value of one indicator for one year.

    Count indicators are recomputed from the long-format table when a single sex is
    selected. Ratio indicators always come from the pipeline's own output, because
    they are not defined for one sex on its own.

    Args:
        indicator: Display name of the indicator.
        year: Year to show.
        sex_label: ``"Total"``, ``"Male"`` or ``"Female"``.
        indicators: The required indicator table.
        long_table: The long-format population table.

    Returns:
        A frame with a ``county`` column and a ``value`` column.
    """
    if indicator in config.RATIO_INDICATORS:
        column = config.RATIO_INDICATORS[indicator]
        frame = indicators.loc[indicators["year"] == year, ["county", column]]
        return frame.rename(columns={column: "value"})

    column, bands = config.COUNT_INDICATORS[indicator]
    if sex_label == "Total":
        frame = indicators.loc[indicators["year"] == year, ["county", column]]
        return frame.rename(columns={column: "value"})

    sexes = SEX_OPTIONS[sex_label]
    rows = long_table[
        (long_table["year"] == year)
        & (long_table["sex"].isin(sexes))
        & (long_table["age_band"].isin(bands))
    ]
    return rows.groupby("county", as_index=False)["population"].sum().rename(
        columns={"population": "value"}
    )


def build_choropleth(
    values: pd.DataFrame,
    counties: gpd.GeoDataFrame,
    indicator: str,
    indicators: pd.DataFrame,
    year: int,
    selected: list[str],
) -> go.Figure:
    """Build the county choropleth for the selected indicator.

    Counts use a sequential colour scale and ratios a diverging one centred on the
    national median, as the spec asks.

    Args:
        values: Output of :func:`county_values`.
        counties: County polygons.
        indicator: Display name of the indicator, used as the legend title.
        indicators: The required indicator table, for the hover tooltip.
        year: Year being shown.
        selected: Counties currently selected, outlined on the map.

    Returns:
        A Plotly figure.
    """
    context = indicators[indicators["year"] == year][
        ["county", "total_population", "children_under_5", "elderly_65plus",
         "dependency_ratio", "sex_ratio"]
    ]
    frame = values.merge(context, on="county", how="left")

    is_ratio = indicator in config.RATIO_INDICATORS
    figure = px.choropleth(
        frame,
        geojson=counties.__geo_interface__,
        locations="county",
        featureidkey=f"properties.{config.COUNTY_NAME_FIELD}",
        color="value",
        color_continuous_scale="RdBu_r" if is_ratio else "YlOrRd",
        color_continuous_midpoint=frame["value"].median() if is_ratio else None,
        labels={"value": indicator},
        custom_data=["county", "total_population", "children_under_5",
                     "elderly_65plus", "dependency_ratio", "sex_ratio"],
    )
    figure.update_traces(
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            f"{indicator}: %{{z:,.2f}}<br>"
            "Total population: %{customdata[1]:,.0f}<br>"
            "Children under 5: %{customdata[2]:,.0f}<br>"
            "Elderly 65+: %{customdata[3]:,.0f}<br>"
            "Dependency ratio: %{customdata[4]:.2f}<br>"
            "Sex ratio: %{customdata[5]:.2f}<extra></extra>"
        ),
        marker_line_color="white",
        marker_line_width=0.5,
    )
    if selected:
        chosen = counties[counties[config.COUNTY_NAME_FIELD].isin(selected)]
        figure.add_trace(
            go.Choropleth(
                geojson=chosen.__geo_interface__,
                locations=chosen[config.COUNTY_NAME_FIELD],
                featureidkey=f"properties.{config.COUNTY_NAME_FIELD}",
                z=[1] * len(chosen),
                colorscale=[[0, "rgba(0,0,0,0)"], [1, "rgba(0,0,0,0)"]],
                marker_line_color="#111111",
                marker_line_width=2.0,
                showscale=False,
                hoverinfo="skip",
            )
        )
    figure.update_geos(fitbounds="locations", visible=False)
    figure.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=560)
    return figure


def build_age_pyramid(
    long_table: pd.DataFrame, year: int, sex_label: str, selected: list[str]
) -> go.Figure:
    """Build the age pyramid for the current selection.

    With no county selected the pyramid covers all of Kenya; with several selected
    it shows their combined total.

    Args:
        long_table: The long-format population table.
        year: Year to show.
        sex_label: ``"Total"``, ``"Male"`` or ``"Female"``.
        selected: Counties currently selected, or an empty list for the whole country.

    Returns:
        A Plotly figure.
    """
    rows = long_table[long_table["year"] == year]
    if selected:
        rows = rows[rows["county"].isin(selected)]

    totals = rows.groupby(["age_band", "sex"], as_index=False)["population"].sum()
    order = [band for band in config.AGE_BANDS]
    labels = [config.AGE_BAND_LABELS[band] for band in order]

    figure = go.Figure()
    for sex, colour, sign in (("m", "#1f4e79", -1), ("f", "#c0504d", 1)):
        if sex not in SEX_OPTIONS[sex_label]:
            continue
        by_band = totals[totals["sex"] == sex].set_index("age_band")["population"]
        figure.add_trace(
            go.Bar(
                y=labels,
                x=[sign * float(by_band.get(band, 0.0)) for band in order],
                name="Male" if sex == "m" else "Female",
                orientation="h",
                marker_color=colour,
                hovertemplate="%{y}<br>%{customdata:,.0f}<extra></extra>",
                customdata=[float(by_band.get(band, 0.0)) for band in order],
            )
        )

    figure.update_layout(
        barmode="relative",
        height=560,
        margin=dict(l=0, r=0, t=10, b=0),
        xaxis_title="Population",
        yaxis_title="Age group",
        legend=dict(orientation="h", y=1.02, x=0),
    )
    figure.update_xaxes(tickformat="~s")
    return figure


def apply_map_click(county_names: list[str]) -> None:
    """Fold any county clicked on the map into the sidebar selection.

    Streamlit stores the map's selection under its widget key. This runs before the
    multiselect is created, so the widget picks the new value up on this rerun. The
    click signature is remembered so that a stale selection cannot keep re-adding a
    county the user has just removed from the dropdown.

    Args:
        county_names: Every valid county name, used to ignore anything unexpected.
    """
    event = st.session_state.get("map_chart")
    points = (event or {}).get("selection", {}).get("points", []) or []

    clicked: list[str] = []
    for point in points:
        name = point.get("location")
        if name is None:
            custom = point.get("customdata") or []
            name = custom[0] if custom else None
        if name in county_names:
            clicked.append(name)

    signature = tuple(sorted(set(clicked)))
    if signature == st.session_state.get("last_map_click"):
        return
    st.session_state["last_map_click"] = signature

    current = list(st.session_state.get("selected_counties", []))
    for name in clicked:
        if name not in current:
            current.append(name)
    st.session_state["selected_counties"] = current


def main() -> None:
    """Lay out and render the dashboard."""
    st.set_page_config(page_title="Kenya population by county", layout="wide")
    st.title("Kenya population by county, 2021-2025")
    st.caption("WorldPop 1 km age and sex structures aggregated to GADM counties.")

    indicators = load_indicators()
    long_table = load_long_table()
    counties = load_counties()
    county_names = counties[config.COUNTY_NAME_FIELD].tolist()

    apply_map_click(county_names)

    all_indicators = list(config.COUNT_INDICATORS) + list(config.RATIO_INDICATORS)
    with st.sidebar:
        st.header("Filters")
        year = st.selectbox("Year", sorted(indicators["year"].unique()), index=4)
        indicator = st.selectbox("Indicator", all_indicators)

        is_ratio = indicator in config.RATIO_INDICATORS
        sex_label = st.radio(
            "Sex", list(SEX_OPTIONS), horizontal=True, disabled=is_ratio,
            help="Ratios are not defined for a single sex, so this applies to the "
                 "count indicators only.",
        )
        if is_ratio:
            st.caption(f"{indicator} combines both sexes by definition, so the sex "
                       "toggle does not apply to the map. It still applies to the pyramid.")

        st.multiselect("Counties (optional)", county_names, key="selected_counties",
                       help="Or click a county on the map.")
        if st.button("Clear selection"):
            st.session_state["selected_counties"] = []
            st.session_state["last_map_click"] = ()
            st.rerun()

    selected = list(st.session_state.get("selected_counties", []))
    map_sex = "Total" if is_ratio else sex_label
    values = county_values(indicator, year, map_sex, indicators, long_table)

    left, right = st.columns(2)
    with left:
        st.subheader(f"{indicator}, {year}")
        st.plotly_chart(
            build_choropleth(values, counties, indicator, indicators, year, selected),
            width="stretch", key="map_chart",
            on_select="rerun", selection_mode="points",
        )
    with right:
        scope = ", ".join(selected) if selected else "Kenya"
        st.subheader(f"Age structure, {year} — {scope}")
        st.plotly_chart(
            build_age_pyramid(long_table, year, sex_label, selected),
            width="stretch",
        )

    if INTERPRETATION_MARKDOWN.strip():
        st.markdown("---")
        st.markdown(INTERPRETATION_MARKDOWN)


if __name__ == "__main__":
    main()
