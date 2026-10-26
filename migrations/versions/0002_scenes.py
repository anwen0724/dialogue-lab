"""用户场景与会话归属；初始场景只随本迁移插入一次。"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = depends_on = None


def upgrade():
    op.execute("""CREATE TABLE scenes (
        scene_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        name TEXT NOT NULL, category TEXT NOT NULL, character_name TEXT NOT NULL,
        cover_image TEXT, background_image TEXT, prompt_key TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL DEFAULT 'active',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT scene_status CHECK (status IN ('active','archived'))
    )""")
    op.execute("ALTER TABLE sessions ADD COLUMN scene_id BIGINT")
    op.execute(
        "ALTER TABLE sessions ADD CONSTRAINT session_scene "
        "FOREIGN KEY (scene_id) REFERENCES scenes(scene_id)"
    )
    op.execute("CREATE INDEX session_scene_updated ON sessions(scene_id, updated_at)")
    op.execute("""INSERT INTO scenes(
        name, category, character_name, prompt_key, cover_image, background_image)
        VALUES ('窗边咖啡馆','英语交流','Emma','scene-cafe',
                '/api/scene-assets/cafe.png','/api/scene-assets/cafe.png'),
        ('下一站，理想工作','面试练习','Alex','scene-studio',
                '/api/scene-assets/studio.jpg','/api/scene-assets/studio.jpg'),
        ('晚风与闲谈','随心聊聊','小岚','scene-night',
                '/api/scene-assets/night.jpg','/api/scene-assets/night.jpg')""")


def downgrade():
    op.drop_index("session_scene_updated", table_name="sessions")
    op.drop_constraint("session_scene", "sessions", type_="foreignkey")
    op.drop_column("sessions", "scene_id")
    op.drop_table("scenes")
