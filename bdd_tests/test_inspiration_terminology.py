from pathlib import Path

import pytest
from pytest_bdd import given, scenarios, then, when

from codex_dream.console import ConsoleService
from codex_dream.knowledge import create_knowledge, load_item, record_event, render_lifecycle
from codex_dream.workspace import init_workspace


scenarios("../features/inspiration_terminology.feature")


def candidate_payload():
    return {
        "title": "Synthetic inspiration",
        "kind": "reusable_work",
        "confidence": "high",
        "frequency": "repeated",
        "scope": "project",
        "projects": ["fixture"],
        "task_refs": ["TASK-0001"],
        "observation": "A synthetic fixture repeats.",
        "evidence": ["Synthetic evidence."],
        "interpretation": "A helper may reduce repetition.",
        "cause": "agent_behavior",
        "impact": "The fixture is slower.",
        "recommended_action": "Create a helper.",
        "suggested_artifact": "script",
        "candidate_text_or_outline": "Validate then execute.",
        "limits_and_counterexamples": "Fixture only.",
        "validation_plan": "Observe three tasks.",
    }


@pytest.fixture
def context():
    return {}


@given("存在一个等待人工决定的 CAN 实体")
def proposed_can_entity(tmp_path, context):
    workspace = tmp_path / "workspace"
    init_workspace(workspace)
    item = create_knowledge(
        workspace / "knowledge",
        "Synthetic knowledge",
        "reusable_work",
        "project",
        "Synthetic summary.",
    )
    event = record_event(
        workspace / "knowledge",
        item["knowledge_id"],
        "candidate_proposed",
        candidate_payload(),
    )
    context.update(
        workspace=workspace,
        knowledge_id=item["knowledge_id"],
        event=event,
    )


@when("用户查看 Console 和改进追踪页面")
def inspect_console(context):
    service = ConsoleService(context["workspace"])
    static_root = Path(__file__).parents[1] / "codex_dream" / "console_static"
    context["improvement"] = service.improvements()["items"][0]
    context["console_copy"] = "\n".join(
        (static_root / name).read_text(encoding="utf-8")
        for name in ("index.html", "app.js")
    )


@then("用户可见的生命周期名称应为灵感")
def console_calls_it_inspiration(context):
    assert context["improvement"]["lifecycle_label"] == "灵感"


@then("页面不应继续把这个生命周期称为候选")
def console_avoids_candidate_copy(context):
    assert "候选" not in context["console_copy"]


@when("维护者阅读 Dream 的 Skill README 和报告模板")
def inspect_guides(context):
    root = Path(__file__).parents[1]
    paths = [
        root / "README.md",
        root / "skills/codex-dream/SKILL.md",
        root / "skills/codex-dream/references/knowledge-lifecycle.md",
        root / "templates/weekly-report.md",
    ]
    context["guides"] = {path: path.read_text(encoding="utf-8") for path in paths}


@then("这些指南应把 CAN 实体称为灵感")
def guides_call_it_inspiration(context):
    for path, content in context["guides"].items():
        assert "灵感" in content, path


@then("Skill 应说明 candidate 字段仍是兼容接口")
def skill_documents_compatibility(context):
    skill = next(
        content
        for path, content in context["guides"].items()
        if path.name == "SKILL.md"
    )
    assert "candidate_id" in skill
    assert "compatibility" in skill


@given("调用方仍使用 candidate_proposed 和 candidate_id")
def legacy_candidate_interface(tmp_path, context):
    root = tmp_path / "knowledge"
    item = create_knowledge(
        root,
        "Synthetic knowledge",
        "reusable_work",
        "project",
        "Synthetic summary.",
    )
    event = record_event(
        root,
        item["knowledge_id"],
        "candidate_proposed",
        candidate_payload(),
    )
    context.update(root=root, knowledge_id=item["knowledge_id"], event=event)


@when("知识生命周期记录并渲染这个实体")
def record_and_render(context):
    context["item"] = load_item(context["root"], context["knowledge_id"])
    context["rendered"] = render_lifecycle(context["item"])


@then("生成的稳定标识仍应使用 CAN 前缀")
def stable_can_identifier(context):
    assert context["event"]["data"]["candidate_id"].startswith("CAN-")


@then("内部 candidate 字段和值应保持可读")
def candidate_interface_remains_readable(context):
    candidate_id = context["event"]["data"]["candidate_id"]
    assert context["item"]["candidates"][0]["candidate_id"] == candidate_id
    assert candidate_id in context["rendered"]
