import shutil
from pathlib import Path
from typing import Dict, Any
from config import settings
from core.database import meta_db
from storage.lock import storage_locks

class DiskSentinel:
    """
    50GB 磁盘安全气阀：
    监控 Lazy 缓存池物理占用，在达到高水位时自动触发 LRU 淘汰清理。
    """

    def get_dir_size_bytes(self, path: Path) -> int:
        total = 0
        if not path.exists():
            return 0
        for p in path.glob("**/*"):
            if p.is_file():
                total += p.stat().st_size
        return total

    def get_storage_stats(self) -> Dict[str, Any]:
        """获取系统存储现状"""
        cache_bytes = self.get_dir_size_bytes(settings.CACHE_KLINE_DIR)
        bench_bytes = self.get_dir_size_bytes(settings.BENCHMARK_DIR)
        meta_bytes = settings.META_DB_PATH.stat().st_size if settings.META_DB_PATH.exists() else 0
        
        # 宿主机总磁盘空闲
        disk_usage = shutil.disk_usage(settings.DATA_PATH)
        total_disk_gb = disk_usage.total / (1024 ** 3)
        free_disk_gb = disk_usage.free / (1024 ** 3)

        cache_gb = cache_bytes / (1024 ** 3)
        max_gb = settings.MAX_CACHE_SIZE_GB
        ratio = cache_gb / max_gb if max_gb > 0 else 0

        return {
            "cache_size_gb": round(cache_gb, 3),
            "cache_max_gb": max_gb,
            "cache_usage_ratio": round(ratio * 100, 2),
            "benchmark_size_mb": round(bench_bytes / (1024 ** 2), 2),
            "meta_db_size_mb": round(meta_bytes / (1024 ** 2), 2),
            "host_free_disk_gb": round(free_disk_gb, 2),
            "host_total_disk_gb": round(total_disk_gb, 2),
            "is_safe": free_disk_gb > settings.GLOBAL_DISK_MIN_FREE_GB and ratio < settings.CACHE_HIGH_WATERMARK
        }

    def check_and_evict(self) -> int:
        """
        检查并触发 LRU 淘汰。
        返回已释放的字节数。
        """
        stats = self.get_storage_stats()
        cache_gb = stats["cache_size_gb"]
        high_watermark_gb = settings.MAX_CACHE_SIZE_GB * settings.CACHE_HIGH_WATERMARK
        low_watermark_gb = settings.MAX_CACHE_SIZE_GB * settings.CACHE_LOW_WATERMARK

        # 检查是否需要清理
        if cache_gb < high_watermark_gb and stats["host_free_disk_gb"] > settings.GLOBAL_DISK_MIN_FREE_GB:
            return 0

        print(f"[DiskSentinel] Triggering LRU eviction: Cache is {cache_gb:.2f}GB (High watermark: {high_watermark_gb:.2f}GB)")
        
        freed_bytes = 0
        target_bytes_to_free = int((cache_gb - low_watermark_gb) * (1024 ** 3))
        if target_bytes_to_free <= 0:
            target_bytes_to_free = int(1 * 1024 * 1024 * 1024) # 至少释放 1GB

        # 获取最久未访问的标的
        candidates = meta_db.get_lru_candidates(limit=100)
        
        # 优先清理分钟线，其次清理日K
        minute_candidates = [c for c in candidates if c["period"] not in ["1d", "1w", "1M"]]
        daily_candidates = [c for c in candidates if c["period"] in ["1d", "1w", "1M"]]
        ordered_candidates = minute_candidates + daily_candidates

        for item in ordered_candidates:
            if freed_bytes >= target_bytes_to_free:
                break

            file_path = Path(item["file_path"])
            file_size = item["file_size_bytes"] or (file_path.stat().st_size if file_path.exists() else 0)

            if file_path.exists():
                with storage_locks.lock(str(file_path)):
                    try:
                        file_path.unlink()
                        freed_bytes += file_size
                        # 物理文件成功删除后才移除元数据
                        meta_db.remove_cache_record(item["symbol"], item["period"])
                        print(f"[DiskSentinel] Evicted {item['symbol']} ({item['period']}): freed {file_size / 1024 / 1024:.2f}MB")
                    except Exception as e:
                        print(f"[DiskSentinel] Error deleting {file_path}: {e}. Metadata preserved.")
            else:
                # 物理文件已不存在，清理孤儿元数据
                meta_db.remove_cache_record(item["symbol"], item["period"])

        print(f"[DiskSentinel] Eviction complete: freed total {freed_bytes / 1024 / 1024:.2f}MB")
        return freed_bytes

sentinel = DiskSentinel()
