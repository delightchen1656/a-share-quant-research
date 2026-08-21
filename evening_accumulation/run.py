from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.data import download_all, load_panel
from src.model import backtest_all, generate_signals, train_all


def main() -> None:
    p = argparse.ArgumentParser(description="晚间主力建仓形态策略")
    p.add_argument("command", choices=["download", "train", "backtest", "evening"])
    p.add_argument("--limit", type=int, help="仅下载前 N 只，用于连通性测试")
    p.add_argument("--board", choices=["main", "chinext", "star"], help="仅加载和处理指定板块")
    args = p.parse_args()
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    if args.command == "download":
        download_all(ROOT, cfg, args.limit)
    elif args.command == "train":
        train_all(ROOT, cfg, load_panel(ROOT, args.board), args.board)
    elif args.command == "backtest":
        backtest_all(ROOT, cfg, load_panel(ROOT, args.board), args.board)
    else:
        download_all(ROOT, cfg, None)
        generate_signals(ROOT, cfg, load_panel(ROOT, args.board))


if __name__ == "__main__":
    main()
