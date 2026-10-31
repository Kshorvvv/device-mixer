import json
import sys
sys.dont_write_bytecode=True
import controller,registry

root=registry.ROOT
records=[root/'phone-restore.json']+list((root/'devices').glob('*/phone-restore.json'))
failed=False
for path in records:
    if not path.exists():continue
    try:
        controller.STATE=path.parent;controller.JOURNAL=path;controller.IDENTITY=path.parent/'phone.json'
        controller.restore_phone()
    except Exception:failed=True
print(json.dumps({'state':'restore_pending' if failed else 'recovered','message':'部分设备待恢复，请确认无线连接并解锁后重试。' if failed else '普通使用设置已恢复。'},ensure_ascii=False),flush=True)
sys.exit(1 if failed else 0)
