import importlib.metadata
import subprocess
import sys

import flightkit

EXPECTED = {
    "AuthenticationError",
    "Cache",
    "CurrencyResult",
    "Engine",
    "FareSource",
    "FlightkitError",
    "InvalidResponseError",
    "MemoryCache",
    "Price",
    "PricedTrip",
    "ProviderError",
    "ProviderStatusError",
    "ProviderUnavailableError",
    "RateLimitedError",
    "Search",
    "SearchFailure",
    "SearchResult",
    "SearchStats",
    "TooManySearchesError",
    "TripQuery",
    "TripResult",
    "ZerolookClient",
    "__version__",
}


def test_public_names_are_exactly_the_expected_ones():
    # Adding or removing a public name should be a deliberate change to this list.
    assert set(flightkit.__all__) == EXPECTED


def test_every_public_name_is_importable():
    for name in flightkit.__all__:
        assert hasattr(flightkit, name), name


def test_version_comes_from_package_metadata():
    assert flightkit.__version__ == importlib.metadata.version("flightkit")


def test_star_import_gives_the_public_names():
    namespace: dict[str, object] = {}
    exec("from flightkit import *", namespace)
    assert EXPECTED - {"__version__"} <= namespace.keys()


def test_public_api_does_not_pull_in_optional_extras():
    code = (
        "import sys, flightkit; "
        "loaded = {'fastapi', 'uvicorn', 'mcp'} & sys.modules.keys(); "
        "assert not loaded, loaded"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
