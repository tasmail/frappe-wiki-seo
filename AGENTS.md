# AGENTS.md

Rules for AI coding agents and humans working in this repository. The plan of the app is in `tasmail/erpnext-infra`
(the Wiki SEO plan, part (a)); the rules of that repository's `AGENTS.md` apply here too.

## Scope and status

The app fixes the served HTML of the Wiki pages of a Frappe v15 site (`<html lang>`, the language meta, the `hreflang`
links, the title suffix, `og:site_name`, the logo link) and adds `X-Robots-Tag` to the service paths and the HTML error
pages, through one `after_request` hook. It does not import or change the Wiki app, and it touches no other page. Do not
widen it (Builder pages, other headers, other sites' templates) without the owner's word.
Built: the hook, the route map, the unit tests. Nothing is installed on a site yet. The deploy side (the release group, the
playbook that installs the app and writes the site config key `wiki_seo`) is in `tasmail/erpnext-infra`; the README of
this repository says what the app does, how and why.

## How work is done

Every task, however small, goes through these steps:

1. **Analysis.** Read the code, the docs and the real state; write down what is known and what is not.
2. **Grilling.** Put every decision the analysis could not settle to the owner, in rounds, each with a recommended answer.
   If none is open, say "no open decisions".
3. **Plan**, in writing: scope, non-goals, files, side effects, risks, rollback, verification, decisions for the owner.
4. **Plan review** by an independent reviewer (a person or a fresh agent session with no shared context, given the plan and
   the sources, not the author's conclusions): APPROVE or CHANGES-NEEDED. The author reading their own plan is not a review.
5. **Implementation** on a branch, only after step 4.
6. **Pull request** with the plan and the plan review in the description. It is reviewed on its exact current head by an
   independent reviewer; the review is a PR comment naming the head SHA. A later commit needs a new review.
7. **Merge** only on the owner's command, only the reviewed head, after checking the PR state and CI.
8. **Deploy** (a bench build, installing the app on a site, writing or switching the site config key) only on the owner's
   explicit command, each time, QA before production. The deploy tooling lives in `tasmail/erpnext-infra`.

Plan approval never authorises a side effect, a merge or a deploy. Nothing is pushed to `main`; check a PR with
`gh pr view <n> --json state,headRefName` before touching it, and never reuse a merged or closed branch.

## Rules

- **English everywhere** in the repository: code, comments, commits, PRs, docs, messages. No AI attribution, no
  `Co-Authored-By`, no session links, no model names.
- **Secrets never reach the console, a log, the model or a commit.** The app needs none; CI has none and runs on
  GitHub-hosted runners with `pull_request` (never `pull_request_target`), because the repository is public.
- **Never end with uncommitted changes**: commit and push on a branch, or ask.
- **Do not claim what is not true** in the README or the texts (no ranking, compatibility or performance claims that are
  not tested).
- **The hook never fails a request**: everything stays inside its `try/except`, all changes are computed before any is
  applied, one `set_data()`. A new rule gets a test that an error inside it leaves the response byte-identical.
- **The configuration is a contract** with `press/wiki_seo_site.py` of `tasmail/erpnext-infra`:
  `tests/fixtures/infra_config.json` holds what that script writes. Change both sides together and refresh the fixture.
- Fixtures are cut from served pages (`scripts/cut_fixture.py`), never written by hand; a Wiki upgrade (a new commit of
  `frappe/wiki`) means new fixtures and a check of the anchors.

## Code conventions

- Frappe v15 only (`frappe>=15,<16` in `[tool.bench.frappe-dependencies]`, `dependencies = []` in `pyproject.toml`), flit,
  Python `>=3.10`.
- **Tabs**, line length 110 (`ruff format`).
- Commit messages: one imperative English sentence without a prefix ("Add ...", "Fix ..."), one logical change per commit.
- Unit tests run without a bench against a `frappe` stub (`tests/conftest.py`) and real werkzeug responses; coverage
  stays at 90 % or more.
- Format and lint locally before a push; run the regression tests in PR CI on the exact head.
