#!/usr/bin/env python
"""高级用法示例 - 演示 pyobs 的高级功能。

运行前请设置环境变量：
    export OBS_ACCESS_KEY_ID=your-access-key
    export OBS_SECRET_ACCESS_KEY=your-secret-key
    export OBS_ENDPOINT=https://obs.cn-north-4.myhuaweicloud.com
"""

import fsspec
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed


def example_thread_safety():
    """示例: 多线程安全访问。

    OBSFileSystem 使用 threading.local() 为每个线程创建独立的 ObsClient，
    确保线程安全。
    """
    print("\n=== 多线程安全访问 ===")

    fs = fsspec.filesystem('obs')
    bucket = "your-bucket-name"
    base_path = f"{bucket}/thread-test"

    results = []
    errors = []
    lock = threading.Lock()

    def worker(thread_id: int, num_operations: int):
        """线程工作函数。"""
        try:
            for i in range(num_operations):
                path = f"{base_path}/thread_{thread_id}_file_{i}.txt"
                content = f"Thread {thread_id}, Operation {i}, Time {time.time()}"

                # 写入
                fs.pipe_file(path, content.encode())

                # 读取验证
                data = fs.cat_file(path)
                assert data.decode() == content

                # 删除
                fs.rm(path)

                with lock:
                    results.append((thread_id, i, True))

        except Exception as e:
            with lock:
                errors.append((thread_id, str(e)))

    num_threads = 5
    operations_per_thread = 10

    print(f"  启动 {num_threads} 个线程，每个执行 {operations_per_thread} 次操作...")

    threads = []
    start_time = time.time()

    for i in range(num_threads):
        t = threading.Thread(target=worker, args=(i, operations_per_thread))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    elapsed = time.time() - start_time

    print(f"  完成:")
    print(f"    成功操作: {len(results)}")
    print(f"    失败操作: {len(errors)}")
    print(f"    总耗时: {elapsed:.2f}s")

    if errors:
        print(f"  错误详情:")
        for thread_id, error in errors:
            print(f"    线程 {thread_id}: {error}")


def example_signed_url():
    """示例: 预签名 URL 的各种用法。"""
    print("\n=== 预签名 URL ===")

    fs = fsspec.filesystem('obs')
    bucket = "your-bucket-name"

    # 创建测试文件
    test_path = f"{bucket}/signed-url-test/document.txt"
    fs.pipe_file(test_path, b"This is a test document for signed URL.")

    try:
        # 1. 默认签名 (1小时)
        url_1h = fs.sign(test_path)
        print(f"  1小时有效 URL:")
        print(f"    {url_1h[:80]}...")

        # 2. 自定义过期时间
        url_24h = fs.sign(test_path, expiration=86400)  # 24小时
        print(f"\n  24小时有效 URL:")
        print(f"    {url_24h[:80]}...")

        # 3. 短时间 URL (用于临时分享)
        url_5min = fs.sign(test_path, expiration=300)  # 5分钟
        print(f"\n  5分钟有效 URL:")
        print(f"    {url_5min[:80]}...")

        # 4. 使用签名 URL 下载 (使用 requests)
        print(f"\n  使用签名 URL 下载:")
        try:
            import requests
            response = requests.get(url_1h)
            if response.status_code == 200:
                print(f"    下载成功: {response.text}")
            else:
                print(f"    下载失败: HTTP {response.status_code}")
        except ImportError:
            print("    (需要安装 requests 库)")

    except Exception as e:
        print(f"  错误: {e}")
    finally:
        try:
            fs.rm(test_path)
        except:
            pass


def example_directory_operations():
    """示例: 目录操作。"""
    print("\n=== 目录操作 ===")

    fs = fsspec.filesystem('obs')
    bucket = "your-bucket-name"
    base_path = f"{bucket}/dir-test"

    try:
        # 1. 创建目录结构
        print("  创建目录结构:")
        fs.makedirs(f"{base_path}/level1/level2/level3")
        print(f"    已创建: {base_path}/level1/level2/level3")

        # 2. 在各级目录创建文件
        for level in ['level1', 'level1/level2', 'level1/level2/level3']:
            fs.pipe_file(f"{base_path}/{level}/file.txt", f"File in {level}".encode())
            print(f"    创建文件: {base_path}/{level}/file.txt")

        # 3. 列出目录内容
        print(f"\n  列出 {base_path}/level1:")
        items = fs.ls(f"{base_path}/level1")
        for item in items:
            print(f"    - {item['name']} ({item['type']})")

        # 4. 递归列出所有内容
        print(f"\n  递归列出 {base_path}:")
        all_items = fs.ls(base_path, detail=True)
        for item in all_items:
            print(f"    - {item['name']} ({item['type']}, {item.get('size', 0)} bytes)")

        # 5. 检查目录存在性
        print(f"\n  目录存在性检查:")
        print(f"    {base_path}/level1 存在: {fs.exists(f'{base_path}/level1')}")
        print(f"    {base_path}/nonexistent 存在: {fs.exists(f'{base_path}/nonexistent')}")

        # 6. 获取目录信息
        print(f"\n  目录信息:")
        info = fs.info(f"{base_path}/level1")
        print(f"    类型: {info['type']}")
        print(f"    名称: {info['name']}")

    except Exception as e:
        print(f"  错误: {e}")
    finally:
        # 清理
        try:
            fs.rm(base_path, recursive=True)
            print(f"\n  已清理: {base_path}")
        except:
            pass


