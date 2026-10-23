---
name: research
description: Find current facts and docs via websearch, webfetch/webcrawl, and Context7.
---

# Research skill

Use when the answer depends on fresh external facts, library APIs, or docs past your training cutoff. If the answer is in the repo, read it instead.

## Pipeline
1. **Library/framework APIs — Context7 first.** `context7_resolve` to get a library id, then `context7_docs`. Skip resolve when the user already gave `/org/project`.
2. **Everything else — search.** `websearch` with a precise query (include the version or year). Start with `urls_only` or `compact`, then fetch; do not pull full pages for every hit.
3. **Fetch.** `webfetch` the best 1–2 URLs. Use `preview_only` to screen a page before taking the body.
4. **Crawl last.** `webcrawl` only when the answer is spread across several pages of one site (a docs tree, an RFC split into sections).

## Freshness
- Treat training knowledge as stale for APIs, CLI flags, versions, and current events.
- Prefer official docs, release notes, and changelogs over blog posts.
- When the answer depends on what you fetched, cite the URL.

## Avoid
- Inventing MCP servers, tools, or flags that are not available
- Crawling when one fetch answers the question
- Searching the web for something `grep` can answer in the repo
- Quoting fetched content you did not actually read
