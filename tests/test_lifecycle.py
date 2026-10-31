"""Exercise actual child shutdown using isolated fake devices, never the real phone."""
from pathlib import Path
import json
import os
import selectors
import subprocess
import tempfile
import time
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'mac'

class Lifecycle(unittest.TestCase):
    def trial(self, mode):
        with tempfile.TemporaryDirectory(prefix='device-mix-lifecycle-') as directory:
            base = Path(directory)
            client = base/'scrcpy'
            client.write_text('#!/usr/bin/python3\nimport os,time\nfrom pathlib import Path\nPath(__file__).with_suffix(".pid").write_text(str(os.getpid()))\nwhile True:time.sleep(0.1)\n')
            if mode == 'reconnect':
                (base/'second.pid').write_text('')
                client.write_text('''#!/usr/bin/python3
import os,time,sys
from pathlib import Path
base=Path(__file__).parent
count=base/'attempts'
number=int(count.read_text())+1 if count.exists() else 1
count.write_text(str(number))
Path(__file__).with_suffix('.pid').write_text(str(os.getpid()))
if number == 1:
    time.sleep(0.9)
    sys.exit(2)
(base/'second.pid').write_text(str(os.getpid()))
while True:time.sleep(0.1)
''')
            client.chmod(0o700)
            route = base/'audio-route'
            route.write_text('#!/usr/bin/python3\nprint(\'{"processes":[{"output_running":true,"devices":[{"name":"Test Headphones"}]}]}\')\n')
            route.chmod(0o700)
            runner = base/'runner.py'
            runner.write_text('''import sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import controller as c
c.STATE=Path(sys.argv[2]);c.JOURNAL=c.STATE/'restore.json';c.RES=c.STATE
c.usb_phone=lambda:('test-usb','test-identity')
c.resolve_phone=lambda mode:('test-usb','test-identity')
c.needs_profile_switch=lambda target,headphone:True
def media(target,headphone,desired=None,before_change=None):
    if before_change:before_change(True)
    if desired is True:(c.STATE/'restored').write_text('yes')
    return True
c.phone_ui.media_switch=media
c.run('Test Headphones',100,True)
''')
            process = subprocess.Popen(['/usr/bin/python3',str(runner),str(SOURCE),str(base)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            selector = selectors.DefaultSelector();selector.register(process.stdout,selectors.EVENT_READ)
            ready = False; deadline = time.monotonic()+8
            reconnected = False
            while time.monotonic()<deadline and process.poll() is None:
                if selector.select(.3):
                    message=json.loads(process.stdout.readline())
                    if message['state']=='reconnecting':reconnected=True
                    if message['state']=='running':
                        if mode != 'reconnect' or reconnected:ready=True;break
            self.assertTrue(ready,'fake audio output never became ready')
            child_pid=int((base/'scrcpy.pid').read_text())
            if mode in ('parent_eof','reconnect'):
                process.stdin.close();process.stdin=None
            else:
                process.terminate()
            stdout,stderr=process.communicate(timeout=8)
            self.assertEqual(process.returncode,0,stderr.decode())
            self.assertTrue((base/'restored').exists())
            self.assertFalse((base/'restore.json').exists())
            with self.assertRaises(ProcessLookupError):os.kill(child_pid,0)
            self.assertIn(b'"state": "stopped"',stdout)
            if mode == 'reconnect':
                self.assertTrue(reconnected)
                self.assertEqual((base/'attempts').read_text(),'2')
    def test_parent_exit(self):self.trial('parent_eof')
    def test_stop_signal(self):self.trial('signal')
    def test_wireless_client_restart(self):self.trial('reconnect')

if __name__=='__main__':unittest.main()
