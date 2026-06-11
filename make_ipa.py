#!/usr/bin/env python3
"""
make_ipa.py — 一键修改 IPA: 注入 KM 引擎 dylib 并重新打包

用法:
  如果已有编译好的 dylib:
    python3 make_ipa.py --ipa 原版.ipa --dylib KMEngine.dylib --out 调色-KM版.ipa

  如果还没有 dylib (需要先在 macOS 上编译):
    1. 将 build_dylib.sh + 所有 .h/.m 文件复制到 Mac
    2. ./build_dylib.sh
    3. 将生成的 KMEngine.dylib 复制回来
    4. python3 make_ipa.py ...
"""

import os
import sys
import shutil
import tempfile
import zipfile
import subprocess
import argparse


def extract_ipa(ipa_path, dest_dir):
    """解压 IPA"""
    print(f"Extracting: {ipa_path}")
    with zipfile.ZipFile(ipa_path, 'r') as zf:
        zf.extractall(dest_dir)

    # 找 .app 目录
    payload = os.path.join(dest_dir, 'Payload')
    apps = [d for d in os.listdir(payload) if d.endswith('.app')]
    if not apps:
        raise ValueError("No .app bundle found in IPA")
    app_dir = os.path.join(payload, apps[0])
    print(f"  App: {apps[0]}")
    return app_dir


def patch_binary(app_dir, dylib_name='KMEngine.dylib'):
    """注入 dylib 加载命令到主二进制"""
    info_plist = os.path.join(app_dir, 'Info.plist')

    # 读取可执行文件名
    import plistlib
    with open(info_plist, 'rb') as f:
        plist = plistlib.load(f)

    exe_name = plist.get('CFBundleExecutable', '')
    exe_path = os.path.join(app_dir, exe_name)

    if not os.path.exists(exe_path):
        raise ValueError(f"Binary not found: {exe_path}")

    # 检查是否已经 patch 过
    with open(exe_path, 'rb') as f:
        existing = f.read()
    dylib_ref = f'@executable_path/{dylib_name}'.encode('ascii')
    if dylib_ref in existing:
        print(f"  [skip] Binary already references {dylib_name}, skipping patch")
        return exe_path

    dylib_path = f'@executable_path/{dylib_name}'

    # 调用 patch_macho.py
    script_dir = os.path.dirname(os.path.abspath(__file__))
    patcher = os.path.join(script_dir, 'patch_macho.py')

    result = subprocess.run(
        ['python3', patcher, exe_path, dylib_path],
        capture_output=True,
        env={**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'}
    )
    output = result.stdout.decode('utf-8', errors='replace') if isinstance(result.stdout, bytes) else result.stdout
    print(output)
    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError("Mach-O patch failed")

    return exe_path


def copy_dylib(app_dir, dylib_path, dylib_name='KMEngine.dylib'):
    """复制 dylib 到 .app bundle"""
    dest = os.path.join(app_dir, dylib_name)
    shutil.copy2(dylib_path, dest)
    print(f"  Copied {dylib_name} -> .app/")
    return dest


def repackage_ipa(app_dir, output_path):
    """重新打包为 IPA"""
    parent = os.path.dirname(app_dir)  # Payload/
    grandparent = os.path.dirname(parent)  # temp dir

    # 创建 Payload/{app}
    payload_name = os.path.basename(os.path.dirname(app_dir))
    app_name = os.path.basename(app_dir)

    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(grandparent):
            for fn in files:
                full_path = os.path.join(root, fn)
                arcname = os.path.relpath(full_path, grandparent)
                zf.write(full_path, arcname)

    print(f"  Created: {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(description='Make IPA with KM Engine')
    parser.add_argument('--ipa', required=True, help='Original IPA file')
    parser.add_argument('--dylib', help='Pre-compiled KMEngine.dylib (skip if not yet compiled)')
    parser.add_argument('--out', default=None, help='Output IPA path')
    parser.add_argument('--patch-only', action='store_true', help='Only patch binary, dont add dylib')

    args = parser.parse_args()

    if args.out is None:
        base = os.path.splitext(os.path.basename(args.ipa))[0]
        args.out = f'{base}-KM.ipa'

    # Determine if dylib exists
    dylib_path = args.dylib
    if dylib_path and not os.path.exists(dylib_path):
        print(f"WARNING: dylib not found at {dylib_path}")
        print("Will patch binary but dylib must be compiled separately.")
        dylib_path = None

    # Extract
    tmpdir = tempfile.mkdtemp(prefix='ipa_km_')
    try:
        app_dir = extract_ipa(args.ipa, tmpdir)

        # Patch binary (always, unless dylib is provided AND we're not in patch-only)
        if dylib_path or args.patch_only:
            patch_binary(app_dir)

        # Copy dylib
        if dylib_path:
            copy_dylib(app_dir, dylib_path)

        # Keep backup files from patcher (don't auto-delete)
        # They're useful if something goes wrong
        for f in os.listdir(app_dir):
            if f.endswith('.backup'):
                print(f"  [kept] backup: {f} (保留用于恢复)")

        # Repackage
        repackage_ipa(app_dir, args.out)

        print(f"\n{'='*50}")
        print(f"Done: {args.out}")
        print(f"{'='*50}")

        if not dylib_path:
            print()
            print("NOTE: KMEngine.dylib was NOT included (not compiled yet).")
            print("To complete the build:")
            print("  1. Copy build_dylib.sh + *.h + *.m to your Mac")
            print("  2. Run ./build_dylib.sh")
            print("  3. Copy build/KMEngine.dylib back")
            print(f"  4. Re-run: python3 make_ipa.py --ipa {args.ipa} --dylib KMEngine.dylib")

    finally:
        shutil.rmtree(tmpdir)


if __name__ == '__main__':
    main()
