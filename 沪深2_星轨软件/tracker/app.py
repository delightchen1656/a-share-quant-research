from __future__ import annotations

import argparse
import csv
import io
import json
import secrets
import socket
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from service import Tracker, HERE
from store import now

PORT=18762
TOKEN=secrets.token_urlsafe(32)
tracker=None


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass

    def send(self,status,body,ctype='application/json; charset=utf-8'):
        if not isinstance(body,bytes): body=body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type',ctype)
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        if self.headers.get('Host') not in (f'127.0.0.1:{PORT}',f'localhost:{PORT}'):
            self.send(403,'{}'); return
        if self.path=='/api/state':
            try: self.send(200,json.dumps(tracker.snapshot(),ensure_ascii=False))
            except Exception as exc: self.send(500,json.dumps({'error':str(exc)},ensure_ascii=False))
        elif self.path=='/api/export':
            data=tracker.snapshot(); out=io.StringIO(); writer=csv.writer(out)
            writer.writerow(['类型','股票','触发价','股数','有效日期','状态'])
            for x in data['orders']: writer.writerow(['买单',x['symbol'],x['trigger'],x['quantity']-x['filled'],x['expiry'],x['status']])
            for x in data['positions']: writer.writerow(['持仓止盈/止损',x['symbol'],f"{x['take']}/{x['stop']}",x['quantity'],x['exit_session'] or x['deadline'],'已设置' if x['protection'] else '待设置'])
            for x in data['signals']: writer.writerow(['推荐',x['symbol'],x['trigger'],x['quantity'],x['expiry'],x['status']])
            self.send(200,('\ufeff'+out.getvalue()).encode('utf-8'),'text/csv; charset=utf-8')
        elif self.path=='/api/backups':
            self.send(200,json.dumps(tracker.ledger.backups(),ensure_ascii=False))
        elif self.path in ('/tracking.js','/tracking.css'):
            name=self.path[1:]
            self.send(200,(HERE/'ui'/name).read_text(encoding='utf-8'),
                      'text/javascript; charset=utf-8' if name.endswith('.js') else 'text/css; charset=utf-8')
        elif self.path in ('/','/index.html'):
            html=(HERE/'ui/index.html').read_text(encoding='utf-8').replace('__TOKEN__',TOKEN)
            self.send(200,html,'text/html; charset=utf-8')
        else: self.send(404,'{}')

    def do_POST(self):
        if self.headers.get('Host')!=f'127.0.0.1:{PORT}' or self.headers.get('X-Tracker-Token')!=TOKEN:
            self.send(403,'{}'); return
        try:
            length=int(self.headers.get('Content-Length',0))
            if length>65536: raise ValueError('请求过大')
            d=json.loads(self.rfile.read(length))
            if self.path=='/api/update': tracker.update(); result={'ok':True}
            elif self.path=='/api/backup': result={'path':str(tracker.ledger.backup())}
            elif self.path=='/api/restore':
                if d.get('confirmation')!='恢复备份': raise ValueError('请输入恢复备份确认')
                with tracker.lock:
                    preserved=tracker.ledger.restore(d['name'])
                result={'preserved':str(preserved)}
            elif self.path=='/api/action': result=tracker.action(d['kind'],d.get('data',{}))
            else: raise ValueError('未知接口')
            self.send(200,json.dumps(result,ensure_ascii=False))
        except Exception as exc: self.send(400,json.dumps({'error':str(exc)},ensure_ascii=False))


def scheduler():
    last=''
    attempted=0.
    while True:
        clock=now()
        day=clock.date().isoformat()
        retry=tracker.info.get('status')=='blocked' and time.monotonic()-attempted>=300
        phase=day+(':close1900' if clock.hour>=19 else ':prepare1830')
        if (clock.hour,clock.minute)>=(18,30) and (last!=phase or retry) and not tracker.running:
            tracker.update(); last=phase; attempted=time.monotonic()
        time.sleep(30)


def main():
    global tracker
    p=argparse.ArgumentParser(); p.add_argument('--update',action='store_true'); p.add_argument('--no-open',action='store_true'); args=p.parse_args()
    if args.update:
        # The scheduled process asks the active server to refresh through a local file flag.
        folder=HERE/'data'; folder.mkdir(exist_ok=True)
        (folder/'refresh_requested').write_text(now().isoformat())
        try:
            with socket.create_connection(('127.0.0.1',PORT),timeout=1): return
        except OSError: pass
    try: server=ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
    except OSError:
        if not args.no_open and not args.update: webbrowser.open(f'http://127.0.0.1:{PORT}')
        return
    tracker=Tracker()
    tracker.update()
    threading.Thread(target=scheduler,daemon=True).start()
    def watch():
        while True:
            flag=HERE/'data/refresh_requested'
            if flag.exists():
                flag.unlink(); tracker.update()
            time.sleep(5)
    threading.Thread(target=watch,daemon=True).start()
    if not args.no_open and not args.update: webbrowser.open(f'http://127.0.0.1:{PORT}')
    server.serve_forever()


if __name__=='__main__': main()
