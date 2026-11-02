"""保存会话约定和同一请求中的多步模型、工具消息。"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    statements = """
        ALTER TABLE sessions ADD COLUMN session_state JSONB NOT NULL
        DEFAULT '{"activity": null, "instructions": []}'::jsonb;
        ALTER TABLE session_messages ADD COLUMN step INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE session_messages ADD CONSTRAINT message_step CHECK (step >= 0);
        ALTER TABLE session_messages DROP CONSTRAINT message_kind;
        ALTER TABLE session_messages ADD CONSTRAINT message_kind
        CHECK (message_kind IN ('user_message', 'assistant_message', 'tool_result'));
        ALTER TABLE session_messages DROP CONSTRAINT message_request;
        ALTER TABLE session_messages ADD CONSTRAINT message_request
        UNIQUE (session_id, message_kind, request_id, step);
        ALTER TABLE session_messages ADD CONSTRAINT user_step
        CHECK (message_kind <> 'user_message' OR step = 0);
    """
    for statement in statements.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade():
    # 不能将多步消息挤回单回复结构；保留数据并明确拒绝有损降级。
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM session_messages WHERE step <> 0
                     OR message_kind = 'tool_result') THEN
            RAISE EXCEPTION 'Agent messages exist; restore a pre-upgrade backup to downgrade';
          END IF;
        END $$;
    """)
    statements = """
        ALTER TABLE session_messages DROP CONSTRAINT user_step;
        ALTER TABLE session_messages DROP CONSTRAINT message_request;
        ALTER TABLE session_messages ADD CONSTRAINT message_request
        UNIQUE (session_id, message_kind, request_id);
        ALTER TABLE session_messages DROP CONSTRAINT message_kind;
        ALTER TABLE session_messages ADD CONSTRAINT message_kind
        CHECK (message_kind IN ('user_message', 'assistant_message'));
        ALTER TABLE session_messages DROP COLUMN step;
        ALTER TABLE sessions DROP COLUMN session_state;
    """
    for statement in statements.split(";"):
        if statement.strip():
            op.execute(statement)
