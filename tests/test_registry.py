"""Only enroll authorized transports, keep separate state and user choices."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mac'))
import registry


class Registry(unittest.TestCase):
    def test_authorized_devices_auto_enroll_and_keep_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'known-devices.json').write_text(json.dumps({'phone-a': {'name': 'Old name', 'enabled': False}}))
            listing = 'List of devices attached\nusb-a device usb:1\nadb-tablet-b-nonce._adb-tls-connect._tcp device\n'
            services = 'adb-tablet-b-nonce _adb-tls-connect._tcp 192.168.1.7:35003\nadb-stranger-nonce _adb-tls-connect._tcp 192.168.1.8:35003\n'
            queries = []
            def command(adb, *args, **kwargs):
                if args[0] == 'devices': return listing
                if args[0] == 'mdns': return services
                self.fail('Registry must not connect to advertised strangers')
            def adb(target, *args, **kwargs):
                queries.append(target)
                serial, name = ('phone-a', 'Phone A') if target == 'usb-a' else ('tablet-b', 'Tablet B')
                return serial if args[-1] == 'ro.serialno' else name
            with patch.object(registry, 'ROOT', root), patch.object(registry.wireless, 'command', command), patch.object(registry.phone_ui, 'adb', adb):
                rows = {r['id']: r for r in registry.scan()}
                self.assertEqual(set(rows), {'phone-a', 'tablet-b'})
                self.assertFalse(rows['phone-a']['enabled'])
                self.assertTrue(rows['tablet-b']['enabled'])
                self.assertTrue(rows['tablet-b']['wireless'])
                self.assertTrue(rows['phone-a']['usb'])
                a, b = registry.device_dir('phone-a'), registry.device_dir('tablet-b')
                self.assertNotEqual(a, b)
                self.assertEqual(json.loads((b/'wireless.json').read_text())['endpoint'], '192.168.1.7:35003')
                self.assertEqual(json.loads((a/'phone.json').read_text())['serial'], 'phone-a')
            self.assertNotIn('192.168.1.8:35003', queries)

    def test_unauthorized_and_plain_tcp_transports_not_enrolled(self):
        with tempfile.TemporaryDirectory() as directory:
            listing = 'List of devices attached\nusb-x unauthorized usb:1\n192.168.1.9:5555 device\nusb-y offline usb:2\n'
            def command(adb, *args, **kwargs):
                return listing if args[0] == 'devices' else ''
            with patch.object(registry, 'ROOT', Path(directory)), patch.object(registry.wireless, 'command', command), patch.object(registry.phone_ui, 'adb') as adb:
                self.assertEqual(registry.scan(), [])
                adb.assert_not_called()


if __name__ == '__main__': unittest.main()
