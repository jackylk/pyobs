# pyobs 架构设计文档

## 1. 概述

pyobs 是一个基于 fsspec 的华为云 OBS (Object Storage Service) 文件系统实现。它提供了与 fsspec 兼容的接口，使用户能够像操作本地文件系统一样操作 OBS 存储。

> 💡 **相关项目**: 如果您需要将 OBS 挂载为本地目录，请查看姊妹项目 [obsfuse](https://github.com/obsfuse/obsfuse) - 基于 Rust 的高性能 FUSE 文件系统实现。

### 1.1 设计目标

- **兼容性**: 完全兼容 fsspec 接口规范，支持所有 fsspec 生态工具
- **易用性**: 简单的配置和使用方式，支持环境变量配置
- **高性能**: 支持大文件分块上传，线程安全的客户端管理
- **可靠性**: 完善的错误处理和异常管理

### 1.2 技术栈

| 组件 | 技术选型 | 说明 |
|------|---------|------|
| 底层 SDK | esdk-obs-python | 华为官方 OBS Python SDK |
| 接口规范 | fsspec | Python 文件系统抽象层 |
| Python 版本 | >= 3.8 | 支持类型注解 |

---

## 2. 系统架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户应用层                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │  Python  │  │   Ray    │  │  Pandas  │  │  Dask    │        │
│  │  程序    │  │   Data   │  │          │  │          │        │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘        │
│       │             │             │             │               │
│       └─────────────┴─────────────┴─────────────┘               │
│                           │                                      │
│                           ▼                                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    fsspec 抽象层                         │   │
│  │              fsspec.filesystem('obs', ...)              │   │
│  └────────────────────────────┬────────────────────────────┘   │
└───────────────────────────────│─────────────────────────────────┘
                                │
┌───────────────────────────────│─────────────────────────────────┐
│                               ▼                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                   OBSFileSystem                          │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐      │   │
│  │  │   认证管理   │  │   路径解析   │  │   缓存管理   │      │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘      │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐      │   │
│  │  │  文件操作    │  │  目录操作    │  │  元数据操作  │      │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘      │   │
│  └────────────────────────────┬────────────────────────────┘   │
│                               │                                  │
│  ┌────────────────────────────┴────────────────────────────┐   │
│  │                      OBSFile                             │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐      │   │
│  │  │   缓冲读取   │  │   缓冲写入   │  │  分块上传    │      │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘      │   │
│  └────────────────────────────┬────────────────────────────┘   │
│                               │                                  │
│                        pyobs 核心层                              │
└───────────────────────────────│─────────────────────────────────┘
                                │
┌───────────────────────────────│─────────────────────────────────┐
│                               ▼                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                  esdk-obs-python                         │   │
│  │                    (ObsClient)                           │   │
│  └────────────────────────────┬────────────────────────────┘   │
│                        华为 OBS SDK                              │
└───────────────────────────────│─────────────────────────────────┘
                                │
                                ▼
                    ┌───────────────────┐
                    │   华为云 OBS 服务   │
                    │  (HTTP/HTTPS API) │
                    └───────────────────┘
```

### 2.2 模块结构

```
pyobs/
├── __init__.py         # 模块入口，导出公共接口
├── _version.py         # 版本信息
├── core.py             # OBSFileSystem 核心实现
├── file.py             # OBSFile 文件对象实现
├── errors.py           # 自定义异常类
└── utils.py            # 工具函数
```

---

## 3. 核心组件设计

### 3.1 OBSFileSystem 类

`OBSFileSystem` 是核心文件系统类，继承自 `fsspec.AbstractFileSystem`。

#### 3.1.1 类图

```
┌─────────────────────────────────────────────────────────────┐
│                    AbstractFileSystem                        │
│                        (fsspec)                              │
└─────────────────────────────┬───────────────────────────────┘
                              │ 继承
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     OBSFileSystem                            │
├─────────────────────────────────────────────────────────────┤
│ 类属性:                                                      │
│   protocol = ("obs", "hwobs")                               │
│   _extra_tokenize_attributes                                │
├─────────────────────────────────────────────────────────────┤
│ 实例属性:                                                    │
│   key: str              # Access Key ID                     │
│   secret: str           # Secret Access Key                 │
│   endpoint: str         # OBS 服务端点                       │
│   token: str | None     # 临时安全令牌                       │
│   default_block_size: int                                   │
│   _local: threading.local  # 线程本地存储                    │
├─────────────────────────────────────────────────────────────┤
│ 核心方法:                                                    │
│   __init__(key, secret, endpoint, token, ...)               │
│   client -> ObsClient   # 线程安全的客户端属性               │
│   _call_obs(method, *args, **kwargs)  # OBS API 调用封装    │
│   _split_path(path) -> (bucket, key)                        │
├─────────────────────────────────────────────────────────────┤
│ 文件操作:                                                    │
│   ls(path, detail) -> list                                  │
│   info(path) -> dict                                        │
│   exists(path) -> bool                                      │
│   cat_file(path, start, end) -> bytes                       │
│   pipe_file(path, value)                                    │
│   _open(path, mode, ...) -> OBSFile                         │
│   rm(path, recursive)                                       │
│   rm_file(path)                                             │
│   cp_file(path1, path2)                                     │
├─────────────────────────────────────────────────────────────┤
│ 目录操作:                                                    │
│   mkdir(path, create_parents)                               │
│   makedirs(path, exist_ok)                                  │
│   rmdir(path)                                               │
├─────────────────────────────────────────────────────────────┤
│ 辅助方法:                                                    │
│   sign(path, expiration, method) -> str                     │
│   size(path) -> int                                         │
│   isfile(path) -> bool                                      │
│   isdir(path) -> bool                                       │
│   created(path) -> str                                      │
│   modified(path) -> str                                     │
├─────────────────────────────────────────────────────────────┤
│ 内部方法:                                                    │
│   _upload_simple(bucket, key, data)                         │
│   _upload_multipart(bucket, key, data, part_size)           │
└─────────────────────────────────────────────────────────────┘
```

#### 3.1.2 认证机制

支持两种认证方式：

1. **参数传入**（优先级高）
   ```python
   fs = OBSFileSystem(
       key='your-access-key',
       secret='your-secret-key',
       endpoint='https://obs.cn-north-4.myhuaweicloud.com',
       token='optional-security-token'  # 可选，用于临时凭证
   )
   ```

2. **环境变量**（优先级低）
   ```bash
   export OBS_ACCESS_KEY_ID=your-access-key
   export OBS_SECRET_ACCESS_KEY=your-secret-key
   export OBS_ENDPOINT=https://obs.cn-north-4.myhuaweicloud.com
   export OBS_SECURITY_TOKEN=optional-token  # 可选
   ```

#### 3.1.3 线程安全设计

使用 `threading.local()` 为每个线程创建独立的 `ObsClient` 实例：

```python
class OBSFileSystem(AbstractFileSystem):
    def __init__(self, ...):
        self._local = threading.local()

    @property
    def client(self) -> ObsClient:
        if not hasattr(self._local, "client") or self._local.client is None:
            self._local.client = ObsClient(
                access_key_id=self.key,
                secret_access_key=self.secret,
                server=self.endpoint,
                security_token=self.token,
            )
        return self._local.client
```

这种设计确保：
- 多线程环境下每个线程使用独立的连接
- 避免连接竞争和状态混乱
- 支持 Ray 等分布式框架的并行访问

### 3.2 OBSFile 类

`OBSFile` 继承自 `fsspec.spec.AbstractBufferedFile`，提供缓冲的文件读写操作。

#### 3.2.1 类图

```
┌─────────────────────────────────────────────────────────────┐
│                  AbstractBufferedFile                        │
│                       (fsspec)                               │
└─────────────────────────────┬───────────────────────────────┘
                              │ 继承
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                        OBSFile                               │
├─────────────────────────────────────────────────────────────┤
│ 实例属性:                                                    │
│   fs: OBSFileSystem     # 关联的文件系统                     │
│   bucket: str           # 桶名                               │
│   key: str              # 对象键                             │
│   _upload_id: str       # 分块上传 ID                        │
│   _parts: list          # 已上传的分块列表                   │
│   _part_number: int     # 当前分块编号                       │
├─────────────────────────────────────────────────────────────┤
│ 读取方法:                                                    │
│   _fetch_range(start, end) -> bytes                         │
├─────────────────────────────────────────────────────────────┤
│ 写入方法:                                                    │
│   _initiate_upload()                                        │
│   _upload_chunk(final) -> bool                              │
│   _start_multipart_upload()                                 │
│   _upload_part(data)                                        │
│   _complete_multipart_upload()                              │
│   _abort_multipart_upload()                                 │
├─────────────────────────────────────────────────────────────┤
│ 生命周期:                                                    │
│   close()                                                   │
│   discard()                                                 │
└─────────────────────────────────────────────────────────────┘
```

#### 3.2.2 分块上传策略

```
┌─────────────────────────────────────────────────────────────┐
│                    上传决策流程                              │
└─────────────────────────────────────────────────────────────┘

                    开始上传
                       │
                       ▼
              ┌────────────────┐
              │ 文件大小 > 100MB │
              └────────┬───────┘
                       │
           ┌───────────┴───────────┐
           │ Yes                   │ No
           ▼                       ▼
    ┌──────────────┐       ┌──────────────┐
    │  分块上传     │       │  简单上传     │
    │ (Multipart)  │       │ (putContent) │
    └──────┬───────┘       └──────────────┘
           │
           ▼
    ┌──────────────┐
    │ 初始化上传    │
    │ (initiate)   │
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │ 循环上传分块  │◄───────┐
    │ (uploadPart) │        │
    └──────┬───────┘        │
           │                │
           ▼                │
    ┌──────────────┐   Yes  │
    │ 还有数据？    │────────┘
    └──────┬───────┘
           │ No
           ▼
    ┌──────────────┐
    │ 完成上传      │
    │ (complete)   │
    └──────────────┘
```

**分块上传参数**：
- 阈值：100MB（超过此大小自动使用分块上传）
- 默认分块大小：5MB
- 最大分块数：10000
- 最大文件大小：约 48.8TB（10000 × 5MB）

### 3.3 错误处理

#### 3.3.1 异常层次结构

```
Exception
    │
    └── OBSError (基类)
            │
            ├── OBSFileNotFoundError (404)
            │       └── FileNotFoundError
            │
            ├── OBSPermissionError (403)
            │       └── PermissionError
            │
            ├── OBSConnectionError
            │       └── ConnectionError
            │
            └── OBSUploadError
                    │
                    └── OBSMultipartError
```

#### 3.3.2 错误映射

| HTTP 状态码 | OBS 错误码 | pyobs 异常 |
|------------|-----------|-----------|
| 404 | NoSuchKey, NoSuchBucket | OBSFileNotFoundError |
| 403 | AccessDenied | OBSPermissionError |
| 连接失败 | - | OBSConnectionError |
| 上传失败 | - | OBSUploadError |

### 3.4 工具函数 (utils.py)

```python
# 路径解析
split_path(path) -> (bucket, key)      # 分割路径为桶和键
normalize_path(path) -> str            # 标准化路径
join_path(bucket, key) -> str          # 组合桶和键

# 路径判断
is_directory_marker(key) -> bool       # 是否为目录标记

# 路径操作
ensure_trailing_slash(path) -> str     # 确保末尾斜杠
remove_trailing_slash(path) -> str     # 移除末尾斜杠
get_parent_path(path) -> str           # 获取父路径

# 认证
get_credentials_from_env() -> tuple    # 从环境变量获取凭证
```

---

## 4. API 与 OBS 操作映射

### 4.1 方法映射表

| fsspec 方法 | OBS API | 说明 |
|-------------|---------|------|
| `ls()` | `listBuckets`, `listObjects` | 列出桶或对象 |
| `info()` | `headBucket`, `getObjectMetadata` | 获取元数据 |
| `exists()` | `headBucket`, `getObjectMetadata` | 检查存在性 |
| `cat_file()` | `getObject` | 读取对象内容 |
| `pipe_file()` | `putContent`, multipart upload | 写入对象 |
| `_open()` | - | 返回 OBSFile 对象 |
| `rm()` | `deleteObject`, `deleteObjects` | 删除对象 |
| `mkdir()` | `createBucket`, `putContent` | 创建目录 |
| `rmdir()` | `deleteBucket`, `deleteObject` | 删除目录 |
| `cp_file()` | `copyObject` | 复制对象 |
| `sign()` | `createSignedUrl` | 生成预签名 URL |

### 4.2 数据流图

#### 4.2.1 读取流程

```
用户调用 fs.cat_file('bucket/file.txt')
              │
              ▼
    ┌─────────────────────┐
    │  normalize_path()   │
    │  split_path()       │
    └──────────┬──────────┘
               │
               ▼
    ┌─────────────────────┐
    │  _call_obs()        │
    │  'getObject'        │
    └──────────┬──────────┘
               │
               ▼
    ┌─────────────────────┐
    │  ObsClient          │
    │  .getObject()       │
    └──────────┬──────────┘
               │
               ▼
    ┌─────────────────────┐
    │  HTTP GET           │
    │  OBS Service        │
    └──────────┬──────────┘
               │
               ▼
    ┌─────────────────────┐
    │  返回 bytes         │
    └─────────────────────┘
```

#### 4.2.2 写入流程（简单上传）

```
用户调用 fs.pipe_file('bucket/file.txt', data)
              │
              ▼
    ┌─────────────────────┐
    │  检查数据大小        │
    │  < 100MB ?          │
    └──────────┬──────────┘
               │ Yes
               ▼
    ┌─────────────────────┐
    │  _upload_simple()   │
    │  putContent         │
    └──────────┬──────────┘
               │
               ▼
    ┌─────────────────────┐
    │  HTTP PUT           │
    │  OBS Service        │
    └─────────────────────┘
```

#### 4.2.3 写入流程（分块上传）

```
用户调用 fs.pipe_file('bucket/large.bin', large_data)
              │
              ▼
    ┌─────────────────────┐
    │  检查数据大小        │
    │  >= 100MB ?         │
    └──────────┬──────────┘
               │ Yes
               ▼
    ┌─────────────────────┐
    │ initiateMultipart   │
    │ Upload              │
    └──────────┬──────────┘
               │
               ▼
    ┌─────────────────────┐
    │  循环 uploadPart    │◄───┐
    │  (每块 5MB)         │    │
    └──────────┬──────────┘    │
               │               │
               ▼               │
    ┌─────────────────────┐    │
    │  还有数据？         │────┘
    └──────────┬──────────┘
               │ No
               ▼
    ┌─────────────────────┐
    │ completeMultipart   │
    │ Upload              │
    └─────────────────────┘
```

---

## 5. 配置说明

### 5.1 pyproject.toml 配置

```toml
[project.entry-points."fsspec.specs"]
obs = "pyobs:OBSFileSystem"
hwobs = "pyobs:OBSFileSystem"
```

这个配置将 `obs` 和 `hwobs` 协议注册到 fsspec，使得：
- `fsspec.filesystem('obs', ...)` 返回 `OBSFileSystem` 实例
- `fsspec.open('obs://bucket/key', ...)` 可以直接打开 OBS 文件

### 5.2 环境变量配置

| 环境变量 | 必需 | 说明 |
|---------|------|------|
| `OBS_ACCESS_KEY_ID` | 是 | Access Key ID |
| `OBS_SECRET_ACCESS_KEY` | 是 | Secret Access Key |
| `OBS_ENDPOINT` | 是 | OBS 服务端点 URL |
| `OBS_SECURITY_TOKEN` | 否 | 临时安全令牌 |

### 5.3 常用端点

| 区域 | 端点 |
|------|------|
| 华北-北京四 | https://obs.cn-north-4.myhuaweicloud.com |
| 华东-上海一 | https://obs.cn-east-3.myhuaweicloud.com |
| 华南-广州 | https://obs.cn-south-1.myhuaweicloud.com |
| 亚太-香港 | https://obs.ap-southeast-1.myhuaweicloud.com |
| 亚太-新加坡 | https://obs.ap-southeast-3.myhuaweicloud.com |

---

## 6. 性能考虑

### 6.1 连接管理

- 每个线程维护独立的 `ObsClient` 连接
- 连接在首次使用时延迟创建
- 文件系统实例被 fsspec 缓存，避免重复创建

### 6.2 大文件处理

- 自动检测文件大小，超过 100MB 使用分块上传
- 分块大小可配置（默认 5MB）
- 支持最大 10000 个分块

### 6.3 缓冲读写

- `OBSFile` 继承 `AbstractBufferedFile`，提供缓冲功能
- 支持范围读取（Range GET），减少不必要的数据传输
- 写入时先缓冲到内存，在关闭或刷新时提交

---

## 7. 扩展性

### 7.1 与 Ray 集成

```python
import ray
import fsspec

fs = fsspec.filesystem('obs', key='...', secret='...', endpoint='...')

# Ray Data 读取
ds = ray.data.read_parquet('obs://bucket/data/', filesystem=fs)

# Ray Data 写入
ds.write_parquet('obs://bucket/output/', filesystem=fs)
```

### 7.2 与 Pandas 集成

```python
import pandas as pd
import fsspec

fs = fsspec.filesystem('obs', key='...', secret='...', endpoint='...')

# 读取
with fs.open('bucket/data.csv', 'rb') as f:
    df = pd.read_csv(f)

# 写入
with fs.open('bucket/output.csv', 'wb') as f:
    df.to_csv(f, index=False)
```

### 7.3 与 Dask 集成

```python
import dask.dataframe as dd

storage_options = {
    'key': '...',
    'secret': '...',
    'endpoint': '...'
}

# 读取
df = dd.read_parquet('obs://bucket/data/', storage_options=storage_options)

# 写入
df.to_parquet('obs://bucket/output/', storage_options=storage_options)
```

---

## 8. 测试策略

### 8.1 单元测试

- 使用 Mock 模拟 `ObsClient`
- 测试所有公共 API
- 测试错误处理路径

### 8.2 集成测试

- 需要真实的 OBS 凭证
- 测试实际的文件读写操作
- 测试大文件分块上传

### 8.3 测试覆盖

| 模块 | 测试重点 |
|------|---------|
| core.py | 文件系统操作、认证、错误处理 |
| file.py | 缓冲读写、分块上传 |
| utils.py | 路径解析、工具函数 |
| errors.py | 异常类型、错误信息 |

---

## 9. 版本历史

### v0.1.0 (初始版本)

- 实现 `OBSFileSystem` 核心功能
- 支持基本文件操作：读、写、删除、复制
- 支持目录操作：创建、删除、列表
- 支持预签名 URL 生成
- 支持大文件分块上传
- 线程安全的客户端管理
