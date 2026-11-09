"""Every guard of the hook leaves the response untouched: the same bytes and the same headers."""

import pytest
from conftest import FOSSDOC, fixture, html_response, make_request
from werkzeug.wrappers import Response

from wiki_seo import hook

PAGE = "/docs/howto-change-localization"


def snapshot(response):
	return response.status_code, list(response.headers.items()), response.get_data()


def run(response, path=PAGE, **kwargs):
	before = snapshot(response)
	hook.after_request(response=response, request=make_request(path, **kwargs))
	return before, snapshot(response)


def test_the_page_is_rewritten_when_no_guard_applies(fossdoc):
	before, after = run(html_response(fixture("fossdoc_uk.html")))
	assert before != after


@pytest.mark.parametrize(
	"value",
	[
		None,
		"on",
		[],
		{"enabled": False},
		{"enabled": "false"},
		{"enabled": 0},
		{"enabled": "disabled"},
		{"enabled": ""},
		{"enabled": None},
		{"enabled": 2},
	],
)
def test_no_config_or_the_kill_switch_is_a_no_op(fossdoc, value):
	if value is None:
		fossdoc.local.conf.pop("wiki_seo")
	elif isinstance(value, dict):
		fossdoc.local.conf["wiki_seo"] = {**FOSSDOC, **value}
	elif value == []:
		fossdoc.local.conf["wiki_seo"] = {key: v for key, v in FOSSDOC.items() if key != "enabled"}
	else:
		fossdoc.local.conf["wiki_seo"] = value
	before, after = run(html_response(fixture("fossdoc_uk.html")))
	assert before == after
	assert fossdoc.wiki.queries == [] and fossdoc.cache.calls == []


def test_a_missing_response_is_left_alone(fossdoc):
	hook.after_request(response=None, request=make_request(PAGE))
	assert fossdoc.log.lines == [] and fossdoc.cache.calls == []


def test_the_request_of_frappe_local_is_used_when_none_is_passed(fossdoc):
	response = html_response(fixture("fossdoc_uk.html"))
	fossdoc.local.request = make_request(PAGE)
	hook.after_request(response=response)
	assert response.headers.get("X-Wiki-Seo") == "1"


def test_no_request_at_all_is_a_no_op(fossdoc):
	before = snapshot(response := html_response(fixture("fossdoc_uk.html")))
	hook.after_request(response=response)
	assert snapshot(response) == before


@pytest.mark.parametrize("host", ["shop.example.org", "qa.wiki.example.org", "evil.example"])
def test_a_host_outside_the_config_is_left_alone(fossdoc, host):
	before, after = run(html_response(fixture("fossdoc_uk.html")), host=host)
	assert before == after


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "OPTIONS"])
def test_a_method_other_than_get_or_head_is_left_alone(fossdoc, method):
	before, after = run(html_response(fixture("fossdoc_uk.html"), status=404), method=method)
	assert before == after


def test_head_is_rewritten_like_get(fossdoc):
	response = html_response(fixture("fossdoc_uk.html"))
	run(response, method="HEAD")
	assert response.headers.get("X-Wiki-Seo") == "1"


def test_a_direct_passthrough_response_is_left_alone(fossdoc):
	response = html_response(fixture("fossdoc_uk.html"), status=404)
	response.direct_passthrough = True
	before = (response.status_code, list(response.headers.items()))
	hook.after_request(response=response, request=make_request(PAGE))
	assert (response.status_code, list(response.headers.items())) == before


def test_a_streamed_response_is_not_read(fossdoc):
	consumed = []

	def chunks():
		consumed.append(True)
		yield b"<html><head></head></html>"

	response = Response(chunks(), status=404, content_type="text/html; charset=utf-8")
	hook.after_request(response=response, request=make_request(PAGE))
	assert consumed == [] and "X-Robots-Tag" not in response.headers


def test_an_encoded_body_is_left_alone(fossdoc):
	response = html_response(fixture("fossdoc_uk.html"), headers={"Content-Encoding": "gzip"})
	before, after = run(response)
	assert before == after


@pytest.mark.parametrize(
	"path",
	[
		"/api/method/ping",
		"/api",
		"/app",
		"/app/wiki-page",
		"/desk",
		"/assets/wiki/dist/css/wiki.bundle.css",
		"/files/fossdoc-favicon.svg",
		"/private/files/a.pdf",
		"/socket.io/",
	],
)
def test_service_prefixes_are_left_alone(fossdoc, path):
	fossdoc.local.conf["wiki_seo"]["noindex_paths"] = ["api", "app", "files"]
	before, after = run(html_response(b"<html><head></head></html>", status=404), path=path)
	assert before == after


def test_a_page_that_only_starts_like_a_service_prefix_is_not_skipped(fossdoc):
	response = html_response(status=404)
	run(response, path="/apptop-application-uk")
	assert response.headers.getlist("X-Robots-Tag") == ["noindex, nofollow"]


@pytest.mark.parametrize("status", [301, 302, 304, 307, 308])
def test_a_redirect_is_left_alone(fossdoc, status):
	fossdoc.local.conf["wiki_seo"]["noindex_paths"] = ["docs"]
	response = Response(
		b"", status=status, headers={"Location": "/docs/docs-overview"}, content_type="text/html"
	)
	before, after = run(response, path="/docs")
	assert before == after
