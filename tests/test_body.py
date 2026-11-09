"""The body rules on the head and navbar of Wiki pages as www.fossdoc.com and erp.foss.ua served them (Wiki 2372f859f6)."""

import re

import pytest
from conftest import FOSSDOC, fixture, html_response, make_request

from wiki_seo import hook

SLUG = "howto-change-localization"
BASE = "https://www.fossdoc.com"


def rewrite(body: bytes, path: str, host="www.fossdoc.com", query_string=None):
	response = html_response(body)
	hook.after_request(response=response, request=make_request(path, host=host, query_string=query_string))
	return response


def head(data: bytes) -> str:
	return data[: data.index(b"</head>")].decode()


def hreflang(data: bytes) -> list:
	return re.findall(
		r'<link rel="alternate" hreflang="([^"]+)" href="([^"]+)" data-fd-hreflang>', head(data)
	)


def brand(data: bytes) -> str:
	return re.search(r'<a class="navbar-brand".*?>', data.decode(), re.DOTALL).group(0)


@pytest.mark.parametrize(
	("name", "space", "language", "title"),
	[
		("fossdoc_uk.html", "docs", "uk", "Зміна локалізації СЕД"),
		("fossdoc_ru.html", "ru/docs", "ru", "Изменение локализации СЭД"),
		("fossdoc_en.html", "en/docs", "en", "How to Change Localization Settings in FossDoc"),
	],
)
def test_a_served_page_of_each_language_is_fixed(fossdoc, name, space, language, title):
	original = fixture(name)
	response = rewrite(original, f"/{space}/{SLUG}")
	data = response.get_data()
	text = head(data)
	assert response.headers["X-Wiki-Seo"] == "1"
	assert re.search(r"<html[^>]*>", text).group(0) == f'<html lang="{language}">'
	assert re.findall(r'<meta name="language"[^>]*>', text) == [
		f'<meta name="language" content="{language}">'
	]
	assert re.findall(r"<title>(.*?)</title>", text) == [f"{title} | FossDoc"]
	assert text.count('property="og:site_name"') == 1
	assert (
		f'<meta property="og:title"  content="{title}"><meta property="og:site_name" content="FossDoc">'
		in text
	)
	assert hreflang(data) == [
		("uk", f"{BASE}/docs/{SLUG}"),
		("ru", f"{BASE}/ru/docs/{SLUG}"),
		("en", f"{BASE}/en/docs/{SLUG}"),
		("x-default", f"{BASE}/docs/{SLUG}"),
	]
	canonical = f'<link rel="canonical" href="{BASE}/{space}/{SLUG}">'
	assert f'{canonical}<link rel="alternate" hreflang="uk"' in text
	# the logo: the multi-line attributes are kept, only the href changes
	assert brand(data) == (
		f'<a class="navbar-brand" alt="Go to home page" data-prefix=""\n      href="/{space}/docs-overview">'
	)
	# nothing else changes: the tail after the logo anchor is byte-identical
	assert (
		data[data.index(b"</a>", data.index(b'class="navbar-brand"')) :]
		== original[original.index(b"</a>", original.index(b'class="navbar-brand"')) :]
	)
	assert len(response.get_data()) == int(response.headers["Content-Length"])


def test_the_rewrite_is_idempotent(fossdoc):
	path = f"/ru/docs/{SLUG}"
	once = rewrite(fixture("fossdoc_ru.html"), path).get_data()
	again = rewrite(once, path)
	assert again.get_data() == once
	assert "X-Wiki-Seo" not in again.headers  # nothing was left to change
	response = html_response(fixture("fossdoc_ru.html"))
	for _ in range(3):
		hook.after_request(response=response, request=make_request(path))
	assert response.get_data() == once


