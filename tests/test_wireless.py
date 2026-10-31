from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mac'))
import wireless

class Discovery(unittest.TestCase):
    def test_changed_port_replaces_saved_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state/'phone.json').write_text(json.dumps({'serial': 'test-phone'}))
            (state/'wireless.json').write_text(json.dumps({'serial': 'test-phone', 'endpoint': '192.168.1.9:35001'}))
            connected = []
            def command(adb, *args, **kwargs):
                if args[0] == 'devices': return 'List of devices attached\n'
                if args[0] == 'mdns': return 'adb-test-phone-nonce _adb-tls-connect._tcp 192.168.1.9:35002\n'
                if args[0] == 'connect': connected.append(args[1]); return 'connected'
                self.fail('unexpected network operation')
            with patch.object(wireless, 'command', command), patch.object(wireless, 'reachable', return_value=True), patch.object(wireless, 'matches', side_effect=lambda a,t,s:t.endswith(':35002')):
                target, serial = wireless.discover('fake-adb', state)
            self.assertEqual(target, '192.168.1.9:35002')
            self.assertEqual(connected, [target])
            self.assertEqual(json.loads((state/'wireless.json').read_text())['endpoint'], target)

    def test_only_pinned_native_tls_service_is_accepted(self):
        listing = '\n'.join([
            'adb-other-phone-nonce _adb-tls-connect._tcp 192.168.1.8:35001',
            'adb-test-phone-nonce _adb-tls-pairing._tcp 192.168.1.9:35002',
            'adb-test-phone-nonce _adb-tls-connect._tcp 192.168.1.9:35003',
            'adb-test-phone-nonce _adb-tls-connect._tcp 8.8.8.8:35004',
        ])
        self.assertEqual(wireless.tls_services(listing, 'test-phone'), ['192.168.1.9:35003'])

if __name__ == '__main__': unittest.main()
