"""prune_old_backups 备份轮转的单元测试。"""
import os
import time

from service import ormService


def test_prune_keeps_latest_n(tmp_path, monkeypatch):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    monkeypatch.setattr(ormService.appPaths, "DATA_DIR", str(tmp_path))

    # 造 5 个备份，mtime 递增（旧的在前）
    files = []
    for i in range(5):
        p = backup_dir / f"data_2026010{i}_000000.db"
        p.write_bytes(b"x")
        ts = time.time() - (5 - i) * 100  # 越早越小
        os.utime(p, (ts, ts))
        files.append(str(p))

    removed = ormService.prune_old_backups(keep=2)
    assert removed == 3
    remaining = sorted(os.listdir(backup_dir))
    assert len(remaining) == 2
    # 保留的是最新的两个（i=3,4）
    assert "data_20260103_000000.db" in remaining
    assert "data_20260104_000000.db" in remaining


def test_prune_no_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ormService.appPaths, "DATA_DIR", str(tmp_path / "nonexist"))
    assert ormService.prune_old_backups(keep=2) == 0


def test_prune_keep_zero_removes_all(tmp_path, monkeypatch):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    monkeypatch.setattr(ormService.appPaths, "DATA_DIR", str(tmp_path))
    for i in range(3):
        (backup_dir / f"b{i}.db").write_bytes(b"x")
    assert ormService.prune_old_backups(keep=0) == 3
    assert os.listdir(backup_dir) == []
