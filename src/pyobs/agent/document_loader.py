"""文档加载器 - 兼容 LangChain 的文档加载接口。

提供从 OBS 加载各种格式文档的功能，可直接用于 LangChain 和 LlamaIndex。
"""

import json
import os
from typing import Any, Dict, Iterator, List, Optional, Union
from datetime import datetime
import fsspec

# 尝试导入 LangChain 的 Document 类，如果不存在则使用自定义类
try:
    from langchain_core.documents import Document
except ImportError:
    try:
        from langchain.schema import Document
    except ImportError:
        # 自定义 Document 类，兼容 LangChain 接口
        class Document:
            """文档类，兼容 LangChain Document 接口。"""

            def __init__(self, page_content: str, metadata: Optional[Dict[str, Any]] = None):
                self.page_content = page_content
                self.metadata = metadata or {}

            def __repr__(self) -> str:
                return f"Document(page_content='{self.page_content[:50]}...', metadata={self.metadata})"


class OBSDocumentLoader:
    """从 OBS 加载单个文档。

    支持的格式：
    - 文本文件 (.txt, .md, .csv, .json, .xml, .html, .log)
    - 代码文件 (.py, .js, .java, .go, .rs, .cpp, .c, .h)

    对于 PDF、Word 等二进制格式，需要配合其他库使用。

    Example:
        >>> loader = OBSDocumentLoader("mybucket/docs/readme.md")
        >>> docs = loader.load()
        >>> print(docs[0].page_content)

        # 与 LangChain 配合使用
        >>> from langchain.text_splitter import CharacterTextSplitter
        >>> splitter = CharacterTextSplitter(chunk_size=1000)
        >>> chunks = splitter.split_documents(docs)
    """

    # 文本文件扩展名
    TEXT_EXTENSIONS = {
        '.txt', '.md', '.markdown', '.csv', '.json', '.xml', '.html', '.htm',
        '.log', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf',
        '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.go', '.rs', '.cpp',
        '.c', '.h', '.hpp', '.cs', '.rb', '.php', '.swift', '.kt', '.scala',
        '.sh', '.bash', '.zsh', '.sql', '.r', '.R', '.m', '.mm'
    }

    def __init__(
        self,
        path: str,
        fs: Optional[Any] = None,
        encoding: str = "utf-8",
        metadata: Optional[Dict[str, Any]] = None,
        **fs_kwargs
    ):
        """初始化文档加载器。

        Args:
            path: OBS 路径，格式为 "bucket/path/to/file.txt"
            fs: 可选的 fsspec 文件系统实例，不传则自动创建
            encoding: 文件编码，默认 utf-8
            metadata: 附加到文档的额外元数据
            **fs_kwargs: 传递给 fsspec.filesystem('obs') 的参数
        """
        self.path = path
        self.encoding = encoding
        self.extra_metadata = metadata or {}

        if fs is not None:
            self.fs = fs
        else:
            self.fs = fsspec.filesystem('obs', **fs_kwargs)

    def load(self) -> List[Document]:
        """加载文档。

        Returns:
            包含单个 Document 的列表
        """
        # 读取文件内容
        content = self.fs.cat_file(self.path)

        # 尝试解码
        try:
            text = content.decode(self.encoding)
        except UnicodeDecodeError:
            # 尝试其他编码
            for enc in ['utf-8', 'gbk', 'gb2312', 'latin-1']:
                try:
                    text = content.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                raise ValueError(f"无法解码文件 {self.path}，请指定正确的编码")

        # 获取文件信息
        info = self.fs.info(self.path)

        # 构建元数据
        metadata = {
            "source": f"obs://{self.path}",
            "path": self.path,
            "size": info.get("size", len(content)),
            "last_modified": info.get("LastModified", ""),
            "content_type": info.get("ContentType", ""),
            **self.extra_metadata
        }

        return [Document(page_content=text, metadata=metadata)]

    def lazy_load(self) -> Iterator[Document]:
        """惰性加载文档（生成器方式）。

        Yields:
            Document 对象
        """
        for doc in self.load():
            yield doc


