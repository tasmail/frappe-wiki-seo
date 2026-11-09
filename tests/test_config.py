"""The site config key `wiki_seo`: tolerant parsing, host normalisation and the contract with the deploy side."""

import json

import pytest
from conftest import FIXTURES, fixture, html_response, make_request

from wiki_seo import hook

# The objects that press/wiki_seo_site.py of tasmail/erpnext-infra prints, with example names in place of the QA and
# internal hosts (see "source" in the file); tests/test_wiki_seo_site.py of that repository tests the real hosts.
CONTRACT = json.loads((FIXTURES / "infra_config.json").read_text(encoding="utf-8"))["sites"]


@pytest.mark.parametrize(
	("host", "expected"),
	[
		("www.fossdoc.com", "www.fossdoc.com"),
		("WWW.FossDoc.COM", "www.fossdoc.com"),
		("www.fossdoc.com:443", "www.fossdoc.com"),
		("www.fossdoc.com.", "www.fossdoc.com"),
		("[::1]:8000", "[::1]"),
		(None, ""),
	],
)
def test_the_host_is_normalised(host, expected):
	assert hook.normalise_host(host) == expected


def test_missing_keys_take_safe_defaults():
	config = hook.Config({})
	assert config.hosts == set() and config.spaces == {} and config.base_url == ""
	assert config.x_default == "uk" and config.title_suffix == "" and config.site_name == ""
	assert config.noindex_paths == set() and config.noindex_errors is True


def test_malformed_values_are_ignored_and_unknown_keys_too():
	config = hook.Config(
		{
			"hosts": "www.fossdoc.com",
			"base_url": 5,
			"spaces": ["docs"],
			"x_default": None,
			"title_suffix": 1,
			"noindex_paths": ["/Login/", 3, "", "/"],
			"noindex_errors": "yes",
			"future_key": {"a": 1},
		}
	)
	assert config.hosts == set() and config.base_url == "" and config.spaces == {}
	assert config.x_default == "uk" and config.title_suffix == ""
	assert config.noindex_paths == {"login"} and config.noindex_errors is True
	assert hook.Config({"spaces": {"/docs/": "uk", "x": 1, "/": "en"}, "noindex_errors": False}).spaces == {
		"docs": "uk"
	}
	assert hook.Config({"noindex_errors": False}).noindex_errors is False


@pytest.mark.parametrize("enabled", [True, 1, "on", "true", None])
def test_anything_but_an_off_value_keeps_it_on(frappe_stub, enabled):
	frappe_stub.local.conf["wiki_seo"] = {"enabled": enabled}
	assert hook.load_config() is not None


@pytest.mark.parametrize("enabled", [False, 0, "0", "false", "Off", " no "])
def test_an_off_value_is_the_kill_switch(frappe_stub, enabled):
	frappe_stub.local.conf["wiki_seo"] = {"enabled": enabled}
	assert hook.load_config() is None


def test_the_contract_covers_the_three_sites_and_both_modes():
	"""The key set and the value shapes of the object of press/wiki_seo_site.py; its own repository has the matching test
	with the real hosts, so a change of either side shows in one of them."""
	assert len(CONTRACT) == 3
	for modes in CONTRACT.values():
		assert set(modes) == {"on", "off"}
		raw = modes["on"]
		assert (
			isinstance(raw["hosts"], list) and raw["hosts"] and all(isinstance(h, str) for h in raw["hosts"])
		)
		assert raw["base_url"].startswith("https://") and not raw["base_url"].endswith("/")
		assert raw["spaces"] == {"docs": "uk", "ru/docs": "ru", "en/docs": "en"} and raw["x_default"] == "uk"
		assert (
			raw["title_suffix"].startswith(" | ") and isinstance(raw["site_name"], str) and raw["site_name"]
		)
		assert raw["noindex_paths"] and all("/" not in path for path in raw["noindex_paths"])
		assert raw["noindex_errors"] is True
		assert modes["on"]["enabled"] is True and modes["off"]["enabled"] is False
		assert {key: value for key, value in modes["on"].items() if key != "enabled"} == {
			key: value for key, value in modes["off"].items() if key != "enabled"
		}


@pytest.mark.parametrize("site", sorted(CONTRACT))
def test_the_config_of_the_deploy_side_is_read_as_meant(frappe_stub, site):
	raw = CONTRACT[site]["on"]
	assert set(raw) == {
		"enabled",
		"hosts",
		"base_url",
		"spaces",
		"x_default",
		"title_suffix",
		"site_name",
		"noindex_paths",
		"noindex_errors",
	}
	frappe_stub.local.conf["wiki_seo"] = raw
	config = hook.load_config()
	assert config.hosts == set(raw["hosts"]) and config.base_url == raw["base_url"]
	assert config.spaces == {"docs": "uk", "ru/docs": "ru", "en/docs": "en"} and config.x_default == "uk"
	assert config.title_suffix == raw["title_suffix"] and config.site_name == raw["site_name"]
	assert config.noindex_paths == set(raw["noindex_paths"]) and "login" in config.noindex_paths
	assert config.noindex_errors is True
	frappe_stub.local.conf["wiki_seo"] = CONTRACT[site]["off"]
	assert hook.load_config() is None


@pytest.mark.parametrize("site", sorted(CONTRACT))
def test_every_host_and_service_path_of_the_deploy_side_works(frappe_stub, site):
	raw = CONTRACT[site]["on"]
	frappe_stub.local.conf["wiki_seo"] = raw
	frappe_stub.wiki.add_space("docs", ["howto-change-localization"])
	for host in raw["hosts"]:
		response = html_response(fixture("fossdoc_uk.html"))
		hook.after_request(
			response=response, request=make_request("/docs/howto-change-localization", host=host)
		)
		assert response.headers.get("X-Wiki-Seo") == "1", host
		assert raw["title_suffix"].encode() in response.get_data()
	for route in raw["noindex_paths"]:
		for path in (f"/{route}", f"/{route}/sub", f"/{route.upper()}"):
			response = html_response()
			hook.after_request(response=response, request=make_request(path, host=raw["hosts"][0]))
			assert response.headers.getlist("X-Robots-Tag") == ["noindex, nofollow"], path
