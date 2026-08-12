"""Build the btb_geo.dll C acceleration kernel for the AI.

Usage:
    python AI/build_geo.py

The script locates a suitable compiler automatically (env GXX, common
TDM-GCC / MinGW install paths, or PATH lookup), compiles AI/btb_geo.c
with -O2 into AI/btb_geo.dll, and verifies the DLL loads via ctypes.
"""

import ctypes
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'btb_geo.c')
DLL = os.path.join(HERE, 'btb_geo.dll')

# Common Windows GCC install locations (checked in order).
GCC_CANDIDATES = [
    r'C:\Program Files (x86)\Embarcadero\Dev-Cpp\TDM-GCC-64\bin\g++.exe',
    r'C:\Program Files\Embarcadero\Dev-Cpp\TDM-GCC-64\bin\g++.exe',
    r'C:\TDM-GCC-64\bin\g++.exe',
    r'C:\msys64\mingw64\bin\g++.exe',
    r'C:\msys64\ucrt64\bin\g++.exe',
    r'C:\MinGW\bin\g++.exe',
]


def find_gxx():
    env = os.environ.get('GXX')
    if env and os.path.isfile(env):
        return env
    for c in GCC_CANDIDATES:
        if os.path.isfile(c):
            return c
    found = shutil.which('g++')
    if found:
        return found
    return None


def main():
    if not os.path.isfile(SRC):
        print(f'[build_geo] source not found: {SRC}')
        return 1

    gxx = find_gxx()
    if not gxx:
        print('[build_geo] ERROR: no g++ found. Set GXX env var or install MinGW/TDM-GCC.')
        return 1
    print(f'[build_geo] compiler: {gxx}')

    cmd = [
        gxx, '-O2', '-shared', '-static-libgcc', '-static-libstdc++',
        '-o', DLL, SRC,
    ]
    print(f'[build_geo] cmd: {" ".join(cmd)}')
    r = subprocess.run(cmd)
    if r.returncode != 0 or not os.path.isfile(DLL):
        print('[build_geo] ERROR: compilation failed.')
        return 1

    size = os.path.getsize(DLL)
    try:
        ctypes.CDLL(DLL)
        ok = True
    except OSError as e:
        ok = False
        err = str(e)
    if not ok:
        print(f'[build_geo] ERROR: DLL built but ctypes cannot load it: {err}')
        return 1
    print(f'[build_geo] OK: {DLL} ({size} bytes) loads via ctypes.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