class OBSDirectoryLoader:
    """从 OBS 目录批量加载文档。

    支持递归加载、文件过滤、并行加载等功能。

    Example:
        >>> loader = OBSDirectoryLoader(
        ...     "mybucket/documents/",
        ...     glob="**/*.md",
        ...     recursive=True
        ... )
        >>> docs = loader.load()
        >>> print(f"加载了 {len(docs)} 个文档")

        # 只加载特定类型
        >>> loader = OBSDirectoryLoader(
        ...     "mybucket/code/",
        ...     suffixes=[".py", ".js"],
        ...     exclude=["__pycache__", "node_modules"]
        ... )
    """

    def __init__(
        self,
        path: str,
        fs: Optional[Any] = None,
        glob: str = "**/*",
        suffixes: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
        recursive: bool = True,
        encoding: str = "utf-8",
        max_concurrency: int = 10,
        show_progress: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
        **fs_kwargs
    ):
        """初始化目录加载器。

        Args:
            path: OBS 目录路径，格式为 "bucket/path/to/dir/"
            fs: 可选的 fsspec 文件系统实例
            glob: glob 模式，默认匹配所有文件
            suffixes: 文件后缀过滤，如 [".txt", ".md"]
            exclude: 排除的路径模式，如 ["__pycache__", ".git"]
            recursive: 是否递归加载子目录
            encoding: 文件编码
            max_concurrency: 最大并发数
            show_progress: 是否显示进度
            metadata: 附加到所有文档的额外元数据
            **fs_kwargs: 传递给 fsspec.filesystem('obs') 的参数
        """
        self.path = path.rstrip('/') + '/'
        self.glob = glob
        self.suffixes = set(suffixes) if suffixes else None
        self.exclude = exclude or []
        self.recursive = recursive
        self.encoding = encoding
        self.max_concurrency = max_concurrency
        self.show_progress = show_progress
        self.extra_metadata = metadata or {}

        if fs is not None:
            self.fs = fs
        else:
            self.fs = fsspec.filesystem('obs', **fs_kwargs)

    def _should_include(self, file_path: str) -> bool:
        """判断文件是否应该被包含。"""
        # 检查排除模式
        for pattern in self.exclude:
            if pattern in file_path:
                return False

        # 检查后缀
        if self.suffixes:
            ext = os.path.splitext(file_path)[1].lower()
            if ext not in self.suffixes:
                return False

        # 检查是否为文本文件
        ext = os.path.splitext(file_path)[1].lower()
        if ext and ext not in OBSDocumentLoader.TEXT_EXTENSIONS:
            return False

        return True

    def _list_files(self) -> List[str]:
        """列出所有符合条件的文件。"""
        files = []

        try:
            # 列出目录内容
            items = self.fs.ls(self.path, detail=True)

            for item in items:
                item_path = item['name']
                item_type = item.get('type', 'file')

                if item_type == 'directory':
                    if self.recursive:
                        # 递归加载子目录
                        sub_loader = OBSDirectoryLoader(
                            item_path,
                            fs=self.fs,
                            glob=self.glob,
                            suffixes=list(self.suffixes) if self.suffixes else None,
                            exclude=self.exclude,
                            recursive=True,
                            encoding=self.encoding
                        )
                        files.extend(sub_loader._list_files())
                else:
                    if self._should_include(item_path):
                        files.append(item_path)
        except Exception as e:
            print(f"警告: 无法列出目录 {self.path}: {e}")

        return files

    def load(self) -> List[Document]:
        """加载所有文档。

        Returns:
            Document 列表
        """
        files = self._list_files()
        documents = []

        if self.show_progress:
            try:
                from tqdm import tqdm
                files = tqdm(files, desc="加载文档")
            except ImportError:
                pass

        for file_path in files:
            try:
                loader = OBSDocumentLoader(
                    file_path,
                    fs=self.fs,
                    encoding=self.encoding,
                    metadata=self.extra_metadata
                )
                documents.extend(loader.load())
            except Exception as e:
                print(f"警告: 无法加载文件 {file_path}: {e}")

        return documents

    def lazy_load(self) -> Iterator[Document]:
        """惰性加载文档。

        Yields:
            Document 对象
        """
        files = self._list_files()

        for file_path in files:
            try:
                loader = OBSDocumentLoader(
                    file_path,
                    fs=self.fs,
                    encoding=self.encoding,
                    metadata=self.extra_metadata
                )
                for doc in loader.lazy_load():
                    yield doc
            except Exception as e:
                print(f"警告: 无法加载文件 {file_path}: {e}")


class OBSBlobLoader:
    """从 OBS 加载二进制文件（PDF、Word、图片等）。

    此加载器返回原始字节，需配合专门的解析库使用。

    Example:
        >>> # 加载 PDF 并用 PyPDF 解析
        >>> from pypdf import PdfReader
        >>> import io
        >>>
        >>> loader = OBSBlobLoader("mybucket/docs/report.pdf")
        >>> blob = loader.load()
        >>> reader = PdfReader(io.BytesIO(blob.data))
        >>> text = reader.pages[0].extract_text()
    """

    def __init__(
        self,
        path: str,
        fs: Optional[Any] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **fs_kwargs
    ):
        """初始化 Blob 加载器。

        Args:
            path: OBS 路径
            fs: 可选的 fsspec 文件系统实例
            metadata: 附加元数据
            **fs_kwargs: 传递给 fsspec.filesystem('obs') 的参数
        """
        self.path = path
        self.extra_metadata = metadata or {}

        if fs is not None:
            self.fs = fs
        else:
            self.fs = fsspec.filesystem('obs', **fs_kwargs)

    def load(self) -> "Blob":
        """加载二进制数据。

        Returns:
            Blob 对象
        """
        data = self.fs.cat_file(self.path)
        info = self.fs.info(self.path)

        metadata = {
            "source": f"obs://{self.path}",
            "path": self.path,
            "size": info.get("size", len(data)),
            "content_type": info.get("ContentType", ""),
            **self.extra_metadata
        }

        return Blob(data=data, metadata=metadata)


class Blob:
    """二进制数据容器，兼容 LangChain Blob 接口。"""

    def __init__(self, data: bytes, metadata: Optional[Dict[str, Any]] = None):
        self.data = data
        self.metadata = metadata or {}

    @property
    def source(self) -> str:
        return self.metadata.get("source", "")

    def as_bytes(self) -> bytes:
        return self.data

    def as_string(self, encoding: str = "utf-8") -> str:
        return self.data.decode(encoding)
