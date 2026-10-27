"""将场景统一命名为角色，保留记录 ID、文件引用与会话关联。"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = depends_on = None


def _rename(source, target):
    """只重命名数据库对象，不重新插入或转换业务记录。"""
    op.rename_table(f"{source}s", f"{target}s")
    op.alter_column(f"{target}s", f"{source}_id", new_column_name=f"{target}_id")
    op.alter_column("sessions", f"{source}_id", new_column_name=f"{target}_id")
    for previous, current in (
        (f"{source}s_pkey", f"{target}s_pkey"),
        (f"{source}s_prompt_key_key", f"{target}s_prompt_key_key"),
        (f"{source}_status", f"{target}_status"),
    ):
        op.execute(f"ALTER TABLE {target}s RENAME CONSTRAINT {previous} TO {current}")
    op.execute(f"ALTER TABLE sessions RENAME CONSTRAINT session_{source} TO session_{target}")
    op.execute(f"ALTER INDEX session_{source}_updated RENAME TO session_{target}_updated")
    op.execute(f"ALTER SEQUENCE {source}s_{source}_id_seq RENAME TO {target}s_{target}_id_seq")


def upgrade():
    _rename("scene", "character")


def downgrade():
    _rename("character", "scene")
