# pyobs

华为云 OBS (Object Storage Service) 的 fsspec 文件系统实现。

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)

## 功能特性

- ✅ 完全兼容 fsspec 接口
- ✅ 支持 `obs://` 和 `hwobs://` 协议
- ✅ 自动大文件分块上传（>100MB）
- ✅ 线程安全设计，支持多线程并发
- ✅ 支持临时凭证（Security Token）
- ✅ 预签名 URL 生成
- ✅ 与 Ray、Pandas、Dask 无缝集成
- ✅ AI Agent 开发支持（文档加载、上下文存储、检查点管理）

> 💡 **需要将 OBS 挂载为本地目录？** 请查看姊妹项目 [obsfuse](https://github.com/obsfuse/obsfuse) - 基于 Rust 的高性能 FUSE 文件系统实现。

## 目录

- [安装](#安装)
  - [Linux](#linux)
  - [macOS](#macos)
  - [Docker 容器](#docker-容器)
- [配置](#配置)
- [快速开始](#快速开始)
- [API 参考](#api-参考)
- [高级用法](#高级用法)
- [与其他框架集成](#与其他框架集成)
- [故障排除](#故障排除)

## 安装

### Linux

#### Ubuntu/Debian

```bash
# 安装 Python 和 pip（如果尚未安装）
sudo apt update
sudo apt install -y python3 python3-pip python3-venv

# 创建虚拟环境（推荐）
python3 -m venv pyobs-env
source pyobs-env/bin/activate

# 安装 pyobs
pip install pyobs

# 或从源码安装
git clone https://github.com/pyobs/pyobs.git
cd pyobs
pip install -e .
```

#### CentOS/RHEL/Rocky Linux

```bash
# 安装 Python 和 pip
sudo yum install -y python3 python3-pip

# 创建虚拟环境
python3 -m venv pyobs-env
source pyobs-env/bin/activate

# 安装 pyobs
pip install pyobs
```

#### Arch Linux

```bash
# 安装 Python
sudo pacman -S python python-pip

# 安装 pyobs
pip install pyobs
```

### macOS

#### 使用 Homebrew（推荐）

```bash
# 安装 Python（如果尚未安装）
brew install python

# 创建虚拟环境（推荐）
python3 -m venv pyobs-env
source pyobs-env/bin/activate

# 安装 pyobs
pip install pyobs
```

#### 使用系统 Python

```bash
# 直接安装（可能需要 sudo）
pip3 install pyobs

# 或在用户目录安装
pip3 install --user pyobs
```

### Docker 容器

#### 使用官方 Python 镜像

```dockerfile
# Dockerfile
FROM python:3.11-slim

# 安装 pyobs
RUN pip install --no-cache-dir pyobs

# 设置工作目录
WORKDIR /app

# 复制应用代码
COPY . .

# 运行应用
CMD ["python", "your_script.py"]
```

构建和运行：

```bash
# 构建镜像
docker build -t my-obs-app .

# 运行容器（传入环境变量）
docker run -e OBS_ACCESS_KEY_ID=your-key \
           -e OBS_SECRET_ACCESS_KEY=your-secret \
           -e OBS_ENDPOINT=https://obs.cn-north-4.myhuaweicloud.com \
           my-obs-app
```

#### 使用 Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  app:
    build: .
    environment:
      - OBS_ACCESS_KEY_ID=${OBS_ACCESS_KEY_ID}
      - OBS_SECRET_ACCESS_KEY=${OBS_SECRET_ACCESS_KEY}
      - OBS_ENDPOINT=${OBS_ENDPOINT}
    volumes:
      - ./data:/app/data
```

创建 `.env` 文件：

```bash
# .env
OBS_ACCESS_KEY_ID=your-access-key
OBS_SECRET_ACCESS_KEY=your-secret-key
OBS_ENDPOINT=https://obs.cn-north-4.myhuaweicloud.com
```

运行：

```bash
docker-compose up
```

#### 在 Kubernetes 中使用

```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: obs-app
spec:
  replicas: 1
  selector:
    matchLabels:
      app: obs-app
  template:
    metadata:
      labels:
        app: obs-app
    spec:
      containers:
      - name: app
        image: my-obs-app:latest
        env:
        - name: OBS_ACCESS_KEY_ID
          valueFrom:
            secretKeyRef:
              name: obs-credentials
              key: access-key
        - name: OBS_SECRET_ACCESS_KEY
          valueFrom:
            secretKeyRef:
              name: obs-credentials
              key: secret-key
        - name: OBS_ENDPOINT
          value: "https://obs.cn-north-4.myhuaweicloud.com"
```

创建 Secret：

```bash
kubectl create secret generic obs-credentials \
  --from-literal=access-key=your-access-key \
  --from-literal=secret-key=your-secret-key
```

## 配置

### 环境变量配置（推荐）

在使用前设置以下环境变量：

```bash
# Linux/macOS
export OBS_ACCESS_KEY_ID=your-access-key
export OBS_SECRET_ACCESS_KEY=your-secret-key
export OBS_ENDPOINT=https://obs.cn-north-4.myhuaweicloud.com

# 可选：临时凭证
export OBS_SECURITY_TOKEN=your-security-token
```

在 Windows 上：

```powershell
# PowerShell
$env:OBS_ACCESS_KEY_ID = "your-access-key"
$env:OBS_SECRET_ACCESS_KEY = "your-secret-key"
$env:OBS_ENDPOINT = "https://obs.cn-north-4.myhuaweicloud.com"
```

```cmd
# CMD
set OBS_ACCESS_KEY_ID=your-access-key
set OBS_SECRET_ACCESS_KEY=your-secret-key
set OBS_ENDPOINT=https://obs.cn-north-4.myhuaweicloud.com
```

### 常用 OBS 端点

| 区域 | 端点 |
|------|------|
| 华北-北京四 | https://obs.cn-north-4.myhuaweicloud.com |
| 华东-上海一 | https://obs.cn-east-3.myhuaweicloud.com |
| 华南-广州 | https://obs.cn-south-1.myhuaweicloud.com |
| 亚太-香港 | https://obs.ap-southeast-1.myhuaweicloud.com |
| 亚太-新加坡 | https://obs.ap-southeast-3.myhuaweicloud.com |

完整的端点列表请参考[华为云 OBS 文档](https://support.huaweicloud.com/endpoint-obs/obs_03_0030.html)。

## 快速开始

### 基本使用

```python
import fsspec

# 方式1：使用环境变量（推荐）
fs = fsspec.filesystem('obs')

# 方式2：显式传入凭证
fs = fsspec.filesystem('obs',
    key='your-access-key',
    secret='your-secret-key',
    endpoint='https://obs.cn-north-4.myhuaweicloud.com')

# 列出所有 bucket
print(fs.ls(''))

# 列出 bucket 中的文件
print(fs.ls('mybucket/'))

# 读取文件
data = fs.cat_file('mybucket/path/to/file.txt')
print(data.decode('utf-8'))

# 写入文件
fs.pipe_file('mybucket/path/to/new_file.txt', b'Hello, OBS!')

# 检查文件是否存在
if fs.exists('mybucket/path/to/file.txt'):
    print('文件存在')

# 获取文件信息
info = fs.info('mybucket/path/to/file.txt')
print(f"大小: {info['size']} 字节")

# 删除文件
fs.rm('mybucket/path/to/file.txt')

# 复制文件
fs.cp_file('mybucket/src.txt', 'mybucket/dst.txt')
```

### 使用上下文管理器

```python
import fsspec

fs = fsspec.filesystem('obs')

# 读取文件
with fs.open('mybucket/file.txt', 'rb') as f:
    content = f.read()
    print(content.decode('utf-8'))

# 写入文件
with fs.open('mybucket/output.txt', 'wb') as f:
    f.write(b'Hello, World!')

# 逐行读取
with fs.open('mybucket/data.txt', 'r') as f:
    for line in f:
        print(line.strip())
```

### 使用 URL 方式

```python
import fsspec

storage_options = {
    'key': 'your-access-key',
    'secret': 'your-secret-key',
    'endpoint': 'https://obs.cn-north-4.myhuaweicloud.com'
}

# 读取
with fsspec.open('obs://mybucket/file.txt', 'rb', **storage_options) as f:
    content = f.read()

# 写入
with fsspec.open('obs://mybucket/output.txt', 'wb', **storage_options) as f:
    f.write(b'Hello from URL!')
```

## API 参考

### OBSFileSystem 方法

#### 文件操作

| 方法 | 描述 | 示例 |
|------|------|------|
| `ls(path, detail=True)` | 列出目录内容 | `fs.ls('bucket/')` |
| `info(path)` | 获取文件/目录信息 | `fs.info('bucket/file.txt')` |
| `exists(path)` | 检查路径是否存在 | `fs.exists('bucket/file.txt')` |
| `cat_file(path, start=None, end=None)` | 读取文件内容 | `fs.cat_file('bucket/file.txt')` |
| `pipe_file(path, value)` | 写入文件内容 | `fs.pipe_file('bucket/file.txt', b'data')` |
| `open(path, mode='rb')` | 打开文件 | `fs.open('bucket/file.txt', 'rb')` |
| `rm(path, recursive=False)` | 删除文件/目录 | `fs.rm('bucket/file.txt')` |
| `rm_file(path)` | 删除单个文件 | `fs.rm_file('bucket/file.txt')` |
| `cp_file(path1, path2)` | 复制文件 | `fs.cp_file('bucket/a.txt', 'bucket/b.txt')` |

#### 目录操作

| 方法 | 描述 | 示例 |
|------|------|------|
| `mkdir(path, create_parents=True)` | 创建目录 | `fs.mkdir('bucket/dir/')` |
| `makedirs(path, exist_ok=True)` | 递归创建目录 | `fs.makedirs('bucket/a/b/c/')` |
| `rmdir(path)` | 删除空目录 | `fs.rmdir('bucket/dir/')` |

#### 辅助方法

| 方法 | 描述 | 示例 |
|------|------|------|
| `sign(path, expiration=3600)` | 生成预签名 URL | `fs.sign('bucket/file.txt')` |
| `size(path)` | 获取文件大小 | `fs.size('bucket/file.txt')` |
| `isfile(path)` | 检查是否为文件 | `fs.isfile('bucket/file.txt')` |
| `isdir(path)` | 检查是否为目录 | `fs.isdir('bucket/dir/')` |
| `created(path)` | 获取创建时间 | `fs.created('bucket/file.txt')` |
| `modified(path)` | 获取修改时间 | `fs.modified('bucket/file.txt')` |

### 异常类

| 异常 | 描述 | HTTP 状态码 |
|------|------|------------|
| `OBSError` | OBS 操作基础异常 | - |
| `OBSFileNotFoundError` | 文件或 bucket 不存在 | 404 |
| `OBSPermissionError` | 权限不足 | 403 |
| `OBSConnectionError` | 连接失败 | - |
| `OBSUploadError` | 上传失败 | - |
| `OBSMultipartError` | 分块上传失败 | - |

## 高级用法

### 预签名 URL

```python
import fsspec

fs = fsspec.filesystem('obs')

# 生成下载 URL（默认 1 小时有效）
download_url = fs.sign('mybucket/file.txt')
print(f"下载链接: {download_url}")

# 指定有效期（秒）
url_2h = fs.sign('mybucket/file.txt', expiration=7200)

# 生成上传 URL
upload_url = fs.sign('mybucket/upload.txt', method='PUT')
print(f"上传链接: {upload_url}")
```

### 目录操作

```python
import fsspec

fs = fsspec.filesystem('obs')

# 创建目录
fs.mkdir('mybucket/newdir')

# 递归创建目录
fs.makedirs('mybucket/path/to/deep/dir')

# 删除空目录
fs.rmdir('mybucket/emptydir')

# 递归删除目录及其内容
fs.rm('mybucket/dir', recursive=True)
```

### 大文件处理

对于大于 100MB 的文件，pyobs 会自动使用分块上传：

```python
import fsspec

fs = fsspec.filesystem('obs')

# 读取大文件
with open('large_local_file.bin', 'rb') as f:
    data = f.read()

# 自动使用分块上传
fs.pipe_file('mybucket/large_file.bin', data)

# 或使用流式写入
with fs.open('mybucket/large_file.bin', 'wb') as f:
    with open('large_local_file.bin', 'rb') as local_f:
        while chunk := local_f.read(10 * 1024 * 1024):  # 10MB 块
            f.write(chunk)
```

### 范围读取

```python
import fsspec

fs = fsspec.filesystem('obs')

# 读取文件的一部分
first_1kb = fs.cat_file('mybucket/file.txt', start=0, end=1024)

# 从偏移量开始读取
from_1mb = fs.cat_file('mybucket/file.txt', start=1024*1024)
```

## 与其他框架集成

### Ray Data

```python
import ray
import fsspec

# 创建文件系统
fs = fsspec.filesystem('obs',
    key='your-access-key',
    secret='your-secret-key',
    endpoint='https://obs.cn-north-4.myhuaweicloud.com')

# 初始化 Ray
ray.init()

# 读取 Parquet 文件
ds = ray.data.read_parquet(
    'obs://mybucket/data.parquet',
    filesystem=fs
)
print(f"行数: {ds.count()}")

# 读取目录下的所有 Parquet 文件
ds = ray.data.read_parquet(
    'obs://mybucket/data/',
    filesystem=fs
)

# 读取 CSV 文件
ds = ray.data.read_csv(
    'obs://mybucket/data.csv',
    filesystem=fs
)

# 写入数据
ds.write_parquet(
    'obs://mybucket/output/',
    filesystem=fs
)

# 关闭 Ray
ray.shutdown()
```

### Pandas

```python
import pandas as pd
import fsspec

fs = fsspec.filesystem('obs')

# 读取 CSV
with fs.open('mybucket/data.csv', 'rb') as f:
    df = pd.read_csv(f)

# 读取 Parquet
with fs.open('mybucket/data.parquet', 'rb') as f:
    df = pd.read_parquet(f)

# 读取 JSON
with fs.open('mybucket/data.json', 'rb') as f:
    df = pd.read_json(f)

# 写入 CSV
with fs.open('mybucket/output.csv', 'wb') as f:
    df.to_csv(f, index=False)

# 写入 Parquet
with fs.open('mybucket/output.parquet', 'wb') as f:
    df.to_parquet(f)
```

### Dask

```python
import dask.dataframe as dd

storage_options = {
    'key': 'your-access-key',
    'secret': 'your-secret-key',
    'endpoint': 'https://obs.cn-north-4.myhuaweicloud.com'
}

# 读取 Parquet
df = dd.read_parquet(
    'obs://mybucket/data/',
    storage_options=storage_options
)

# 计算
result = df.groupby('category').sum().compute()

# 写入
df.to_parquet(
    'obs://mybucket/output/',
    storage_options=storage_options
)
```

### PyArrow

```python
import pyarrow.parquet as pq
import fsspec

fs = fsspec.filesystem('obs')

# 读取 Parquet
with fs.open('mybucket/data.parquet', 'rb') as f:
    table = pq.read_table(f)
    df = table.to_pandas()

# 写入 Parquet
with fs.open('mybucket/output.parquet', 'wb') as f:
    pq.write_table(table, f)
```

## 故障排除

### 常见错误

#### 1. 认证失败

```
OBSPermissionError: Permission denied: bucket/file.txt
```

解决方法：
- 检查 Access Key 和 Secret Key 是否正确
- 确认 IAM 用户有相应的 OBS 权限
- 如果使用临时凭证，检查 Security Token 是否过期

#### 2. 文件不存在

```
OBSFileNotFoundError: File not found: bucket/file.txt
```

解决方法：
- 使用 `fs.exists()` 检查文件是否存在
- 确认 bucket 名称和路径正确
- 注意路径是否区分大小写

#### 3. 连接超时

```
OBSConnectionError: Failed to connect to OBS
```

解决方法：
- 检查网络连接
- 确认 endpoint URL 正确
- 检查防火墙设置
- 尝试使用 VPN 或代理

#### 4. 端点错误

```
OBSError: The bucket you are attempting to access must be addressed using the specified endpoint.
```

解决方法：
- 确认使用了正确区域的 endpoint
- bucket 只能通过创建时所在区域的 endpoint 访问

### 调试技巧

```python
import logging

# 启用详细日志
logging.basicConfig(level=logging.DEBUG)
logging.getLogger('pyobs').setLevel(logging.DEBUG)
logging.getLogger('obs').setLevel(logging.DEBUG)

# 现在会打印详细的请求和响应信息
```

### 性能优化建议

1. **重用文件系统实例**：避免频繁创建 `OBSFileSystem` 实例
2. **批量操作**：使用 `rm(recursive=True)` 批量删除，而不是逐个删除
3. **流式处理**：对于大文件，使用 `open()` 流式读写，而不是 `cat_file()`/`pipe_file()`
4. **范围读取**：如果只需要文件的一部分，使用 `start` 和 `end` 参数

## 开发

### 安装开发依赖

```bash
git clone https://github.com/pyobs/pyobs.git
cd pyobs
pip install -e ".[dev]"
```

### 运行测试

```bash
# 运行单元测试
pytest tests/test_filesystem.py -v

# 运行集成测试（需要真实凭证）
export OBS_ACCESS_KEY_ID=xxx
export OBS_SECRET_ACCESS_KEY=xxx
export OBS_ENDPOINT=https://obs.cn-north-4.myhuaweicloud.com
export OBS_TEST_BUCKET=your-test-bucket
pytest tests/test_integration.py -v -m integration
```

### 代码风格

```bash
# 格式化代码
black src/pyobs tests

# 类型检查
mypy src/pyobs
```

## 相关项目

- **[obsfuse](https://github.com/obsfuse/obsfuse)** - 基于 Rust 的 OBS FUSE 文件系统，可将 OBS bucket 挂载为本地目录

## 许可证

Apache License 2.0

## 贡献

欢迎提交 Issue 和 Pull Request！

## 相关链接

- [华为云 OBS 文档](https://support.huaweicloud.com/obs/index.html)
- [fsspec 文档](https://filesystem-spec.readthedocs.io/)
- [esdk-obs-python](https://github.com/huaweicloud/huaweicloud-sdk-python-obs)
