#!/usr/bin/env python
"""大文件上传示例 - 演示分块上传功能。

运行前请设置环境变量：
    export OBS_ACCESS_KEY_ID=your-access-key
    export OBS_SECRET_ACCESS_KEY=your-secret-key
    export OBS_ENDPOINT=https://obs.cn-north-4.myhuaweicloud.com
"""

import fsspec
import time
import hashlib
import tempfile
import os


def format_size(size_bytes: int) -> str:
    """格式化文件大小。"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} PB"


def format_speed(bytes_per_sec: float) -> str:
    """格式化传输速度。"""
    return f"{format_size(bytes_per_sec)}/s"


def create_test_file(size_mb: int, path: str) -> str:
    """创建指定大小的测试文件，返回 MD5 哈希。"""
    print(f"  创建 {size_mb}MB 测试文件...")

    chunk_size = 1024 * 1024  # 1MB
    hasher = hashlib.md5()

    with open(path, 'wb') as f:
        for i in range(size_mb):
            # 生成可重复的随机数据
            data = bytes([((i * 256 + j) % 256) for j in range(chunk_size)])
            f.write(data)
            hasher.update(data)

            if (i + 1) % 100 == 0:
                print(f"    已写入 {i + 1}MB...")

    return hasher.hexdigest()


def example_pipe_file_upload():
    """示例: 使用 pipe_file 上传大文件。

    pipe_file 会自动根据文件大小选择:
    - 小于 100MB: 简单上传
    - 大于等于 100MB: 分块上传
    """
    print("\n=== 使用 pipe_file 上传大文件 ===")

    fs = fsspec.filesystem('obs')
    bucket = "your-bucket-name"

    # 创建测试数据 (50MB，使用简单上传)
    size_mb = 50
    data = bytes([i % 256 for i in range(size_mb * 1024 * 1024)])
    original_md5 = hashlib.md5(data).hexdigest()

    remote_path = f"{bucket}/large-file-test/pipe_file_50mb.bin"

    try:
        print(f"  上传 {size_mb}MB 文件到 {remote_path}")
        start_time = time.time()

        fs.pipe_file(remote_path, data)

        elapsed = time.time() - start_time
        speed = len(data) / elapsed

        print(f"  上传完成:")
        print(f"    大小: {format_size(len(data))}")
        print(f"    耗时: {elapsed:.2f}s")
        print(f"    速度: {format_speed(speed)}")

        # 验证
        info = fs.info(remote_path)
        print(f"    远程文件大小: {format_size(info['size'])}")

        # 下载验证
        print(f"  下载验证...")
        downloaded = fs.cat_file(remote_path)
        downloaded_md5 = hashlib.md5(downloaded).hexdigest()

        if original_md5 == downloaded_md5:
            print(f"    MD5 校验通过: {original_md5}")
        else:
            print(f"    MD5 校验失败!")
            print(f"      原始: {original_md5}")
            print(f"      下载: {downloaded_md5}")

    except Exception as e:
        print(f"  错误: {e}")
    finally:
        try:
            fs.rm(remote_path)
            print(f"  已清理: {remote_path}")
        except:
            pass


def example_multipart_upload():
    """示例: 大文件分块上传 (>100MB 自动触发)。"""
    print("\n=== 分块上传大文件 (>100MB) ===")

    fs = fsspec.filesystem('obs')
    bucket = "your-bucket-name"

    # 创建 150MB 测试文件 (会触发分块上传)
    size_mb = 150

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp_path = tmp.name

    try:
        original_md5 = create_test_file(size_mb, tmp_path)
        print(f"  原始文件 MD5: {original_md5}")

        # 读取并上传
        remote_path = f"{bucket}/large-file-test/multipart_150mb.bin"

        print(f"  开始分块上传到 {remote_path}...")
        start_time = time.time()

        with open(tmp_path, 'rb') as f:
            data = f.read()

        fs.pipe_file(remote_path, data)

        elapsed = time.time() - start_time
        speed = len(data) / elapsed

        print(f"  上传完成:")
        print(f"    大小: {format_size(len(data))}")
        print(f"    耗时: {elapsed:.2f}s")
        print(f"    速度: {format_speed(speed)}")

        # 验证
        info = fs.info(remote_path)
        print(f"    远程文件大小: {format_size(info['size'])}")

    except Exception as e:
        print(f"  错误: {e}")
    finally:
        # 清理本地文件
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

        # 清理远程文件
        try:
            fs.rm(f"{bucket}/large-file-test", recursive=True)
        except:
            pass


def example_streaming_upload():
    """示例: 使用文件对象流式上传。"""
    print("\n=== 流式上传 ===")

    fs = fsspec.filesystem('obs')
    bucket = "your-bucket-name"

    remote_path = f"{bucket}/large-file-test/streaming.bin"

    try:
        print(f"  使用上下文管理器流式写入...")

        # 使用上下文管理器写入
        # 这种方式适合需要分多次写入的场景
        total_written = 0
        chunk_size = 5 * 1024 * 1024  # 5MB chunks

        with fs.open(remote_path, 'wb') as f:
            for i in range(10):  # 写入 10 个 5MB 块 = 50MB
                chunk = bytes([((i * 256 + j) % 256) for j in range(chunk_size)])
                f.write(chunk)
                total_written += len(chunk)
                print(f"    已写入 {format_size(total_written)}")

        print(f"  写入完成: {format_size(total_written)}")

        # 验证
        info = fs.info(remote_path)
        print(f"  远程文件大小: {format_size(info['size'])}")

        # 流式读取
        print(f"\n  流式读取验证...")
        total_read = 0

        with fs.open(remote_path, 'rb') as f:
            while True:
                data = f.read(chunk_size)
                if not data:
                    break
                total_read += len(data)

        print(f"  读取完成: {format_size(total_read)}")

    except Exception as e:
        print(f"  错误: {e}")
    finally:
        try:
            fs.rm(remote_path)
        except:
            pass


def example_range_read():
    """示例: 范围读取大文件的部分内容。"""
    print("\n=== 范围读取 ===")

    fs = fsspec.filesystem('obs')
    bucket = "your-bucket-name"

    # 创建测试文件
    size_mb = 20
    data = bytes([i % 256 for i in range(size_mb * 1024 * 1024)])
    remote_path = f"{bucket}/large-file-test/range_read.bin"

    try:
        fs.pipe_file(remote_path, data)
        print(f"  已上传 {size_mb}MB 测试文件")

        # 范围读取
        print(f"\n  范围读取测试:")

        # 读取前 1KB
        start, end = 0, 1024
        partial = fs.cat_file(remote_path, start=start, end=end)
        print(f"  读取 [{start}, {end}): {len(partial)} 字节")
        assert partial == data[start:end], "范围读取验证失败"

        # 读取中间 1MB
        start, end = 5 * 1024 * 1024, 6 * 1024 * 1024
        partial = fs.cat_file(remote_path, start=start, end=end)
        print(f"  读取 [{format_size(start)}, {format_size(end)}): {len(partial)} 字节")
        assert partial == data[start:end], "范围读取验证失败"

        # 读取最后 1KB
        start, end = len(data) - 1024, len(data)
        partial = fs.cat_file(remote_path, start=start, end=end)
        print(f"  读取最后 1KB: {len(partial)} 字节")
        assert partial == data[start:end], "范围读取验证失败"

        print(f"\n  所有范围读取验证通过!")

    except Exception as e:
        print(f"  错误: {e}")
    finally:
        try:
            fs.rm(remote_path)
        except:
            pass


def example_concurrent_upload():
    """示例: 并发上传多个文件。"""
    print("\n=== 并发上传 ===")

    import concurrent.futures

    bucket = "your-bucket-name"
    num_files = 5
    file_size_mb = 10

    def upload_file(file_index: int) -> dict:
        """上传单个文件。"""
        # 每个线程创建自己的 fs 实例（线程安全）
        fs = fsspec.filesystem('obs')

        data = bytes([((file_index * 256 + i) % 256) for i in range(file_size_mb * 1024 * 1024)])
        path = f"{bucket}/large-file-test/concurrent/file_{file_index}.bin"

        start_time = time.time()
        fs.pipe_file(path, data)
        elapsed = time.time() - start_time

        return {
            'file_index': file_index,
            'size': len(data),
            'elapsed': elapsed,
            'speed': len(data) / elapsed
        }

    try:
        print(f"  并发上传 {num_files} 个 {file_size_mb}MB 文件...")

        start_time = time.time()

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_files) as executor:
            futures = [executor.submit(upload_file, i) for i in range(num_files)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        total_elapsed = time.time() - start_time
        total_size = sum(r['size'] for r in results)

        print(f"\n  上传结果:")
        for r in sorted(results, key=lambda x: x['file_index']):
            print(f"    文件 {r['file_index']}: {format_size(r['size'])} in {r['elapsed']:.2f}s ({format_speed(r['speed'])})")

        print(f"\n  总计:")
        print(f"    文件数: {num_files}")
        print(f"    总大小: {format_size(total_size)}")
        print(f"    总耗时: {total_elapsed:.2f}s")
        print(f"    有效速度: {format_speed(total_size / total_elapsed)}")

    except Exception as e:
        print(f"  错误: {e}")
    finally:
        try:
            fs = fsspec.filesystem('obs')
            fs.rm(f"{bucket}/large-file-test/concurrent", recursive=True)
        except:
            pass


def main():
    """运行所有大文件示例。"""
    print("=" * 60)
    print("大文件操作示例")
    print("=" * 60)

    # 简单上传
    example_pipe_file_upload()

    # 流式上传
    example_streaming_upload()

    # 范围读取
    example_range_read()

    # 并发上传
    example_concurrent_upload()

    # 分块上传 (需要较大内存和时间)
    # 取消注释以测试
    # example_multipart_upload()

    print("\n所有示例完成!")


if __name__ == "__main__":
    main()
