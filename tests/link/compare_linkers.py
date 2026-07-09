"""Compare lld-link vs bootstrap/link.py output for all .obj files in build/examples.

Historical development aid; not part of the default test suite.
"""
import os, subprocess, sys, hashlib, struct

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))
OBJ_DIR = os.path.join(ROOT_DIR, "build", "examples")
LLD = os.path.join(ROOT_DIR, "tools", "lld-link.exe")
LINK_PY = os.path.join(ROOT_DIR, "bootstrap", "link.py")
SDK_LIB = r"C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\um\x64"


def md5(path):
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def hexdump(path, n=128):
    with open(path, "rb") as f:
        data = f.read()
    for i in range(0, min(n, len(data)), 16):
        hex_part = " ".join(f"{b:02x}" for b in data[i : i + 16])
        print(f"  {i:04x}: {hex_part}")


def main():
    obj_files = sorted(
        f for f in os.listdir(OBJ_DIR) if f.endswith(".obj")
    )
    
    diff_count = 0
    for obj_name in obj_files:
        base = obj_name.replace(".obj", "")
        obj_path = os.path.join(OBJ_DIR, obj_name)
        exe_lld = os.path.join(OBJ_DIR, f"{base}_lld.exe")
        exe_py = os.path.join(OBJ_DIR, f"{base}_py.exe")
        
        # Link with lld-link
        subprocess.run(
            [LLD, "/subsystem:console", f"/entry:_start", f"/out:{exe_lld}",
             "/timestamp:0",
             obj_path,
             os.path.join(SDK_LIB, "kernel32.lib"),
             os.path.join(SDK_LIB, "user32.lib")],
            capture_output=True,
        )
        
        # Link with link.py
        subprocess.run(
            [sys.executable, LINK_PY, obj_path, "-o", exe_py],
            capture_output=True,
        )
        
        lld_sz = os.path.getsize(exe_lld) if os.path.exists(exe_lld) else 0
        py_sz = os.path.getsize(exe_py) if os.path.exists(exe_py) else 0
        
        if lld_sz == py_sz and md5(exe_lld) == md5(exe_py):
            print(f"  OK: {base} ({lld_sz} bytes)")
        else:
            diff_count += 1
            print(f"  DIFF: {base}  lld={lld_sz}  py={py_sz}")
    
    print(f"\n{diff_count} diffs out of {len(obj_files)}")

if __name__ == "__main__":
    main()
