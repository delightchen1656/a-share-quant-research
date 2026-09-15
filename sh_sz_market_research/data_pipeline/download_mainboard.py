"""Resumable BaoStock downloader for Shanghai/Shenzhen Main Board daily bars."""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

import baostock as bs
import pandas as pd


ROOT = Path(__file__).resolve().parent
STATUS_FILE = ROOT / "data" / "status" / "downloader.json"
STOP_FILE = ROOT / "data" / "control" / "stop.request"
FIELDS = "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg,isST"
MAIN_PREFIXES = {
    "SH": ("600", "601", "603", "605"),
    "SZ": ("000", "001", "002", "003"),
}


def result_frame(rs) -> pd.DataFrame:
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    if rs.error_code != "0":
        raise RuntimeError(f"BaoStock {rs.error_code}: {rs.error_msg}")
    return pd.DataFrame(rows, columns=rs.fields)


def standard_symbol(code: str) -> str:
    market, number = code.split(".")
    return f"{number}.{market.upper()}"


def resolve_last_trade_date(end_date: str) -> str:
    dates = result_frame(bs.query_trade_dates(start_date=end_date, end_date=end_date))
    if not dates.empty and dates.iloc[-1]["is_trading_day"] == "1":
        return end_date
    probe_start = (pd.Timestamp(end_date) - pd.Timedelta(days=14)).strftime("%Y-%m-%d")
    dates = result_frame(bs.query_trade_dates(start_date=probe_start, end_date=end_date))
    dates = dates[dates.is_trading_day.eq("1")]
    if dates.empty:
        raise RuntimeError("cannot resolve last trading date")
    return str(dates.iloc[-1]["calendar_date"])


def build_universe(start_date: str, end_date: str) -> pd.DataFrame:
    basic = result_frame(bs.query_stock_basic())
    basic = basic[basic.type.eq("1")].copy()
    basic["symbol"] = basic.code.map(standard_symbol)
    basic["exchange"] = basic.symbol.str[-2:]
    basic["number"] = basic.symbol.str[:6]
    keep_prefix = pd.Series(False, index=basic.index)
    for exchange, prefixes in MAIN_PREFIXES.items():
        keep_prefix |= basic.exchange.eq(exchange) & basic.number.str.startswith(prefixes)
    basic = basic[keep_prefix].copy()
    ipo = pd.to_datetime(basic.ipoDate, errors="coerce")
    out = pd.to_datetime(basic.outDate, errors="coerce")
    # Include every stock that overlaps the requested history, including later
    # delistings. This is required for an unbiased historical training set.
    basic = basic[(ipo.isna() | ipo.le(end_date)) & (out.isna() | out.ge(start_date))].copy()
    basic = basic.sort_values(["exchange", "symbol"]).reset_index(drop=True)
    folder = ROOT / "data" / "metadata"
    folder.mkdir(parents=True, exist_ok=True)
    basic.to_csv(folder / "historical_mainboard_universe.csv", index=False, encoding="utf-8-sig")
    return basic


def get_universe(start_date: str, end_date: str, refresh: bool = False) -> pd.DataFrame:
    """Reuse the saved historical universe on resume, like the proven STAR downloader."""
    cached = ROOT / "data" / "metadata" / "historical_mainboard_universe.csv"
    if cached.exists() and not refresh:
        frame = pd.read_csv(cached, dtype=str, encoding="utf-8-sig")
        required = {"code", "symbol", "exchange", "ipoDate", "outDate"}
        if required.issubset(frame.columns):
            ipo = pd.to_datetime(frame.ipoDate, errors="coerce")
            out = pd.to_datetime(frame.outDate, errors="coerce")
            return frame[(ipo.isna() | ipo.le(end_date)) &
                         (out.isna() | out.ge(start_date))].copy()
    return build_universe(start_date, end_date)


def write_status(**values) -> None:
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"updated_at": datetime.now().isoformat(timespec="seconds"), **values}
    temporary = STATUS_FILE.parent / f"downloader.{os.getpid()}.{time.time_ns()}.tmp"
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        for attempt in range(6):
            try:
                os.replace(temporary, STATUS_FILE)
                return
            except PermissionError:
                if attempt == 5:
                    # A status refresh must never abort market-data downloading.
                    return
                time.sleep(0.05 * (attempt + 1))
    finally:
        try:
            if temporary.exists():
                temporary.unlink()
        except OSError:
            pass


