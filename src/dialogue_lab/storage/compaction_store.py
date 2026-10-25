"""压缩活动与路径切换的事务边界。"""

from sqlalchemy import func, insert, select, update

from dialogue_lab.sessions.types import SessionError
from dialogue_lab.storage.session_store import lock_session
from dialogue_lab.storage.tables import compactions, entries, sessions


class CompactionStore:
    def __init__(self, database):
        self.database = database

    async def begin(self, session_id, anchor, trigger):
        async with self.database.engine.begin() as connection:
            session = await lock_session(connection, session_id)
            if session["active_entry_id"] != anchor:
                raise SessionError("PATH_CHANGED", "当前路径与压缩准备不一致。")
            return (
                await connection.execute(
                    insert(compactions)
                    .values(
                        session_id=session_id,
                        anchor_entry_id=anchor,
                        trigger=trigger,
                        status="running",
                    )
                    .returning(compactions.c.compaction_id)
                )
            ).scalar_one()

    async def apply(self, session_id, compaction_id, covered, first_kept, summary, usage):
        """成功结果与路径切换一起提交；保留旧节点以供原始交流读取。"""
        async with self.database.engine.begin() as connection:
            session = await lock_session(connection, session_id)
            record = (
                (
                    await connection.execute(
                        select(compactions).where(
                            compactions.c.session_id == session_id,
                            compactions.c.compaction_id == compaction_id,
                        )
                    )
                )
                .mappings()
                .one()
            )
            if (
                record["status"] != "running"
                or session["active_entry_id"] != record["anchor_entry_id"]
            ):
                raise SessionError("PATH_CHANGED", "压缩准备已经失效，未切换路径。")
            rows = (
                (
                    await connection.execute(
                        select(entries).where(entries.c.session_id == session_id)
                    )
                )
                .mappings()
                .all()
            )
            by_id = {row["entry_id"]: row for row in rows}
            path = []
            current = session["active_entry_id"]
            while current is not None:
                path.append(current)
                current = by_id[current]["parent_entry_id"]
            path.reverse()
            if (
                covered not in path
                or (
                    first_kept is not None
                    and (
                        first_kept not in path or path.index(first_kept) != path.index(covered) + 1
                    )
                )
                or (first_kept is None and covered != path[-1])
            ):
                raise SessionError("INVALID_COMPACTION_RANGE", "压缩范围不属于当前连续路径。")
            await connection.execute(
                update(compactions)
                .where(compactions.c.compaction_id == compaction_id)
                .values(
                    status="completed",
                    summary_text=summary,
                    usage=usage,
                    covered_until_entry_id=covered,
                    first_kept_entry_id=first_kept,
                    completed_at=func.now(),
                )
            )
            entry_id = (
                await connection.execute(
                    insert(entries)
                    .values(
                        session_id=session_id,
                        parent_entry_id=covered,
                        entry_type="compaction",
                        compaction_id=compaction_id,
                    )
                    .returning(entries.c.entry_id)
                )
            ).scalar_one()
            if first_kept is not None:
                await connection.execute(
                    update(entries)
                    .where(entries.c.entry_id == first_kept)
                    .values(parent_entry_id=entry_id)
                )
            await connection.execute(
                update(sessions)
                .where(sessions.c.session_id == session_id)
                .values(
                    updated_at=func.now(),
                    active_entry_id=(
                        session["active_entry_id"] if first_kept is not None else entry_id
                    ),
                )
            )

    async def fail(self, compaction_id, status, code, message):
        async with self.database.engine.begin() as connection:
            await connection.execute(
                update(compactions)
                .where(
                    compactions.c.compaction_id == compaction_id,
                    compactions.c.status == "running",
                )
                .values(
                    status=status, error_code=code, error_message=message, completed_at=func.now()
                )
            )

    async def interrupt_unfinished(self):
        """单进程重启后，将上次没有收尾的压缩标记为中断；原路径保持不变。"""
        async with self.database.engine.begin() as connection:
            await connection.execute(
                update(compactions)
                .where(compactions.c.status == "running")
                .values(
                    status="interrupted",
                    completed_at=func.now(),
                    error_code="PROCESS_INTERRUPTED",
                    error_message="服务重启，压缩未完成。",
                )
            )
