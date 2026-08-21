from __future__ import annotations

import time
from pathlib import Path

import baostock as bs
import pandas as pd


FIELDS = "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg,isST"


def standard_symbol(code: str) -> str:
    market, number = code.split(".")
    if market == "sh": return f"{number}.SH"
    if market == "sz": return f"{number}.SZ"
    return f"{number}.BJ"


def board_of(symbol: str) -> str:
    code, market = symbol.split(".")
    if market == "BJ": return "beijing"
    if code.startswith(("300", "301")): return "chinext"
    if code.startswith("688"): return "star"
    return "main"


def _result_frame(rs) -> pd.DataFrame:
    rows = []
    while rs.error_code == "0" and rs.next(): rows.append(rs.get_row_data())
    if rs.error_code != "0": raise RuntimeError(f"BaoStock {rs.error_code}: {rs.error_msg}")
    return pd.DataFrame(rows, columns=rs.fields)


def get_universe(root: Path, as_of_date: str) -> pd.DataFrame:
    df = _result_frame(bs.query_stock_basic())
    df = df[df["type"].eq("1")].copy()
    as_of = pd.Timestamp(as_of_date)
    ipo = pd.to_datetime(df["ipoDate"], errors="coerce")
    out = pd.to_datetime(df["outDate"], errors="coerce")
    # Only securities that were still listed on the requested end date.
    df = df[(ipo.isna() | ipo.le(as_of)) & (out.isna() | out.gt(as_of))].copy()
    # BaoStock 沪深代码；北京代码若数据源提供则保留并映射。
    df["symbol"] = df["code"].map(standard_symbol)
    df["board"] = df["symbol"].map(board_of)
    out = root / "data" / "metadata"; out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "universe.csv", index=False, encoding="utf-8-sig")
    return df


def _download_symbol(code: str, start: str, end: str, adjustflag: str) -> pd.DataFrame:
    rs = bs.query_history_k_data_plus(code, FIELDS, start_date=start, end_date=end,
                                      frequency="d", adjustflag=adjustflag)
    df = _result_frame(rs)
    if df.empty: return df
    df["symbol"] = standard_symbol(code); df["board"] = board_of(df["symbol"].iloc[0])
    numeric = ["open", "high", "low", "close", "preclose", "volume", "amount", "turn", "pctChg"]
    df[numeric] = df[numeric].apply(pd.to_numeric, errors="coerce")
    df["date"] = pd.to_datetime(df["date"])
    return df.dropna(subset=["open", "high", "low", "close"])


def _file_complete(target: Path, end_date: str) -> bool:
    """Return True when a file (or an explicit no-data marker) is complete."""
    if target.with_suffix(".no_data").exists():
        return True
    if not target.exists():
        return False
    try:
        dates = pd.read_parquet(target, columns=["date"])["date"]
        return not dates.empty and dates.max() >= pd.Timestamp(end_date)
    except Exception:
        return False


def _in_requested_period(row, start_date: str, end_date: str) -> bool:
    ipo = pd.to_datetime(getattr(row, "ipoDate", ""), errors="coerce")
    out = pd.to_datetime(getattr(row, "outDate", ""), errors="coerce")
    if pd.notna(ipo) and ipo > pd.Timestamp(end_date):
        return False
    if pd.notna(out) and out < pd.Timestamp(start_date):
        return False
    return True


def download_all(root: Path, cfg: dict, limit: int | None = None) -> None:
    login = bs.login()
    if login.error_code != "0": raise RuntimeError(f"BaoStock 登录失败: {login.error_msg}")
    try:
        universe = get_universe(root, cfg["end_date"])
        if limit:
            universe = universe.head(limit)
        log_dir = root / "data" / "logs"; log_dir.mkdir(parents=True, exist_ok=True)
        failures = []
        started = time.monotonic()
        completed_mask = []
        for row in universe.itertuples():
            raw_target = root / "data" / "raw" / f"{row.symbol}.parquet"
            qfq_target = root / "data" / "qfq" / f"{row.symbol}.parquet"
            completed_mask.append(
                _file_complete(raw_target, cfg["end_date"])
                and _file_complete(qfq_target, cfg["end_date"])
            )
        completed_indices = [i for i, done in enumerate(completed_mask) if done]
        checkpoint = max(completed_indices, default=-1)
        scan_start = max(0, checkpoint - 5)
        print(
            f"CHECKPOINT complete={sum(completed_mask)}/{len(universe)}; "
            f"last_downloaded={checkpoint + 1 if checkpoint >= 0 else 'none'}; "
            f"scan_from={scan_start + 1}",
            flush=True,
        )
        fetched = 0
        scan_rows = universe.iloc[scan_start:]
        for i, row in enumerate(scan_rows.itertuples(), scan_start + 1):
            existed_before = completed_mask[i - 1]
            downloaded_any = False
            failed_any = False
            no_data_any = False
            for kind, flag in (("raw", "3"), ("qfq", "2")):
                folder = root / "data" / kind; folder.mkdir(parents=True, exist_ok=True)
                target = folder / f"{row.symbol}.parquet"
                if _file_complete(target, cfg["end_date"]):
                    continue
                try:
                    df = _download_symbol(row.code, cfg["start_date"], cfg["end_date"], flag)
                    if not df.empty:
                        df.to_parquet(target, index=False)
                        downloaded_any = True
                    else:
                        target.with_suffix(".no_data").touch()
                        no_data_any = True
                except Exception as exc:
                    failures.append({"code": row.code, "kind": kind, "error": str(exc)})
                    failed_any = True
                    time.sleep(1)
            if downloaded_any:
                fetched += 1
            elapsed = max(time.monotonic() - started, 0.001)
            rate = fetched / elapsed * 3600 if fetched else 0
            remaining = len(universe) - i
            eta = remaining / rate if rate else 0
            if failed_any:
                status = "FAILED"
            elif downloaded_any:
                status = "DOWNLOADED"
            elif no_data_any:
                status = "NO_DATA"
            elif existed_before:
                status = "EXISTS"
            else:
                status = "COMPLETE"
            print(
                f"[{i:4d}/{len(universe)}] {i / len(universe):6.2%}  [{status:10s}] {row.symbol}  "
                f"本次速度 {rate:,.1f}只/小时  预计剩余 {eta:.1f}小时  失败 {len(failures)}",
                flush=True,
            )
        pd.DataFrame(failures).to_csv(log_dir / "failures.csv", index=False, encoding="utf-8-sig")
        print(f"下载完成：{len(universe)} 只；失败任务 {len(failures)} 个")
    finally:
        bs.logout()


def load_panel(root: Path, board: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    def read(kind: str) -> pd.DataFrame:
        if board == "star":
            files = list((root / "data" / "classified" / "SH" / "star" / kind).glob("*.parquet"))
        elif board == "chinext":
            files = list((root / "data" / "classified" / "SZ" / "chinext" / kind).glob("*.parquet"))
        elif board == "main":
            files = list((root / "data" / "classified").glob(f"*/main/{kind}/*.parquet"))
        else:
            files = list((root / "data" / kind).glob("*.parquet"))
        if not files: raise FileNotFoundError(f"data/{kind} 没有数据，请先运行 download")
        return pd.concat((pd.read_parquet(f) for f in files), ignore_index=True).sort_values(["symbol", "date"])
    return read("raw"), read("qfq")