def test_the_page_without_a_space_logo_points_the_logo_to_the_first_page(frappe_stub):
	frappe_stub.local.conf["wiki_seo"] = {
		**FOSSDOC,
		"hosts": ["erp.foss.ua", "www.erp.foss.ua", "erp-internal.wiki.example.org"],
		"base_url": "https://erp.foss.ua",
		"title_suffix": " | ERP FOSS",
		"site_name": "ERP FOSS",
	}
	frappe_stub.wiki.add_space("docs", ["erp-overview", "avansovi-platezhi"])
	frappe_stub.wiki.add_space("en/docs", ["avansovi-platezhi"])
	original = fixture("erpfoss_uk.html")
	assert b'href=" /"><span>Home</span>' in original  # the template's fallback, with a space
	data = rewrite(original, "/docs/avansovi-platezhi", host="ERP.foss.ua:443").get_data()
	assert (
		brand(data)
		== '<a class="navbar-brand" alt="Go to home page" data-prefix=""\n      href="/docs/erp-overview">'
	)
	assert b'href="/docs/erp-overview"><span>Home</span></a>' in data
	assert '<meta name="language" content="uk">' in head(data)
	assert re.findall(r"<title>(.*?)</title>", head(data)) == ["Авансові платежі | ERP FOSS"]
	assert hreflang(data) == [
		("uk", "https://erp.foss.ua/docs/avansovi-platezhi"),
		("en", "https://erp.foss.ua/en/docs/avansovi-platezhi"),
		("x-default", "https://erp.foss.ua/docs/avansovi-platezhi"),
	]


def test_a_page_of_one_space_gets_no_hreflang(fossdoc):
	data = rewrite(fixture("fossdoc_uk.html"), "/docs/uk-only").get_data()
	assert hreflang(data) == []
	assert '<html lang="uk">' in head(data)


def test_x_default_falls_back_to_the_first_language_without_uk(fossdoc):
	data = rewrite(fixture("fossdoc_ru.html"), "/ru/docs/ru-en").get_data()
	assert hreflang(data) == [
		("ru", f"{BASE}/ru/docs/ru-en"),
		("en", f"{BASE}/en/docs/ru-en"),
		("x-default", f"{BASE}/ru/docs/ru-en"),
	]


def test_the_links_of_the_browser_script_are_not_duplicated(fossdoc):
	body = fixture("fossdoc_uk.html").replace(
		b"</head>", b'<link rel="alternate" hreflang="uk" href="/docs/x" data-fd-hreflang>\n</head>'
	)
	data = rewrite(body, f"/docs/{SLUG}").get_data()
	assert len(hreflang(data)) == 1


def test_the_script_text_that_names_the_links_is_not_taken_for_a_link(fossdoc):
	body = fixture("fossdoc_uk.html")
	assert body.count(b"data-fd-hreflang") >= 2  # in the Wiki Settings script of the body
	assert len(hreflang(rewrite(body, f"/docs/{SLUG}").get_data())) == 4


def test_a_title_with_the_suffix_and_an_og_site_name_are_kept(fossdoc):
	body = (
		fixture("fossdoc_uk.html")
		.replace(b"<title>\xd0\x97", b"<title>X | FossDoc</title><!--")
		.replace(
			b'<meta property="og:type"',
			b'<meta property="og:site_name" content="Own"><meta property="og:type"',
		)
	)
	text = head(rewrite(body, f"/docs/{SLUG}").get_data())
	assert re.findall(r"<title>(.*?)</title>", text)[0] == "X | FossDoc"
	assert re.findall(r'property="og:site_name" content="([^"]*)"', text) == ["Own"]


@pytest.mark.parametrize(
	("path", "query"),
	[
		(f"/docs/{SLUG}/edit-wiki", None),
		(f"/docs/{SLUG}/revisions", None),
		("/docs/new-wiki", None),
		(f"/docs/{SLUG}", "editWiki=1&wikiPagePatch=abc"),
		(f"/docs/{SLUG}", "newWiki=1"),
		("/docs", None),
		("/", None),
		("/product", None),
	],
)
def test_pages_outside_the_route_map_or_in_the_editor_are_not_rewritten(fossdoc, path, query):
	body = fixture("fossdoc_uk.html")
	response = rewrite(body, path, query_string=query)
	assert response.get_data() == body and "X-Wiki-Seo" not in response.headers


def test_a_query_string_of_a_reader_does_not_stop_the_rewrite(fossdoc):
	response = rewrite(fixture("fossdoc_uk.html"), f"/docs/{SLUG}", query_string="utm_source=x")
	assert response.headers.get("X-Wiki-Seo") == "1"


def test_a_space_outside_the_config_is_not_rewritten(fossdoc):
	fossdoc.wiki.add_space("doc", ["other-page"])
	body = fixture("fossdoc_uk.html")
	assert rewrite(body, "/doc/other-page").get_data() == body


