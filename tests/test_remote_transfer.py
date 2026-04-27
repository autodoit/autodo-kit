import tempfile
import os
from pathlib import Path

from autodokit.tools import remote_transfer


def test_transfer_file(tmp_path):
    src = tmp_path / "in.txt"
    src.write_text("hello world", encoding="utf-8")

    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()
    dst = dst_dir / "in.txt"

    res = remote_transfer.transfer(str(src), str(dst))
    assert Path(res["path"]).exists()
    assert res["size"] == src.stat().st_size
    assert res["sha256"] == remote_transfer._sha256(Path(res["path"]))


def test_transfer_directory(tmp_path):
    src_dir = tmp_path / "srcdir"
    src_dir.mkdir()
    (src_dir / "a.txt").write_text("a", encoding="utf-8")
    (src_dir / "sub").mkdir()
    (src_dir / "sub" / "b.txt").write_text("b", encoding="utf-8")

    dst = tmp_path / "dstdir"
    res = remote_transfer.transfer(str(src_dir), str(dst))
    assert Path(res["path"]).exists()
    assert (dst / "a.txt").read_text(encoding="utf-8") == "a"
    assert (dst / "sub" / "b.txt").read_text(encoding="utf-8") == "b"
