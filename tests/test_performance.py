"""The hook runs on every request of a site: what it may cost on a large page and on a request it does not touch."""

import time

from conftest import fixture, html_response, make_request

from wiki_seo import hook

PAGE = "/docs/howto-change-localization"


def best_of(runs, action):
	times = []
	for _ in range(runs):
		start = time.perf_counter()
		action()
		times.append(time.perf_counter() - start)
	return min(times)


def test_a_600_kb_page_is_rewritten_in_under_50_ms(fossdoc):
	body = fixture("fossdoc_uk.html")
	# the sidebar and the content of a big page come after the logo anchor
	cut = body.index(b"<!-- fixture: navbar items")
	body = body[:cut] + b"<p>" + b"x" * (600_000 - len(body)) + b"</p>" + body[cut:]
	assert len(body) >= 600_000
	request = make_request(PAGE)
	hook.after_request(response=html_response(body), request=request)  # warm the route map

	def once():
		response = html_response(body)
		hook.after_request(response=response, request=request)
		assert response.headers["X-Wiki-Seo"] == "1"

	assert best_of(20, once) < 0.05  # a generous bound: a loaded CI runner must not fail it


def test_a_request_it_does_not_touch_costs_no_query_and_no_cache(fossdoc):
	for path in ("/api/method/ping", "/assets/x.css", "/files/a.png"):
		hook.after_request(response=html_response(), request=make_request(path))
	hook.after_request(response=html_response(), request=make_request(PAGE, method="POST"))
	hook.after_request(response=html_response(status=404), request=make_request("/x"))
	assert fossdoc.wiki.queries == []
	assert [call for call in fossdoc.cache.calls if call[0] != "get"] == []
