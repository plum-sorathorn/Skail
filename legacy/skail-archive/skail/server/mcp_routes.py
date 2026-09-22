"""RAG-as-MCP server endpoints and KnowledgeVectorStore singleton management."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from skail import __version__

logger = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2025-03-26"
SERVER_INFO = {"name": "skail", "version": __version__}

TOOLS_MANIFEST = [
    {
        "name": "skail_search",
        "description": (
            "Search indexed codebase symbols. Uses keyword-vector matching "
            "(not semantic embedding). Run skail_index first."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "number", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "skail_index",
        "description": (
            "Index a directory into the Skail knowledge base. "
            "Call before skail_search on a new project."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "root_dir": {"type": "string"},
                "max_files": {"type": "number", "default": 50},
            },
            "required": ["root_dir"],
        },
    },
]

_store_singleton: Any | None = None
_indexed_at: str | None = None


def _get_vector_store() -> Any:
    """Retrieve or lazily initialize the KnowledgeVectorStore singleton."""
    global _store_singleton
    if _store_singleton is not None:
        return _store_singleton

    try:
        from skail.config.manager import get_config

        cfg = get_config()
        selection = getattr(cfg, "selection", None)
        rag_db_path = (
            getattr(selection, "rag_db_path", "~/.skail/rag_db")
            if selection is not None
            else "~/.skail/rag_db"
        )
        db_uri = str(Path(rag_db_path).expanduser())
    except Exception:
        db_uri = ":memory:"

    try:
        from skail.knowledge.vector_store import KnowledgeVectorStore

        _store_singleton = KnowledgeVectorStore(db_uri=db_uri)
    except Exception as exc:
        logger.warning(
            "Failed to initialize KnowledgeVectorStore at %s, fallback to :memory:: %s",
            db_uri,
            exc,
        )
        try:
            from skail.knowledge.vector_store import KnowledgeVectorStore

            _store_singleton = KnowledgeVectorStore(db_uri=":memory:")
        except Exception:
            _store_singleton = None
    return _store_singleton


def reset_mcp_singleton(store: Any | None = None) -> None:
    """Reset the MCP vector store singleton and indexed timestamp for testing."""
    global _store_singleton, _indexed_at
    _store_singleton = store
    _indexed_at = None


async def _mcp_manifest_handler(request: Request) -> JSONResponse:
    """Return the MCP server manifest with capabilities and tool descriptors."""
    try:
        return JSONResponse(
            content={
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "serverInfo": SERVER_INFO,
                "indexed_at": _indexed_at,
                "tools": TOOLS_MANIFEST,
            }
        )
    except Exception as exc:
        logger.warning("Error generating MCP manifest: %s", exc)
        return JSONResponse(
            content={
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "serverInfo": SERVER_INFO,
                "indexed_at": None,
                "tools": TOOLS_MANIFEST,
            }
        )


async def _mcp_tools_call_handler(request: Request) -> JSONResponse:
    """Handle MCP tool invocation for skail_search and skail_index."""
    global _indexed_at
    try:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                content={"status": "error", "error": "invalid_json", "results": []}
            )

        if not isinstance(body, dict):
            return JSONResponse(
                content={"status": "error", "error": "invalid_json", "results": []}
            )

        tool_name = str(body.get("tool") or body.get("name") or "").strip()
        args = body.get("args")
        if not isinstance(args, dict):
            args = body.get("arguments")
        if not isinstance(args, dict):
            args = {
                k: v
                for k, v in body.items()
                if k not in ("tool", "name", "args", "arguments")
            }

        if tool_name == "skail_search":
            query = args.get("query")
            if not query:
                return JSONResponse(
                    content={
                        "results": [],
                        "content": [
                            {
                                "type": "text",
                                "text": "Error: 'query' parameter is required.",
                            }
                        ],
                        "error": "missing_query",
                    }
                )
            try:
                limit = int(args.get("limit", 5))
            except (ValueError, TypeError):
                limit = 5

            store = _get_vector_store()
            if store is None:
                return JSONResponse(
                    content={
                        "results": [],
                        "content": [
                            {"type": "text", "text": "Knowledge store unavailable."}
                        ],
                    }
                )

            results = store.search(query=str(query), limit=limit)
            formatted_results = []
            for r in results or []:
                chunk = getattr(r, "chunk", None)
                if chunk is None:
                    continue
                formatted_results.append(
                    {
                        "id": getattr(chunk, "id", ""),
                        "symbol": getattr(chunk, "symbol", ""),
                        "file": getattr(chunk, "file", ""),
                        "content": getattr(chunk, "content", ""),
                        "score": float(getattr(r, "score", 0.0)),
                        "distance": float(getattr(r, "distance", 0.0)),
                        "metadata": getattr(chunk, "metadata", {}),
                    }
                )

            if formatted_results:
                text_lines = [
                    f"[{r['file']} : {r['symbol']}]\n{r['content']}"
                    for r in formatted_results
                ]
                text_content = "\n\n".join(text_lines)
            else:
                text_content = "No matching symbols found."

            return JSONResponse(
                content={
                    "results": formatted_results,
                    "content": [{"type": "text", "text": text_content}],
                }
            )

        elif tool_name == "skail_index":
            root_dir = args.get("root_dir")
            if not root_dir:
                return JSONResponse(
                    content={
                        "status": "error",
                        "error": "missing_root_dir",
                        "indexed_files": 0,
                        "indexed_at": _indexed_at,
                    }
                )
            try:
                max_files = int(args.get("max_files", 50))
            except (ValueError, TypeError):
                max_files = 50

            store = _get_vector_store()
            if store is None:
                return JSONResponse(
                    content={
                        "status": "error",
                        "error": "store_unavailable",
                        "indexed_files": 0,
                        "indexed_at": _indexed_at,
                    }
                )

            count = store.index_repository(root_dir=root_dir, max_files=max_files)
            _indexed_at = datetime.now(timezone.utc).isoformat()
            return JSONResponse(
                content={
                    "status": "ok",
                    "indexed_files": count,
                    "indexed_at": _indexed_at,
                    "content": [
                        {
                            "type": "text",
                            "text": f"Successfully indexed {count} symbols from {root_dir}",
                        }
                    ],
                }
            )

        else:
            return JSONResponse(
                content={
                    "status": "error",
                    "error": f"unknown_tool: {tool_name}",
                    "results": [],
                }
            )

    except Exception as exc:
        logger.warning("mcp tool call error: %s", exc)
        return JSONResponse(
            content={
                "status": "error",
                "error": str(exc)[:2000],
                "results": [],
            }
        )


def install_mcp_routes(app: Any) -> Any:
    """Mount MCP server endpoints onto the FastAPI app. Never raises."""
    try:
        app.add_api_route("/mcp", _mcp_manifest_handler, methods=["GET"])
    except Exception as exc:
        logger.warning("mount /mcp failed: %s", exc)
    try:
        app.add_api_route("/mcp/tools/call", _mcp_tools_call_handler, methods=["POST"])
    except Exception as exc:
        logger.warning("mount /mcp/tools/call failed: %s", exc)
    return app
