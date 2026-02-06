#!/usr/bin/env python
"""Pandas 集成示例 - 演示如何在 Pandas 中使用 pyobs。

运行前请设置环境变量：
    export OBS_ACCESS_KEY_ID=your-access-key
    export OBS_SECRET_ACCESS_KEY=your-secret-key
    export OBS_ENDPOINT=https://obs.cn-north-4.myhuaweicloud.com

安装依赖：
    pip install pandas pyarrow openpyxl
"""

import fsspec
import pandas as pd
import io


def main():
    # 创建 OBS 文件系统
    print("创建 OBS 文件系统实例...")
    fs = fsspec.filesystem('obs')

    # 替换为你的 bucket 名称
    bucket = "your-bucket-name"
    base_path = f"{bucket}/pandas-example"

    # =========================================================================
    # 1. CSV 文件读写
    # =========================================================================
    print("\n=== CSV 文件读写 ===")

    # 创建示例 DataFrame
    df = pd.DataFrame({
        'name': ['Alice', 'Bob', 'Charlie', 'Diana'],
        'age': [25, 30, 35, 28],
        'city': ['Beijing', 'Shanghai', 'Guangzhou', 'Shenzhen'],
        'salary': [10000, 15000, 12000, 11000]
    })
    print(f"  原始数据:\n{df}")

    try:
        # 写入 CSV 到 OBS
        csv_path = f"{base_path}/data.csv"
        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        fs.pipe_file(csv_path, csv_buffer.getvalue().encode('utf-8'))
        print(f"\n  已写入 CSV: {csv_path}")

        # 从 OBS 读取 CSV
        csv_data = fs.cat_file(csv_path)
        df_read = pd.read_csv(io.BytesIO(csv_data))
        print(f"\n  读取的 CSV 数据:\n{df_read}")

    except Exception as e:
        print(f"  错误: {e}")

    # =========================================================================
    # 2. Parquet 文件读写
    # =========================================================================
    print("\n=== Parquet 文件读写 ===")

    try:
        parquet_path = f"{base_path}/data.parquet"

        # 使用 fsspec 打开文件写入 Parquet
        with fs.open(parquet_path, 'wb') as f:
            df.to_parquet(f, engine='pyarrow', index=False)
        print(f"  已写入 Parquet: {parquet_path}")

        # 使用 fsspec 打开文件读取 Parquet
        with fs.open(parquet_path, 'rb') as f:
            df_parquet = pd.read_parquet(f, engine='pyarrow')
        print(f"\n  读取的 Parquet 数据:\n{df_parquet}")

    except Exception as e:
        print(f"  错误: {e}")

    # =========================================================================
    # 3. JSON 文件读写
    # =========================================================================
    print("\n=== JSON 文件读写 ===")

    try:
        json_path = f"{base_path}/data.json"

        # 写入 JSON
        json_buffer = io.StringIO()
        df.to_json(json_buffer, orient='records', lines=True)
        fs.pipe_file(json_path, json_buffer.getvalue().encode('utf-8'))
        print(f"  已写入 JSON: {json_path}")

        # 读取 JSON
        json_data = fs.cat_file(json_path)
        df_json = pd.read_json(io.BytesIO(json_data), orient='records', lines=True)
        print(f"\n  读取的 JSON 数据:\n{df_json}")

    except Exception as e:
        print(f"  错误: {e}")

    # =========================================================================
    # 4. Excel 文件读写
    # =========================================================================
    print("\n=== Excel 文件读写 ===")

    try:
        excel_path = f"{base_path}/data.xlsx"

        # 写入 Excel
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Sheet1', index=False)
        fs.pipe_file(excel_path, excel_buffer.getvalue())
        print(f"  已写入 Excel: {excel_path}")

        # 读取 Excel
        excel_data = fs.cat_file(excel_path)
        df_excel = pd.read_excel(io.BytesIO(excel_data), engine='openpyxl')
        print(f"\n  读取的 Excel 数据:\n{df_excel}")

    except Exception as e:
        print(f"  错误: {e}")

    # =========================================================================
    # 5. 使用 Pandas 内置的 fsspec 支持
    # =========================================================================
    print("\n=== 使用 Pandas 内置 fsspec 支持 ===")

    try:
        # Pandas 可以直接使用 OBS URL (需要正确配置存储选项)
        storage_options = {
            # 如果使用环境变量认证，可以不传递这些参数
            # 'key': 'your-access-key',
            # 'secret': 'your-secret-key',
            # 'endpoint': 'https://obs.cn-north-4.myhuaweicloud.com'
        }

        # 注意: 这种方式需要 pandas 能够识别 obs:// 协议
        # 由于 pyobs 已经注册了协议，所以可以直接使用
        parquet_direct_path = f"obs://{base_path}/direct.parquet"

        # 直接写入 (某些 Pandas 版本支持)
        # df.to_parquet(parquet_direct_path, storage_options=storage_options)

        print("  Pandas 内置 fsspec 支持可用于支持 storage_options 参数的方法")

    except Exception as e:
        print(f"  注意: {e}")

    # =========================================================================
    # 6. 数据分析示例
    # =========================================================================
    print("\n=== 数据分析示例 ===")

    # 创建更大的数据集
    import numpy as np
    np.random.seed(42)

    large_df = pd.DataFrame({
        'date': pd.date_range('2024-01-01', periods=1000),
        'product': np.random.choice(['A', 'B', 'C', 'D'], 1000),
        'region': np.random.choice(['North', 'South', 'East', 'West'], 1000),
        'sales': np.random.uniform(100, 10000, 1000).round(2),
        'quantity': np.random.randint(1, 100, 1000)
    })

    try:
        # 保存到 OBS
        analysis_path = f"{base_path}/sales_data.parquet"
        with fs.open(analysis_path, 'wb') as f:
            large_df.to_parquet(f, engine='pyarrow', index=False)
        print(f"  已保存销售数据: {analysis_path}")

        # 从 OBS 读取并分析
        with fs.open(analysis_path, 'rb') as f:
            df_sales = pd.read_parquet(f)

        print(f"\n  数据概览:")
        print(f"    行数: {len(df_sales)}")
        print(f"    列: {list(df_sales.columns)}")

        print(f"\n  按产品分组统计:")
        product_stats = df_sales.groupby('product').agg({
            'sales': ['sum', 'mean'],
            'quantity': 'sum'
        }).round(2)
        print(product_stats)

        print(f"\n  按地区分组统计:")
        region_stats = df_sales.groupby('region').agg({
            'sales': ['sum', 'mean'],
            'quantity': 'sum'
        }).round(2)
        print(region_stats)

    except Exception as e:
        print(f"  错误: {e}")

    # =========================================================================
    # 7. 清理
    # =========================================================================
    print("\n=== 清理测试数据 ===")
    try:
        files = fs.ls(base_path)
        for f in files:
            fs.rm(f['name'])
            print(f"  已删除: {f['name']}")
    except Exception as e:
        print(f"  清理时出错: {e}")

    print("\n示例完成!")


if __name__ == "__main__":
    main()
