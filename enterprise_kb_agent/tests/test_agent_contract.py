from app.core.agent import ReActAgent, TOOL_SCHEMAS
from app.routers import agent_router
from app.schemas.request import ChatRequest


def test_public_agent_tools_do_not_include_system_execution():
    tool_names = {item["function"]["name"] for item in TOOL_SCHEMAS}

    assert {"knowledge_search", "summarize_document", "extract_keywords", "extract_metrics"} <= tool_names
    assert "shell_exec" not in tool_names
    assert "file_read" not in tool_names
    assert "file_write" not in tool_names
    assert "shell_exec" not in object.__new__(ReActAgent).tools


def test_legacy_agent_chat_router_uses_run(monkeypatch):
    class DummyAgent:
        def run(self, **kwargs):
            return {
                "session_id": kwargs["session_id"] or "generated-session",
                "answer": "ok",
                "sources": [],
                "tools": ["knowledge_search"],
            }

    monkeypatch.setattr(agent_router, "get_agent_service", lambda: DummyAgent())

    response = agent_router.chat(
        ChatRequest(
            question="ping",
            session_id="demo-session",
            document_id="doc-1",
            top_k=2,
            library="enterprise",
        )
    )

    assert response["code"] == 200
    assert response["data"]["session_id"] == "demo-session"
    assert response["data"]["tools"] == ["knowledge_search"]
