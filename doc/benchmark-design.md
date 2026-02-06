# OBS 文件系统性能测试设计文档

> 本文档定义 OBS 文件系统的性能基准测试方案，适用于 obsfuse (Rust) 和 pyobs (Python) 项目。

## 1. 概述

### 1.1 测试目标

| 目标 | 说明 |
|------|------|
| 单线程基准性能 | 测量各组件在无竞争状态下的纯性能 |
| 多线程并发性能 | 测量高并发访问下的吞吐量和扩展性 |
| OBS 集成性能 | 测量真实网络条件下的读写性能 |
| 缓存效率 | 测量缓存命中率对性能的影响 |

### 1.2 测试模式

| 模式 | 采样数 | 测量时间 | 预估耗时 | 用途 |
|------|--------|----------|----------|------|
| **quick** | 10 | 1秒 | ~2分钟 | 快速验证、CI/CD |
| **normal** | 50 | 5秒 | ~10分钟 | 日常开发 |
| **full** | 100 | 10秒 | ~30分钟 | 发布前完整测试 |

## 2. 测试分类

### 2.1 本地组件测试（无网络依赖）

#### 2.1.1 路径操作性能

| 测试项 | 说明 | 预期指标 |
|--------|------|----------|
| `path_join` | 路径拼接 | > 10M ops/sec |
| `path_parent` | 获取父路径 | > 10M ops/sec |
| `path_filename` | 获取文件名 | > 10M ops/sec |

### 2.2 OBS 集成测试（需要网络）

#### 2.2.1 单文件操作性能

| 测试项 | 文件大小 | 说明 |
|--------|----------|------|
| `obs_write_small` | 1KB | 小文件写入延迟 |
| `obs_write_medium` | 1MB | 中等文件写入吞吐 |
| `obs_write_large` | 100MB | 大文件写入吞吐 |
| `obs_read_small` | 1KB | 小文件读取延迟 |
| `obs_read_medium` | 1MB | 中等文件读取吞吐 |
| `obs_read_large` | 100MB | 大文件读取吞吐 |
| `obs_read_range` | 64KB range | 范围读取性能 |

#### 2.2.2 目录操作性能

| 测试项 | 说明 |
|--------|------|
| `obs_list_small_dir` | 列出 10 个文件的目录 |
| `obs_list_large_dir` | 列出 1000 个文件的目录 |
| `obs_stat` | 获取文件元数据 |
| `obs_exists` | 检查文件是否存在 |

#### 2.2.3 并发 OBS 操作

| 测试项 | 并发数 | 说明 |
|--------|--------|------|
| `obs_concurrent_read` | 1/4/8/16 | 并发读取吞吐量 |
| `obs_concurrent_write` | 1/4/8/16 | 并发写入吞吐量 |
| `obs_concurrent_mixed` | 8 | 混合读写负载 |

## 3. 一致性测试

### 3.1 写后读一致性 (Read-After-Write)

| 测试项 | 说明 | 预期结果 |
|--------|------|----------|
| `consistency_raw` | 写入后立即读取，验证数据一致 | 100% 数据匹配 |
| `consistency_raw_concurrent` | 多线程并发写入不同文件，各自读取验证 | 100% 数据匹配 |
| `consistency_overwrite` | 覆盖写入后读取 | 读取到新数据 |

### 3.2 元数据一致性

| 测试项 | 说明 | 预期结果 |
|--------|------|----------|
| `consistency_size_after_write` | 写入后文件大小正确 | size == 写入字节数 |
| `consistency_create_visible` | 创建文件后立即可见 | exists() == true |
| `consistency_delete_invisible` | 删除文件后立即不可见 | exists() == false |

## 4. 运行方式

### 4.1 Python (pyobs)

```bash
# 快速测试
pytest tests/benchmark/ --quick

# 普通测试
pytest tests/benchmark/

# 完整测试
pytest tests/benchmark/ --full

# 包含 OBS 集成测试
pytest tests/benchmark/ --with-obs

# 只测试特定组件
pytest tests/benchmark/ -k "path"
pytest tests/benchmark/ -k "obs"

# 生成报告
python scripts/run_benchmark.py --report
```

## 5. 输出报告

### 5.1 报告格式

| 格式 | 文件 | 用途 |
|------|------|------|
| Markdown | `perf/benchmark-report.md` | 人类可读报告 |
| JSON | `perf/benchmark-data.json` | 机器可读数据 |

### 5.2 报告内容

```markdown
# 性能测试报告

## 测试环境
- OS: macOS/Linux
- CPU: ...
- Memory: ...
- Python: ...
- 测���时间: ...

## 摘要
- 本地组件: X 项测试, 全部通过
- OBS 集成: Y 项测试, 全部通过

## 详细结果
### 路径操作
| 测试项 | 平均耗时 | P50 | P99 | ops/sec |
|--------|----------|-----|-----|---------|
| ... | ... | ... | ... | ... |
```

## 6. 目录结构

```
pyobs/
├── tests/
│   ├── spec/
│   │   ├── functional-tests.json  # 功能测试规范（共享）
│   │   └── benchmark-spec.json    # 性能测试规范（共享）
│   ├── functional/                # 功能测试实现
│   │   ├── __init__.py
│   │   ├── conftest.py
│   │   └── test_functional.py
│   └── benchmark/                 # 性能测试实现
│       ├── __init__.py
│       ├── conftest.py
│       └── test_benchmark.py
├── perf/
│   ├── benchmark-report.md        # Markdown 报告
│   ├── benchmark-data.json        # JSON 数据
│   └── baseline.json              # 基准数据（用于回归检测）
├── scripts/
│   └── run_benchmark.py           # 测试运行脚本
└── doc/
    ├── benchmark-design.md        # 性能测试设计文档
    └── functional-test-design.md  # 功能测试设计文档
```

## 7. 跨项目共享

### 7.1 共享规范文件

两个项目使用相同的 JSON 规范文件：

| 文件 | 用途 |
|------|------|
| `tests/spec/functional-tests.json` | 功能测试用例定义 |
| `tests/spec/benchmark-spec.json` | 性能测试用例定义 |

### 7.2 报告格式统一

两个项目生成相���格式的报告，便于对比：

```json
{
    "project": "pyobs",
    "version": "0.1.0",
    "timestamp": "2024-02-06T10:30:00Z",
    "mode": "normal",
    "benchmarks": {
        "path/join": {
            "mean_ns": 1234,
            "std_dev_ns": 56,
            "ops_per_sec": 810372
        }
    }
}
```
