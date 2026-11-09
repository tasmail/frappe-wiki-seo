import importlib
from pathlib import Path

try:
	import tomllib
except ModuleNotFoundError:  # Python 3.10
	import tomli as tomllib


ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "wiki_seo"


def _resolve(path):
	module, function = path.rsplit(".", 1)
	return getattr(importlib.import_module(module), function)


def test_hooks_name_the_app_and_handlers_that_exist():
	hooks = importlib.import_module("wiki_seo.hooks")
	assert hooks.app_name == "wiki_seo" and hooks.required_apps == ["frappe"]
	assert hooks.after_request == ["wiki_seo.hook.after_request"]
	assert set(hooks.doc_events) == {"Wiki Page", "Wiki Space"}
	assert set(hooks.doc_events["Wiki Page"]) == {"on_update", "on_trash", "after_rename"}
	assert set(hooks.doc_events["Wiki Space"]) == {"on_update", "on_trash"}
	for path in hooks.after_request + [h for events in hooks.doc_events.values() for h in events.values()]:
		assert callable(_resolve(path))


def test_the_app_does_not_import_the_wiki():
	for source in PACKAGE.rglob("*.py"):
		text = source.read_text()
		assert "import wiki" not in text and "from wiki " not in text and "from wiki." not in text


def test_the_module_in_modules_txt_has_its_folder():
	assert (PACKAGE / "modules.txt").read_text().splitlines() == ["Wiki SEO"]
	assert (PACKAGE / "wiki_seo" / "__init__.py").exists()
	assert (PACKAGE / "patches.txt").exists()


def test_frappe_is_a_bench_dependency_not_a_pip_one():
	project = tomllib.loads((ROOT / "pyproject.toml").read_text())
	assert project["project"]["name"] == "wiki_seo"
	assert project["project"]["dependencies"] == []
	assert project["tool"]["bench"]["frappe-dependencies"]["frappe"] == ">=15.0.0,<16.0.0"
	assert project["project"]["requires-python"] == ">=3.10"
	assert importlib.import_module("wiki_seo").__version__


def test_ci_runs_on_hosted_runners_without_secrets_for_both_pythons():
	ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
	assert "pull_request_target" not in ci and "secrets." not in ci and "self-hosted" not in ci
	assert "pull_request:" in ci and "runs-on: ubuntu-latest" in ci
	assert 'python-version: ["3.10", "3.11"]' in ci and "lint-and-unit:" in ci
	assert "pytest --cov" in ci and "ruff check" in ci and "ruff format --check" in ci
