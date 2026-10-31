import json, re, subprocess, tempfile, time, unicodedata
from pathlib import Path
import xml.etree.ElementTree as ET
RES = Path(__file__).resolve().parent
ADB = RES / "adb"
OCR = RES / "inspect-settings"
def normalise(text):
    return ''.join(c for c in unicodedata.normalize("NFKC", text).casefold() if c.isalnum())
def adb(target, *args, timeout=12):
    p = subprocess.run([str(ADB), '-s', target, *args], capture_output=True, timeout=timeout)
    if p.returncode: raise RuntimeError('设备操作未完成，请检查无线或 USB 连接。')
    return p.stdout.decode(errors='replace').strip()
def xml_snapshot(target):
    remote = '/sdcard/device-mixer-ui.xml'
    adb(target, 'shell', 'rm', '-f', remote)
    response = adb(target, 'shell', 'uiautomator', 'dump', remote, timeout=20)
    if 'dumped to:' not in response:
        raise RuntimeError('没有取得新的设置界面，已停止自动点击。')
    xml = adb(target, 'shell', 'cat', remote)
    adb(target, 'shell', 'rm', '-f', remote)
    root = ET.fromstring(xml)
    packages = {n.get('package') for n in root.iter('node') if n.get('package')}
    if not packages <= {'com.android.settings', 'com.android.systemui'}:
        raise RuntimeError('当前界面不是设置页，已停止自动点击。')
    return root

def bounds(node):
    return tuple(map(int, re.findall(r'\d+', node.get('bounds', ''))))

def tap(target, x, y):
    adb(target, 'shell', 'input', 'tap', str(int(x)), str(int(y)))
    time.sleep(.5)

def screenshot_analysis(target):
    with tempfile.TemporaryDirectory(prefix='device-mixer-') as d:
        image = Path(d) / 'settings.png'
        result = subprocess.run([str(ADB), '-s', target, 'exec-out', 'screencap', '-p'], capture_output=True, timeout=12)
        if result.returncode:
            raise RuntimeError('设置界面读取失败。')
        image.write_bytes(result.stdout)
        p = subprocess.run([str(OCR), str(image)], capture_output=True, timeout=20)
        if p.returncode:
            raise RuntimeError('设置界面识别失败。')
        return json.loads(p.stdout)

def media_switch(target, headphone, desired=None, before_change=None):
    if any(x.strip() == 'showing=true' for x in adb(target, 'shell', 'dumpsys', 'window', 'policy').splitlines()):
        raise RuntimeError('请本人解锁手机，再点开启；工具不会解锁设备。')
    adb(target, 'shell', 'am', 'start', '-W', '-f', '0x10008000', '-a', 'android.settings.BLUETOOTH_SETTINGS')
    time.sleep(.7)
    root = xml_snapshot(target)
    devices = [n for n in root.iter('node') if n.get('text','').strip().casefold() == headphone.strip().casefold()]
    if len(devices) == 1:
        parents = {c: p for p in root.iter() for c in p}
        container = devices[0]
        detail = None
        for _ in range(5):
            matches = [n for n in container.iter('node') if n.get('resource-id') == 'com.android.settings:id/preference_detail' and n.get('clickable') == 'true']
            if len(matches) == 1:
                detail = matches[0]; break
            if container not in parents: break
            container = parents[container]
        if detail is None:
            raise RuntimeError('没有找到 目标耳机 的唯一设置按钮，已停止自动点击。')
        x1, y1, x2, y2 = bounds(detail)
        tap(target, (x1+x2)/2, (y1+y2)/2)
    else:
        raise RuntimeError('没有找到唯一的 目标耳机 设置入口，请连接耳机后重试。')
    xml_snapshot(target)
    image = screenshot_analysis(target)
    matches = [r for r in image['texts'] if r['text'].strip() in ('媒体音频', 'Media audio')]
    if len(matches) != 1 or normalise(headphone) not in normalise(' '.join(r['text'] for r in image['texts'])):
        raise RuntimeError('没有确认媒体音频开关，已停止自动点击。')
    row = matches[0]
    # The inspector samples the right-hand switch beside each recognized label.
    state = row.get('switch')
    if state not in (True, False):
        raise RuntimeError('开关状态不明确，请在手机 目标耳机 设置中手动调整“媒体音频”。')
    if before_change:
        before_change(state)
    if desired is not None and state != desired:
        tap(target, image['width'] * .87, row['y'])
        fresh = xml_snapshot(target)
        ok = [n for n in fresh.iter('node') if n.get('text') in ('OK', '确定')]
        if len(ok) == 1 and any('媒体' in n.get('text', '') or 'audio' in n.get('text', '').lower() for n in fresh.iter('node')):
            x1, y1, x2, y2 = bounds(ok[0]); tap(target, (x1+x2)/2, (y1+y2)/2)
        image = screenshot_analysis(target)
        rows = [r for r in image['texts'] if r['text'].strip() in ('媒体音频', 'Media audio')]
        if len(rows) != 1 or rows[0].get('switch') != desired:
            raise RuntimeError('媒体开关未确认变更，请检查手机设置。')
    # Return through the Settings task to the previous app, preserving its state.
    for _ in range(2):
        focus = adb(target, 'shell', 'dumpsys', 'window', 'windows')
        if not any('mCurrentFocus' in line and 'com.android.settings/' in line for line in focus.splitlines()): break
        adb(target, 'shell', 'input', 'keyevent', 'KEYCODE_BACK')
    return state
