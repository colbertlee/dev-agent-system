"""LangGraph checkpoint 持久化实现。

提供 SQLite 持久化与内存降级两种 checkpointer，用于工作流状态断点续跑。
"""
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Iterator, List, Optional, Tuple

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    RunnableConfig,
    WRITES_IDX_MAP,
    get_checkpoint_id,
)
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.types import TASKS

from dev_agent_system.config import Settings


class SQLiteCheckpointSaver(BaseCheckpointSaver, AbstractContextManager, AbstractAsyncContextManager):
    """基于 SQLite 的 LangGraph checkpoint 持久化。

    每个 workflow 以 ``thread_id``（对应 ``request_id``）为键保存完整状态，
    支持任务中断恢复、历史 checkpoints 查询、同步与异步接口。
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        *,
        serde: Optional[Any] = None,
    ) -> None:
        super().__init__(serde=serde)
        self.db_path = Path(db_path or Settings.checkpoint_db()).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS checkpoints (
                    thread_id TEXT NOT NULL,
                    checkpoint_ns TEXT NOT NULL DEFAULT '',
                    checkpoint_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    data BLOB NOT NULL,
                    metadata_type TEXT NOT NULL,
                    metadata BLOB NOT NULL,
                    parent_checkpoint_id TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
                );
                CREATE INDEX IF NOT EXISTS idx_checkpoints_thread_ns_updated
                    ON checkpoints(thread_id, checkpoint_ns, updated_at DESC);

                CREATE TABLE IF NOT EXISTS checkpoint_writes (
                    thread_id TEXT NOT NULL,
                    checkpoint_ns TEXT NOT NULL DEFAULT '',
                    checkpoint_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    idx INTEGER NOT NULL,
                    channel TEXT NOT NULL,
                    type TEXT NOT NULL,
                    value BLOB NOT NULL,
                    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel)
                );
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path), check_same_thread=False)

    def _dumps(self, obj: Any) -> Tuple[str, bytes]:
        return self.serde.dumps_typed(obj)

    def _loads(self, type_name: str, data: bytes) -> Any:
        return self.serde.loads_typed((type_name, data))

    def _config(self, thread_id: str, checkpoint_ns: str, checkpoint_id: Optional[str]) -> RunnableConfig:
        cfg: RunnableConfig = {"configurable": {"thread_id": thread_id, "checkpoint_ns": checkpoint_ns}}
        if checkpoint_id:
            cfg["configurable"]["checkpoint_id"] = checkpoint_id
        return cfg

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns") or ""
        checkpoint_id = checkpoint["id"]
        parent_id = config["configurable"].get("checkpoint_id")

        c = checkpoint.copy()
        c.pop("pending_sends", None)
        t, data = self._dumps(c)
        mt, mdata = self._dumps(metadata)
        updated_at = datetime.now(timezone.utc).isoformat()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO checkpoints
                (thread_id, checkpoint_ns, checkpoint_id, type, data,
                 metadata_type, metadata, parent_checkpoint_id, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (thread_id, checkpoint_ns, checkpoint_id, t, data, mt, mdata, parent_id, updated_at),
            )
            conn.commit()

        return self._config(thread_id, checkpoint_ns, checkpoint_id)

    def put_writes(
        self,
        config: RunnableConfig,
        writes: List[Tuple[str, Any]],
        task_id: str,
    ) -> None:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns") or ""
        checkpoint_id = config["configurable"]["checkpoint_id"]

        with self._connect() as conn:
            for idx, (channel, value) in enumerate(writes):
                inner_idx = WRITES_IDX_MAP.get(channel, idx)
                t, data = self._dumps(value)
                conn.execute(
                    """
                    INSERT OR REPLACE INTO checkpoint_writes
                    (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, value)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (thread_id, checkpoint_ns, checkpoint_id, task_id, inner_idx, channel, t, data),
                )
            conn.commit()

    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns") or ""
        requested_checkpoint_id = get_checkpoint_id(config)

        with self._connect() as conn:
            if requested_checkpoint_id:
                row = conn.execute(
                    """
                    SELECT checkpoint_id, type, data, metadata_type, metadata, parent_checkpoint_id
                    FROM checkpoints
                    WHERE thread_id = ? AND checkpoint_ns = ? AND checkpoint_id = ?
                    """,
                    (thread_id, checkpoint_ns, requested_checkpoint_id),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT checkpoint_id, type, data, metadata_type, metadata, parent_checkpoint_id
                    FROM checkpoints
                    WHERE thread_id = ? AND checkpoint_ns = ?
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    (thread_id, checkpoint_ns),
                ).fetchone()

            if not row:
                return None

            checkpoint_id, type_name, data, metadata_type, metadata, parent_id = row
            checkpoint = self._loads(type_name, data)
            metadata_obj = self._loads(metadata_type, metadata)

            pending_writes = []
            for task_id, channel, vt, value in conn.execute(
                """
                SELECT task_id, channel, type, value
                FROM checkpoint_writes
                WHERE thread_id = ? AND checkpoint_ns = ? AND checkpoint_id = ?
                ORDER BY idx
                """,
                (thread_id, checkpoint_ns, checkpoint_id),
            ):
                pending_writes.append((task_id, channel, self._loads(vt, value)))

            sends = []
            if parent_id:
                for vt, value in conn.execute(
                    """
                    SELECT type, value
                    FROM checkpoint_writes
                    WHERE thread_id = ? AND checkpoint_ns = ? AND checkpoint_id = ? AND channel = ?
                    ORDER BY idx
                    """,
                    (thread_id, checkpoint_ns, parent_id, TASKS),
                ):
                    sends.append(self._loads(vt, value))

            if isinstance(checkpoint, dict):
                checkpoint["pending_sends"] = sends
            else:
                checkpoint = dict(checkpoint)
                checkpoint["pending_sends"] = sends

            parent_config = self._config(thread_id, checkpoint_ns, parent_id) if parent_id else None
            return CheckpointTuple(
                config=self._config(thread_id, checkpoint_ns, checkpoint_id),
                checkpoint=checkpoint,
                metadata=metadata_obj,
                parent_config=parent_config,
                pending_writes=pending_writes,
            )

    def list(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[dict] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> Iterator[CheckpointTuple]:
        thread_ids: Tuple[str, ...]
        if config:
            thread_ids = (config["configurable"]["thread_id"],)
        else:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT DISTINCT thread_id FROM checkpoints"
                ).fetchall()
            thread_ids = tuple(r[0] for r in rows)

        config_ns = config["configurable"].get("checkpoint_ns") if config else None
        config_checkpoint_id = get_checkpoint_id(config) if config else None
        before_id = get_checkpoint_id(before) if before else None

        count = 0
        for thread_id in thread_ids:
            with self._connect() as conn:
                ns_rows = conn.execute(
                    "SELECT DISTINCT checkpoint_ns FROM checkpoints WHERE thread_id = ?",
                    (thread_id,),
                ).fetchall()
                for (checkpoint_ns,) in ns_rows:
                    if config_ns is not None and checkpoint_ns != config_ns:
                        continue

                    rows = conn.execute(
                        """
                        SELECT checkpoint_id, type, data, metadata_type, metadata,
                               parent_checkpoint_id, updated_at
                        FROM checkpoints
                        WHERE thread_id = ? AND checkpoint_ns = ?
                        ORDER BY updated_at DESC
                        """,
                        (thread_id, checkpoint_ns),
                    ).fetchall()
                    for (
                        checkpoint_id,
                        type_name,
                        data,
                        metadata_type,
                        metadata,
                        parent_id,
                        updated_at,
                    ) in rows:
                        if config_checkpoint_id and checkpoint_id != config_checkpoint_id:
                            continue
                        if before_id and checkpoint_id >= before_id:
                            continue

                        metadata_obj = self._loads(metadata_type, metadata)
                        if filter and not all(
                            metadata_obj.get(k) == v for k, v in filter.items()
                        ):
                            continue

                        if limit is not None:
                            if count >= limit:
                                return
                            count += 1

                        checkpoint = self._loads(type_name, data)
                        pending_writes = [
                            (task_id, channel, self._loads(vt, value))
                            for task_id, channel, vt, value in conn.execute(
                                """
                                SELECT task_id, channel, type, value
                                FROM checkpoint_writes
                                WHERE thread_id = ? AND checkpoint_ns = ? AND checkpoint_id = ?
                                ORDER BY idx
                                """,
                                (thread_id, checkpoint_ns, checkpoint_id),
                            )
                        ]
                        sends = []
                        if parent_id:
                            for vt, value in conn.execute(
                                """
                                SELECT type, value
                                FROM checkpoint_writes
                                WHERE thread_id = ? AND checkpoint_ns = ? AND checkpoint_id = ? AND channel = ?
                                ORDER BY idx
                                """,
                                (thread_id, checkpoint_ns, parent_id, TASKS),
                            ):
                                sends.append(self._loads(vt, value))

                        if isinstance(checkpoint, dict):
                            checkpoint["pending_sends"] = sends
                        else:
                            checkpoint = dict(checkpoint)
                            checkpoint["pending_sends"] = sends

                        yield CheckpointTuple(
                            config=self._config(thread_id, checkpoint_ns, checkpoint_id),
                            checkpoint=checkpoint,
                            metadata=metadata_obj,
                            parent_config=self._config(thread_id, checkpoint_ns, parent_id)
                            if parent_id
                            else None,
                            pending_writes=pending_writes,
                        )

    async def aget_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.get_tuple, config)

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self.put, config, checkpoint, metadata, new_versions
        )

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: List[Tuple[str, Any]],
        task_id: str,
    ) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.put_writes, config, writes, task_id)

    async def alist(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[dict] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> AsyncIterator[CheckpointTuple]:
        loop = asyncio.get_running_loop()
        iterator = await loop.run_in_executor(
            None,
            lambda: list(self.list(config, filter=filter, before=before, limit=limit)),
        )
        for item in iterator:
            yield item

    def __enter__(self) -> "SQLiteCheckpointSaver":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    async def __aenter__(self) -> "SQLiteCheckpointSaver":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None


def make_checkpointer() -> BaseCheckpointSaver:
    """根据配置创建合适的 checkpointer：SQLite 持久化或内存降级。"""
    if not Settings.checkpoint_enabled():
        return MemorySaver()
    try:
        return SQLiteCheckpointSaver()
    except Exception:
        return MemorySaver()
