# frappe-wiki-seo

Server-side SEO for Frappe Wiki pages: lang, hreflang, title suffix and X-Robots-Tag through an after_request hook.

The Frappe app `wiki_seo` (Frappe v15, the Wiki app of `frappe/wiki`). It does nothing until a site has the site config key
`wiki_seo`; with the key it fixes the HTML of the Wiki pages as they are served and adds `X-Robots-Tag` to the error
pages and the service pages of the site. It does not import, change or fork the Wiki app.

Status: **under construction, not installed on any site yet.** The plan and the deploy side (the release group, the
playbook that installs the app and writes the key) are in the infrastructure repository `tasmail/erpnext-infra`.

## Why

The template of the Wiki (`wiki/doctype/wiki_page/templates/base.html`) writes `<html lang="en">` on every page whatever
the language of the space, takes the `language` meta from the site, prints no `hreflang` links, writes the page title
without the name of the site and no `og:site_name`, and points the logo either to the space route (a 301 to its first
page) or, when the space has no logo, to `" /"` (the site root, with a space). A script in the browser can fix the
rendered page, but a crawler that does not run scripts sees the template. This app makes the same fixes in the response
itself.

## How it works

One hook, `after_request` (`wiki_seo.hook.after_request`). Frappe calls it for every request after the response is made,
also for a page that came from the page cache or the HTML cache of the Wiki, so a cached page is fixed too and switching the
hook on or off needs no cache clear. The whole hook is wrapped in `try/except`: an error is logged
(`frappe.logger("wiki_seo")`) and the response stays exactly as it was. All changes are computed first and applied at the
end: the headers, then one `response.set_data()`.

**Guards**, in this order; each leaves the response untouched:

1. no `wiki_seo` key, or `enabled: false` (the kill switch);
2. no response (Frappe passes `None` after an `HTTPException` such as `NotFound`);
3. a host that is not in `hosts` (lower case, the port dropped);
4. a method other than `GET` or `HEAD`;
5. a `direct_passthrough` or streamed response (files, downloads);
6. a body with `Content-Encoding`;
7. a path under `/api`, `/app`, `/desk`, `/assets`, `/files`, `/private`, `/socket.io` (whole path segments);
8. any redirect (3xx).

**Header rules** (the body is not read): `X-Robots-Tag: noindex, nofollow` is added to a response whose first path segment
is in `noindex_paths` (any status, the case ignored: `/login`, `/orders/SO-0001`), and to an HTML response with a status
of 400 or more (`noindex_errors`). It is not added when the response already has that value.

**Body rules**, only for a `200` `text/html` (UTF-8) response whose path is a published page in the sidebar of a configured
space (so the editor, the revisions, a new page, a patch preview and every non-Wiki page never match; the query arguments
`editWiki`, `newWiki` and `wikiPagePatch` are skipped too), only in the `<head>` and in the first navbar anchor:

- `<html lang>` and `<meta name="language">` = the language of the space;
- after the canonical link, one `<link rel="alternate" hreflang="..." href="<base_url>/<space>/<slug>" data-fd-hreflang>`
  per space that publishes the same slug, then `x-default` (`x_default`, or the first language of the slug when it has
  no page in that language); only for a slug that two or more spaces publish, and not when such links are already there
  (a browser script that removes and adds `data-fd-hreflang` links does not make duplicates);
- `<title>` + `title_suffix`, unless the title already ends with it;
- `<meta property="og:site_name">` = `site_name`, unless the page has one;
- the logo anchor (`class="navbar-brand"`, its attributes may span lines) points to the first page of the sidebar of the
  space, for both branches of the template.

A missing element skips its rule only. A rewritten page carries `X-Wiki-Seo: 1`. The rewrite is idempotent.

**Route map.** `{route: (space, slug)}` and the first page of each sidebar, made by two `frappe.get_all` queries (the
sidebars of the Wiki Spaces, the published Wiki Pages) and kept in `frappe.cache` under `wiki_seo:routes` for 600 s. The
`doc_events` of Wiki Page (`on_update`, `on_trash`, `after_rename`) and Wiki Space (`on_update`, `on_trash`) delete the
key. A change that fires no document event (SQL, a patch) shows after at most 600 s.

## Configuration

The site config key `wiki_seo` (one JSON object), read on every request: a change needs no restart. A missing or malformed
field takes the default; unknown fields are ignored.

| Field | Meaning | Default |
| --- | --- | --- |
| `enabled` | `false` (or `0`, `"off"`) turns the hook off: the kill switch | on |
| `hosts` | the host names the hook acts on; any other host of the site is left alone | none (the hook does nothing) |
| `base_url` | the canonical origin of the `hreflang` links | `""` |
| `spaces` | space route -> language, e.g. `{"docs": "uk", "ru/docs": "ru", "en/docs": "en"}`; the order is the order of the links | none (no body rule) |
| `x_default` | the language of `x-default` | `"uk"` |
| `title_suffix` | appended to `<title>`, e.g. `" \| Example"` | none |
| `site_name` | the value of `og:site_name` | none |
| `noindex_paths` | first path segments that get `X-Robots-Tag`, e.g. `["login", "cart"]` | none |
| `noindex_errors` | `X-Robots-Tag` on HTML responses with a status of 400 or more | `true` |

Example:

```json
{
  "wiki_seo": {
    "enabled": true,
    "hosts": ["www.example.com", "example.com"],
    "base_url": "https://www.example.com",
    "spaces": {"docs": "uk", "ru/docs": "ru", "en/docs": "en"},
    "x_default": "uk",
    "title_suffix": " | Example",
    "site_name": "Example",
    "noindex_paths": ["login", "update-password", "me"],
    "noindex_errors": true
  }
}
```

## Cost

A request that a guard or the header rules settle costs a config read and a few comparisons: no query and no Redis call.
Any other `200` HTML page of a configured host costs one `frappe.cache` read (the route map); a Wiki page then a few regular
expressions over the head and up to the logo anchor and one `set_data` (`tests/test_performance.py` pins a 600 KB page
under 5 ms).

## Removing it

Switch it off with `enabled: false` first. Uninstall the app from every site that has it before the code leaves the
bench image.

## Development

```
pip install werkzeug==3.1.9 ruff==0.17.3 pytest==9.2.0 pytest-cov==7.1.0 tomli
ruff check . && ruff format --check .
pytest --cov
```

The unit tests run without a bench against a `frappe` stub (`tests/conftest.py`) and real werkzeug responses. The
fixtures in `tests/fixtures/` are the head and the navbar of Wiki pages as two sites served them (cut by
`scripts/cut_fixture.py`), the pages and language pairs of the documentation publisher of the infrastructure repository
(`pairs.json`: the parity of the `hreflang` pairs with its browser script) and the configuration its deploy script writes
(`infra_config.json`: the contract between the two sides).

## License

MIT, see `LICENSE`.
