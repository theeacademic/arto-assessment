"""Streamlit dashboard for exploring the processed Kenya population data.

Run with:
    streamlit run dashboard/app.py

Reads only the pipeline's outputs -- the processed CSV and the GADM boundaries --
so the dashboard never touches a raster and never recomputes an indicator.

Planned contents (Stage 4):
    Filters:         year, sex (Male / Female / Total), indicator dropdown, and an
                     optional county multi-select.
    Visualisations:  a choropleth of the selected indicator, and an age pyramid.
    Interpretation:  a section written by the author, not generated.
"""
