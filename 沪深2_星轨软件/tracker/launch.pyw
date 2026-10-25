"""Double-click launcher: start local service and open a dedicated Edge window."""
import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
PYTHON=ROOT/'quant_env/Scripts/pythonw.exe'


def listening():
    try:
        with socket.create_connection(('127.0.0.1',18762),timeout=.4): return True
    except OSError: return False


if not listening():
    (HERE/'data').mkdir(exist_ok=True)
    log=open(HERE/'data/service.log','a',encoding='utf-8')
    subprocess.Popen([str(PYTHON),'-B',str(HERE/'app.py'),'--no-open'],cwd=HERE,stdout=log,stderr=log,creationflags=0x08000000)
    for _ in range(80):
        if listening(): break
        time.sleep(.1)
url='http://127.0.0.1:18762'
edge=next((Path(p)/'Microsoft/Edge/Application/msedge.exe' for p in [os.environ.get('ProgramFiles(x86)',''),os.environ.get('ProgramFiles','')] if (Path(p)/'Microsoft/Edge/Application/msedge.exe').exists()),None)
if edge:
    subprocess.Popen([str(edge),'--app='+url,'--window-size=1480,960'])
else: webbrowser.open(url)
