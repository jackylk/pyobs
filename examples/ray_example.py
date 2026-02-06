#!/usr/bin/env python
"""Ray Data 集成示例 - 演示如何在 Ray 中使用 pyobs。

运行前请设置环境变量：
    export OBS_ACCESS_KEY_ID=your-access-key
    export OBS_SECRET_ACCESS_KEY=your-secret-key
    export OBS_ENDPOINT=https://obs.cn-north-4.myhuaweicloud.com

安装依赖：
    pip install "ray[data]" pyarrow pandas
"""

import fsspec
import ray
import tempfile
import os


def create_sample_parquet(fs, bucket: str, path: str):
    """创建示例 Parquet 文件用于测试。"""
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    # 创建示例数据
    df = pd.DataFrame({
        'id': range(1000),
        'name': [f'item_{i}' for i in range(1000)],
        'value': [i * 1.5 for i in range(1000)],
        'category': [f'cat_{i % 10}' for i in range(1000)]
    })

    # 写入本地临时文件
    with tempfile.NamedTemporaryFile(suffix='.parquet', delete=False) as tmp:
        table = pa.Table.from_pandas(df)
        pq.write_table(table, tmp.name)

        # 上传到 OBS
        with open(tmp.name, 'rb') as f:
            fs.pipe_file(f"{bucket}/{path}", f.read())

        os.unlink(tmp.name)

    print(f"  已创建示例 Parquet 文件: {bucket}/{path}")
    return df


def example_read_parquet():
    """示例: 使用 Ray Data 读取 OBS 上的 Parquet 文件。"""
    print("\n=== Ray Data 读取 Parquet ===")

    # 创建 OBS 文件系统
    fs = fsspec.filesystem('obs')
    bucket = "your-bucket-name"  # 替换为你的 bucket

    # 创建测试数据
    create_sample_parquet(fs, bucket, "ray-example/data.parquet")

    try:
        # 使用 Ray Data 读取
        ds = ray.data.read_parquet(
            f"obs://{bucket}/ray-example/data.parquet",
            filesystem=fs
        )

        print(f"  数据集 schema: {ds.schema()}")
        print(f"  行数: {ds.count()}")
        print(f"  分块数: {ds.num_blocks()}")

        # 显示前几行
        print("\n  前 5 行:")
        for row in ds.take(5):
            print(f"    {row}")

    except Exception as e:
        print(f"  错误: {e}")
    finally:
        # 清理
        try:
            fs.rm(f"{bucket}/ray-example/data.parquet")
        except:
            pass


def example_read_parquet_directory():
    """示例: 读取 OBS 目录中的多个 Parquet 文件。"""
    print("\n=== Ray Data 读取 Parquet 目录 ===")

    fs = fsspec.filesystem('obs')
    bucket = "your-bucket-name"

    # 创建多个 Parquet 文件
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    for i in range(3):
        df = pd.DataFrame({
            'partition': [i] * 100,
            'id': range(i * 100, (i + 1) * 100),
            'value': [x * 0.1 for x in range(100)]
        })

        with tempfile.NamedTemporaryFile(suffix='.parquet', delete=False) as tmp:
            table = pa.Table.from_pandas(df)
            pq.write_table(table, tmp.name)

            with open(tmp.name, 'rb') as f:
                fs.pipe_file(f"{bucket}/ray-example/partitioned/part_{i}.parquet", f.read())

            os.unlink(tmp.name)

    print(f"  已创建 3 个分区文件")

    try:
        # 读取整个目录
        ds = ray.data.read_parquet(
            f"obs://{bucket}/ray-example/partitioned/",
            filesystem=fs
        )

        print(f"  总行数: {ds.count()}")
        print(f"  分块数: {ds.num_blocks()}")

    except Exception as e:
        print(f"  错误: {e}")
    finally:
        # 清理
        try:
            fs.rm(f"{bucket}/ray-example/partitioned", recursive=True)
        except:
            pass


def example_write_parquet():
    """示例: 使用 Ray Data 将数据写入 OBS。"""
    print("\n=== Ray Data 写入 Parquet ===")

    fs = fsspec.filesystem('obs')
    bucket = "your-bucket-name"

    try:
        # 创建一个 Ray Dataset
        ds = ray.data.range(1000)
        ds = ds.map(lambda x: {
            "id": x["id"],
            "squared": x["id"] ** 2,
            "label": f"item_{x['id']}"
        })

        print(f"  创建数据集: {ds.count()} 行")

        # 写入 OBS
        ds.write_parquet(
            f"obs://{bucket}/ray-example/output/",
            filesystem=fs
        )

        print(f"  已写入到: {bucket}/ray-example/output/")

        # 验证写入
        files = fs.ls(f"{bucket}/ray-example/output/")
        print(f"  写入的文件数: {len(files)}")
        for f in files[:5]:
            print(f"    - {f['name']}")

    except Exception as e:
        print(f"  错误: {e}")
    finally:
        # 清理
        try:
            fs.rm(f"{bucket}/ray-example/output", recursive=True)
        except:
            pass


