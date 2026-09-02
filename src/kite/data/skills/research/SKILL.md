---
name: research
description: Find current facts and docs via websearch, webfetch/webcrawl, and Context7.
---

# Research skill

Use when you need fresh external info, library APIs, or docs beyond training cutoff.

## Pipeline
1. Prefer **Context7** for framework/library APIs: `context7_resolve` → `context7_docs` (or skip resolve if the user gave `/org/project`).
2. Otherwise `websearch` with a precise query (include version/year when relevant).
3. `webfetch` the best 1–2 URLs for full text.
4. `webcrawl` only when you need several related pages on the same site (docs tree, RFC sections).

## Freshness
- Treat training knowledge as stale for APIs, CLI flags, and current events.
- Prefer official docs, release notes, and changelogs over blogs.
- Cite the URL you relied on when the answer depends on fetched content.

## Avoid
- Inventing MCP servers or tools that are not available
- Crawling when a single fetch answers the question
- Searching when the answer is already in the repo (read/grep first)
