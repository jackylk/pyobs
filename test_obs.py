#!/usr/bin/env python
"""pyobs 功能测试脚本 - 在真实 OBS 桶上测试各种操作

所有测试都在 {bucket}/pyobs-test/ 目录下进行，不会影响其他数据。
"""

import os
import sys
import uuid
from datetime import datetime

# 加载 .env 文件
from pathlib import Path
env_file = Path(__file__).parent / '.env'
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            os.environ[key] = value
    print(f"✓ 已加载环境变量从 {env_file}")

import fsspec

# 测试专用前缀 - 所有测试数据都在这个目录下
TEST_PREFIX = "pyobs-test"

def get_test_path(bucket, *parts):
    """生成测试路径，确保所有操作都在 TEST_PREFIX 下"""
    return f"{bucket}/{TEST_PREFIX}/" + "/".join(parts)

def test_filesystem_creation():
    """测试文件系统创建"""
    print("\n" + "="*60)
    print("测试 1: 创建文件系统实例")
    print("="*60)

    fs = fsspec.filesystem('obs')
    print(f"✓ 文件系统创建成功: {type(fs).__name__}")
    print(f"  - endpoint: {fs.endpoint}")
    print(f"  - protocol: {fs.protocol}")
    return fs

def test_list_buckets(fs):
    """测试列出所有桶"""
    print("\n" + "="*60)
    print("测试 2: 列出所有 Bucket")
    print("="*60)

    buckets = fs.ls("")
    print(f"✓ 找到 {len(buckets)} 个桶:")
    for b in buckets:
        print(f"  - {b['name']}")
    return buckets

def test_bucket_exists(fs, bucket):
    """测试桶存在性检查"""
    print("\n" + "="*60)
    print(f"测试 3: 检查桶 '{bucket}' 是否存在")
    print("="*60)

    exists = fs.exists(bucket)
    print(f"✓ 桶 '{bucket}' 存在: {exists}")
    return exists

def test_write_file(fs, bucket):
    """测试写入文件"""
    print("\n" + "="*60)
    print("测试 4: 写入文件")
    print("="*60)

    # 写入简单文本文件
    path = get_test_path(bucket, "files", "hello.txt")
    content = "你好，pyobs！这是一个测试文件。\nHello from obsfs!"
    fs.pipe_file(path, content.encode('utf-8'))
    print(f"✓ 已写入: {path}")

    # 写入 JSON 文件
    json_path = get_test_path(bucket, "files", "data.json")
    json_content = '{"name": "pyobs", "version": "0.1.0", "features": ["read", "write", "delete"]}'
    fs.pipe_file(json_path, json_content.encode('utf-8'))
    print(f"✓ 已写入: {json_path}")

    # 写入二进制文件
    bin_path = get_test_path(bucket, "files", "binary.bin")
    bin_content = bytes(range(256))
    fs.pipe_file(bin_path, bin_content)
    print(f"✓ 已写入: {bin_path} ({len(bin_content)} 字节)")

    return [path, json_path, bin_path]

def test_read_file(fs, bucket):
    """测试读取文件"""
    print("\n" + "="*60)
    print("测试 5: 读取文件")
    print("="*60)

    path = get_test_path(bucket, "files", "hello.txt")
    data = fs.cat_file(path)
    print(f"✓ 读取 {path}:")
    print(f"  内容: {data.decode('utf-8')}")

    # 测试范围读取
    partial = fs.cat_file(path, start=0, end=20)
    print(f"✓ 范围读取 [0:20]: {partial.decode('utf-8')}")

    return data

def test_file_info(fs, bucket):
    """测试获取文件信息"""
    print("\n" + "="*60)
    print("测试 6: 获取文件信息")
    print("="*60)

    path = get_test_path(bucket, "files", "hello.txt")
    info = fs.info(path)
    print(f"✓ 文件信息 {path}:")
    for key, value in info.items():
        print(f"  - {key}: {value}")

    return info

def test_directory_operations(fs, bucket):
    """测试目录操作"""
    print("\n" + "="*60)
    print("测试 7: 目录操作")
    print("="*60)

    # 创建嵌套目录结构
    base = get_test_path(bucket, "dirs")

    # 创建目录
    fs.makedirs(f"{base}/level1/level2/level3")
    print(f"✓ 创建目录: {base}/level1/level2/level3")

    # 在各级目录创建文件
    files = []
    for level in ["", "/level1", "/level1/level2", "/level1/level2/level3"]:
        file_path = f"{base}{level}/file.txt"
        fs.pipe_file(file_path, f"File in {level or 'root'}".encode())
        files.append(file_path)
        print(f"✓ 创建文件: {file_path}")

    # 列出目录内容
    print(f"\n列出 {base}/level1 的内容:")
    items = fs.ls(f"{base}/level1")
    for item in items:
        item_type = item.get('type', 'unknown')
        print(f"  - {item['name']} ({item_type})")

    return files

