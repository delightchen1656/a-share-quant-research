"""Start one hidden local viewer process; open/reuse only the basic app."""
from pathlib import Path
import argparse,json,subprocess,sys,time,urllib.request,webbrowser
HERE=Path(__file__).resolve().parent
URL='http://127.0.0.1:8766/'
def health():
    try:
        with urllib.request.urlopen(URL+'api/health',timeout=1) as r:return json.load(r)
    except Exception:return None
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--no-browser',action='store_true');args=parser.parse_args()
    info=health()
    if info and info.get('app')!='hushen-basic-kline-viewer':raise RuntimeError('8766端口正由其他软件使用，请先关闭该软件')
    if not info:
        (HERE/'runtime').mkdir(exist_ok=True)
        with (HERE/'runtime/startup.log').open('a',encoding='utf8') as log:
            subprocess.Popen([sys.executable,'-X','utf8','-B',str(HERE/'app.py')],cwd=str(HERE),stdin=subprocess.DEVNULL,stdout=log,stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0,close_fds=True)
        for _ in range(40):
            time.sleep(.2);info=health()
            if info:break
        if not info:raise RuntimeError('启动失败，请查看K线看盘软件/runtime/startup.log')
    if not args.no_browser:webbrowser.open(URL)
    print(URL,flush=True)
if __name__=='__main__':main()
