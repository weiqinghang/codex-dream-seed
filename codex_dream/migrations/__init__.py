from ..schema import CURRENT_KNOWLEDGE_SCHEMA, CURRENT_WORKSPACE_SCHEMA
from .engine import inspect_legacy_workspace, migrate_legacy_workspace, verify_workspace
from .registry import MigrationError, MigrationStep, plan_migration

__all__ = [
    "CURRENT_KNOWLEDGE_SCHEMA",
    "CURRENT_WORKSPACE_SCHEMA",
    "MigrationError",
    "MigrationStep",
    "inspect_legacy_workspace",
    "migrate_legacy_workspace",
    "plan_migration",
    "verify_workspace",
]
