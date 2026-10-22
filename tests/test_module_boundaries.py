"""T01 tests: one module per stage, no cross-stage internal imports, standard library only.

Rules (architecture Section 1, plan T01):
* A stage module, and the shared ``contracts`` module, import no other stage module.
* Only ``cli`` may import stage modules, and only their public names: never a name
  that starts with an underscore, never ``*``, and never a private submodule.
* Every import is the standard library or ``docsync`` itself (D18).
"""

import ast
import importlib
import sys
import unittest
from pathlib import Path

from docsync import contracts

PACKAGE_DIR = Path(contracts.__file__).resolve().parent
STAGES = tuple(contracts.STAGE_MODULES)
STDLIB = set(sys.stdlib_module_names)


def _imported_names(tree, package="docsync"):
    """Yield (dotted_name, imported_member_or_None) for every import in the tree."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, None
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                base = parts[: len(parts) - (node.level - 1)]
                module = ".".join(base + ([node.module] if node.module else []))
            else:
                module = node.module or ""
            for alias in node.names:
                yield module, alias.name


def find_violations(module_name, source):
    """Return a list of rule violations for one module's source text."""
    tree = ast.parse(source)
    problems = []
    is_cli = module_name == "cli"

    for module, member in _imported_names(tree):
        parts = module.split(".")
        top = parts[0]
        if top != "docsync" and top not in STDLIB:
            problems.append("non-standard-library import: %s" % module)
            continue
        if top != "docsync":
            continue
        # the stage being imported: docsync.<stage>... or `from docsync import <stage>`
        stage = None
        if len(parts) >= 2 and parts[1] in STAGES:
            stage = parts[1]
            private_path = any(p.startswith("_") for p in parts[2:])
        elif len(parts) == 1 and member in STAGES:
            stage = member
            private_path = False
        else:
            private_path = False
            if len(parts) == 1 and member and member.startswith("_"):
                problems.append("imports a private name from the package: %s" % member)
            continue
        if not is_cli:
            problems.append("imports another stage module: docsync.%s" % stage)
            continue
        if private_path:
            problems.append("imports a private submodule of docsync.%s" % stage)
        if member is not None and len(parts) >= 2 and (member == "*" or member.startswith("_")):
            problems.append("imports a private or wildcard name from docsync.%s: %s" % (stage, member))

    # attribute access like docsync.mapping.x without an import, and dynamic imports by name
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "docsync":
            if node.attr in STAGES and not is_cli:
                problems.append("reaches another stage through attribute access: docsync.%s" % node.attr)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for stage in STAGES:
                if node.value == "docsync.%s" % stage or node.value.startswith("docsync.%s." % stage):
                    if not is_cli:
                        problems.append("names another stage in a string (dynamic import): %s" % node.value)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", getattr(node.func, "attr", ""))
            if name in {"__import__", "import_module"} and module_name != "cli":
                problems.append("dynamic import call: %s" % name)
    return problems


class PackageLayoutTests(unittest.TestCase):
    def test_one_module_per_stage_plus_contracts(self):
        found = {p.stem for p in PACKAGE_DIR.glob("*.py")}
        self.assertEqual(found, set(STAGES) | {"__init__", "contracts"})

    def test_there_are_eleven_stage_modules(self):
        self.assertEqual(
            STAGES,
            ("cli", "input", "gitadapter", "sizegate", "analysis", "mapping", "generation",
             "validation", "output", "report", "redact"),
        )

    def test_every_module_imports_cleanly_and_has_a_docstring(self):
        for name in STAGES + ("contracts",):
            module = importlib.import_module("docsync.%s" % name)
            self.assertTrue((module.__doc__ or "").strip(), name)

    def test_stage_stubs_export_nothing_yet(self):
        for name in STAGES:
            module = importlib.import_module("docsync.%s" % name)
            self.assertEqual(module.__all__, [], name)


class ActualModulesRespectTheBoundariesTests(unittest.TestCase):
    def test_no_module_violates_the_rules(self):
        for name in STAGES + ("contracts",):
            source = (PACKAGE_DIR / ("%s.py" % name)).read_text(encoding="utf-8")
            self.assertEqual(find_violations(name, source), [], name)

    def test_the_package_init_imports_no_stage(self):
        source = (PACKAGE_DIR / "__init__.py").read_text(encoding="utf-8")
        self.assertEqual(find_violations("__init__", source), [])


class CheckerDetectsViolationsTests(unittest.TestCase):
    """The checker itself is tested, so a passing run means something."""

    def assert_flagged(self, module_name, source):
        self.assertTrue(find_violations(module_name, source), source)

    def assert_clean(self, module_name, source):
        self.assertEqual(find_violations(module_name, source), [], source)

    def test_stage_importing_another_stage_is_flagged(self):
        self.assert_flagged("mapping", "from docsync import analysis\n")
        self.assert_flagged("mapping", "import docsync.analysis\n")
        self.assert_flagged("mapping", "from docsync.analysis import something\n")
        self.assert_flagged("mapping", "from . import analysis\n")
        self.assert_flagged("mapping", "from .analysis import _private\n")
        self.assert_flagged("mapping", "from docsync.analysis._internal import x\n")

    def test_dynamic_and_attribute_access_to_another_stage_is_flagged(self):
        self.assert_flagged("mapping", "import importlib\nimportlib.import_module('docsync.analysis')\n")
        self.assert_flagged("mapping", "mod = __import__('docsync.analysis')\n")
        self.assert_flagged("mapping", "import docsync\nx = docsync.analysis.run\n")

    def test_contracts_and_stdlib_imports_are_allowed(self):
        self.assert_clean("mapping", "import os\nfrom pathlib import Path\nfrom docsync.contracts import ChangedFile\n")
        self.assert_clean("mapping", "from docsync import contracts\n")
        self.assert_clean("mapping", "from . import contracts\n")

    def test_third_party_imports_are_flagged(self):
        self.assert_flagged("mapping", "import requests\n")
        self.assert_flagged("cli", "from yaml import safe_load\n")

    def test_cli_may_import_public_stage_names_only(self):
        self.assert_clean("cli", "from docsync import mapping\n")
        self.assert_clean("cli", "from docsync.mapping import resolve_targets\n")
        self.assert_flagged("cli", "from docsync.mapping import _helper\n")
        self.assert_flagged("cli", "from docsync.mapping import *\n")
        self.assert_flagged("cli", "from docsync.mapping._internal import x\n")
        self.assert_flagged("cli", "import docsync.mapping._internal\n")
        self.assert_flagged("cli", "from docsync import _private\n")


if __name__ == "__main__":
    unittest.main()
