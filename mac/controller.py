"""Authenticated wireless media forwarding, with an explicit USB fallback mode."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import threading
import time

sys.dont_write_bytecode = True
import phone_ui
import wireless
import registry

RES = Path(__file__).resolve().parent
STATE = Path.home() / 'Library/Application Support/Device Mixer'
STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
JOURNAL = STATE / 'phone-restore.json'
IDENTITY = STATE / 'phone.json'
ADB = RES / 'adb'

def atomic_json(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False))
    temp.chmod(0o600)
    temp.replace(path)

def emit(state, message, **values):
    event = dict(state=state, message=message, **values)
    try:
        receipt = STATE / 'recent-status.json'
        events = json.loads(receipt.read_text()) if receipt.exists() else []
        events.append(dict(event, timestamp=time.time()))
        atomic_json(receipt, events[-20:])
    except Exception:
        pass
    try:
        print(json.dumps(event, ensure_ascii=False), flush=True)
    except BrokenPipeError:
        pass

def usb_phone():
    p = subprocess.run([str(ADB), 'devices', '-l'], capture_output=True, text=True, timeout=8)
    devices = [row.split()[0] for row in p.stdout.splitlines()[1:]
               if len(row.split()) > 1 and row.split()[1] == 'device' and ' usb:' in row]
    if len(devices) != 1:
        if 'unauthorized' in p.stdout:
            raise RuntimeError('请解锁手机，并允许这台 Mac 的 USB 调试。')
        raise RuntimeError('请用 USB 线接入目标安卓设备；当前没有找到唯一的已授权 USB 设备。')
    target = devices[0]
    model = phone_ui.adb(target, 'shell', 'getprop', 'ro.product.marketname')
    serial = phone_ui.adb(target, 'shell', 'getprop', 'ro.serialno')
    if not model: model = phone_ui.adb(target, 'shell', 'getprop', 'ro.product.model')
    if not serial or not model:
        raise RuntimeError('当前设备身份未确认。')
    if IDENTITY.exists() and json.loads(IDENTITY.read_text())['serial'] != serial:
        raise RuntimeError('手机身份与本机已接入的设备不同，已停止。')
    if not IDENTITY.exists():
        atomic_json(IDENTITY, {'serial': serial, 'model': model})
    return target, serial

def resolve_phone(transport):
    return usb_phone() if transport == 'usb' else wireless.discover(ADB, STATE)

def needs_profile_switch(target, headphone):
    # A newly added device that has never paired with this headset needs no UI changes.
    if not headphone: raise RuntimeError('耳机名称未确认。')
    manager = phone_ui.adb(target, 'shell', 'dumpsys', 'bluetooth_manager', timeout=10)
    return phone_ui.normalise(headphone) in phone_ui.normalise(manager)

def restore_phone():
    if not JOURNAL.exists():
        return True
    original = json.loads(JOURNAL.read_text())
    try:
        target, serial = resolve_phone('wireless')
    except RuntimeError:
        target, serial = usb_phone()
    if serial != original['serial']:
        raise RuntimeError('恢复记录属于另一台手机，已停止。')
    phone_ui.media_switch(target, original['headphone'], original['media'])
    JOURNAL.unlink()
    return True

def run(headphone, buffer_ms, watch_stdin, transport='wireless'):
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    if watch_stdin:
        def watch_parent():
            try:
                os.read(sys.stdin.fileno(), 1)
            finally:
                stop.set()
        threading.Thread(target=watch_parent, daemon=True).start()
    client = None
    error = None
    started = False
    try:
        if JOURNAL.exists():
            raise RuntimeError('上次的手机媒体设置待恢复，请先点“恢复手机直连音频”。')
        target, serial = resolve_phone(transport)
        label = '无线' if transport == 'wireless' else 'USB'
        emit('preparing', '正在准备手机的' + label + '音频…', transport=transport)
        def before_change(media):
            if media:
                atomic_json(JOURNAL, {'serial': serial, 'headphone': headphone, 'media': True})
        if needs_profile_switch(target, headphone):
            phone_ui.media_switch(target, headphone, False, before_change=before_change)
        if stop.is_set():
            return
        env = os.environ.copy()
        env['ADB'] = str(ADB)
        env['SCRCPY_SERVER_PATH'] = str(RES / 'scrcpy-server')
        env['SDL_AUDIODRIVER'] = 'coreaudio'
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        for attempt in range(4):
            if stop.is_set():
                break
            if attempt:
                emit('reconnecting', '无线连接中断，正在重新查找手机（' + str(attempt) + '/3）…', transport=transport)
                if stop.wait(min(attempt * 2, 5)):
                    break
                try:
                    target, new_serial = resolve_phone(transport)
                    if new_serial != serial:
                        raise RuntimeError('重连设备身份不符合。')
                except RuntimeError as exc:
                    error = str(exc)
                    continue
            args = [str(RES / 'scrcpy'), '--serial=' + target, '--no-window', '--no-video', '--no-control',
                    '--audio-source=output', '--audio-codec=' + ('opus' if transport == 'wireless' else 'raw'), '--force-adb-forward', '--require-audio',
                    '--audio-buffer=' + str(buffer_ms), '--port=27220:27229']
            if transport == 'wireless':
                args.append('--audio-bit-rate=128K')
            client = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
            selector = selectors.DefaultSelector(); selector.register(client.stdout, selectors.EVENT_READ)
            pending = b''; launched = time.monotonic(); last_check = 0.0; last_health = launched
            health_failures = 0; started = False; error = None
            while not stop.is_set():
                for key, _ in selector.select(0.25):
                    data = os.read(key.fileobj.fileno(), 8192)
                    pending = (pending + data)[-16384:]
                    while b'\n' in pending:
                        line, pending = pending.split(b'\n', 1)
                        if b'ERROR:' in line:
                            error = '手机音频暂时断开，正在检查连接。'
                if client.poll() is not None:
                    error = error or '手机音频连接已断开。'
                    break
                if not started and time.monotonic() - last_check > 0.6:
                    last_check = time.monotonic()
                    try:
                        data = subprocess.run([str(RES/'audio-route'), 'processes', str(client.pid)], capture_output=True, timeout=3)
                        snapshot = json.loads(data.stdout)
                        started = any(p['output_running'] and any(d['name'] == headphone for d in p['devices']) for p in snapshot['processes'])
                        if started:
                            error = None
                            emit('running', '手机已通过' + label + '接入；Mac 的声音照常一起播放。', transport=transport)
                    except Exception:
                        pass
                if not started and time.monotonic() - launched > 20:
                    error = error or '耳机音频输出没有就绪，请确认耳机仍连接 Mac，再重试。'
                    break
                if transport == 'wireless' and time.monotonic() - last_health > 10:
                    last_health = time.monotonic()
                    try:
                        good = phone_ui.adb(target, 'shell', 'echo', 'device-mixer-ok', timeout=8) == 'device-mixer-ok'
                    except Exception:
                        good = False
                    health_failures = 0 if good else health_failures + 1
                    if health_failures >= 2:
                        error = '无线连接中断。'
                        break
            selector.close()
            if client.poll() is None:
                client.terminate()
                try: client.wait(timeout=6)
                except subprocess.TimeoutExpired: client.kill(); client.wait()
            client.stdout.close(); client = None
            if stop.is_set():
                error = None
                break
            if transport != 'wireless':
                break
    except Exception as exc:
        error = str(exc) if isinstance(exc, RuntimeError) else '连接未完成，请检查设备连接后重试。'
    finally:
        if client is not None and client.poll() is None:
            client.terminate()
            try:
                client.wait(timeout=6)
            except subprocess.TimeoutExpired:
                client.kill()
                client.wait()
        restored = not JOURNAL.exists()
        if not restored:
            emit('restoring', '转发已停止，正在恢复手机直连音频…')
            try:
                restored = restore_phone()
            except Exception:
                restored = False
        if stop.is_set():
            error = None
        if error:
            emit('error', error, restored=restored)
        if restored:
            emit('stopped', '转发已停止，手机直连音频已恢复。', restored=True)
        else:
            emit('restore_pending', '请恢复手机无线连接并解锁，再点“恢复手机直连音频”。USB 也可作为恢复备用。', restored=False)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['check', 'run', 'recover', 'setup-wireless'])
    parser.add_argument('--transport', choices=['wireless', 'usb'], default='wireless')
    parser.add_argument('--headphone', default='soundcore Space 2')
    parser.add_argument('--buffer', type=int, choices=[100, 200], default=100)
    parser.add_argument('--watch-stdin', action='store_true')
    parser.add_argument('--device-id')
    args = parser.parse_args()
    if args.device_id:
        global STATE, JOURNAL, IDENTITY
        if args.device_id not in registry.records(): raise RuntimeError('设备尚未向本机授权。')
        STATE = registry.device_dir(args.device_id); STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
        JOURNAL = STATE/'phone-restore.json'; IDENTITY = STATE/'phone.json'
    try:
        if args.action == 'check':
            resolve_phone(args.transport)
            emit('checked', '小米 15 Ultra 的' + ('无线' if args.transport == 'wireless' else 'USB') + '连接正常。', pending=JOURNAL.exists(), transport=args.transport)
            return
        with (STATE / 'session.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('已有混音正在运行，请先停止原来的会话。')
            if args.action == 'run':
                run(args.headphone, args.buffer, args.watch_stdin, args.transport)
            elif args.action == 'setup-wireless':
                wireless.setup(ADB, STATE, usb_phone, phone_ui)
                emit('wireless_ready', '手机无线连接已接入，可以拔掉 USB 线。', transport='wireless')
            else:
                restore_phone()
                emit('recovered', '手机直连音频已恢复。', restored=True)
    except Exception as exc:
        emit('error', str(exc) if isinstance(exc, RuntimeError) else '操作未完成，请重试。')
        sys.exit(1)

if __name__ == '__main__':
    main()
