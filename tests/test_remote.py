from pathlib import Path
import hashlib
import http.client
import json
import os
import ssl
import subprocess
import tempfile
import unittest
import urllib.parse

class ControlAPI(unittest.TestCase):
    def test_pinned_pair_auth_and_command_allowlist(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);env=os.environ.copy();env['DEVICE_MIXER_STATE']=directory
            script=Path(__file__).resolve().parents[1]/'mac/remote_server.py'
            process=subprocess.Popen(['/usr/bin/python3',str(script)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,text=True)
            try:
                ready=json.loads(process.stdout.readline());self.assertEqual(ready['event'],'ready')
                context=ssl.create_default_context(cafile=str(root/'remote-cert.pem'));context.check_hostname=False
                def request(method,path,body=None,token=None):
                    c=http.client.HTTPSConnection('127.0.0.1',ready['port'],context=context,timeout=5);c.connect()
                    self.assertEqual(hashlib.sha256(c.sock.getpeercert(binary_form=True)).hexdigest(),ready['fingerprint'])
                    headers={'Content-Type':'application/json'}
                    if token:headers['Authorization']='Bearer '+token
                    c.request(method,path,None if body is None else json.dumps(body),headers);r=c.getresponse();data=json.loads(r.read());code=r.status;c.close();return code,data
                self.assertEqual(request('GET','/status')[0],401)
                process.stdin.write(json.dumps({'type':'pair','name':'test phone'})+'\n');process.stdin.flush()
                pairing=json.loads(process.stdout.readline());key=urllib.parse.parse_qs(urllib.parse.urlsplit(pairing['uri']).query)['k'][0]
                code,reply=request('POST','/pair',{'key':key});self.assertEqual(code,200);token=reply['token']
                self.assertEqual(json.loads(process.stdout.readline())['event'],'paired')
                self.assertEqual(request('POST','/pair',{'key':key})[0],403)
                self.assertEqual(request('GET','/status',token=token)[1]['mode'],'normal')
                self.assertEqual(request('POST','/command',{'action':'shell'},token)[0],400)
                self.assertEqual(request('POST','/command',{'action':'start'},token)[0],202)
                self.assertEqual(json.loads(process.stdout.readline()),{'event':'command','action':'start'})
                self.assertNotIn(token,(root/'remote-paired.json').read_text())
            finally:
                process.stdin.close();process.stdin=None
                process.communicate(timeout=6)
                self.assertEqual(process.returncode,0)

if __name__=='__main__':unittest.main()
