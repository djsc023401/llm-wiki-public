from __future__ import annotations

from collections.abc import Mapping

from .chat_search import run_chat_search
from .chat_store import append_chat_turn, build_chat_context_from_session, get_chat_session
from .config import Settings, load_settings


def ask_chat(
    query: str,
    *,
    limit: int = 8,
    session_id: str | None = None,
    context: Mapping[str, object] | None = None,
    source: str = "web",
    create_session_if_missing: bool = False,
    settings: Settings | None = None,
) -> dict:
    """Run chat retrieval/answering and persist the resulting turn."""
    resolved = settings or load_settings()
    chat_context = dict(context) if isinstance(context, Mapping) else None
    if session_id:
        session = get_chat_session(session_id, settings=resolved)
        if session is None:
            if not create_session_if_missing:
                raise ValueError("chat_session_not_found")
        elif chat_context is None:
            chat_context = build_chat_context_from_session(session_id, settings=resolved)

    result = run_chat_search(query, limit=int(limit), settings=resolved, context=chat_context)
    conversation = append_chat_turn(
        query=query,
        result=result,
        session_id=session_id,
        source=source,
        create_session_if_missing=create_session_if_missing,
        settings=resolved,
    )
    latest_turn = conversation.get("turns", [])[-1] if conversation.get("turns") else {}
    response = dict(result)
    response["session_id"] = conversation["id"]
    response["turn_id"] = latest_turn.get("id")
    response["conversation"] = conversation
    return response
