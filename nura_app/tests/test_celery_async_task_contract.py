import ast
from pathlib import Path


TASKS_PATH = Path(__file__).parents[1] / "core" / "tasks.py"
EXPECTED_ASYNC_TASKS = {
    "generate_mini_report",
    "deliver_mini_report",
    "deliver_repeated_mini_report",
    "deliver_chat_response",
    "generate_full_report",
    "generate_prelaunch_full_report",
    "notify_full_matrix_payment_confirmed",
    "process_report_generation_job",
    "deliver_full_report",
    "dispatch_report_generation_jobs",
    "reconcile_report_generation_jobs",
    "reconcile_chat_deliveries",
    "generate_compatibility_report",
    "send_daily_card",
    "send_daily_tarot_card",
    "send_weekly_tarot_spread",
    "send_monthly_tarot_portal",
    "check_inactive_users",
    "check_expiring_subscriptions",
    "downgrade_expired_subscriptions",
    "charge_recurring_subscriptions",
    "send_broadcast",
    "dispatch_broadcast_campaign",
    "reconcile_broadcast_campaigns",
    "send_magic_link_email",
    "cleanup_expired_guest_profiles",
    "block_inactive_users",
    "delete_inactive_users",
    "monitor_health",
}


def _tree() -> ast.Module:
    return ast.parse(TASKS_PATH.read_text(encoding="utf-8"))


def _is_celery_task(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and isinstance(decorator.func.value, ast.Name)
        and decorator.func.value.id == "celery_app"
        and decorator.func.attr == "task"
        for decorator in node.decorator_list
    )


def test_exact_async_task_inventory_uses_canonical_wrapper() -> None:
    task_nodes = {
        node.name: node
        for node in _tree().body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and _is_celery_task(node)
    }

    assert set(task_nodes) == EXPECTED_ASYNC_TASKS
    for name, node in task_nodes.items():
        wrapper_calls = [
            child
            for child in ast.walk(node)
            if isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "_run_async"
        ]
        assert len(wrapper_calls) == 1, name


def test_tasks_import_wrapper_and_do_not_manage_process_loop() -> None:
    tree = _tree()
    wrapper_imports = [
        alias
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "core.celery_async"
        for alias in node.names
        if alias.name == "run_celery_async" and alias.asname == "_run_async"
    ]
    assert len(wrapper_imports) == 1
    assert not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_run_async"
        for node in tree.body
    )

    forbidden_attributes = {"new_event_loop", "run_until_complete", "set_event_loop"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in forbidden_attributes
            assert not (
                isinstance(node.func.value, ast.Name)
                and node.func.value.id == "asyncio"
                and node.func.attr == "run"
            )
