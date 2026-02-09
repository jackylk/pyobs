"""上下文存储 - 用于 Agent 会话和上下文管理。

提供将 Agent 对话历史、上下文状态等持久化到 OBS 的功能。
"""

import json
import pickle
import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass, asdict, field
import fsspec


@dataclass
class Message:
    """对话消息。"""
    role: str  # "user", "assistant", "system", "function", "tool"
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        return cls(**data)

    def to_langchain(self) -> Any:
        """转换为 LangChain 消息格式。"""
        try:
            from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

            if self.role == "user":
                return HumanMessage(content=self.content)
            elif self.role == "assistant":
                return AIMessage(content=self.content)
            elif self.role == "system":
                return SystemMessage(content=self.content)
            else:
                return HumanMessage(content=self.content)
        except ImportError:
            return {"role": self.role, "content": self.content}


@dataclass
class Conversation:
    """对话会话。"""
    id: str
    messages: List[Message] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def add_message(self, role: str, content: str, **kwargs) -> Message:
        """添加消息。"""
        msg = Message(role=role, content=content, **kwargs)
        self.messages.append(msg)
        self.updated_at = datetime.now().isoformat()
        return msg

    def add_user_message(self, content: str, **kwargs) -> Message:
        """添加用户消息。"""
        return self.add_message("user", content, **kwargs)

    def add_assistant_message(self, content: str, **kwargs) -> Message:
        """添加助手消息。"""
        return self.add_message("assistant", content, **kwargs)

    def add_system_message(self, content: str, **kwargs) -> Message:
        """添加系统消息。"""
        return self.add_message("system", content, **kwargs)

    def get_messages(self, limit: Optional[int] = None) -> List[Message]:
        """获取消息列表。"""
        if limit:
            return self.messages[-limit:]
        return self.messages

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "messages": [m.to_dict() for m in self.messages],
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Conversation":
        messages = [Message.from_dict(m) for m in data.get("messages", [])]
        return cls(
            id=data["id"],
            messages=messages,
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
        )

    def to_langchain_messages(self) -> List[Any]:
        """转换为 LangChain 消息列表。"""
        return [m.to_langchain() for m in self.messages]


class ConversationStore:
    """对话存储 - 将对话历史持久化到 OBS。

    支持保存、加载、搜索对话历史，适用于：
    - 长期记忆存储
    - 多轮对话管理
    - 跨会话上下文保持

    Example:
        >>> store = ConversationStore("mybucket/conversations/")
        >>>
        >>> # 创建新对话
        >>> conv = store.create("user_123_session_1")
        >>> conv.add_user_message("你好")
        >>> conv.add_assistant_message("你好！有什么可以帮助你的？")
        >>> store.save(conv)
        >>>
        >>> # 加载对话
        >>> conv = store.load("user_123_session_1")
        >>> print(conv.messages)
        >>>
        >>> # 与 LangChain 集成
        >>> messages = conv.to_langchain_messages()
    """

    def __init__(
        self,
        base_path: str,
        fs: Optional[Any] = None,
        **fs_kwargs
    ):
        """初始化对话存储。

        Args:
            base_path: OBS 基础路径，如 "mybucket/conversations/"
            fs: 可选的 fsspec 文件系统实例
            **fs_kwargs: 传递给 fsspec.filesystem('obs') 的参数
        """
        self.base_path = base_path.rstrip('/') + '/'

        if fs is not None:
            self.fs = fs
        else:
            self.fs = fsspec.filesystem('obs', **fs_kwargs)

    def _get_path(self, conversation_id: str) -> str:
        """获取对话文件路径。"""
        return f"{self.base_path}{conversation_id}.json"

    def create(self, conversation_id: str, metadata: Optional[Dict] = None) -> Conversation:
        """创建新对话。"""
        return Conversation(id=conversation_id, metadata=metadata or {})

    def save(self, conversation: Conversation) -> None:
        """保存对话到 OBS。"""
        path = self._get_path(conversation.id)
        data = json.dumps(conversation.to_dict(), ensure_ascii=False, indent=2)
        self.fs.pipe_file(path, data.encode('utf-8'))

    def load(self, conversation_id: str) -> Optional[Conversation]:
        """从 OBS 加载对话。"""
        path = self._get_path(conversation_id)

        if not self.fs.exists(path):
            return None

        data = self.fs.cat_file(path)
        return Conversation.from_dict(json.loads(data.decode('utf-8')))

    def load_or_create(self, conversation_id: str, metadata: Optional[Dict] = None) -> Conversation:
        """加载对话，不存在则创建。"""
        conv = self.load(conversation_id)
        if conv is None:
            conv = self.create(conversation_id, metadata)
        return conv

    def delete(self, conversation_id: str) -> bool:
        """删除对话。"""
        path = self._get_path(conversation_id)
        if self.fs.exists(path):
            self.fs.rm(path)
            return True
        return False

    def list_conversations(self, prefix: str = "") -> List[str]:
        """列出所有对话 ID。"""
        try:
            items = self.fs.ls(self.base_path, detail=False)
            ids = []
            for item in items:
                if item.endswith('.json'):
                    conv_id = item.split('/')[-1].replace('.json', '')
                    if prefix and not conv_id.startswith(prefix):
                        continue
                    ids.append(conv_id)
            return ids
        except:
            return []

    def exists(self, conversation_id: str) -> bool:
        """检查对话是否存在。"""
        return self.fs.exists(self._get_path(conversation_id))