def test_no_spaces_in_the_config_means_no_body_rule_and_no_query(fossdoc):
	fossdoc.local.conf["wiki_seo"]["spaces"] = {}
	body = fixture("fossdoc_uk.html")
	assert rewrite(body, f"/docs/{SLUG}").get_data() == body
	assert fossdoc.wiki.queries == []


def test_a_missing_anchor_skips_only_that_rule(fossdoc):
	body = fixture("fossdoc_uk.html").replace(b'class="navbar-brand"', b'class="brand"')
	response = rewrite(body, f"/docs/{SLUG}")
	data = response.get_data()
	assert response.headers["X-Wiki-Seo"] == "1" and '<html lang="uk">' in head(data)
	assert data[data.index(b"</head>") :] == body[body.index(b"</head>") :]


def test_a_page_with_only_the_anchor_to_fix_is_rewritten(fossdoc):
	body = (
		b'<html lang="uk"><head><meta name="language" content="uk"></head>'
		b'<body><a\n  href="/docs"\n  class="x navbar-brand y">L</a><a class="navbar-brand" href="/z">2</a></body></html>'
	)
	data = rewrite(body, "/docs/uk-only").get_data()
	assert data.endswith(
		b'<a\n  href="/docs/docs-overview"\n  class="x navbar-brand y">L</a><a class="navbar-brand" href="/z">2</a></body></html>'
	)


def test_an_anchor_without_href_gets_one(fossdoc):
	body = b"<html><head></head><body><a class='navbar-brand'>L</a></body></html>"
	data = rewrite(body, "/docs/uk-only").get_data()
	assert b"<a href=\"/docs/docs-overview\" class='navbar-brand'>L</a>" in data


def test_a_navbar_brand_container_is_not_the_anchor(fossdoc):
	body = b'<html><head></head><body><a class="navbar-brand-container" href="/q">x</a></body></html>'
	assert b'href="/q"' in rewrite(body, "/docs/uk-only").get_data()


def test_missing_tags_are_handled(fossdoc):
	body = b"<head></head><body></body>"
	data = rewrite(body, f"/docs/{SLUG}").get_data()
	assert data.startswith(b'<head><meta name="language" content="uk">\n<link rel="alternate" hreflang="uk"')
	assert b'<meta property="og:site_name" content="FossDoc"></head>' in data


def test_a_page_without_a_head_end_is_not_rewritten(fossdoc):
	body = b"<html><body>no head</body></html>"
	assert rewrite(body, f"/docs/{SLUG}").get_data() == body


def test_a_charset_other_than_utf8_is_not_rewritten(fossdoc):
	response = html_response(fixture("fossdoc_uk.html"))
	response.headers["Content-Type"] = "text/html; charset=windows-1251"
	body = response.get_data()
	hook.after_request(response=response, request=make_request(f"/docs/{SLUG}"))
	assert response.get_data() == body


def test_an_html_tag_without_lang_gets_it(fossdoc):
	data = rewrite(b"<html class='a'><head></head></html>", "/docs/uk-only").get_data()
	assert data.startswith(b"<html lang=\"uk\" class='a'>")


def test_values_are_escaped(fossdoc):
	fossdoc.local.conf["wiki_seo"]["title_suffix"] = " | A&B <x>"
	fossdoc.local.conf["wiki_seo"]["site_name"] = 'A "B"'
	text = head(rewrite(b"<html><head><title>T</title></head></html>", "/docs/uk-only").get_data())
	assert "<title>T | A&amp;B &lt;x&gt;</title>" in text
	assert 'content="A &quot;B&quot;"' in text


def test_an_error_inside_a_rule_leaves_the_response_byte_identical(fossdoc, monkeypatch):
	def broken(*args):
		raise ValueError("boom")

	monkeypatch.setattr(hook, "set_logo_href", broken)
	response = html_response(fixture("fossdoc_uk.html"))
	before = (response.status_code, list(response.headers.items()), response.get_data())
	hook.after_request(response=response, request=make_request(f"/docs/{SLUG}"))
	assert (response.status_code, list(response.headers.items()), response.get_data()) == before
	assert fossdoc.log.lines == ["wiki_seo: a body rule failed, the body is left as it was"]


