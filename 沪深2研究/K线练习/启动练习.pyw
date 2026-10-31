"""Double-click to open the independent local practice application."""
import os,socket,subprocess,time,webbrowser
from pathlib import Path
HERE=Path(__file__).resolve().parent
def ready():
    try:
        with socket.create_connection(('127.0.0.1',18763),timeout=.4):return True
    except OSError:return False
if not ready():
    (HERE/'data').mkdir(exist_ok=True)
    log=open(HERE/'data/service.log','a',encoding='utf-8')
    subprocess.Popen([str(HERE.parents[1]/'quant_env/Scripts/pythonw.exe'),'-B',str(HERE/'app.py')],cwd=HERE,stdout=log,stderr=log,creationflags=0x08000000)
    for _ in range(50):
        if ready():break
        time.sleep(.1)
edge=next((Path(p)/'Microsoft/Edge/Application/msedge.exe' for p in [os.environ.get('ProgramFiles(x86)',''),os.environ.get('ProgramFiles','')] if (Path(p)/'Microsoft/Edge/Application/msedge.exe').exists()),None)
if edge:subprocess.Popen([str(edge),'--app=http://127.0.0.1:18763','--window-size=1580,1000'])
else:webbrowser.open('http://127.0.0.1:18763')
