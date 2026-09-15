"""Local dashboard and natural-language controller for the downloader."""
from __future__ import annotations

import json
import os
import sys
import threading
import webbrowser
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from download_mainboard import run as run_downloader, write_status

ROOT = Path(__file__).resolve().parent
DATA, WEB = ROOT / "data", ROOT / "web"
STATUS_FILE = DATA / "status" / "downloader.json"
STOP_FILE = DATA / "control" / "stop.request"
PID_FILE = DATA / "control" / "dashboard_child.pid"
LOG_FILE = DATA / "logs" / "downloader_console.log"
UNIVERSE_FILE = DATA / "metadata" / "historical_mainboard_universe.csv"
HOST, PORT = "127.0.0.1", 8765
DOWNLOAD_THREAD, LOCK = None, threading.Lock()


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {} if default is None else default


def pid_alive(pid) -> bool:
    try:
        pid = int(pid)
        if pid <= 0:
            return False
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def marker_counts():
    result = {"SH": {"raw": 0, "qfq": 0}, "SZ": {"raw": 0, "qfq": 0}}
    recent = []
    for kind in ("raw", "qfq"):
        for exchange in ("SH", "SZ"):
            folder = DATA / kind / exchange
            markers = list(folder.glob("*.complete.json")) if folder.exists() else []
            result[exchange][kind] = len(markers)
            recent.extend(markers)
    recent.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    items = []
    for path in recent[:10]:
        meta = read_json(path)
        items.append({"symbol": meta.get("symbol", path.name.split(".complete")[0]),
                      "kind": meta.get("kind", path.parent.parent.name),
                      "time": meta.get("completed_at", ""), "rows": meta.get("rows", 0)})
    return result, items


def universe_counts():
    counts = {"SH": 0, "SZ": 0}
    if not UNIVERSE_FILE.exists():
        return counts
    with UNIVERSE_FILE.open("r", encoding="utf-8-sig", errors="replace") as stream:
        header = stream.readline().strip().split(",")
        try:
            idx = header.index("exchange")
        except ValueError:
            return counts
        for line in stream:
            cols = line.rstrip("\n").split(",")
            if len(cols) > idx and cols[idx] in counts:
                counts[cols[idx]] += 1
    return counts


def current_status():
    counts, recent = marker_counts()
    stocks, runtime = universe_counts(), read_json(STATUS_FILE)
    completed = sum(x[k] for x in counts.values() for k in ("raw", "qfq"))
    total = sum(stocks.values()) * 2
    local_thread_alive = DOWNLOAD_THREAD is not None and DOWNLOAD_THREAD.is_alive()
    external_process_alive = runtime.get("pid") != os.getpid() and pid_alive(runtime.get("pid"))
    running = local_thread_alive or external_process_alive
    state = runtime.get("state", "idle")
    if state == "running" and not running:
        state = "interrupted"
    return {"state": state, "running": running, "pid": runtime.get("pid"),
            "completed": completed, "total": total,
            "percent": round(completed / total * 100, 2) if total else 0,
            "counts": counts, "stocks": stocks, "recent": recent,
            "current": runtime.get("current_symbol"), "kind": runtime.get("current_kind"),
            "phase": runtime.get("phase"),
            "speed": runtime.get("speed_per_hour", 0), "eta": runtime.get("eta_hours"),
            "failures": runtime.get("failures", 0), "updated_at": runtime.get("updated_at"),
            "range": [runtime.get("start_date", "2018-01-01"), runtime.get("end_date", "2026-09-12")]}


def start_download(exchange="ALL"):
    global DOWNLOAD_THREAD
    with LOCK:
        if current_status()["running"]:
            return False, "下载程序已经在运行"
        STOP_FILE.parent.mkdir(parents=True, exist_ok=True)
        if STOP_FILE.exists():
            STOP_FILE.unlink()
        PID_FILE.write_text(str(os.getpid()), encoding="ascii")
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATUS_FILE.write_text(json.dumps({
            "state": "preparing", "pid": os.getpid(), "exchange": exchange,
            "start_date": "2018-01-01", "end_date": "2026-09-12",
            "total_tasks": current_status()["total"],
            "completed_tasks": current_status()["completed"],
            "speed_per_hour": 0, "eta_hours": None, "failures": 0,
            "updated_at": datetime.now().isoformat(timespec="seconds")
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        DOWNLOAD_THREAD = threading.Thread(
            target=download_worker, args=(exchange,),
            name="mainboard-downloader", daemon=True)
        DOWNLOAD_THREAD.start()
        return True, f"已从断点继续下载（{exchange}）"


def download_worker(exchange):
    try:
        run_downloader(exchange)
    except BaseException as exc:
        write_status(state="failed", pid=os.getpid(), exchange=exchange,
                     error=f"{type(exc).__name__}: {exc}", total_tasks=current_status()["total"],
                     completed_tasks=current_status()["completed"])


def request_stop():
    STOP_FILE.parent.mkdir(parents=True, exist_ok=True)
    STOP_FILE.write_text(datetime.now().isoformat(timespec="seconds"), encoding="utf-8")
    return True, "已申请安全暂停；当前股票保存完成后停止"


def interpret(text: str):
    value = (text or "").strip().lower().replace(" ", "")
    if not value:
        return False, "请输入一句话，例如：继续下载"
    if any(word in value for word in ("暂停", "停止", "停一下", "别下了")):
        return request_stop()
    if any(word in value for word in ("继续", "开始", "续跑", "接着下", "恢复")):
        exchange = "SH" if any(x in value for x in ("沪市", "上海", "只下沪")) else "SZ" if any(x in value for x in ("深市", "深圳", "只下深")) else "ALL"
        return start_download(exchange)
    if any(word in value for word in ("多少", "进度", "状态", "多久", "下载到哪")):
        status = current_status()
        eta = "暂时无法估算" if status["eta"] is None else f"预计还需 {status['eta']} 小时"
        return True, f"已完成 {status['completed']}/{status['total']} 项，进度 {status['percent']}%，{eta}。"
    return False, "我目前能理解：继续下载、暂停下载、查看进度、只下载沪市、只下载深市"


def read_body(handler):
    try:
        return json.loads(handler.rfile.read(int(handler.headers.get("Content-Length", "0"))).decode("utf-8"))
    except Exception:
        return {}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)
    def log_message(self, fmt, *args):
        return
    def end_headers(self):
        # The dashboard changes frequently; never keep an old JS/CSS copy.
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        super().end_headers()
    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if urlparse(self.path).path == "/api/status":
            return self.send_json(current_status())
        return super().do_GET()
    def do_POST(self):
        data, path = read_body(self), urlparse(self.path).path
        if path == "/api/start": ok, message = start_download(data.get("exchange", "ALL"))
        elif path == "/api/stop": ok, message = request_stop()
        elif path == "/api/chat": ok, message = interpret(data.get("message", ""))
        else: return self.send_json({"ok": False, "message": "未知操作"}, 404)
        self.send_json({"ok": ok, "message": message, "status": current_status()})


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    # Never let multiple dashboard instances share the same Windows port.
    # Competing servers made the browser alternate between stale states.
    allow_reuse_address = False


if __name__ == "__main__":
    url = f"http://{HOST}:{PORT}"
    try:
        server = DashboardServer((HOST, PORT), Handler)
    except OSError:
        # A dashboard is already serving this port. Opening it is the desired
        # behavior for a second launcher click, not an error.
        webbrowser.open(url)
        raise SystemExit(0)
    print(f"Dashboard: {url}")
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Dashboard stopped. Download checkpoints are preserved.")
    finally:
        server.server_close()
