#!/usr/bin/env python3
"""로컬 시험용 OCI CLI 대역. ject-pg-backup / restore-test가 쓰는 os 명령만 디렉터리로 흉내낸다."""
import json, os, shutil, sys
ROOT = os.environ.get("FAKE_OCI_ROOT", "/tmp/fake-oci")
a = [x for x in sys.argv[1:]]
if "--auth" in a:
    i = a.index("--auth"); del a[i:i+2]
def opt(name, default=None):
    return a[a.index(name)+1] if name in a else default
if a[:3] == ["os", "ns", "get"]:
    print("fakens"); sys.exit(0)
assert a[:2] == ["os", "object"], a
cmd = a[2]
bucket = opt("-bn"); base = os.path.join(ROOT, bucket); os.makedirs(base, exist_ok=True)
if os.environ.get("FAKE_OCI_FAIL") == cmd:
    print("simulated failure", file=sys.stderr); sys.exit(1)
if cmd == "put":
    dst = os.path.join(base, opt("--name"))
    if "--no-overwrite" in a and os.path.exists(dst): sys.exit("exists")
    os.makedirs(os.path.dirname(dst), exist_ok=True); shutil.copyfile(opt("--file"), dst)
elif cmd == "head":
    p = os.path.join(base, opt("--name"))
    if not os.path.exists(p): sys.exit("404")
    print(json.dumps({"content-length": str(os.path.getsize(p))}))
elif cmd == "list":
    pre = opt("--prefix", ""); out = []
    for d, _, fs in os.walk(base):
        for f in fs:
            n = os.path.relpath(os.path.join(d, f), base)
            if n.startswith(pre): out.append({"name": n})
    print(json.dumps({"data": sorted(out, key=lambda x: x["name"])}))
elif cmd == "bulk-delete":
    pre = opt("--prefix")
    shutil.rmtree(os.path.join(base, pre), ignore_errors=True)
elif cmd == "bulk-download":
    pre = opt("--prefix"); dd = opt("--download-dir")
    src = os.path.join(base, pre)
    shutil.copytree(src, os.path.join(dd, pre), dirs_exist_ok=True)
else:
    sys.exit("unsupported " + cmd)