def download_frame(code: str, start_date: str, end_date: str, adjustflag: str) -> pd.DataFrame:
    frame = result_frame(bs.query_history_k_data_plus(
        code, FIELDS, start_date=start_date, end_date=end_date,
        frequency="d", adjustflag=adjustflag,
    ))
    if frame.empty:
        return frame
    frame["symbol"] = standard_symbol(code)
    numeric = ["open", "high", "low", "close", "preclose", "volume", "amount", "turn", "pctChg"]
    frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")
    frame["date"] = pd.to_datetime(frame.date)
    return frame.dropna(subset=["open", "high", "low", "close"])


def complete_marker(target: Path) -> Path:
    return target.with_suffix(".complete.json")


def is_complete(target: Path, start_date: str, end_date: str, flag: str) -> bool:
    marker = complete_marker(target)
    if not marker.exists():
        return False
    try:
        meta = json.loads(marker.read_text(encoding="utf-8"))
        return (meta.get("start_date") == start_date and meta.get("end_date") == end_date
                and meta.get("adjustflag") == flag and (target.exists() or meta.get("rows") == 0))
    except Exception:
        return False


def save_frame(frame: pd.DataFrame, target: Path, meta: dict) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if not frame.empty:
        temporary = target.with_suffix(".tmp.parquet")
        frame.to_parquet(temporary, index=False)
        os.replace(temporary, target)
    complete_marker(target).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def run(exchange: str) -> None:
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    write_status(state="preparing", phase="正在连接免费数据源", pid=os.getpid(),
                 exchange=exchange, start_date=cfg["start_date"],
                 end_date=cfg["end_date"], total_tasks=0, completed_tasks=0)
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError("BaoStock login failed: " + login.error_msg)
    failures = []
    try:
        write_status(state="preparing", phase="正在确认最近交易日", pid=os.getpid(),
                     exchange=exchange, start_date=cfg["start_date"],
                     end_date=cfg["end_date"], total_tasks=0, completed_tasks=0)
        effective_end = resolve_last_trade_date(cfg["end_date"])
        has_cached_universe = (ROOT / "data" / "metadata" / "historical_mainboard_universe.csv").exists()
        phase = "正在读取本地股票清单" if has_cached_universe else "正在下载历史股票清单"
        write_status(state="preparing", phase=phase, pid=os.getpid(),
                     exchange=exchange, start_date=cfg["start_date"],
                     end_date=effective_end, total_tasks=0, completed_tasks=0)
        universe = get_universe(cfg["start_date"], effective_end,
                                refresh=bool(cfg.get("refresh_universe_on_start", False)))
        if exchange != "ALL":
            universe = universe[universe.exchange.eq(exchange)].copy()
        total = len(universe)
        tasks = [(row, kind, flag) for row in universe.itertuples(index=False)
                 for kind, flag in cfg["adjustments"].items()]
        done = 0
        for row, kind, flag in tasks:
            target = ROOT / "data" / kind / row.exchange / f"{row.symbol}.parquet"
            if is_complete(target, cfg["start_date"], effective_end, flag):
                done += 1
        completed_indices = []
        for stock_index, row in enumerate(universe.itertuples(index=False)):
            complete_pair = True
            for kind, flag in cfg["adjustments"].items():
                target = ROOT / "data" / kind / row.exchange / f"{row.symbol}.parquet"
                complete_pair = complete_pair and is_complete(
                    target, cfg["start_date"], effective_end, flag)
            if complete_pair:
                completed_indices.append(stock_index)
        checkpoint_stock = max(completed_indices, default=-1)
        scan_stock = max(0, checkpoint_stock - 5)
        scan_start = scan_stock * len(cfg["adjustments"])
        started = time.monotonic()
        fetched = 0
        write_status(state="running", phase="正在核验断点并下载", pid=os.getpid(), exchange=exchange,
                     start_date=cfg["start_date"], end_date=effective_end,
                     total_tasks=len(tasks), completed_tasks=done,
                     downloaded_this_run=0, failures=0, current_symbol=None,
                     current_kind=None, speed_per_hour=0, eta_hours=None)
        print(f"MAINBOARD {exchange} range={cfg['start_date']}..{effective_end} stocks={total} tasks={len(tasks)} resume={done} scan_from_stock={scan_stock + 1}", flush=True)
        for index, (row, kind, flag) in enumerate(tasks[scan_start:], scan_start + 1):
            if STOP_FILE.exists():
                write_status(state="stopped", pid=os.getpid(), exchange=exchange,
                             start_date=cfg["start_date"], end_date=effective_end,
                             total_tasks=len(tasks), completed_tasks=done,
                             downloaded_this_run=fetched, failures=len(failures),
                             current_symbol=row.symbol, current_kind=kind,
                             speed_per_hour=0, eta_hours=None)
                print("STOPPED safely at task boundary; completed files remain reusable.", flush=True)
                return
            target = ROOT / "data" / kind / row.exchange / f"{row.symbol}.parquet"
            if is_complete(target, cfg["start_date"], effective_end, flag):
                # The checkpoint total was counted before the loop. Skip known
                # files without rewriting status thousands of times; this makes
                # resume scanning nearly instantaneous on Windows.
                continue
            else:
                try:
                    frame = download_frame(row.code, cfg["start_date"], effective_end, flag)
                    save_frame(frame, target, {
                        "symbol": row.symbol, "code": row.code, "kind": kind,
                        "adjustflag": flag, "start_date": cfg["start_date"],
                        "end_date": effective_end, "rows": int(len(frame)),
                        "first_date": str(frame.date.min().date()) if len(frame) else None,
                        "last_date": str(frame.date.max().date()) if len(frame) else None,
                        "completed_at": datetime.now().isoformat(timespec="seconds"),
                    })
                    fetched += 1
                    done += 1
                    status = "DOWNLOADED" if len(frame) else "NO_DATA"
                except Exception as exc:
                    failures.append({"symbol": row.symbol, "kind": kind, "error": str(exc)})
                    status = "FAILED"
                    time.sleep(1)
            elapsed = max(time.monotonic() - started, 0.001)
            rate = fetched / elapsed * 3600 if fetched else 0.0
            remaining = len(tasks) - done
            eta = remaining / rate if rate else 0.0
            write_status(state="running", phase="正在下载行情", pid=os.getpid(), exchange=exchange,
                         start_date=cfg["start_date"], end_date=effective_end,
                         total_tasks=len(tasks), completed_tasks=done,
                         downloaded_this_run=fetched, failures=len(failures),
                         current_symbol=row.symbol, current_kind=kind,
                         speed_per_hour=round(rate, 1),
                         eta_hours=round(eta, 2) if rate else None)
            print(f"[{index:5d}/{len(tasks)}] {index/len(tasks):6.2%} [{status:10s}] {row.symbol} {kind:3s} speed={rate:,.1f} tasks/h ETA={eta:.1f}h failures={len(failures)}", flush=True)
        log_dir = ROOT / "data" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(failures, columns=["symbol", "kind", "error"]).to_csv(
            log_dir / f"failures_{exchange}.csv", index=False, encoding="utf-8-sig")
        write_status(state="completed", pid=os.getpid(), exchange=exchange,
                     start_date=cfg["start_date"], end_date=effective_end,
                     total_tasks=len(tasks), completed_tasks=done,
                     downloaded_this_run=fetched, failures=len(failures),
                     current_symbol=None, current_kind=None,
                     speed_per_hour=0, eta_hours=0)
        print(f"COMPLETE exchange={exchange} stocks={total} tasks={len(tasks)} failures={len(failures)}", flush=True)
    finally:
        bs.logout()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--exchange", choices=["SH", "SZ", "ALL"], default="ALL")
    args = parser.parse_args()
    try:
        run(args.exchange)
    except Exception as exc:
        write_status(state="failed", pid=os.getpid(), exchange=args.exchange,
                     error=str(exc), total_tasks=0, completed_tasks=0)
        raise
