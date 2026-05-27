from app.core.tool_planner import LLMToolPlanner


class DummyLLM:
    def __init__(self, response: str | Exception):
        self.response = response

    def generate(self, *args, **kwargs) -> str:
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class DummyTool:
    args_schema = None

    def __init__(self, name: str, description: str = "test tool"):
        self.name = name
        self.description = description


def build_planner(response: str | Exception) -> LLMToolPlanner:
    tools = [
        DummyTool("knowledge_search_tool"),
        DummyTool("document_summary_tool"),
        DummyTool("keyword_extract_tool"),
        DummyTool("experiment_metric_tool"),
    ]
    return LLMToolPlanner(DummyLLM(response), tools)


def test_llm_plan_selects_and_orders_tools(monkeypatch):
    planner = build_planner(
        '{"tools": ["experiment_metric_tool"], "rationale": "用户要比较实验指标"}'
    )
    from app.core import tool_planner
    monkeypatch.setattr(tool_planner.settings, "enable_llm_tool_planner", True)

    plan = planner.plan("比较这篇论文中的实验指标", history=[], document_id=None)

    assert plan.planner == "llm"
    assert plan.tool_names == ["knowledge_search_tool", "experiment_metric_tool"]
    assert "实验指标" in plan.rationale


def test_invalid_llm_plan_falls_back_to_rules(monkeypatch):
    planner = build_planner(ValueError("model unavailable"))
    from app.core import tool_planner
    monkeypatch.setattr(tool_planner.settings, "enable_llm_tool_planner", True)

    plan = planner.plan("请总结这个文档", history=[], document_id=None)

    assert plan.planner == "rules_fallback"
    assert plan.tool_names == ["knowledge_search_tool", "document_summary_tool"]
