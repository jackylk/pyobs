"""检查点管理 - Agent 状态保存与恢复。

提供 Agent 运行状态的检查点功能，支持：
- 中断恢复
- 状态回滚
- 版本管理
"""

import json
import pickle
import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional, TypeVar, Generic
from dataclasses import dataclass, asdict, field
import fsspec


T = TypeVar('T')


@dataclass
class Checkpoint:
    """检查点数据。"""
    id: str
    name: str
    data: Dict[str, Any]
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Checkpoint":
        return cls(**d)


class CheckpointManager:
    """检查点管理器 - 保存和恢复 Agent 状态。

    功能：
    - 保存任意时刻的 Agent 状态
    - 支持多版本检查点
    - 快速回滚到任意检查点
    - 检查点命名和标签

    Example:
        >>> manager = CheckpointManager("mybucket/agent/checkpoints/")
        >>>
        >>> # 保存检查点
        >>> state = {
        ...     "step": 10,
        ...     "messages": [...],
        ...     "memory": {...}
        ... }
        >>> cp_id = manager.save("step_10", state, metadata={"reason": "before tool call"})
        >>>
        >>> # 列出检查点
        >>> checkpoints = manager.list()
        >>> for cp in checkpoints:
        ...     print(f"{cp.name} - {cp.created_at}")
        >>>
        >>> # 恢复检查点
        >>> state = manager.load("step_10")
        >>> # 或加载最新检查点
        >>> state = manager.load_latest()
    """

    def __init__(
        self,
        base_path: str,
        fs: Optional[Any] = None,
        max_checkpoints: int = 100,
        **fs_kwargs
    ):
        """初始化检查点管理器。

        Args:
            base_path: OBS 基础路径
            fs: 可选的 fsspec 文件系统实例
            max_checkpoints: 最大检查点数量，超过后删除最旧的
            **fs_kwargs: 传递给 fsspec.filesystem('obs') 的参数
        """
        self.base_path = base_path.rstrip('/') + '/'
        self.max_checkpoints = max_checkpoints

        if fs is not None:
            self.fs = fs
        else:
            self.fs = fsspec.filesystem('obs', **fs_kwargs)

        # 索引文件路径
        self._index_path = f"{self.base_path}_index.json"

    def _generate_id(self, name: str) -> str:
        """生成检查点 ID。"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        hash_suffix = hashlib.md5(f"{name}{timestamp}".encode()).hexdigest()[:8]
        return f"{timestamp}_{hash_suffix}"

    def _get_checkpoint_path(self, checkpoint_id: str) -> str:
        """获取检查点文件路径。"""
        return f"{self.base_path}{checkpoint_id}.json"

    def _get_data_path(self, checkpoint_id: str) -> str:
        """获取检查点数据文件路径。"""
        return f"{self.base_path}{checkpoint_id}.pkl"

    def _load_index(self) -> Dict[str, Any]:
        """加载索引文件。"""
        if not self.fs.exists(self._index_path):
            return {"checkpoints": []}

        try:
            data = self.fs.cat_file(self._index_path)
            return json.loads(data.decode('utf-8'))
        except:
            return {"checkpoints": []}

    def _save_index(self, index: Dict[str, Any]) -> None:
        """保存索引文件。"""
        data = json.dumps(index, ensure_ascii=False, indent=2)
        self.fs.pipe_file(self._index_path, data.encode('utf-8'))

    def save(
        self,
        name: str,
        data: Any,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """保存检查点。

        Args:
            name: 检查点名称
            data: 要保存的数据（任意 Python 对象）
            metadata: 附加元数据

        Returns:
            检查点 ID
        """
        checkpoint_id = self._generate_id(name)

        # 创建检查点元数据
        checkpoint = Checkpoint(
            id=checkpoint_id,
            name=name,
            data={},  # 实际数据存储在单独的 pkl 文件
            metadata=metadata or {}
        )

        # 保存元数据
        meta_path = self._get_checkpoint_path(checkpoint_id)
        meta_json = json.dumps(checkpoint.to_dict(), ensure_ascii=False, indent=2)
        self.fs.pipe_file(meta_path, meta_json.encode('utf-8'))

        # 保存数据
        data_path = self._get_data_path(checkpoint_id)
        self.fs.pipe_file(data_path, pickle.dumps(data))

        # 更新索引
        index = self._load_index()
        index["checkpoints"].append({
            "id": checkpoint_id,
            "name": name,
            "created_at": checkpoint.created_at,
            "metadata": checkpoint.metadata
        })

        # 清理旧检查点
        if len(index["checkpoints"]) > self.max_checkpoints:
            old_checkpoints = index["checkpoints"][:-self.max_checkpoints]
            for old_cp in old_checkpoints:
                self._delete_checkpoint_files(old_cp["id"])
            index["checkpoints"] = index["checkpoints"][-self.max_checkpoints:]

        self._save_index(index)

        return checkpoint_id

    def _delete_checkpoint_files(self, checkpoint_id: str) -> None:
        """删除检查点文件。"""
        try:
            meta_path = self._get_checkpoint_path(checkpoint_id)
            data_path = self._get_data_path(checkpoint_id)
            if self.fs.exists(meta_path):
                self.fs.rm(meta_path)
            if self.fs.exists(data_path):
                self.fs.rm(data_path)
        except:
            pass

    def load(self, name_or_id: str) -> Optional[Any]:
        """加载检查点数据。

        Args:
            name_or_id: 检查点名称或 ID

        Returns:
            检查点数据，不存在返回 None
        """
        # 先尝试作为 ID 加载
        data_path = self._get_data_path(name_or_id)
        if self.fs.exists(data_path):
            data = self.fs.cat_file(data_path)
            return pickle.loads(data)

        # 尝试按名称查找最新的
        index = self._load_index()
        for cp in reversed(index["checkpoints"]):
            if cp["name"] == name_or_id:
                data_path = self._get_data_path(cp["id"])
                if self.fs.exists(data_path):
                    data = self.fs.cat_file(data_path)
                    return pickle.loads(data)

        return None

    def load_latest(self) -> Optional[Any]:
        """加载最新的检查点。"""
        index = self._load_index()
        if not index["checkpoints"]:
            return None

        latest = index["checkpoints"][-1]
        return self.load(latest["id"])

    def load_checkpoint(self, name_or_id: str) -> Optional[Checkpoint]:
        """加载检查点元数据。"""
        index = self._load_index()

        for cp in reversed(index["checkpoints"]):
            if cp["id"] == name_or_id or cp["name"] == name_or_id:
                meta_path = self._get_checkpoint_path(cp["id"])
                if self.fs.exists(meta_path):
                    meta_data = self.fs.cat_file(meta_path)
                    return Checkpoint.from_dict(json.loads(meta_data.decode('utf-8')))

        return None

    def list(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """列出所有检查点。

        Returns:
            检查点信息列表（按时间倒序）
        """
        index = self._load_index()
        checkpoints = list(reversed(index["checkpoints"]))

        if limit:
            checkpoints = checkpoints[:limit]

        return checkpoints

    def delete(self, name_or_id: str) -> bool:
        """删除检查点。"""
        index = self._load_index()

        for i, cp in enumerate(index["checkpoints"]):
            if cp["id"] == name_or_id or cp["name"] == name_or_id:
                self._delete_checkpoint_files(cp["id"])
                index["checkpoints"].pop(i)
                self._save_index(index)
                return True

        return False

    def clear(self) -> int:
        """清除所有检查点。

        Returns:
            删除的检查点数量
        """
        index = self._load_index()
        count = len(index["checkpoints"])

        for cp in index["checkpoints"]:
            self._delete_checkpoint_files(cp["id"])

        self._save_index({"checkpoints": []})
        return count

    def get_by_name(self, name: str) -> List[Dict[str, Any]]:
        """获取指定名称的所有检查点。"""
        index = self._load_index()
        return [cp for cp in index["checkpoints"] if cp["name"] == name]


class AutoCheckpoint:
    """自动检查点上下文管理器。

    Example:
        >>> manager = CheckpointManager("mybucket/checkpoints/")
        >>>
        >>> with AutoCheckpoint(manager, "process_step", interval=5) as auto_cp:
        ...     for i in range(100):
        ...         # 处理逻辑
        ...         state = {"step": i, "data": process(i)}
        ...         auto_cp.update(state)  # 每 5 次自动保存
    """

    def __init__(
        self,
        manager: CheckpointManager,
        name: str,
        interval: int = 10,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """初始化自动检查点。

        Args:
            manager: 检查点管理器
            name: 检查点名称前缀
            interval: 保存间隔（每 N 次更新保存一次）
            metadata: 附加元数据
        """
        self.manager = manager
        self.name = name
        self.interval = interval
        self.metadata = metadata or {}
        self._count = 0
        self._last_state = None

    def __enter__(self) -> "AutoCheckpoint":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        # 退出时保存最终状态
        if self._last_state is not None:
            self.manager.save(f"{self.name}_final", self._last_state, self.metadata)

    def update(self, state: Any, force: bool = False) -> Optional[str]:
        """更新状态。

        Args:
            state: 当前状态
            force: 强制保存

        Returns:
            如果保存了检查点，返回检查点 ID
        """
        self._last_state = state
        self._count += 1

        if force or self._count % self.interval == 0:
            return self.manager.save(
                f"{self.name}_{self._count}",
                state,
                {**self.metadata, "count": self._count}
            )

        return None
