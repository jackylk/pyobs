# pyobs 示例程序

本目录包含 pyobs 的各种使用示例。

## 前提条件

运行示例前，请设置以下环境变量：

```bash
export OBS_ACCESS_KEY_ID=your-access-key
export OBS_SECRET_ACCESS_KEY=your-secret-key
export OBS_ENDPOINT=https://obs.cn-north-4.myhuaweicloud.com
```

并修改示例代码中的 `bucket = "your-bucket-name"` 为你的实际 bucket 名称。

## 示例文件

### [basic_usage.py](basic_usage.py)

基本使用示例，演示核心文件操作：

- 创建文件系统实例
- 列出 bucket
- 写入/读取文件
- 检查文件存在性
- 获取文件信息
- 使用上下文管理器
- 复制文件
- 生成预签名 URL
- 删除文件

```bash
python examples/basic_usage.py
```

### [pandas_example.py](pandas_example.py)

Pandas 集成示例，演示与 Pandas 的配合使用：

- CSV 文件读写
- Parquet 文件读写
- JSON 文件读写
- Excel 文件读写
- 数据分析示例

依赖：
```bash
pip install pandas pyarrow openpyxl
```

运行：
```bash
python examples/pandas_example.py
```

### [ray_example.py](ray_example.py)

Ray Data 集成示例，演示在 Ray 中使用 pyobs：

- 读取 Parquet 文件
- 读取 Parquet 目录（多文件）
- 写入 Parquet 文件
- ETL 数据转换
- 读取 CSV 文件
- 读取 JSON Lines 文件

依赖：
```bash
pip install "ray[data]" pyarrow pandas
```

运行：
```bash
python examples/ray_example.py
```

### [large_file_example.py](large_file_example.py)

大文件操作示例，演示大文件处理：

- 使用 pipe_file 上传
- 流式上传
- 范围读取
- 并发上传
- 分块上传（>100MB）

```bash
python examples/large_file_example.py
```

### [advanced_usage.py](advanced_usage.py)

高级用法示例，演示进阶功能：

- 协议注册验证
- fsspec 缓存行为
- 上下文管理器用法
- 目录操作
- 错误处理
- 预签名 URL
- 多线程安全访问

```bash
python examples/advanced_usage.py
```

## 注意事项

1. **费用**: 示例会在 OBS 上创建和删除对象，可能产生少量费用
2. **权限**: 确保使用的 AK/SK 有足够的权限
3. **清理**: 示例程序会尝试清理创建的测试文件，但如果中途失败可能会遗留文件
4. **大文件**: `large_file_example.py` 会创建较大的测试文件，请确保有足够的内存和网络带宽
