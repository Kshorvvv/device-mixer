import argparse
import json
from pathlib import Path
import subprocess
import sys
sys.dont_write_bytecode=True
import registry,wireless

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--device-id',required=True);parser.add_argument('--pair-uri',required=True);a=parser.parse_args()
    if a.device_id not in registry.records():raise RuntimeError('设备尚未授权。')
    folder=registry.device_dir(a.device_id)
    try:target,serial=wireless.discover(registry.ADB,folder)
    except RuntimeError:
        rows=wireless.command(registry.ADB,'devices','-l').splitlines()[1:];target=None
        for row in rows:
            if ' usb:' in row and len(row.split())>1 and row.split()[1]=='device':
                candidate=row.split()[0]
                if wireless.matches(registry.ADB,candidate,a.device_id):target=candidate;break
        if target is None:raise RuntimeError('设备连接不可用。')
    apk=Path(__file__).resolve().parent/'DeviceMixerRemote.apk'
    result=subprocess.run([str(registry.ADB),'-s',target,'install','-r',str(apk)],capture_output=True,timeout=90)
    if result.returncode or b'Success' not in result.stdout:raise RuntimeError('安装尚未完成；若手机出现安装确认，请允许此应用后重试。')
    # Do not print the private one-time pairing URI or raw Android launch output.
    uri="'"+a.pair_uri.replace("'","'\\''")+"'"
    result=subprocess.run([str(registry.ADB),'-s',target,'shell','am','start','-W','-n','io.github.kshorvvv.devicemixer/.MainActivity','--es','pair_uri',uri],capture_output=True,timeout=20)
    if result.returncode:raise RuntimeError('应用已安装，请在手机打开设备混音遥控器。')
    print(json.dumps({'state':'installed','message':'安卓遥控器已安装，正在自动配对。'},ensure_ascii=False),flush=True)
if __name__=='__main__':
    try:main()
    except Exception as e:print(json.dumps({'state':'error','message':str(e) if isinstance(e,RuntimeError) else '手机端安装未完成，请重试。'},ensure_ascii=False),flush=True);sys.exit(1)