class ContextStore:
    """通用上下文存储 - 存储任意 Agent 状态和上下文。

    支持存储：
    - Agent 配置和状态
    - 工具调用结果缓存
    - 中间计算结果
    - 任意 Python 对象（通过 pickle）

    Example:
        >>> store = ContextStore("mybucket/agent_context/")
        >>>
        >>> # 存储 JSON 数据
        >>> store.put("config/agent_settings", {
        ...     "model": "gpt-4",
        ...     "temperature": 0.7
        ... })
        >>>
        >>> # 存储任意对象
        >>> store.put_object("cache/embeddings", embeddings_array)
        >>>
        >>> # 读取
        >>> config = store.get("config/agent_settings")
        >>> embeddings = store.get_object("cache/embeddings")
    """

    def __init__(
        self,
        base_path: str,
        fs: Optional[Any] = None,
        **fs_kwargs
    ):
        """初始化上下文存储。

        Args:
            base_path: OBS 基础路径
            fs: 可选的 fsspec 文件系统实例
            **fs_kwargs: 传递给 fsspec.filesystem('obs') 的参数
        """
        self.base_path = base_path.rstrip('/') + '/'

        if fs is not None:
            self.fs = fs
        else:
            self.fs = fsspec.filesystem('obs', **fs_kwargs)

    def _get_path(self, key: str, suffix: str = ".json") -> str:
        """获取存储路径。"""
        return f"{self.base_path}{key}{suffix}"

    def put(self, key: str, value: Any) -> None:
        """存储 JSON 可序列化的数据。"""
        path = self._get_path(key, ".json")
        data = json.dumps(value, ensure_ascii=False, indent=2, default=str)
        self.fs.pipe_file(path, data.encode('utf-8'))

    def get(self, key: str, default: Any = None) -> Any:
        """获取 JSON 数据。"""
        path = self._get_path(key, ".json")

        if not self.fs.exists(path):
            return default

        try:
            data = self.fs.cat_file(path)
            return json.loads(data.decode('utf-8'))
        except:
            return default

    def put_object(self, key: str, obj: Any) -> None:
        """存储任意 Python 对象（使用 pickle）。"""
        path = self._get_path(key, ".pkl")
        data = pickle.dumps(obj)
        self.fs.pipe_file(path, data)

    def get_object(self, key: str, default: Any = None) -> Any:
        """获取 Python 对象。"""
        path = self._get_path(key, ".pkl")

        if not self.fs.exists(path):
            return default

        try:
            data = self.fs.cat_file(path)
            return pickle.loads(data)
        except:
            return default

    def put_text(self, key: str, text: str) -> None:
        """存储文本。"""
        path = self._get_path(key, ".txt")
        self.fs.pipe_file(path, text.encode('utf-8'))

    def get_text(self, key: str, default: str = "") -> str:
        """获取文本。"""
        path = self._get_path(key, ".txt")

        if not self.fs.exists(path):
            return default

        try:
            data = self.fs.cat_file(path)
            return data.decode('utf-8')
        except:
            return default

    def delete(self, key: str, suffix: str = ".json") -> bool:
        """删除数据。"""
        path = self._get_path(key, suffix)
        if self.fs.exists(path):
            self.fs.rm(path)
            return True
        return False

    def exists(self, key: str, suffix: str = ".json") -> bool:
        """检查数据是否存在。"""
        return self.fs.exists(self._get_path(key, suffix))

    def list_keys(self, prefix: str = "") -> List[str]:
        """列出所有 key。"""
        try:
            search_path = f"{self.base_path}{prefix}"
            items = self.fs.ls(search_path, detail=False)
            keys = []
            for item in items:
                # 移除基础路径和扩展名
                key = item.replace(self.base_path, '')
                for ext in ['.json', '.pkl', '.txt']:
                    if key.endswith(ext):
                        key = key[:-len(ext)]
                        break
                keys.append(key)
            return list(set(keys))
        except:
            return []
