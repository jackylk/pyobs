#!/usr/bin/env python
"""基本使用示例 - 演示 pyobs 的基本文件操作。

运行前请设置环境变量：
    export OBS_ACCESS_KEY_ID=your-access-key
    export OBS_SECRET_ACCESS_KEY=your-secret-key
    export OBS_ENDPOINT=https://obs.cn-north-4.myhuaweicloud.com
"""

import fsspec


def main():
    # 创建文件系统实例（使用环境变量认证）
    print("创建 OBS 文件系统实例...")
    fs = fsspec.filesystem('obs')

    # 也可以显式传入凭证
    # fs = fsspec.filesystem('obs',
    #     key='your-access-key',
    #     secret='your-secret-key',
    #     endpoint='https://obs.cn-north-4.myhuaweicloud.com')

    # 替换为你的 bucket 名称
    bucket = "your-bucket-name"

    # =========================================================================
    # 1. 列出 bucket
    # =========================================================================
    print("\n=== 列出所有 Bucket ===")
    try:
        buckets = fs.ls("")
        for b in buckets:
            print(f"  - {b['name']}")
    except Exception as e:
        print(f"  错误: {e}")

    # =========================================================================
    # 2. 写入文件
    # =========================================================================
    print("\n=== 写入文件 ===")
    test_path = f"{bucket}/pyobs-example/hello.txt"
    content = b"Hello, OBS! This is a test file from pyobsfs."

    try:
        fs.pipe_file(test_path, content)
        print(f"  已写入: {test_path}")
        print(f"  内容长度: {len(content)} 字节")
    except Exception as e:
        print(f"  错误: {e}")

    # =========================================================================
    # 3. 检查文件是否存在
    # =========================================================================
    print("\n=== 检查文件存在性 ===")
    try:
        exists = fs.exists(test_path)
        print(f"  {test_path} 存在: {exists}")
    except Exception as e:
        print(f"  错误: {e}")

    # =========================================================================
    # 4. 获取文件信息
    # =========================================================================
    print("\n=== 获取文件信息 ===")
    try:
        info = fs.info(test_path)
        print(f"  名称: {info['name']}")
        print(f"  类型: {info['type']}")
        print(f"  大小: {info['size']} 字节")
        print(f"  最后修改: {info.get('LastModified', 'N/A')}")
    except Exception as e:
        print(f"  错误: {e}")

    # =========================================================================
    # 5. 读取文件
    # =========================================================================
    print("\n=== 读取文件 ===")
    try:
        data = fs.cat_file(test_path)
        print(f"  内容: {data.decode('utf-8')}")
    except Exception as e:
        print(f"  错误: {e}")

    # =========================================================================
    # 6. 使用上下文管理器读写
    # =========================================================================
    print("\n=== 使用上下文管理器 ===")
    context_path = f"{bucket}/pyobs-example/context_test.txt"

    try:
        # 写入
        with fs.open(context_path, 'wb') as f:
            f.write(b"Written using context manager!")
        print(f"  已写入: {context_path}")

        # 读取
        with fs.open(context_path, 'rb') as f:
            data = f.read()
        print(f"  读取内容: {data.decode('utf-8')}")
    except Exception as e:
        print(f"  错误: {e}")

    # =========================================================================
    # 7. 复制文件
    # =========================================================================
    print("\n=== 复制文件 ===")
    copy_path = f"{bucket}/pyobs-example/hello_copy.txt"

    try:
        fs.cp_file(test_path, copy_path)
        print(f"  已复制: {test_path} -> {copy_path}")
    except Exception as e:
        print(f"  错误: {e}")

    # =========================================================================
    # 8. 列出目录内容
    # =========================================================================
    print("\n=== 列出目录内容 ===")
    try:
        files = fs.ls(f"{bucket}/pyobs-example/")
        for f in files:
            print(f"  - {f['name']} ({f['type']}, {f.get('size', 0)} bytes)")
    except Exception as e:
        print(f"  错误: {e}")

    # =========================================================================
    # 9. 生成预签名 URL
    # =========================================================================
    print("\n=== 生成预签名 URL ===")
    try:
        url = fs.sign(test_path, expiration=3600)
        print(f"  预签名 URL (1小时有效):")
        print(f"  {url[:100]}...")
    except Exception as e:
        print(f"  错误: {e}")

    # =========================================================================
    # 10. 删除文件
    # =========================================================================
    print("\n=== 清理测试文件 ===")
    try:
        # 删除单个文件
        fs.rm(test_path)
        print(f"  已删除: {test_path}")

        fs.rm(copy_path)
        print(f"  已删除: {copy_path}")

        fs.rm(context_path)
        print(f"  已删除: {context_path}")

        # 或者递归删除整个目录
        # fs.rm(f"{bucket}/pyobs-example", recursive=True)
    except Exception as e:
        print(f"  错误: {e}")

    print("\n示例完成!")


if __name__ == "__main__":
    main()
