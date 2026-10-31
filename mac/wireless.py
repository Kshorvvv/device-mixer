"""Discover only the already pinned phone's authenticated Android TLS service."""
import ipaddress
import json
from pathlib import Path
import re
import socket
import subprocess
import time

def command(adb, *args, timeout=5):
    result = subprocess.run([str(adb), *args], capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('连接操作未完成。')
    return result.stdout.decode(errors='replace').strip()

def valid_endpoint(value):
    try:
        host, port = value.rsplit(':', 1)
        address = ipaddress.ip_address(host.strip('[]'))
        return (address.is_private or address.is_link_local) and not address.is_loopback and 0 < int(port) < 65536
    except (ValueError, AttributeError):
        return False

def reachable(endpoint):
    if not valid_endpoint(endpoint):
        return False
    host, port = endpoint.rsplit(':', 1)
    try:
        with socket.create_connection((host.strip('[]'), int(port)), timeout=0.6):
            return True
    except OSError:
        return False

def tls_services(text, serial):
    return [line.split()[-1] for line in text.splitlines()
            if ('adb-' + serial + '-') in line and '_adb-tls-connect._tcp' in line
            and valid_endpoint(line.split()[-1])]

def matches(adb, target, serial):
    try:
        return command(adb, '-s', target, 'shell', 'getprop', 'ro.serialno', timeout=3) == serial
    except Exception:
        return False

def discover(adb, state):
    identity = state / 'phone.json'
    if not identity.exists():
        raise RuntimeError('首次设置请用 USB 接入手机，点“启用手机无线”。之后即可拔线。')
    serial = json.loads(identity.read_text())['serial']
    saved_file = state / 'wireless.json'
    saved = json.loads(saved_file.read_text()) if saved_file.exists() else {}
    rows = command(adb, 'devices', '-l').splitlines()[1:]
    trusted = []
    for line in rows:
        fields = line.split()
        if len(fields) < 2 or fields[1] != 'device' or ' usb:' in line:
            continue
        target = fields[0]
        if (('adb-' + serial + '-') in target and '_adb-tls-connect._tcp' in target) or target == saved.get('endpoint'):
            trusted.append(target)
    for target in trusted:
        if matches(adb, target, serial):
            return target, serial
    services = tls_services(command(adb, 'mdns', 'services'), serial)
    endpoints = services + ([saved['endpoint']] if valid_endpoint(saved.get('endpoint')) and saved.get('serial') == serial else [])
    for endpoint in dict.fromkeys(endpoints):
        if not reachable(endpoint):
            continue
        try:
            command(adb, 'connect', endpoint)
        except Exception:
            continue
        if matches(adb, endpoint, serial):
            temporary = saved_file.with_suffix('.tmp')
            temporary.write_text(json.dumps({'serial': serial, 'endpoint': endpoint, 'transport': 'native-adb-tls'}))
            temporary.chmod(0o600); temporary.replace(saved_file)
            return endpoint, serial
    raise RuntimeError('没有找到手机无线连接。请让手机与 Mac 处于同一可互通网络，并打开手机“无线调试”；再点检查连接。')

def setup(adb, state, usb_phone, phone_ui):
    target, serial = usb_phone()
    phone_ui.adb(target, 'shell', 'settings', 'put', 'global', 'adb_wifi_enabled', '1')
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            return discover(adb, state)
        except RuntimeError:
            time.sleep(0.5)
    raise RuntimeError('无线开关已请求开启，但尚未连接。请在手机开发者选项打开“无线调试”并允许当前网络，然后点检查连接。之前的配对可直接复用。')