def example_transform_and_write():
    """示例: 使用 Ray Data 进行 ETL 操作。"""
    print("\n=== Ray Data ETL 示例 ===")

    fs = fsspec.filesystem('obs')
    bucket = "your-bucket-name"

    # 创建源数据
    create_sample_parquet(fs, bucket, "ray-example/source.parquet")

    try:
        # 读取源数据
        ds = ray.data.read_parquet(
            f"obs://{bucket}/ray-example/source.parquet",
            filesystem=fs
        )

        print(f"  源数据: {ds.count()} 行")

        # 转换: 过滤并添加新列
        transformed = ds.filter(lambda row: row['value'] > 500)
        transformed = transformed.map(lambda row: {
            **row,
            'value_normalized': row['value'] / 1000,
            'processed': True
        })

        print(f"  转换后: {transformed.count()} 行")

        # 写入结果
        transformed.write_parquet(
            f"obs://{bucket}/ray-example/transformed/",
            filesystem=fs
        )

        print(f"  ETL 完成，结果已写入: {bucket}/ray-example/transformed/")

    except Exception as e:
        print(f"  错误: {e}")
    finally:
        # 清理
        try:
            fs.rm(f"{bucket}/ray-example", recursive=True)
        except:
            pass


def example_read_csv():
    """示例: 使用 Ray Data 读取 OBS 上的 CSV 文件。"""
    print("\n=== Ray Data 读取 CSV ===")

    fs = fsspec.filesystem('obs')
    bucket = "your-bucket-name"

    # 创建示例 CSV
    csv_content = b"""id,name,value,category
1,apple,10.5,fruit
2,banana,5.0,fruit
3,carrot,3.0,vegetable
4,orange,8.0,fruit
5,potato,2.5,vegetable
"""

    try:
        fs.pipe_file(f"{bucket}/ray-example/data.csv", csv_content)
        print(f"  已创建 CSV 文件")

        # 读取 CSV
        ds = ray.data.read_csv(
            f"obs://{bucket}/ray-example/data.csv",
            filesystem=fs
        )

        print(f"  行数: {ds.count()}")
        print(f"  Schema: {ds.schema()}")

        # 按类别聚合
        for row in ds.take_all():
            print(f"    {row}")

    except Exception as e:
        print(f"  错误: {e}")
    finally:
        try:
            fs.rm(f"{bucket}/ray-example/data.csv")
        except:
            pass


def example_read_json():
    """示例: 使用 Ray Data 读取 OBS 上的 JSON 文件。"""
    print("\n=== Ray Data 读取 JSON Lines ===")

    fs = fsspec.filesystem('obs')
    bucket = "your-bucket-name"

    # 创建示例 JSON Lines 文件
    jsonl_content = b"""{"id": 1, "event": "click", "timestamp": "2024-01-01T00:00:00Z"}
{"id": 2, "event": "view", "timestamp": "2024-01-01T00:01:00Z"}
{"id": 3, "event": "purchase", "timestamp": "2024-01-01T00:02:00Z"}
{"id": 4, "event": "click", "timestamp": "2024-01-01T00:03:00Z"}
"""

    try:
        fs.pipe_file(f"{bucket}/ray-example/events.jsonl", jsonl_content)
        print(f"  已创建 JSON Lines 文件")

        # 读取 JSON Lines
        ds = ray.data.read_json(
            f"obs://{bucket}/ray-example/events.jsonl",
            filesystem=fs
        )

        print(f"  行数: {ds.count()}")
        print(f"  数据:")
        for row in ds.take_all():
            print(f"    {row}")

    except Exception as e:
        print(f"  错误: {e}")
    finally:
        try:
            fs.rm(f"{bucket}/ray-example/events.jsonl")
        except:
            pass


def main():
    """运行所有 Ray 示例。"""
    print("=" * 60)
    print("Ray Data + OBS 集成示例")
    print("=" * 60)

    # 初始化 Ray
    if not ray.is_initialized():
        ray.init()
        print(f"Ray 已初始化: {ray.cluster_resources()}")

    try:
        # 运行示例
        example_read_csv()
        example_read_json()
        example_read_parquet()
        example_read_parquet_directory()
        example_write_parquet()
        example_transform_and_write()

    finally:
        ray.shutdown()
        print("\nRay 已关闭")

    print("\n所有示例完成!")


if __name__ == "__main__":
    main()
