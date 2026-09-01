"""Built-in Context7 docs tools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from kite.tools.context7 import make_context7_tools, query_docs, resolve_library


def _mock_response(payload: dict, *, status: int = 200) -> MagicMock:
    body = json.dumps(payload).encode()
    resp = MagicMock()
    resp.read.return_value = body
    resp.status = status
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


@patch("kite.tools.context7.urlopen")
def test_resolve_library_formats_results(mock_urlopen) -> None:
    mock_urlopen.return_value = _mock_response(
        {
            "results": [
                {"id": "/vercel/next.js", "title": "Next.js", "description": "React framework"},
            ]
        }
    )
    out = resolve_library("next.js", "app router middleware")
    assert out["ok"] is True
    assert "/vercel/next.js" in out["output"]
    assert out["library_id"] == "/vercel/next.js"


@patch("kite.tools.context7.urlopen")
def test_query_docs_formats_snippets(mock_urlopen) -> None:
    mock_urlopen.return_value = _mock_response(
        {
            "codeSnippets": [
                {
                    "codeTitle": "useState",
                    "codeList": [{"code": "const [x, setX] = useState(0)"}],
                }
            ],
            "infoSnippets": [{"content": "Hooks must run at top level."}],
        }
    )
    out = query_docs("/facebook/react", "How do I use useState?")
    assert out["ok"] is True
    assert "useState" in out["output"]
    assert "Hooks must run" in out["output"]


def test_make_context7_tools_returns_pair() -> None:
    tools = make_context7_tools()
    names = {t.name for t in tools}
    assert names == {"context7_resolve", "context7_docs"}
