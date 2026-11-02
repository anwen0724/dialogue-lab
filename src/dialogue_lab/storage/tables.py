"""角色与会话持久结构；消息内容和路径分开保存，身份正文保存在文档中。"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()


def identity(name):
    return Column(name, BigInteger, Identity(always=True), primary_key=True)


def timestamp(name, *, nullable=False, default=False):
    return Column(
        name,
        DateTime(timezone=True),
        nullable=nullable,
        server_default=func.now() if default else None,
    )


characters = Table(
    "characters",
    metadata,
    identity("character_id"),
    Column("name", Text, nullable=False),
    Column("category", Text, nullable=False),
    Column("character_name", Text, nullable=False),
    Column("tts_voice", Text),
    Column("cover_image", Text),
    Column("background_image", Text),
    Column("prompt_key", Text, nullable=False, unique=True),
    Column("memory_revision", Integer, nullable=False, server_default="0"),
    Column("status", Text, nullable=False, server_default="active"),
    timestamp("created_at", default=True),
    timestamp("updated_at", default=True),
    CheckConstraint("status IN ('active', 'archived')", name="character_status"),
)


sessions = Table(
    "sessions",
    metadata,
    identity("session_id"),
    Column("character_id", BigInteger),
    ForeignKeyConstraint(["character_id"], ["characters.character_id"], name="session_character"),
    Column("title", Text, nullable=False),
    Column("status", Text, nullable=False, server_default="active"),
    Column("active_entry_id", BigInteger),
    Column("model_selection", JSONB),
    Column(
        "session_state",
        JSONB,
        nullable=False,
        server_default='{"activity": null, "instructions": []}',
    ),
    timestamp("created_at", default=True),
    timestamp("updated_at", default=True),
    timestamp("archived_at", nullable=True),
    CheckConstraint(
        "(status = 'active' AND archived_at IS NULL) OR "
        "(status = 'archived' AND archived_at IS NOT NULL)",
        name="session_status",
    ),
)

Index("session_character_updated", sessions.c.character_id, sessions.c.updated_at)

messages = Table(
    "session_messages",
    metadata,
    identity("message_id"),
    Column("session_id", BigInteger, nullable=False),
    Column("request_id", UUID(as_uuid=True), nullable=False),
    Column("message_kind", Text, nullable=False),
    Column("step", Integer, nullable=False, server_default="0"),
    Column("playback_state", Text),
    Column("message_json", JSONB, nullable=False),
    timestamp("created_at", default=True),
    timestamp("completed_at", nullable=True),
    CheckConstraint(
        "message_kind IN ('user_message', 'assistant_message', 'tool_result')", name="message_kind"
    ),
    CheckConstraint("step >= 0", name="message_step"),
    CheckConstraint(
        "playback_state IS NULL OR (message_kind = 'assistant_message' "
        "AND playback_state IN ('unconfirmed', 'completed', 'interrupted'))",
        name="message_playback",
    ),
    CheckConstraint("message_kind <> 'user_message' OR step = 0", name="user_step"),
    UniqueConstraint("session_id", "message_kind", "request_id", "step", name="message_request"),
    UniqueConstraint("session_id", "message_id", name="message_session_id"),
    ForeignKeyConstraint(["session_id"], ["sessions.session_id"], name="message_session"),
)

entries = Table(
    "session_entries",
    metadata,
    identity("entry_id"),
    Column("session_id", BigInteger, nullable=False),
    Column("parent_entry_id", BigInteger),
    Column("entry_type", Text, nullable=False),
    Column("message_id", BigInteger, unique=True),
    Column("compaction_id", BigInteger, unique=True),
    timestamp("created_at", default=True),
    UniqueConstraint("session_id", "entry_id", name="entry_session_id"),
    CheckConstraint(
        "parent_entry_id IS NULL OR parent_entry_id <> entry_id", name="entry_not_self"
    ),
    CheckConstraint(
        "(entry_type = 'message' AND message_id IS NOT NULL AND compaction_id IS NULL) "
        "OR (entry_type = 'compaction' AND compaction_id IS NOT NULL AND message_id IS NULL)",
        name="entry_content",
    ),
    ForeignKeyConstraint(["session_id"], ["sessions.session_id"], name="entry_session"),
    ForeignKeyConstraint(
        ["session_id", "parent_entry_id"],
        ["session_entries.session_id", "session_entries.entry_id"],
        name="entry_parent",
    ),
    ForeignKeyConstraint(
        ["session_id", "message_id"],
        ["session_messages.session_id", "session_messages.message_id"],
        name="entry_message",
    ),
)

compactions = Table(
    "session_compactions",
    metadata,
    identity("compaction_id"),
    Column("session_id", BigInteger, nullable=False),
    Column("anchor_entry_id", BigInteger, nullable=False),
    Column("trigger", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("summary_text", Text),
    Column("memory_revision", Integer, nullable=False, server_default="0"),
    Column("covered_until_entry_id", BigInteger),
    Column("first_kept_entry_id", BigInteger),
    Column("usage", JSONB),
    Column("error_code", Text),
    Column("error_message", Text),
    timestamp("started_at", default=True),
    timestamp("completed_at", nullable=True),
    UniqueConstraint("session_id", "compaction_id", name="compaction_session_id"),
    CheckConstraint(
        "status IN ('running','completed','failed','cancelled','interrupted')",
        name="compaction_status",
    ),
    CheckConstraint(
        "(status = 'running' AND completed_at IS NULL) OR "
        "(status <> 'running' AND completed_at IS NOT NULL)",
        name="compaction_completion",
    ),
    CheckConstraint(
        "status <> 'completed' OR (summary_text IS NOT NULL AND length(trim(summary_text)) > 0 "
        "AND covered_until_entry_id IS NOT NULL)",
        name="compaction_summary",
    ),
    ForeignKeyConstraint(["session_id"], ["sessions.session_id"], name="compaction_session"),
)

for field in ("anchor_entry_id", "covered_until_entry_id", "first_kept_entry_id"):
    compactions.append_constraint(
        ForeignKeyConstraint(
            ["session_id", field],
            ["session_entries.session_id", "session_entries.entry_id"],
            name=f"compaction_{field}",
        )
    )
entries.append_constraint(
    ForeignKeyConstraint(
        ["session_id", "compaction_id"],
        ["session_compactions.session_id", "session_compactions.compaction_id"],
        name="entry_compaction",
        use_alter=True,
    )
)
sessions.append_constraint(
    ForeignKeyConstraint(
        ["session_id", "active_entry_id"],
        ["session_entries.session_id", "session_entries.entry_id"],
        name="session_active_entry",
        use_alter=True,
    )
)

memories = Table(
    "memories",
    metadata,
    identity("memory_id"),
    Column("character_id", BigInteger, nullable=False),
    ForeignKeyConstraint(["character_id"], ["characters.character_id"]),
    Column("content", Text),
    Column("is_core", Boolean, nullable=False, server_default="false"),
    Column("revision", Integer, nullable=False, server_default="1"),
    Column("status", Text, nullable=False, server_default="active"),
    timestamp("created_at", default=True),
    timestamp("updated_at", default=True),
    CheckConstraint("revision > 0"),
    CheckConstraint(
        "(status = 'active' AND content IS NOT NULL AND length(trim(content)) > 0) "
        "OR (status = 'forgotten' AND content IS NULL AND NOT is_core)",
        name="memory_content",
    ),
)
Index("memory_character", memories.c.character_id, memories.c.status, memories.c.is_core)

memory_sources = Table(
    "memory_sources",
    metadata,
    Column("memory_id", BigInteger, primary_key=True),
    Column("revision", Integer, primary_key=True),
    Column("message_id", BigInteger, primary_key=True),
    ForeignKeyConstraint(["memory_id"], ["memories.memory_id"]),
    ForeignKeyConstraint(["message_id"], ["session_messages.message_id"]),
    CheckConstraint("revision > 0"),
)
