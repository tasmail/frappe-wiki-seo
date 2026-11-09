"""The route map: what is in it, its cache and its invalidation, and the parity of its pairs with the browser script."""

import json

import pytest
from conftest import FIXTURES, html_response, make_request

from wiki_seo import hook, routes

SPACES = {"docs": "uk", "ru/docs": "ru", "en/docs": "en"}


def test_only_published_pages_of_a_sidebar_are_in_the_map(frappe_stub):
	frappe_stub.wiki.add_space(
		"docs", ["a", "b", "draft", "hidden"], unpublished=("draft",), hidden=("hidden",), outside=("old",)
	)
	frappe_stub.wiki.add_space("empty", [])
	frappe_stub.wiki.pages["stray"] = ("elsewhere/c", 1)
	frappe_stub.wiki.spaces[0][1].append(("stray", 0))  # a page whose route is not under its space
	frappe_stub.wiki.spaces[0][1].append(("gone", 0))  # a sidebar row of a deleted page
	frappe_stub.wiki.add_space("docs2", ["x/y"])  # a nested route: the browser script never pairs it either
	route_map = routes.build()
	assert route_map.routes == {"docs/a": ("docs", "a"), "docs/b": ("docs", "b")}
	assert route_map.first == {"docs": "a"}
	assert route_map.page("/docs/a/") == ("docs", "a")
	assert route_map.page("/docs/old") is None
	assert frappe_stub.wiki.queries == ["Wiki Space", "Wiki Page"]


def test_the_first_page_skips_hidden_and_unpublished_pages(frappe_stub):
	frappe_stub.wiki.add_space(
		"docs", ["draft", "hidden", "real"], unpublished=("draft",), hidden=("hidden",)
	)
	assert routes.build().first == {"docs": "real"}


def test_the_map_is_cached_for_600_seconds_and_built_once(frappe_stub):
	frappe_stub.wiki.add_space("docs", ["a"])
	for _ in range(5):
		assert routes.get().page("/docs/a") == ("docs", "a")
	assert frappe_stub.wiki.queries == ["Wiki Space", "Wiki Page"]
	assert frappe_stub.cache.ttls == {"wiki_seo:routes": 600}
	assert routes.TTL == 600


def test_a_document_event_drops_the_map(frappe_stub):
	frappe_stub.wiki.add_space("docs", ["a"])
	routes.get()
	frappe_stub.wiki.add_space("ru/docs", ["a"])
	assert routes.get().page("/ru/docs/a") is None  # still the cached map
	routes.clear(object(), "on_update")
	routes.clear(object(), "after_rename", "old", "new", False)
	assert routes.get().page("/ru/docs/a") == ("ru/docs", "a")
	assert frappe_stub.cache.calls.count(("delete", "wiki_seo:routes")) == 2


def test_a_cache_failure_leaves_the_page_untouched(fossdoc):
	def down(key):
		raise ConnectionError("redis is down")

	fossdoc.cache.get_value = down
	body = (FIXTURES / "fossdoc_uk.html").read_bytes()
	response = html_response(body)
	hook.after_request(response=response, request=make_request("/docs/howto-change-localization"))
	assert response.get_data() == body and len(fossdoc.log.lines) == 1


def test_languages_follow_the_order_of_the_config(frappe_stub):
	frappe_stub.wiki.add_space("en/docs", ["a"])
	frappe_stub.wiki.add_space("docs", ["a"])
	assert routes.build().languages("a", SPACES) == ["uk", "en"]


PARITY = json.loads((FIXTURES / "pairs.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("group", ["fossdoc", "erpfoss"])
def test_the_pairs_equal_those_of_the_browser_script(frappe_stub, group):
	"""The spaces as press/fossdoc_wiki.py publishes them: a `sidebar: 0` page is not in the sidebar (an older run may
	have left it as a page), a `published: 0` page is in the sidebar but not published."""
	data = PARITY[group]
	spaces = {space["route"]: space["language"] for space in data["spaces"]}
	slugs = set()
	for space in data["spaces"]:
		pages = space["pages"]
		frappe_stub.wiki.add_space(
			space["route"],
			[page["slug"] for page in pages if page["sidebar"]],
			unpublished={page["slug"] for page in pages if not page["published"]},
			outside=[page["slug"] for page in pages if not page["sidebar"]],
		)
		slugs.update(page["slug"] for page in pages)
	route_map = routes.build()
	pairs = {}
	for slug in sorted(slugs):
		languages = route_map.languages(slug, spaces)
		if len(languages) > 1:
			pairs[slug] = languages
	assert pairs == data["pairs"]
	assert len(pairs) > 40
	# and x-default is uk when the slug has a uk page, else the first language of the pair
	config = hook.Config({"base_url": "https://x", "spaces": spaces, "x_default": "uk"})
	for slug, languages in pairs.items():
		links = hook.hreflang_links(config, route_map, slug).decode()
		default = "uk" if "uk" in languages else languages[0]
		target = next(route for route, language in spaces.items() if language == default)
		assert links.endswith(f'hreflang="x-default" href="https://x/{target}/{slug}" data-fd-hreflang>')
		assert links.count("<link") == len(languages) + 1
