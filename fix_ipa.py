#!/usr/bin/env python3
"""
fix_ipa.py — 最终修复: 从损坏版 IPA 出发, 只修正 vmsize + fileoff, 不动 SYMTAB
"""

import struct, sys, os, shutil, zipfile, tempfile

LC_SEGMENT_64 = 0x19
LC_SYMTAB = 0x02
LC_DYSYMTAB = 0x0B
LC_LOAD_DYLIB = 0x0C
LC_LOAD_WEAK_DYLIB = 0x18 | 0x80000000
LC_DYLD_INFO_ONLY = 0x22 | 0x80000000
LC_FUNCTION_STARTS = 0x26
LC_DATA_IN_CODE = 0x29
LC_CODE_SIGNATURE = 0x1D


def fix_binary(data: bytes) -> bytes:
    """修复损坏的二进制: 修正 vmsize + 更新 fileoff/section 偏移"""

    # 找到注入的 WEAK_DYLIB 来确定 shift_amount
    ncmds = struct.unpack_from('<I', data, 16)[0]
    pos = 32
    shift_amount = 0
    injected_idx = -1
    injected_pos = -1

    for i in range(ncmds):
        cmd, cmdsize = struct.unpack_from('<II', data, pos)
        if cmd == LC_LOAD_WEAK_DYLIB:
            name_off = struct.unpack_from('<I', data, pos + 8)[0]
            name = data[pos + name_off:].split(b'\x00')[0].decode('ascii', errors='replace')
            if 'KMEngine' in name:
                injected_idx = i
                injected_pos = pos
                shift_amount = cmdsize
                print(f'  找到注入的 WEAK_DYLIB #{i}: {name} (size={cmdsize})')
                break
        pos += cmdsize

    if injected_idx < 0:
        print("  未找到 KMEngine 引用，无需修复")
        return data

    print(f'  shift_amount = {shift_amount}')

    new_data = bytearray(data)
    pos = 32
    for i in range(ncmds):
        cmd, cmdsize = struct.unpack_from('<II', data, pos)

        if cmd == LC_SEGMENT_64:
            segname = data[pos+8:pos+24].rstrip(b'\x00').decode('ascii', errors='replace')

            # 1. 修复 vmsize (被 bug 加了 shift_amount)
            vmsize = struct.unpack_from('<Q', data, pos + 32)[0]
            if vmsize >= shift_amount:
                struct.pack_into('<Q', new_data, pos + 32, vmsize - shift_amount)

            # 2. 正确更新 fileoff (offset 40)
            fileoff = struct.unpack_from('<Q', data, pos + 40)[0]
            filesize = struct.unpack_from('<Q', data, pos + 48)[0]
            if fileoff > 0 and filesize > 0:
                struct.pack_into('<Q', new_data, pos + 40, fileoff + shift_amount)

            # 3. 修正 section 内部 offset 和 reloff
            nsects = struct.unpack_from('<I', data, pos + 64)[0]
            for s in range(nsects):
                sec_off = pos + 72 + s * 80
                sec_offset = struct.unpack_from('<I', data, sec_off + 48)[0]
                if sec_offset > 0:
                    struct.pack_into('<I', new_data, sec_off + 48, sec_offset + shift_amount)
                reloff = struct.unpack_from('<I', data, sec_off + 56)[0]
                if reloff > 0:
                    struct.pack_into('<I', new_data, sec_off + 56, reloff + shift_amount)

        elif cmd in (LC_FUNCTION_STARTS, LC_DATA_IN_CODE, LC_CODE_SIGNATURE):
            val = struct.unpack_from('<I', data, pos + 8)[0]
            if val > 0:
                struct.pack_into('<I', new_data, pos + 8, val + shift_amount)

        elif cmd == LC_DYLD_INFO_ONLY:
            for local_off in [8, 12, 16, 20, 24]:
                field_off = pos + local_off
                val = struct.unpack_from('<I', data, field_off)[0]
                if val > 0:
                    struct.pack_into('<I', new_data, field_off, val + shift_amount)

        # 注意: 不修改 LC_SYMTAB 和 LC_DYSYMTAB!
        # 损坏版中它们的偏移没被动过(和原版一样), 且 stroff+strsize 恰好等于文件大小

        pos += cmdsize

    return bytes(new_data)


def main():
    ipa_path = sys.argv[1] if len(sys.argv) > 1 else 'build/调色-KM-v3.0-损坏版.ipa'
    out_path = sys.argv[2] if len(sys.argv) > 2 else 'build/调色-KM-v3.0-fixed.ipa'

    tmpdir = tempfile.mkdtemp(prefix='ipa_fix_')
    try:
        print(f'Extracting: {ipa_path}')
        with zipfile.ZipFile(ipa_path, 'r') as zf:
            zf.extractall(tmpdir)

        payload = os.path.join(tmpdir, 'Payload')
        app_dir = os.path.join(payload, os.listdir(payload)[0])
        print(f'  App: {os.path.basename(app_dir)}')

        import plistlib
        with open(os.path.join(app_dir, 'Info.plist'), 'rb') as f:
            plist = plistlib.load(f)
        exe_name = plist.get('CFBundleExecutable', '')
        exe_path = os.path.join(app_dir, exe_name)

        # 备份
        shutil.copy2(exe_path, exe_path + '.bak')

        with open(exe_path, 'rb') as f:
            data = f.read()

        print(f'\nFixing {exe_name} ({len(data)} bytes)...')
        fixed = fix_binary(data)

        with open(exe_path, 'wb') as f:
            f.write(fixed)

        # 验证
        ncmds = struct.unpack_from('<I', fixed, 16)[0]
        pos = 32
        ok = True
        for i in range(ncmds):
            cmd, cmdsize = struct.unpack_from('<II', fixed, pos)
            if cmd == LC_SEGMENT_64:
                segname = fixed[pos+8:pos+24].rstrip(b'\x00').decode('ascii', errors='replace')
                fileoff = struct.unpack_from('<Q', fixed, pos + 40)[0]
                filesize = struct.unpack_from('<Q', fixed, pos + 48)[0]
                if filesize > 0 and fileoff + filesize > len(fixed):
                    print(f'  [CORRUPT] {segname}: 0x{fileoff:X}+0x{filesize:X}')
                    ok = False
                else:
                    print(f'  [OK] {segname}: 0x{fileoff:X}+0x{filesize:X}')
            elif cmd == LC_SYMTAB:
                stroff = struct.unpack_from('<I', fixed, pos + 16)[0]
                strsize = struct.unpack_from('<I', fixed, pos + 20)[0]
                end = stroff + strsize
                if end > len(fixed):
                    print(f'  [CORRUPT] SYMTAB: stroff+strsize=0x{end:X} > 0x{len(fixed):X}')
                    ok = False
                else:
                    print(f'  [OK] SYMTAB: stroff=0x{stroff:X} strsize={strsize} end=0x{end:X}')
            pos += cmdsize

        if ok:
            print('\n  Binary VALID!')

        # 重新打包
        grandparent = os.path.dirname(os.path.dirname(app_dir))
        with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(grandparent):
                for fn in files:
                    if fn.endswith('.bak'):
                        continue
                    full_path = os.path.join(root, fn)
                    arcname = os.path.relpath(full_path, grandparent)
                    zf.write(full_path, arcname)

        print(f'\nDone: {out_path}')

    finally:
        shutil.rmtree(tmpdir)


if __name__ == '__main__':
    main()