def test_an_error_inside_a_body_rule_keeps_the_header_rule(fossdoc, monkeypatch):
	monkeypatch.setattr(hook, "add_title_suffix", lambda *args: 1 / 0)
	fossdoc.local.conf["wiki_seo"]["noindex_paths"] = ["docs"]
	body = fixture("fossdoc_uk.html")
	response = html_response(body)
	hook.after_request(response=response, request=make_request(f"/docs/{SLUG}"))
	assert response.headers.getlist("X-Robots-Tag") == ["noindex, nofollow"]
	assert response.get_data() == body and "X-Wiki-Seo" not in response.headers


def test_an_error_outside_the_body_rules_leaves_the_response_untouched(fossdoc, monkeypatch):
	monkeypatch.setattr(hook, "header_rules", lambda *args: 1 / 0)
	response = html_response(fixture("fossdoc_uk.html"))
	before = (list(response.headers.items()), response.get_data())
	hook.after_request(response=response, request=make_request(f"/docs/{SLUG}"))
	assert (list(response.headers.items()), response.get_data()) == before
	assert fossdoc.log.lines == ["wiki_seo: the hook failed, the response is left as it was"]


def test_a_broken_logger_does_not_leave_the_hook(fossdoc, monkeypatch):
	monkeypatch.setattr(hook, "header_rules", lambda *args: 1 / 0)
	monkeypatch.setattr(fossdoc, "logger", lambda name=None: 1 / 0)
	hook.after_request(response=html_response(), request=make_request("/x"))  # does not raise


def test_a_repeated_failure_is_logged_once_a_minute(fossdoc, monkeypatch):
	monkeypatch.setattr(hook, "set_logo_href", lambda *args: 1 / 0)
	for _ in range(5):
		hook.after_request(
			response=html_response(fixture("fossdoc_uk.html")), request=make_request(f"/docs/{SLUG}")
		)
	assert len(fossdoc.log.lines) == 1
	clock = [hook.time.monotonic() + 61]
	monkeypatch.setattr(hook.time, "monotonic", lambda: clock[0])
	hook.after_request(
		response=html_response(fixture("fossdoc_uk.html")), request=make_request(f"/docs/{SLUG}")
	)
	assert len(fossdoc.log.lines) == 2


def test_a_space_route_is_matched_without_the_case(fossdoc):
	response = rewrite(fixture("fossdoc_uk.html"), f"/Docs/{SLUG.upper()}")
	assert response.headers.get("X-Wiki-Seo") == "1"
	fossdoc.local.conf["wiki_seo"]["spaces"] = {"DOCS": "uk", "ru/docs": "ru"}
	assert rewrite(fixture("fossdoc_uk.html"), f"/docs/{SLUG}").headers.get("X-Wiki-Seo") == "1"


def test_slugs_are_percent_quoted_and_escaped_in_urls(frappe_stub):
	frappe_stub.local.conf["wiki_seo"] = dict(FOSSDOC)
	frappe_stub.wiki.add_space("docs", ['a"b<c>д', "x"])
	frappe_stub.wiki.add_space("ru/docs", ['a"b<c>д'])
	data = rewrite(
		b'<html><head></head><body><a class="navbar-brand" href="/">L</a></body></html>', "/docs/x"
	).get_data()
	assert b'href="/docs/a%22b%3Cc%3E%D0%B4"' in data  # the logo: the first page of the sidebar
	text = head(rewrite(b"<html><head></head></html>", "/docs/" + 'a"b<c>д').get_data())
	assert 'hreflang="ru" href="https://www.fossdoc.com/ru/docs/a%22b%3Cc%3E%D0%B4"' in text


def test_two_spaces_of_one_language_give_one_link_of_it(frappe_stub):
	frappe_stub.local.conf["wiki_seo"] = {
		**FOSSDOC,
		"spaces": {"docs": "uk", "old/docs": "uk", "en/docs": "en"},
	}
	frappe_stub.wiki.add_space("docs", ["only-old"])
	frappe_stub.wiki.add_space("old/docs", ["p", "only-old"])
	frappe_stub.wiki.add_space("en/docs", ["p"])
	assert hreflang(rewrite(b"<html><head></head></html>", "/en/docs/p").get_data()) == [
		("uk", f"{BASE}/old/docs/p"),
		("en", f"{BASE}/en/docs/p"),
		("x-default", f"{BASE}/old/docs/p"),
	]
	assert hreflang(rewrite(b"<html><head></head></html>", "/docs/only-old").get_data()) == []
