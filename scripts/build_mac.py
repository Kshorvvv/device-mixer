from pathlib import Path
import argparse
import hashlib
import json
import platform
import plistlib
import shutil
import subprocess
import tarfile
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--tools',help='Existing verified scrcpy v5.0 portable directory');a=p.parse_args()
if platform.machine()!='arm64':raise SystemExit('This initial build currently targets Apple Silicon Macs.')
if a.tools:tools=Path(a.tools)
else:
    cache=ROOT/'.tools';cache.mkdir(exist_ok=True)
    archive=cache/'scrcpy-macos-aarch64-v5.0.tar.gz'
    expected='7cb4e41c859b05b36e89dc9be6c353cc5980c00d7f7f6a763b5b355551b82e9c'
    if not archive.exists():
        url='https://github.com/Genymobile/scrcpy/releases/download/v5.0/scrcpy-macos-aarch64-v5.0.tar.gz'
        with urllib.request.urlopen(url,timeout=60) as source,archive.open('wb') as target:shutil.copyfileobj(source,target)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=expected:raise SystemExit('Official scrcpy package checksum mismatch')
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            if not (cache/member.name).resolve().is_relative_to(cache.resolve()):raise SystemExit('Unsafe archive path')
            if member.issym() or member.islnk():raise SystemExit('Unexpected archive link')
        tar.extractall(cache)
    tools=cache/'scrcpy-macos-aarch64-v5.0'
assets=ROOT/'assets'
if not (assets/'AppIcon.icns').exists():
    subprocess.run(['xcrun','swift',str(ROOT/'scripts/icon.swift'),str(assets)],check=True)
    subprocess.run(['iconutil','-c','icns',str(assets/'AppIcon.iconset'),'-o',str(assets/'AppIcon.icns')],check=True)
app=ROOT/'dist/设备混音.app';contents=app/'Contents';res=contents/'Resources';binary=contents/'MacOS'
res.mkdir(parents=True,exist_ok=True);binary.mkdir(parents=True,exist_ok=True)
info={'CFBundleName':'设备混音','CFBundleDisplayName':'设备混音','CFBundleIdentifier':'cn.local.device-mixer','CFBundleExecutable':'DeviceMixer','CFBundlePackageType':'APPL','CFBundleShortVersionString':'0.4.0','CFBundleVersion':'5','CFBundleIconFile':'AppIcon.icns','LSMinimumSystemVersion':'14.2','NSHighResolutionCapable':True,'NSLocalNetworkUsageDescription':'发现你已授权的安卓设备，并通过加密连接接收手机控制；不上传音频。','NSBonjourServices':['_devicemix._tcp']}
(contents/'Info.plist').write_bytes(plistlib.dumps(info))
def run(args):subprocess.run([str(v) for v in args],check=True)
run(['xcrun','swiftc','-swift-version','5','-O','-target','arm64-apple-macos14.2',ROOT/'mac/Route.swift',ROOT/'mac/Desktop.swift','-o',binary/'DeviceMixer'])
run(['xcrun','swiftc','-O','-target','arm64-apple-macos14.2',ROOT/'mac/audio_route.swift','-o',res/'audio-route'])
run(['xcrun','swiftc','-O','-target','arm64-apple-macos14.2',ROOT/'mac/Inspector.swift','-o',res/'inspect-settings'])
for file in (ROOT/'mac').glob('*.py'):shutil.copy2(file,res/file.name)
for name in ['adb','scrcpy','scrcpy-server']:shutil.copy2(tools/name,res/name)
shutil.copy2(tools/'LICENSE',res/'scrcpy-LICENSE')
shutil.copy2(assets/'AppIcon.icns',res/'AppIcon.icns')
if (ROOT/'dist/DeviceMixerRemote.apk').exists():shutil.copy2(ROOT/'dist/DeviceMixerRemote.apk',res/'DeviceMixerRemote.apk')
cache=res/'__pycache__'
if cache.exists():shutil.rmtree(cache)
run(['codesign','--force','--deep','--sign','-',app]);run(['codesign','--verify','--deep','--strict',app])
print('Mac app built:',app)
