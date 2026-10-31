"""Remember devices this Mac is already authorized to access; never probe strangers."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
import phone_ui
import wireless

ROOT = Path.home()/'Library/Application Support/Device Mixer'
ADB = Path(__file__).resolve().parent/'adb'

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2)); temporary.chmod(0o600); temporary.replace(path)

def device_dir(serial):
    return ROOT/'devices'/hashlib.sha256(serial.encode()).hexdigest()[:20]

def records():
    path = ROOT/'known-devices.json'
    result = json.loads(path.read_text()) if path.exists() else {}
    old = ROOT/'phone.json'
    if old.exists():
        value = json.loads(old.read_text()); serial = value['serial']
        result.setdefault(serial, {'name': value.get('model', 'Android'), 'enabled': True})
    return result

def scan():
    known = records()
    try: services = wireless.command(ADB, 'mdns', 'services')
    except Exception: services = ''
    listing = wireless.command(ADB, 'devices', '-l')
    online = {}
    primary = json.loads((ROOT/'phone.json').read_text())['serial'] if (ROOT/'phone.json').exists() else None
    for line in listing.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 2 or fields[1] != 'device': continue
        target = fields[0]; usb = ' usb:' in line
        endpoints = [l.split()[-1] for l in services.splitlines() if '_adb-tls-connect._tcp' in l and len(l.split()) >= 3]
        cached = json.loads((ROOT/'wireless.json').read_text()) if (ROOT/'wireless.json').exists() else {}
        if not usb and '_adb-tls-connect._tcp' not in target and target not in endpoints and target != cached.get('endpoint'): continue
        try:
            serial = phone_ui.adb(target, 'shell', 'getprop', 'ro.serialno', timeout=3)
            name = phone_ui.adb(target, 'shell', 'getprop', 'ro.product.marketname', timeout=3)
            if not name: name = phone_ui.adb(target, 'shell', 'getprop', 'ro.product.model', timeout=3)
            if not serial or not name: continue
        except Exception: continue
        known.setdefault(serial, {'name': name, 'enabled': True})
        known[serial]['name'] = name
        item = online.setdefault(serial, {'usb': False, 'wireless': False})
        item['usb' if usb else 'wireless'] = True
        folder = device_dir(serial); folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        save(folder/'phone.json', {'serial': serial, 'model': name})
        peers = wireless.tls_services(services, serial)
        endpoint = target if target in peers else (peers[0] if peers else None)
        if endpoint:
            save(folder/'wireless.json', {'serial': serial, 'endpoint': endpoint, 'transport': 'native-adb-tls'})
        elif serial == primary and cached.get('serial') == serial:
            save(folder/'wireless.json', cached)
    save(ROOT/'known-devices.json', known)
    result = []
    for serial, record in known.items():
        folder = device_dir(serial)
        if not (folder/'phone.json').exists(): save(folder/'phone.json', {'serial': serial, 'model': record['name']})
        if serial == primary and not (folder/'wireless.json').exists() and (ROOT/'wireless.json').exists(): save(folder/'wireless.json', json.loads((ROOT/'wireless.json').read_text()))
        item = online.get(serial, {})
        pending = (folder/'phone-restore.json').exists() or (serial == primary and (ROOT/'phone-restore.json').exists())
        result.append({'id': serial, 'name': record['name'], 'enabled': record.get('enabled', True), 'online': bool(item), 'wireless': item.get('wireless', False), 'usb': item.get('usb', False), 'pending': pending})
    return result

def main():
    p = argparse.ArgumentParser(); p.add_argument('action', choices=['scan','enable']); p.add_argument('--device-id'); p.add_argument('--enabled', choices=['true','false']); a = p.parse_args()
    if a.action == 'enable':
        known = records()
        if a.device_id not in known: raise RuntimeError('设备尚未授权。')
        known[a.device_id]['enabled'] = a.enabled == 'true'; save(ROOT/'known-devices.json', known)
    print(json.dumps({'state': 'devices', 'devices': scan()}, ensure_ascii=False), flush=True)

if __name__ == '__main__':
    try: main()
    except Exception: print(json.dumps({'state':'error','message':'设备检查未完成，请检查无线连接。'},ensure_ascii=False),flush=True); sys.exit(1)
