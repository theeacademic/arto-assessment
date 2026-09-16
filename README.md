Kenya population by county, 2021-2025
=====================================

A reproducible pipeline that pulls WorldPop's 1 km age and sex population rasters for
Kenya, aggregates them to county boundaries, works out a set of demographic
indicators, and serves the result through a small Streamlit dashboard.

Live dashboard: https://arto-assessment-fsdexqisns6qmumckhrbrf.streamlit.app/

Built for the AHADI technical assessment.


Why this matters
----------------

Kenya's counties are responsible for delivering health services, but they differ a
great deal in age structure. A county with a large under-five population needs
immunisation, nutrition and paediatric capacity. A county with a larger share of
over-65s needs chronic disease management instead. The dependency ratio, which
compares people outside working age to those in it, says something about how much of
the county's health spending has to be carried by a working population. Knowing which
counties look like which is the starting point for allocating resources sensibly, and
that is what this project makes visible.


Data
----

Population figures come from WorldPop age and sex structures, Global 2015-2030 release
R2025A, 1 km constrained and UN-adjusted (1km_ua/constrained), Kenya, 2021-2025. That
is twenty age bands and three sex codes per year.

Boundaries come from GADM 4.1 Kenya level 2. Level 2 is 300 constituencies, so the
pipeline dissolves these up to the 47 counties held in the NAME_1 field.

Nothing is downloaded by hand. The pipeline asks WorldPop's REST API what exists,
falls back to a URL pattern if the API is unavailable, and caches everything on disk
so a second run costs no network time.


What it produces
----------------

| Output | Contents |
| --- | --- |
| data/processed/kenya_population_by_county.csv | 235 rows: 47 counties by 5 years, with the ten required indicators |
| data/processed/kenya_population_by_county_age_sex.csv | 9,400 rows by county, year, sex and age band, used by the dashboard |
| data/processed/validation_log.txt | Every file processed, every check run, every decision taken |
| outputs/figures/ | Three static figures |


Setup
-----

Requires Python 3.12.

```bash
git clone https://github.com/theeacademic/arto-assessment.git
cd arto-assessment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```


Running it
----------

```bash
python -m src.pipeline
```

The first run downloads about 300 MB of rasters and takes roughly ten minutes on a
slow connection. Every run after that reuses the cache and finishes in under thirty
seconds. Output goes to data/processed/ and outputs/figures/.

Then start the dashboard:

```bash
streamlit run dashboard/app.py
```

It opens at http://localhost:8501. Filter by year, indicator, sex and county. The map
and the age pyramid both respond, and clicking a county on the map adds it to the
selection.

A deployed copy runs at
https://arto-assessment-fsdexqisns6qmumckhrbrf.streamlit.app/ if you would rather not
run the pipeline yourself. It may take around thirty seconds to wake if it has been
idle.


Layout
------

```
src/
  config.py        constants and the decisions that shape the run
  data_access.py   URL discovery, existence checks, cached parallel download
  validation.py    filename parsing, completeness, CRS and county checks
  aggregation.py   zonal sums, indicators, output CSVs
  figures.py       the three static plots
  pipeline.py      entry point
dashboard/app.py   the Streamlit app
tests/             reproducibility checks on the committed outputs
data/raw/          cached downloads (gitignored, except the GADM file)
data/processed/    the datasets and the validation log
outputs/figures/   the figures
docs/              the AI use log
```


Decisions and assumptions
-------------------------

A few things in the brief were ambiguous or contradictory. I resolved them as follows
rather than guessing silently.

- Unconstrained versus 1km_ua/constrained. The brief says unconstrained in prose but
  gives a path that says constrained. The path is the one that exists on WorldPop, so
  I followed the path.
- GADM level 2 is not counties. The brief labels level 2 as counties, but it actually
  holds 300 constituencies. Since the required output column is called county and the
  brief elsewhere says 47 counties, I dissolve level 2 up to NAME_1.
- Totals from male plus female. WorldPop also publishes a combined total raster. I
  verify all 300 files exist but download only the 200 male and female ones, and sum
  those, which saves about 150 MB of transfer.
- Nodata is not a negative value. The rasters use -99999 for nodata. That is masked
  out of every sum. A genuinely negative population would be a data defect, so it is
  reported separately and halts the run. Across all 200 rasters there were none.
- County names are left as GADM writes them. Six run together, such as HomaBay and
  TransNzoia. Renaming them would break the join back to the boundaries.
- The dependency ratio here is not the published one. The brief defines it using
  under-fives, where the conventional demographic measure uses ages 0-14. The values
  in this dataset therefore run between roughly 18 and 42, where published figures for
  Kenya sit near 70. Correct for the formula given, but not the same quantity.
- A second CSV was necessary. The required schema carries no sex and no age band, so
  the dashboard's sex toggle and age pyramid could not be built from it alone. The
  long-format file exists for that, and the required schema is untouched.


Checks
------

There is a small test script that re-validates the committed outputs against the
claims made here:

```bash
python tests/test_reproducibility.py
```

It checks the CSV schema and row counts, that the county names match the boundary
file, that the age groups sum back to the total population, that every ratio
recomputes from its own components, that the two CSVs agree with each other, and that
the national totals quoted below are what the data holds. It needs only the committed
files, so it runs on a fresh clone without downloading any rasters; the few checks
that need the raster cache are skipped with a note if it is empty. It exits non-zero
if anything fails.

The pipeline itself verified that all 300 expected age-sex-year combinations exist on
the server, that the rasters and boundaries are both in EPSG:4326 so no reprojection
was needed, and that all 47 counties are present. The fast zonal sums were
cross-checked against rasterstats and agree to within 0.03%, the difference being
pixels on county boundaries. National totals run from 52.6 million in 2021 to 56.9
million in 2025, which sits sensibly against the 47.6 million counted in the 2019
census.


AI use
------

I used Claude for this assessment. The full disclosure, including the prompts I gave
it and what it produced at each stage, is in docs/ai_use.txt.
