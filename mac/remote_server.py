"""Small pinned-TLS control API. It cannot execute shell commands or return audio."""
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import secrets
import select
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.parse

STATE = Path(os.environ.get('DEVICE_MIXER_STATE', str(Path.home()/'Library/Application Support/Device Mixer')))
STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
lock = threading.RLock()
status = {'mode':'normal','message':'普通模式','devices':[]}
pending_pairs = {}
tokens_file = STATE/'remote-paired.json'
tokens = json.loads(tokens_file.read_text()) if tokens_file.exists() else {}
stdout_lock = threading.Lock()

def emit(event, **values):
    with stdout_lock:
        try: print(json.dumps(dict(event=event, **values),ensure_ascii=False),flush=True)
        except BrokenPipeError: pass

def save_tokens():
    temporary=tokens_file.with_suffix('.tmp'); temporary.write_text(json.dumps(tokens)); temporary.chmod(0o600); temporary.replace(tokens_file)

def local_ip():
    primary=STATE/'wireless.json'
    if primary.exists():
        try:
            peer=json.loads(primary.read_text())['endpoint'].rsplit(':',1)[0].strip('[]')
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as s:
                s.connect((peer,443)); return s.getsockname()[0]
        except Exception: pass
    for interface in ['en0','en1','en2']:
        value=subprocess.run(['/usr/sbin/ipconfig','getifaddr',interface],capture_output=True,text=True).stdout.strip()
        try:
            if ipaddress.ip_address(value).is_private:return value
        except ValueError:pass
    return '127.0.0.1'

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def response(self,code,data):
        body=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def authenticated(self):
        header=self.headers.get('Authorization','')
        if not header.startswith('Bearer '): return False
        digest=hashlib.sha256(header[7:].encode()).hexdigest()
        with lock: return digest in tokens
    def body(self):
        size=int(self.headers.get('Content-Length','0'))
        if size <= 0 or size > 4096:raise ValueError()
        return json.loads(self.rfile.read(size))
    def do_GET(self):
        if self.path!='/status':self.response(404,{'error':'not found'});return
        if not self.authenticated():self.response(401,{'error':'unauthorized'});return
        with lock: result=dict(status)
        self.response(200,result)
    def do_POST(self):
        try:
            if self.headers.get('Origin') or not self.headers.get('Content-Type','').startswith('application/json'):self.response(403,{'error':'native client required'});return
            data=self.body()
            if self.path=='/pair':
                key=data.get('key','')
                with lock:
                    record=pending_pairs.pop(hashlib.sha256(key.encode()).hexdigest(),None)
                    if not record or record['expires']<time.time():self.response(403,{'error':'pairing expired'});return
                    token=secrets.token_urlsafe(32);digest=hashlib.sha256(token.encode()).hexdigest()
                    tokens[digest]={'name':record['name'],'created':time.time()};save_tokens()
                self.response(200,{'token':token,'server':'Device Mixer'});emit('paired',name=record['name']);return
            if not self.authenticated():self.response(401,{'error':'unauthorized'});return
            if self.path!='/command' or data.get('action') not in ('start','stop','refresh'):
                self.response(400,{'error':'unsupported command'});return
            emit('command',action=data['action'])
            self.response(202,{'accepted':True})
        except Exception:
            try:self.response(400,{'error':'bad request'})
            except Exception:pass

class Server(ThreadingHTTPServer):
    daemon_threads=True
    def get_request(self):
        connection,address=self.socket.accept();connection.settimeout(5)
        return context.wrap_socket(connection,server_side=True,do_handshake_on_connect=False),address

certificate=STATE/'remote-cert.pem';private_key=STATE/'remote-key.pem'
if not certificate.exists() or not private_key.exists():
    subprocess.run(['/usr/bin/openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(private_key),'-out',str(certificate),'-days','3650','-subj','/CN=DeviceMixerLocal'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    private_key.chmod(0o600);certificate.chmod(0o600)
fingerprint=hashlib.sha256(ssl.PEM_cert_to_DER_cert(certificate.read_text())).hexdigest()
context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2;context.load_cert_chain(str(certificate),str(private_key))
server=Server(('0.0.0.0',0),Handler)
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
emit('ready',port=server.server_port,fingerprint=fingerprint)
try:
    while True:
        line=sys.stdin.readline()
        if not line:break
        try:
            value=json.loads(line)
            if value.get('type')=='status':
                with lock: status=value['data']
            elif value.get('type')=='pair':
                key=secrets.token_urlsafe(32)
                with lock:pending_pairs[hashlib.sha256(key.encode()).hexdigest()]={'name':value.get('name','Android'),'expires':time.time()+180}
                query=urllib.parse.urlencode({'h':local_ip(),'p':server.server_port,'f':fingerprint,'k':key})
                emit('pairing',uri='devicemixer://pair?'+query)
        except Exception:pass
finally:
    server.shutdown();server.server_close();thread.join(timeout=2)
