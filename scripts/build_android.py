from pathlib import Path
import argparse
import os
import secrets
import shutil
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--jdk',default=os.environ.get('JAVA_HOME'));p.add_argument('--platform');p.add_argument('--build-tools');a=p.parse_args()
if not all([a.jdk,a.platform,a.build_tools]):p.error('Provide --jdk, --platform (android.jar), and --build-tools paths.')
jdk=Path(a.jdk);bt=Path(a.build_tools);platform=Path(a.platform)
build=ROOT/'.local-build/android';build.mkdir(parents=True,exist_ok=True)
classes=build/'classes';classes.mkdir(exist_ok=True);dex=build/'dex';dex.mkdir(exist_ok=True)
def run(args):subprocess.run([str(x) for x in args],check=True)
sources=list((ROOT/'android/src').rglob('*.java'))
run([jdk/'bin/javac','--release','8','-encoding','UTF-8','-classpath',platform,'-d',classes,*sources])
run([jdk/'bin/jar','cf',build/'classes.jar','-C',classes,'.'])
run([jdk/'bin/java','-cp',bt/'lib/d8.jar','com.android.tools.r8.D8','--lib',platform,'--min-api','26','--output',dex,build/'classes.jar'])
res=ROOT/'android/res/drawable';res.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/'assets/icon-192.png',res/'icon.png')
run([bt/'aapt2','compile','--dir',ROOT/'android/res','-o',build/'compiled.zip'])
run([bt/'aapt2','link','-I',platform,'--manifest',ROOT/'android/AndroidManifest.xml','-o',build/'unsigned.apk',build/'compiled.zip'])
with zipfile.ZipFile(build/'unsigned.apk','a',zipfile.ZIP_DEFLATED) as z:
    for file in dex.glob('*.dex'):z.write(file,file.name)
run([bt/'zipalign','-f','4',build/'unsigned.apk',build/'aligned.apk'])
sign=ROOT/'.local-build/signing';sign.mkdir(exist_ok=True,mode=0o700)
password=sign/'password';keystore=sign/'development.p12'
if not password.exists():password.write_text(secrets.token_urlsafe(32));password.chmod(0o600)
if not keystore.exists():run([jdk/'bin/keytool','-genkeypair','-keystore',keystore,'-storetype','PKCS12','-alias','mixer','-keyalg','RSA','-keysize','3072','-validity','10000','-dname','CN=Device Mixer Development','-storepass:file',password,'-keypass:file',password])
keystore.chmod(0o600)
dist=ROOT/'dist';dist.mkdir(exist_ok=True)
run([jdk/'bin/java','-jar',bt/'lib/apksigner.jar','sign','--ks',keystore,'--ks-key-alias','mixer','--ks-pass','file:'+str(password),'--out',dist/'DeviceMixerRemote.apk',build/'aligned.apk'])
run([jdk/'bin/java','-jar',bt/'lib/apksigner.jar','verify',dist/'DeviceMixerRemote.apk'])
print('Android APK built and signature verified:',dist/'DeviceMixerRemote.apk')
