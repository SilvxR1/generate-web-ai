from enum import Enum

from sqlalchemy import Enum as SAEnum


def str_enum[EnumT: Enum](enum_cls: type[EnumT], length: int) -> SAEnum:
    """SQLAlchemy's Enum type persists the Python member *name*
    (`"WORKFLOW_RUN"`) by default, not its `.value` (`"workflow_run"`).
    Every CHECK constraint, Pydantic schema, and future JSON API in this
    codebase speaks in `.value` — without `values_callable` here, the
    column would silently desync from all of them (e.g.
    ck_executions_target_matches_type comparing against `'workflow_run'`
    while the column actually stores `'WORKFLOW_RUN'`).
    """
    return SAEnum(enum_cls, native_enum=False, length=length, values_callable=lambda obj: [e.value for e in obj])
