"""The header rules: `X-Robots-Tag: noindex, nofollow` on the service paths and on HTML error pages, never the body."""

import pytest
from conftest import fixture, html_response, make_request
from werkzeug.wrappers import Response

from wiki_seo import hook


def robots(response):
	return response.headers.getlist("X-Robots-Tag")


def run(response, path, **kwargs):
	hook.after_request(response=response, request=make_request(path, **kwargs))
	return response


@pytest.mark.parametrize("path", ["/login", "/login/", "/cart", "/me", "/update-password", "/LOGIN"])
@pytest.mark.parametrize("status", [200, 403, 404])
def test_a_service_path_gets_the_header_at_any_status(fossdoc, path, status):
	response = run(html_response(status=status), path)
	assert robots(response) == ["noindex, nofollow"]
	assert "X-Wiki-Seo" not in response.headers


def test_a_service_path_matches_its_sub_paths_and_ignores_the_query(fossdoc):
	fossdoc.local.conf["wiki_seo"]["noindex_paths"] = ["orders", "printview"]
	assert robots(run(html_response(), "/orders/SO-0001")) == ["noindex, nofollow"]
	assert robots(run(html_response(), "/printview", query_string="doctype=Sales+Order")) == [
		"noindex, nofollow"
	]
	assert robots(run(html_response(), "/ordersx")) == []
	assert robots(run(html_response(), "/docs/orders")) == []


def test_a_service_path_gets_the_header_on_json_too(fossdoc):
	response = Response(b"{}", content_type="application/json")
	assert robots(run(response, "/me")) == ["noindex, nofollow"]


@pytest.mark.parametrize("status", [400, 403, 404, 429, 500, 502])
def test_an_html_error_page_gets_the_header(fossdoc, status):
	body = b"<html><head><title>Not Found</title></head><body></body></html>"
	response = run(html_response(body, status=status), "/docs/no-such-page")
	assert robots(response) == ["noindex, nofollow"]
	assert response.get_data() == body  # the header rules never read or change the body


def test_a_wiki_404_page_is_not_rewritten(fossdoc):
	body = fixture("fossdoc_uk.html")
	response = run(html_response(body, status=404), "/docs/howto-change-localization")
	assert response.get_data() == body and "X-Wiki-Seo" not in response.headers


def test_a_json_error_gets_no_header(fossdoc):
	response = run(Response(b"{}", status=500, content_type="application/json"), "/some-page")
	assert robots(response) == []


def test_the_error_rule_can_be_switched_off(fossdoc):
	fossdoc.local.conf["wiki_seo"]["noindex_errors"] = False
	assert robots(run(html_response(status=404), "/nowhere")) == []
	assert robots(run(html_response(status=404), "/login")) == ["noindex, nofollow"]


def test_a_public_page_gets_no_header(fossdoc):
	assert robots(run(html_response(fixture("fossdoc_uk.html")), "/docs/howto-change-localization")) == []
	assert robots(run(html_response(), "/")) == []


@pytest.mark.parametrize("present", ["noindex, nofollow", "noindex,nofollow", "NOINDEX, NOFOLLOW"])
def test_the_header_is_added_once(fossdoc, present):
	response = html_response(status=404, headers={"X-Robots-Tag": present})
	run(response, "/login")
	run(response, "/login")
	assert robots(response) == [present]


def test_another_robots_value_gets_ours_next_to_it(fossdoc):
	response = html_response(status=404, headers={"X-Robots-Tag": "noarchive"})
	assert robots(run(response, "/x")) == ["noarchive", "noindex, nofollow"]
