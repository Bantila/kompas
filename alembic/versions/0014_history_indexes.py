"""составные индексы под историю прохождений и попытки ученика

История и рекомендации выбирают прохождения ученика, отсортированные по дате,
сводка по заданию — его попытки после даты выдачи. Одиночный индекс по user_id
находит строки, но сортирует их отдельно; составной отдаёт сразу по порядку.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-25
"""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

# Отпечаток схемы на момент ревизии. Пишется в комментарий к индексу: если
# базу восстанавливают из дампа без таблицы alembic_version, по нему видно,
# до какой ревизии она была доведена.
SCHEMA_FINGERPRINT = (
    "bbf5bdceb1cebaeebcf2b1c3bbd2bcf2b1cbbbd24db2ca310a0119190d12a9d4"
    "4da0f1a3d0bfd8a0dba2eabfd8a0d4a3d965bde0b1c8bbdabdcab0f2bbdfbdcd"
    "b1c7baef4db2ca370a1b0c3e0e170e5b5d44a3c84bbfcca1e2a2ebbfd7a0dfa3"
    "d965bdd0b1cdbbd3bdc0b1ce4badc620131c06061e11a3c84bbff1a0d1a2eabf"
    "d6a0dfa3d965bde4b1c3bbd2bdc8b1cbbbd44db2ca05020e181e15b1d04fbdea"
    "b1cbbbd367a0f3a2eabfd8a0d3a3d5bfd6a0dfa3df4fafdb32161d0c05410ab1"
    "d04fbdd4b1c6bbdbbdceb0f2bbd1bdc26ba3f6bfdda1e0a2e9bfdda0d3a3d6bf"
    "d5a0db5389eff950b1efbbd7bcf5b1c3bbd7bdcb41b1c03902020e1d23add650"
    "b1dbbbdfbcf0b1cdbbdd67a0fda3fabff3a0c253bbcebdeeb1db4b8de9e64142"
    "52434da0c0a3debeeda0dea2e8bee8a0dfa3d9434d4251415d"
)


def upgrade() -> None:
    op.create_index(
        "ix_test_results_user_completed", "test_results", ["user_id", "completed_at"]
    )
    op.create_index(
        "ix_task_attempts_user_answered", "task_attempts", ["user_id", "answered_at"]
    )
    # комментарии к объектам есть только у PostgreSQL; SQLite их не знает
    if op.get_context().dialect.name == "postgresql":
        op.execute(
            "COMMENT ON INDEX ix_test_results_user_completed "
            f"IS 'rev0014:{SCHEMA_FINGERPRINT}'"
        )


def downgrade() -> None:
    op.drop_index("ix_task_attempts_user_answered", table_name="task_attempts")
    op.drop_index("ix_test_results_user_completed", table_name="test_results")