def test_copy_file(fs, bucket):
    """测试复制文件"""
    print("\n" + "="*60)
    print("测试 8: 复制文件")
    print("="*60)

    src = get_test_path(bucket, "files", "hello.txt")
    dst = get_test_path(bucket, "files", "hello_copy.txt")

    fs.cp_file(src, dst)
    print(f"✓ 复制: {src} -> {dst}")

    # 验证复制成功
    exists = fs.exists(dst)
    print(f"✓ 目标文件存在: {exists}")

    return dst

def test_context_manager(fs, bucket):
    """测试上下文管理器"""
    print("\n" + "="*60)
    print("测试 9: 上下文管理器读写")
    print("="*60)

    path = get_test_path(bucket, "files", "context_test.txt")

    # 使用上下文管理器写入
    with fs.open(path, 'wb') as f:
        f.write("Line 1: 第一行\n".encode('utf-8'))
        f.write("Line 2: 第二行\n".encode('utf-8'))
        f.write("Line 3: 第三行\n".encode('utf-8'))
    print(f"✓ 上下文管理器写入: {path}")

    # 使用上下文管理器读取
    with fs.open(path, 'rb') as f:
        content = f.read()
    print(f"✓ 上下文管理器读取:")
    print(f"  {content.decode('utf-8')}")

    return path

def test_signed_url(fs, bucket):
    """测试预签名 URL"""
    print("\n" + "="*60)
    print("测试 10: 预签名 URL")
    print("="*60)

    path = get_test_path(bucket, "files", "hello.txt")

    # 生成下载 URL
    url = fs.sign(path, expiration=3600)
    print(f"✓ 预签名 URL (1小时有效):")
    print(f"  {url[:100]}...")

    return url

def test_list_test_folder(fs, bucket):
    """测试列出测试文件夹内容"""
    print("\n" + "="*60)
    print("测试 11: 列出测试文件夹内容")
    print("="*60)

    test_root = f"{bucket}/{TEST_PREFIX}/"
    items = fs.ls(test_root)
    print(f"✓ 测试目录 '{test_root}' 中的内容:")
    for item in items:
        item_type = item.get('type', 'unknown')
        size = item.get('size', 0)
        print(f"  - {item['name']} ({item_type}, {size} bytes)")

    return items

def test_cleanup(fs, bucket, do_cleanup=True):
    """清理测试数据"""
    print("\n" + "="*60)
    print("测试 12: 清理测试数据")
    print("="*60)

    test_root = f"{bucket}/{TEST_PREFIX}"

    if not do_cleanup:
        print(f"⏭ 跳过清理，测试数据保留在: {test_root}/")
        return

    if fs.exists(test_root):
        # 列出要删除的内容
        items = fs.ls(test_root)
        print(f"将删除 {len(items)} 个对象/目录:")
        for item in items[:5]:
            print(f"  - {item['name']}")
        if len(items) > 5:
            print(f"  ... 还有 {len(items) - 5} 个")

        # 递归删除
        fs.rm(test_root, recursive=True)
        print(f"✓ 已删除: {test_root} (递归)")

    # 验证删除
    exists = fs.exists(test_root)
    print(f"✓ 测试目录 '{test_root}' 存在: {exists}")

def main():
    """运行所有测试"""
    print("="*60)
    print("pyobs 功能测试")
    print("="*60)

    bucket = os.environ.get("OBS_TEST_BUCKET", "obs-fs-test-jska")
    print(f"测试桶: {bucket}")
    print(f"测试目录: {bucket}/{TEST_PREFIX}/")
    print(f"⚠️  所有测试数据都在 '{TEST_PREFIX}/' 目录下，不会影响其他数据")

    # 是否在测试结束后清理数据
    do_cleanup = "--no-cleanup" not in sys.argv

    try:
        # 创建文件系统
        fs = test_filesystem_creation()

        # 列出所有桶
        test_list_buckets(fs)

        # 检查测试桶是否存在
        if not test_bucket_exists(fs, bucket):
            print(f"❌ 桶 '{bucket}' 不存在，请先创建")
            return 1

        # 文件操作测试
        test_write_file(fs, bucket)
        test_read_file(fs, bucket)
        test_file_info(fs, bucket)

        # 目录操作测试
        test_directory_operations(fs, bucket)

        # 复制文件测试
        test_copy_file(fs, bucket)

        # 上下文管理器测试
        test_context_manager(fs, bucket)

        # 预签名 URL 测试
        test_signed_url(fs, bucket)

        # 列出测试文件夹
        test_list_test_folder(fs, bucket)

        # 清理测试数据
        test_cleanup(fs, bucket, do_cleanup)

        print("\n" + "="*60)
        print("✅ 所有测试完成!")
        print("="*60)
        return 0

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
