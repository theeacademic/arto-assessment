"""Programmatic discovery and cached download of the source data.

Nothing here is downloaded by hand. Raster URLs are discovered from the WorldPop
REST API, falling back to the URL pattern in :mod:`src.config` if the API cannot be
reached, and the GADM boundary file is fetched from its published URL.

Two details are deliberate. First, existence of every expected age-sex-year
combination is checked with cheap HTTP HEAD requests across all three sex codes,
while only the ``f`` and ``m`` rasters are actually downloaded -- the completeness
check therefore covers the full set without paying to transfer a third of it.
Second, downloads run in a thread pool and write to a temporary ``.part`` file that
is renamed only on success, so an interrupted run never leaves a truncated file in
the cache and re-running the pipeline costs no network time for files already held.

No missing or failed file is repaired, substituted or skipped quietly: the failure
is returned to the caller, which records it in the validation log.
"""

from __future__ import annotations

import logging
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src import config
from src.utils import ensure_dir, human_bytes


def build_session() -> requests.Session:
    """Return an HTTP session that retries transient failures.

    The WorldPop host is slow enough over this connection that a dropped request
    is likely across several hundred calls, so retries with a backoff are applied
    rather than letting one blip fail the run.

    Returns:
        A ``requests.Session`` with a retry policy mounted for HTTP and HTTPS.
    """
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=config.MAX_DOWNLOAD_WORKERS)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def urls_from_template(year: int) -> list[str]:
    """Build the expected raster URLs for one year from the configured pattern.

    Args:
        year: Calendar year, for example ``2021``.

    Returns:
        One URL per age band and sex code, in configuration order.
    """
    return [
        config.WORLDPOP_URL_TEMPLATE.format(
            year=year,
            iso3_upper=config.COUNTRY_ISO3.upper(),
            iso3_lower=config.COUNTRY_ISO3.lower(),
            sex=sex,
            age=age,
        )
        for sex in config.SEX_CODES
        for age in config.AGE_BANDS
    ]


def urls_from_rest_api(session: requests.Session, logger: logging.Logger) -> dict[int, list[str]]:
    """Ask the WorldPop REST API which files exist for Kenya, by year.

    This is the "directory listing" route the spec allows: the API returns one
    record per year, each carrying the full list of published file URLs.

    Args:
        session: HTTP session to use.
        logger: Logger for recording what the API returned.

    Returns:
        A mapping of year to the list of raster URLs the API reports for that
        year, restricted to the years in ``config.YEARS``. An empty mapping is
        returned if the API cannot be reached or gives an unexpected payload,
        which signals the caller to fall back to the URL template.
    """
    try:
        response = session.get(
            config.WORLDPOP_REST_URL,
            params={"iso3": config.COUNTRY_ISO3},
            timeout=config.REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        records = response.json().get("data", [])
    except (requests.RequestException, ValueError) as error:
        logger.warning("WorldPop REST API unavailable (%s); using URL template", error)
        return {}

    by_year: dict[int, list[str]] = {}
    for record in records:
        try:
            year = int(record.get("popyear"))
        except (TypeError, ValueError):
            continue
        if year in config.YEARS:
            by_year[year] = list(record.get("files") or [])

    if by_year:
        logger.info(
            "REST API listed %d years: %s",
            len(by_year),
            ", ".join(f"{y} ({len(u)} files)" for y, u in sorted(by_year.items())),
        )
    else:
        logger.warning("REST API returned no records for %s; using URL template", config.COUNTRY_ISO3)
    return by_year


def discover_raster_urls(session: requests.Session, logger: logging.Logger) -> dict[int, list[str]]:
    """Discover the raster URLs for every configured year.

    Tries the REST API first and falls back to the configured URL template for
    any year the API did not cover, so a listing outage cannot stop the pipeline.

    Args:
        session: HTTP session to use.
        logger: Logger for recording which route supplied each year.

    Returns:
        A mapping of year to raster URLs, with one entry per year in
        ``config.YEARS``.
    """
    listed = urls_from_rest_api(session, logger)
    discovered: dict[int, list[str]] = {}
    for year in config.YEARS:
        if listed.get(year):
            discovered[year] = listed[year]
        else:
            logger.info("Year %d: falling back to constructed URLs", year)
            discovered[year] = urls_from_template(year)
    return discovered


def url_exists(url: str, session: requests.Session) -> tuple[str, bool, int]:
    """Check whether one URL is present, without downloading its body.

    Args:
        url: URL to test.
        session: HTTP session to use.

    Returns:
        A tuple of the URL, whether the server reported it present, and the
        content length in bytes (zero when unknown or absent).
    """
    try:
        response = session.head(url, timeout=config.REQUEST_TIMEOUT_SECONDS, allow_redirects=True)
        if response.status_code != 200:
            return url, False, 0
        return url, True, int(response.headers.get("Content-Length", 0))
    except requests.RequestException:
        return url, False, 0


def check_urls_exist(
    urls: list[str], session: requests.Session, logger: logging.Logger
) -> dict[str, int]:
    """Check a batch of URLs in parallel and report which are present.

    Args:
        urls: URLs to test.
        session: HTTP session to use.
        logger: Logger for recording the count found.

    Returns:
        A mapping of URL to content length for every URL that exists. URLs that
        are absent are omitted, so the caller can compare against what it
        expected and log the difference.
    """
    found: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=config.MAX_DOWNLOAD_WORKERS) as pool:
        futures = [pool.submit(url_exists, url, session) for url in urls]
        for future in as_completed(futures):
            url, exists, size = future.result()
            if exists:
                found[url] = size
    logger.info("Checked %d URLs: %d present, %d absent", len(urls), len(found), len(urls) - len(found))
    return found


