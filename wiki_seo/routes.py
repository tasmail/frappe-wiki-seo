"""The route map of the Wiki: which served route is which page of which space, read from the database once per 600 s.

Only a published Wiki Page that stands in the sidebar of a Wiki Space (a Wiki Group Item that is not hidden) is in the
map, so the editor, the revisions, a new page, a patch preview and every Builder page never match. The map holds the
routes of every space; the hook looks only at the spaces of its configuration.
"""

import frappe

CACHE_KEY = "wiki_seo:routes"
TTL = 600  # seconds: the bound of staleness after a change that fires no document event (SQL, a patch)


class RouteMap:
	"""`routes`: {"docs/slug": ("docs", "slug")}; `first`: {"docs": "slug"}, the first page of the sidebar of a space."""

	def __init__(self, routes: dict, first: dict):
		self.routes, self.first = routes, first

	def page(self, path: str):
		"""(space, slug) of a request path, or None (`/Docs/Page` finds `docs/page`)."""
		route = path.strip("/")
		return self.routes.get(route) or self.routes.get(route.lower())

	def languages(self, slug: str, spaces: dict) -> list:
		"""The languages of the spaces (in the order of `spaces`, each once) that publish `slug` in their sidebar."""
		languages = []
		for space, language in spaces.items():
			if language not in languages and self.page(f"{space}/{slug}"):
				languages.append(language)
		return languages


def build() -> RouteMap:
	"""Two queries: the sidebars of the spaces (in their order) and the published pages."""
	sidebars = frappe.get_all(
		"Wiki Space",
		fields=[
			"route",
			"`tabWiki Group Item`.wiki_page",
			"`tabWiki Group Item`.hide_on_sidebar",
		],
		order_by="`tabWiki Group Item`.idx asc",
		limit_page_length=0,
		as_list=True,
	)
	published = dict(
		frappe.get_all(
			"Wiki Page",
			filters={"published": 1},
			fields=["name", "route"],
			limit_page_length=0,
			as_list=True,
		)
	)
	routes, first = {}, {}
	for space, page, hidden in sidebars:
		route = published.get(page)
		if not space or hidden or not route or not route.startswith(space + "/"):
			continue
		slug = route[len(space) + 1 :]
		if not slug or "/" in slug:
			continue
		routes[route] = (space, slug)
		first.setdefault(space, slug)
	return RouteMap(routes, first)


def get() -> RouteMap:
	"""The map from `frappe.cache`, built and stored for TTL seconds when it is not there."""
	cached = frappe.cache.get_value(CACHE_KEY)
	if cached is not None:
		return RouteMap(*cached)
	route_map = build()
	frappe.cache.set_value(CACHE_KEY, (route_map.routes, route_map.first), expires_in_sec=TTL)
	return route_map


def clear(doc=None, method=None, *args, **kwargs):
	"""`doc_events` of Wiki Page and Wiki Space: drop the map, the next request builds it again."""
	frappe.cache.delete_value(CACHE_KEY)
