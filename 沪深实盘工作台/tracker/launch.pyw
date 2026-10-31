"""Desktop window owns its local server; closing the window exits both."""
import msvcrt
import os
import socket
import subprocess
import time
import traceback
from datetime import datetime
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())
PYTHON=ROOT/'quant_env/Scripts/pythonw.exe'


def report_failure(exc):
    """pythonw has no console: preserve diagnostics and show an actionable error."""
    data=HERE/'data';data.mkdir(exist_ok=True)
    path=data/'launcher.log'
    with path.open('a',encoding='utf-8') as log:
        log.write('\n'+datetime.now().isoformat()+'\n'+traceback.format_exc())
    import ctypes
    ctypes.windll.user32.MessageBoxW(None,str(exc)+'\n\n启动日志：'+str(path),'晚间工作台启动失败',0x10)


def open_window(edge,data):
    return subprocess.Popen([str(edge),'--app=http://127.0.0.1:18762',
        '--user-data-dir='+str(data/'desktop_browser'),'--disable-background-mode',
        '--no-first-run','--no-default-browser-check','--window-size=1480,960'])


def listening():
    try:
        with socket.create_connection(('127.0.0.1',18762),timeout=.4): return True
    except OSError: return False


def wait_reused_browser(profile):
    """Edge may hand a new app window to an existing profile process.

    In that case the short-lived client exits immediately. Keep the desktop
    owner alive until the real profile process exits, so its server survives.
    """
    import ctypes
    from ctypes import wintypes
    profile_text=str(profile).replace("'","''")
    script=("Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'msedge.exe' -and "
        " $_.CommandLine -like '*"+profile_text+"*' -and $_.CommandLine -notmatch '--type=' } | Select-Object -ExpandProperty ProcessId")
    result=subprocess.run(['powershell.exe','-NoProfile','-Command',script],capture_output=True,text=True,
        creationflags=0x08000000,timeout=20)
    pids=[int(p) for p in result.stdout.split() if p.isdigit()]
    if not pids:return
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenProcess(0x00100000,False,pids[0])
    if handle:
        try:kernel.WaitForSingleObject(handle,0xFFFFFFFF)
        finally:kernel.CloseHandle(handle)


def main():
    data=HERE/'data';data.mkdir(exist_ok=True)
    edge=next((Path(p)/'Microsoft/Edge/Application/msedge.exe' for p in
        [os.environ.get('ProgramFiles(x86)',''),os.environ.get('ProgramFiles','')]
        if (Path(p)/'Microsoft/Edge/Application/msedge.exe').exists()),None)
    if edge is None:
        raise RuntimeError('需要 Microsoft Edge 以使用随窗口退出的桌面模式')
    with (data/'desktop.lock').open('a+b') as lock:
        lock.seek(0);lock.write(b'1');lock.flush();lock.seek(0)
        try: msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:
            # Reopening the shortcut shows the existing desktop app. The
            # original launcher continues to own the server/profile lifetime.
            if listening():open_window(edge,data)
            return
        if listening():
            raise RuntimeError('本地端口18762被已有后台占用，桌面窗口尚未启动。请先结束该软件的临时后台后重试；不要删除账本或重复启动行情更新。')
        with (data/'service.log').open('a',encoding='utf-8') as log:
            server=subprocess.Popen([str(PYTHON),'-B',str(HERE/'app.py'),'--no-open',
                '--owner-pid',str(os.getpid())],cwd=HERE,stdout=log,stderr=log,creationflags=0x08000000)
            for _ in range(150):
                if listening(): break
                if server.poll() is not None: raise RuntimeError('沪深2后台启动失败，请查看service.log')
                time.sleep(.1)
            else: raise RuntimeError('沪深2后台启动超时')
            window=open_window(edge,data)
            window.wait()
            wait_reused_browser(data/'desktop_browser')
            # On exit the server's owner watcher also stops the venv child.


if __name__=='__main__':
    try:main()
    except Exception as exc:report_failure(exc)