def download_file(
    url: str,
    destination: Path,
    session: requests.Session,
    expected_size: int = 0,
) -> tuple[str, Path | None, str]:
    """Download one file to ``destination`` unless a good copy is already cached.

    A file already on disk is reused when its size matches ``expected_size``, or
    when it is non-empty and no expected size is known. The body is streamed to a
    ``.part`` file and renamed only after a complete transfer, so an interrupted
    run cannot leave a truncated file that a later run would trust.

    Args:
        url: File to fetch.
        destination: Local path to write to.
        session: HTTP session to use.
        expected_size: Content length from the existence check, if known.

    Returns:
        A tuple of the URL, the local path on success or ``None`` on failure, and
        a short status of ``"cached"``, ``"downloaded"`` or an error message.
    """
    if destination.exists():
        actual = destination.stat().st_size
        if (expected_size and actual == expected_size) or (not expected_size and actual > 0):
            return url, destination, "cached"

    partial = destination.with_suffix(destination.suffix + ".part")
    try:
        with session.get(url, stream=True, timeout=config.REQUEST_TIMEOUT_SECONDS) as response:
            response.raise_for_status()
            with partial.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1 << 16):
                    handle.write(chunk)
        partial.replace(destination)
        return url, destination, "downloaded"
    except requests.RequestException as error:
        partial.unlink(missing_ok=True)
        return url, None, f"failed: {error}"


def download_many(
    urls_with_sizes: dict[str, int],
    destination_dir: Path,
    session: requests.Session,
    logger: logging.Logger,
) -> tuple[list[Path], list[str]]:
    """Download many files in parallel, reusing anything already cached.

    Args:
        urls_with_sizes: Mapping of URL to expected content length.
        destination_dir: Directory to write the files into.
        session: HTTP session to use.
        logger: Logger for progress and failures.

    Returns:
        A tuple of the local paths that are now available, and the URLs that
        failed. Failures are returned rather than retried or ignored, so the
        caller decides what to do about them.
    """
    ensure_dir(destination_dir)
    paths: list[Path] = []
    failures: list[str] = []
    cached = downloaded = 0

    with ThreadPoolExecutor(max_workers=config.MAX_DOWNLOAD_WORKERS) as pool:
        futures = {
            pool.submit(
                download_file,
                url,
                destination_dir / url.rsplit("/", 1)[-1],
                session,
                size,
            ): url
            for url, size in urls_with_sizes.items()
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            url, path, status = future.result()
            if path is None:
                failures.append(url)
                logger.error("Download %s -- %s", status, url)
                continue
            paths.append(path)
            if status == "cached":
                cached += 1
            else:
                downloaded += 1
            if completed % 25 == 0 or completed == len(futures):
                logger.info("  progress: %d/%d files", completed, len(futures))

    total_bytes = sum(p.stat().st_size for p in paths)
    logger.info(
        "Rasters available: %d (%d newly downloaded, %d already cached, %s on disk)",
        len(paths), downloaded, cached, human_bytes(total_bytes),
    )
    return paths, failures


def fetch_boundaries(session: requests.Session, logger: logging.Logger) -> Path:
    """Download and unpack the GADM Kenya boundary file, unless already cached.

    Args:
        session: HTTP session to use.
        logger: Logger for recording what was fetched.

    Returns:
        Path to the extracted GeoJSON file.

    Raises:
        requests.RequestException: If the boundary file cannot be downloaded.
        FileNotFoundError: If the archive contains no ``.json`` member.
    """
    ensure_dir(config.RAW_DIR)
    archive = config.RAW_DIR / config.GADM_URL.rsplit("/", 1)[-1]
    extracted = config.RAW_DIR / archive.name.replace(".zip", "")

    if extracted.exists() and extracted.stat().st_size > 0:
        logger.info("Boundaries already cached: %s (%s)", extracted.name, human_bytes(extracted.stat().st_size))
        return extracted

    _, path, status = download_file(config.GADM_URL, archive, session)
    if path is None:
        raise requests.RequestException(f"Could not fetch boundaries: {status}")
    logger.info("Boundary archive %s (%s)", status, human_bytes(archive.stat().st_size))

    with zipfile.ZipFile(archive) as bundle:
        members = [m for m in bundle.namelist() if m.lower().endswith(".json")]
        if not members:
            raise FileNotFoundError(f"No .json member inside {archive.name}")
        with bundle.open(members[0]) as source, extracted.open("wb") as target:
            target.write(source.read())

    logger.info("Boundaries extracted to %s (%s)", extracted.name, human_bytes(extracted.stat().st_size))
    return extracted