def example_error_handling():
    """示例: 错误处理。"""
    print("\n=== 错误处理 ===")

    from pyobsfs import (
        OBSError,
        OBSFileNotFoundError,
        OBSPermissionError,
    )

    fs = fsspec.filesystem('obs')
    bucket = "your-bucket-name"

    # 1. 文件不存在
    print("  测试文件不存在错误:")
    try:
        fs.cat_file(f"{bucket}/nonexistent-file-12345.txt")
    except FileNotFoundError as e:
        print(f"    捕获到 FileNotFoundError: {e}")
    except OBSFileNotFoundError as e:
        print(f"    捕获到 OBSFileNotFoundError: {e}")

    # 2. Bucket 不存在
    print("\n  测试 Bucket 不存在错误:")
    try:
        fs.ls("nonexistent-bucket-xyz-12345/")
    except (FileNotFoundError, OBSError) as e:
        print(f"    捕获到错误: {type(e).__name__}: {e}")

    # 3. 优雅处理
    print("\n  优雅的错误处理模式:")
    path = f"{bucket}/maybe-exists.txt"

    if fs.exists(path):
        data = fs.cat_file(path)
        print(f"    文件存在，内容长度: {len(data)}")
    else:
        print(f"    文件不存在: {path}")


def example_caching():
    """示例: fsspec 缓存。"""
    print("\n=== fsspec 缓存 ===")

    # fsspec 默认会缓存 FileSystem 实例
    # 相同参数的 filesystem() 调用会返回同一个实例

    print("  创建多个 filesystem 实例:")

    fs1 = fsspec.filesystem('obs')
    fs2 = fsspec.filesystem('obs')

    print(f"    fs1 id: {id(fs1)}")
    print(f"    fs2 id: {id(fs2)}")
    print(f"    fs1 is fs2: {fs1 is fs2}")  # 可能为 True (取决于参数)

    # 禁用缓存
    print("\n  禁用实例缓存:")
    fs3 = fsspec.filesystem('obs', skip_instance_cache=True)
    fs4 = fsspec.filesystem('obs', skip_instance_cache=True)

    print(f"    fs3 id: {id(fs3)}")
    print(f"    fs4 id: {id(fs4)}")
    print(f"    fs3 is fs4: {fs3 is fs4}")  # False


def example_context_manager():
    """示例: 上下文管理器的正确使用。"""
    print("\n=== 上下文管理器 ===")

    fs = fsspec.filesystem('obs')
    bucket = "your-bucket-name"
    path = f"{bucket}/context-test/file.txt"

    try:
        # 1. 写入模式
        print("  写入文件:")
        with fs.open(path, 'wb') as f:
            f.write(b"Line 1\n")
            f.write(b"Line 2\n")
            f.write(b"Line 3\n")
        print(f"    已写入: {path}")

        # 2. 读取模式
        print("\n  读取文件:")
        with fs.open(path, 'rb') as f:
            content = f.read()
        print(f"    内容: {content.decode()}")

        # 3. 逐行读取
        print("  逐行读取:")
        with fs.open(path, 'rb') as f:
            for i, line in enumerate(f, 1):
                print(f"    行 {i}: {line.decode().strip()}")

        # 4. 文本模式 (需要指定 encoding)
        print("\n  文本模式:")
        # 注意: 具体支持取决于 OBSFile 实现
        # 通常推荐使用二进制模式然后手动 decode

    except Exception as e:
        print(f"  错误: {e}")
    finally:
        try:
            fs.rm(f"{bucket}/context-test", recursive=True)
        except:
            pass


def example_protocol_registration():
    """示例: 协议注册验证。"""
    print("\n=== 协议注册 ===")

    # pyobs 注册了两个协议: obs 和 hwobs
    print("  已注册的协议:")

    # 检查 obs 协议
    try:
        fs_obs = fsspec.filesystem('obs')
        print(f"    obs: {type(fs_obs).__name__}")
    except Exception as e:
        print(f"    obs: 错误 - {e}")

    # 检查 hwobs 协议
    try:
        fs_hwobs = fsspec.filesystem('hwobs')
        print(f"    hwobs: {type(fs_hwobs).__name__}")
    except Exception as e:
        print(f"    hwobs: 错误 - {e}")

    # 显示所有已知协议
    print("\n  fsspec 已知协议:")
    known = fsspec.available_protocols()
    obs_protocols = [p for p in known if 'obs' in p.lower()]
    for p in obs_protocols:
        print(f"    - {p}")


def main():
    """运行所有高级示例。"""
    print("=" * 60)
    print("高级用法示例")
    print("=" * 60)

    # 协议注册
    example_protocol_registration()

    # fsspec 缓存
    example_caching()

    # 上下文管理器
    example_context_manager()

    # 目录操作
    example_directory_operations()

    # 错误处理
    example_error_handling()

    # 预签名 URL
    example_signed_url()

    # 多线程
    example_thread_safety()

    print("\n所有高级示例完成!")


if __name__ == "__main__":
    main()
