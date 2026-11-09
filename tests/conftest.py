"""A stub of `frappe` for the unit tests: they run without a bench, a site or Redis.

The stub module is made once, so the modules of the app that import `frappe` keep working; the autouse fixture resets its
state for every test. `frappe.get_all` answers the two queries of `wiki_seo.routes.build` from in-memory tables
(`FRAPPE.wiki`); the responses and requests are real werkzeug objects.
"""

import sys
import types
from pathlib import Path

import pytest
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request, Response

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class _Logger:
	def __init__(self):
		self.lines = []

	def info(self, message, *args, **kwargs):
		self.lines.append(message % args if args else message)

	def error(self, message, *args, **kwargs):
		self.lines.append(message % args if args else message)


class FakeCache:
	"""The part of `frappe.cache` that the app uses: get_value, set_value with a TTL and delete_value."""

	def __init__(self):
		self.values, self.ttls, self.calls = {}, {}, []

	def get_value(self, key):
		self.calls.append(("get", key))
		return self.values.get(key)

	def set_value(self, key, value, expires_in_sec=None):
		self.calls.append(("set", key))
		self.values[key], self.ttls[key] = value, expires_in_sec

	def delete_value(self, key):
		self.calls.append(("delete", key))
		self.values.pop(key, None)


class Wiki:
	"""The rows of Wiki Space (with its sidebar, Wiki Group Item) and Wiki Page that the stub serves."""

	def __init__(self):
		self.spaces = []  # [(route, [(wiki_page, hide_on_sidebar), ...])]
		self.pages = {}  # name -> (route, published)
		self.queries = []

	def add_space(self, route, slugs, hidden=(), unpublished=(), outside=()):
		"""A space whose sidebar lists `slugs` in order; `outside`: published pages of the space not in the sidebar."""
		items = []
		for slug in slugs:
			name = f"{route}/{slug}#page"
			self.pages[name] = (f"{route}/{slug}", 0 if slug in unpublished else 1)
			items.append((name, 1 if slug in hidden else 0))
		for slug in outside:
			self.pages[f"{route}/{slug}#page"] = (f"{route}/{slug}", 1)
		self.spaces.append((route, items))

	def get_all(
		self, doctype, filters=None, fields=None, order_by=None, limit_page_length=None, as_list=False
	):
		self.queries.append(doctype)
		assert as_list and limit_page_length == 0
		if doctype == "Wiki Space":
			assert fields == [
				"route",
				"`tabWiki Group Item`.wiki_page",
				"`tabWiki Group Item`.hide_on_sidebar",
			]
			assert order_by == "`tabWiki Group Item`.idx asc"
			rows = []
			for route, items in self.spaces:
				rows.extend((idx, route, page, hidden) for idx, (page, hidden) in enumerate(items, 1))
				if not items:  # the left join gives a space with no sidebar one row of nulls
					rows.append((0, route, None, None))
			return [row[1:] for row in sorted(rows, key=lambda row: row[0])]
		assert doctype == "Wiki Page" and filters == {"published": 1} and fields == ["name", "route"]
		return [(name, route) for name, (route, published) in self.pages.items() if published]


def _make_frappe():
	frappe = types.ModuleType("frappe")
	frappe.log = _Logger()
	frappe.logger = lambda name=None: frappe.log
	frappe.get_all = lambda *args, **kwargs: frappe.wiki.get_all(*args, **kwargs)
	sys.modules["frappe"] = frappe
	return frappe


FRAPPE = _make_frappe()

FOSSDOC = {
	"hosts": ["www.fossdoc.com", "fossdoc.com", "fossdocprod.erp-crm.org"],
	"base_url": "https://www.fossdoc.com",
	"spaces": {"docs": "uk", "ru/docs": "ru", "en/docs": "en"},
	"x_default": "uk",
	"title_suffix": " | FossDoc",
	"site_name": "FossDoc",
	"noindex_paths": ["login", "cart", "me", "update-password"],
	"noindex_errors": True,
}


@pytest.fixture(autouse=True)
def frappe_stub():
	FRAPPE.local = types.SimpleNamespace(conf={}, request=None)
	FRAPPE.cache = FakeCache()
	FRAPPE.wiki = Wiki()
	FRAPPE.log.lines.clear()
	return FRAPPE


@pytest.fixture
def fossdoc(frappe_stub):
	"""The site config of the FossDoc site and its three spaces, the page of the fixtures in all of them."""
	frappe_stub.local.conf["wiki_seo"] = dict(FOSSDOC)
	frappe_stub.wiki.add_space("docs", ["docs-overview", "howto-change-localization", "uk-only"])
	frappe_stub.wiki.add_space("ru/docs", ["docs-overview", "howto-change-localization", "ru-en"])
	frappe_stub.wiki.add_space("en/docs", ["docs-overview", "howto-change-localization", "ru-en"])
	return frappe_stub


def fixture(name: str) -> bytes:
	return (FIXTURES / name).read_bytes()


def make_request(path="/", method="GET", host="www.fossdoc.com", query_string=None):
	return Request(
		EnvironBuilder(
			path=path, method=method, base_url=f"https://{host}", query_string=query_string
		).get_environ()
	)


def html_response(body=b"<html><head></head><body></body></html>", status=200, **kwargs):
	return Response(body, status=status, content_type="text/html; charset=utf-8", **kwargs)
