import ast
import importlib.metadata
import pathlib
import re
import subprocess
import sys

CORE = pathlib.Path(__file__).parents[1] / "src" / "flightkit" / "core"
FORBIDDEN_IN_CORE = (
    "fastapi",
    "uvicorn",
    "mcp",
    "httpx",
    "flightkit.adapters",
    "flightkit.entrypoints",
)
OPTIONAL_DEPS = {"fastapi", "uvicorn", "mcp"}


def _imports(path: pathlib.Path) -> set[str]:
    package = ["flightkit", "core", *path.relative_to(CORE).parent.parts]
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = package[: len(package) - node.level + 1] if node.level else []
            module = ".".join([*base, *filter(None, [node.module])])
            # `from .. import adapters` puts the submodule in the alias
            names.update(f"{module}.{a.name}" for a in node.names)
    return names


def test_core_imports_nothing_forbidden():
    for py in CORE.rglob("*.py"):
        for name in _imports(py):
            assert not name.startswith(FORBIDDEN_IN_CORE), f"{py.name} imports {name}"


def test_importing_flightkit_does_not_load_fastapi():
    code = "import sys, flightkit; assert 'fastapi' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True)


def test_optional_deps_are_only_declared_as_extras():
    # Checks the package metadata, not the current venv, so it passes with extras installed.
    for requirement in importlib.metadata.requires("flightkit") or []:
        name = re.split(r"[\s<>=!~;\[]", requirement, maxsplit=1)[0].lower()
        if name in OPTIONAL_DEPS:
            assert "extra ==" in requirement, f"{name} is a required dependency: {requirement}"
