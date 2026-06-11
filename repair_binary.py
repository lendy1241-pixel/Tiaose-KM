#!/usr/bin/env python3
"""
repair_binary.py — 修复被 patch_macho.py (bug版) 损坏的 Mach-O 二进制

bug: patch_macho.py 在 patch_offsets() 中把 segment command offset 32 (vmsize)
     当作 fileoff (offset 40) 来处理，导致:
       - vmsize 被错误地 += shift_amount
       - fileoff 没有被更新
       - section 内部的 offset / reloff 也没有被更新

本脚本使用 "revert + re-patch" 策略:
  1. 删除注入的 WEAK_DYLIB command
  2. 将后续数据前移，恢复原始二进制
  3. 用正确的方式重新注入 WEAK_DYLIB
"""

import struct
import sys
import os
import shutil
import zipfile
import tempfile

# ============================================================
# 常量
# ============================================================
MH_MAGIC_64 = 0xFEEDFACF
MH_CIGAM_64 = 0xCFFAEDFE

LC_SEGMENT_64        = 0x19
LC_SYMTAB            = 0x02
LC_DYSYMTAB          = 0x0B
LC_LOAD_DYLIB        = 0x0C
LC_LOAD_WEAK_DYLIB   = 0x18 | 0x80000000
LC_DYLD_INFO_ONLY    = 0x22 | 0x80000000
LC_FUNCTION_STARTS   = 0x26
LC_DATA_IN_CODE      = 0x29
LC_CODE_SIGNATURE    = 0x1D
LC_BUILD_VERSION     = 0x32


def parse_macho(data: bytes):
    """解析 Mach-O 结构"""
    magic = struct.unpack_from('<I', data, 0)[0]
    if magic == MH_MAGIC_64:
        endian = '<'
    elif magic == MH_CIGAM_64:
        endian = '>'
    else:
        raise ValueError(f"不是 64-bit Mach-O (magic=0x{magic:08X})")

    ncmds = struct.unpack_from(f'{endian}I', data, 16)[0]
    sizeofcmds = struct.unpack_from(f'{endian}I', data, 20)[0]

    commands = []
    pos = 32
    for i in range(ncmds):
        cmd, cmdsize = struct.unpack_from(f'{endian}II', data, pos)
        cmd_data = {
            'index': i, 'cmd': cmd, 'cmdsize': cmdsize, 'offset': pos,
            'raw': data[pos:pos+cmdsize]
        }
        if cmd == LC_SEGMENT_64:
            cmd_data['segname'] = data[pos+8:pos+24].rstrip(b'\x00').decode('ascii', errors='replace')
        elif cmd == LC_LOAD_WEAK_DYLIB:
            name_off = struct.unpack_from(f'{endian}I', data, pos+8)[0]
            cmd_data['dylib_name'] = data[pos+name_off:].split(b'\x00')[0].decode('ascii', errors='replace')
        commands.append(cmd_data)
        pos += cmdsize

    return endian, ncmds, sizeofcmds, commands


def revert_patch(data: bytes) -> bytes:
    """
    删除注入的 WEAK_DYLIB command，还原为原始二进制。

    步骤:
      1. 找到 KMEngine WEAK_DYLIB command 的位置
      2. 将其从 LC 区域删除，后续 LC 和 segment 数据前移
      3. 修复 vmsize (减去 shift_amount)
      4. 更新 ncmds 和 sizeofcmds
    """
    endian, ncmds, sizeofcmds, commands = parse_macho(data)

    # 找到注入的 command
    injected_idx = -1
    injected_offset = -1
    shift_amount = 0
    for cmd in commands:
        if cmd['cmd'] == LC_LOAD_WEAK_DYLIB and cmd.get('dylib_name', '') == '@executable_path/KMEngine.dylib':
            injected_idx = cmd['index']
            injected_offset = cmd['offset']
            shift_amount = cmd['cmdsize']
            break

    if injected_idx < 0:
        print("  [INFO] 未找到注入的 KMEngine WEAK_DYLIB")
        return data

    print(f'  删除注入的 WEAK_DYLIB #{injected_idx} at offset 0x{injected_offset:X} (size={shift_amount})')

    # 构建新二进制: 删除注入的 LC，前移后续数据
    new_data = bytearray()

    # 1. 新 header
    header = bytearray(data[:32])
    new_ncmds = ncmds - 1
    new_sizeofcmds = sizeofcmds - shift_amount
    struct.pack_into(f'{endian}I', header, 16, new_ncmds)
    struct.pack_into(f'{endian}I', header, 20, new_sizeofcmds)
    new_data += header

    # 2. 除注入 command 外的所有 LC (修复 vmsize)
    for cmd in commands:
        if cmd['index'] == injected_idx:
            continue  # 跳过注入的 command

        lc_data = bytearray(cmd['raw'])

        if cmd['cmd'] == LC_SEGMENT_64:
            # 修复 vmsize (被错误地加了 shift_amount)
            vmsize = struct.unpack_from(f'{endian}Q', lc_data, 32)[0]
            if vmsize >= shift_amount:
                struct.pack_into(f'{endian}Q', lc_data, 32, vmsize - shift_amount)

        new_data += bytes(lc_data)

    # 3. Segment 数据 (从注入点之后开始)
    #    注入点在 LC 区域中间，注入点之后还有原生 LC
    #    segment 数据在所有 LC 之后
    old_lc_end = 32 + sizeofcmds  # 旧 LC 区域结束 = segment 数据开始
    segment_data_start = old_lc_end  # 在原始文件中
    new_data += data[segment_data_start:]

    return bytes(new_data)


def inject_dylib_correct(data: bytes, dylib_path: str) -> bytes:
    """
    使用正确的偏移量注入 LC_LOAD_WEAK_DYLIB。

    (这是修复后的 patch_macho.py 逻辑)
    """
    endian, ncmds, sizeofcmds, commands = parse_macho(data)

    # 找到最后一个 LC_LOAD_DYLIB
    last_dylib_idx = -1
    for cmd in commands:
        if cmd['cmd'] == LC_LOAD_DYLIB:
            last_dylib_idx = cmd['index']

    if last_dylib_idx < 0:
        raise ValueError("找不到 LC_LOAD_DYLIB")

    insert_after = commands[last_dylib_idx]
    print(f'  在 LC_LOAD_DYLIB #{last_dylib_idx} 之后插入')

    # 构建新 LC_LOAD_WEAK_DYLIB
    path_bytes = dylib_path.encode('ascii') + b'\x00'
    padding = (8 - (len(path_bytes) % 8)) % 8
    path_bytes += b'\x00' * padding

    cmdsize = 24 + len(path_bytes)
    new_cmd = struct.pack(
        f'{endian}IIIIII',
        LC_LOAD_WEAK_DYLIB,
        cmdsize,
        24,
        2,
        0x00010000,
        0x00010000,
    ) + path_bytes

    shift_amount = cmdsize
    print(f'  新 WEAK_DYLIB: {dylib_path} (size={cmdsize})')

    # 构建新二进制
    lc_start = 32
    new_ncmds = ncmds + 1
    new_sizeofcmds = sizeofcmds + shift_amount

    new_data = bytearray()
    header = bytearray(data[:32])
    struct.pack_into(f'{endian}I', header, 16, new_ncmds)
    struct.pack_into(f'{endian}I', header, 20, new_sizeofcmds)
    new_data += header

    # LC 区域 + 修正所有文件偏移
    for cmd in commands:
        lc_data = bytearray(cmd['raw'])

        # --- 正确的偏移修正 ---
        if cmd['cmd'] == LC_SEGMENT_64:
            # fileoff 在 offset 40!! (不是 32)
            fileoff = struct.unpack_from(f'{endian}Q', lc_data, 40)[0]
            filesize = struct.unpack_from(f'{endian}Q', lc_data, 48)[0]
            if fileoff > 0 and filesize > 0:
                struct.pack_into(f'{endian}Q', lc_data, 40, fileoff + shift_amount)

            # 修正 section 内部的 offset 和 reloff
            nsects = struct.unpack_from(f'{endian}I', lc_data, 64)[0]
            for s in range(nsects):
                sec_off = 72 + s * 80
                # section.offset (uint32 at sec_off+48)
                sec_offset = struct.unpack_from(f'{endian}I', lc_data, sec_off + 48)[0]
                if sec_offset > 0:
                    struct.pack_into(f'{endian}I', lc_data, sec_off + 48, sec_offset + shift_amount)
                # section.reloff (uint32 at sec_off+56)
                reloff = struct.unpack_from(f'{endian}I', lc_data, sec_off + 56)[0]
                if reloff > 0:
                    struct.pack_into(f'{endian}I', lc_data, sec_off + 56, reloff + shift_amount)

        elif cmd['cmd'] == LC_SYMTAB:
            for field_off in [8, 16]:
                val = struct.unpack_from(f'{endian}I', lc_data, field_off)[0]
                if val > 0:
                    struct.pack_into(f'{endian}I', lc_data, field_off, val + shift_amount)

        elif cmd['cmd'] == LC_DYSYMTAB:
            for field_off in range(8, len(lc_data), 4):
                if field_off + 4 <= len(lc_data):
                    val = struct.unpack_from(f'{endian}I', lc_data, field_off)[0]
                    if 0 < val < 10_000_000:
                        struct.pack_into(f'{endian}I', lc_data, field_off, val + shift_amount)

        elif cmd['cmd'] == LC_DYLD_INFO_ONLY:
            for field_off in [8, 12, 16, 20, 24]:
                val = struct.unpack_from(f'{endian}I', lc_data, field_off)[0]
                if val > 0:
                    struct.pack_into(f'{endian}I', lc_data, field_off, val + shift_amount)

        elif cmd['cmd'] in (LC_FUNCTION_STARTS, LC_DATA_IN_CODE, LC_CODE_SIGNATURE):
            val = struct.unpack_from(f'{endian}I', lc_data, 8)[0]
            if val > 0:
                struct.pack_into(f'{endian}I', lc_data, 8, val + shift_amount)

        new_data += bytes(lc_data)

        # 在最后一个 dylib 之后插入新 command
        if cmd['index'] == last_dylib_idx:
            new_data += new_cmd

    # Segment 数据
    segment_data_start = lc_start + sizeofcmds
    new_data += data[segment_data_start:]

    return bytes(new_data)


def main():
    ipa_path = sys.argv[1] if len(sys.argv) > 1 else 'build/调色-KM-v3.0.ipa'
    out_path = sys.argv[2] if len(sys.argv) > 2 else ipa_path.replace('.ipa', '-fixed.ipa')

    tmpdir = tempfile.mkdtemp(prefix='ipa_repair_')
    try:
        print(f'Extracting: {ipa_path}')
        with zipfile.ZipFile(ipa_path, 'r') as zf:
            zf.extractall(tmpdir)

        payload = os.path.join(tmpdir, 'Payload')
        apps = [d for d in os.listdir(payload) if d.endswith('.app')]
        if not apps:
            raise ValueError('No .app bundle found')
        app_dir = os.path.join(payload, apps[0])
        print(f'  App: {apps[0]}')

        import plistlib
        info_plist = os.path.join(app_dir, 'Info.plist')
        with open(info_plist, 'rb') as f:
            plist = plistlib.load(f)
        exe_name = plist.get('CFBundleExecutable', '')
        exe_path = os.path.join(app_dir, exe_name)
        print(f'  Binary: {exe_name}')

        # 备份
        backup_path = exe_path + '.corrupted_backup'
        shutil.copy2(exe_path, backup_path)

        # 读取
        with open(exe_path, 'rb') as f:
            corrupted = f.read()

        print(f'\n=== Step 1: Revert (删除旧的错误注入) ===')
        original = revert_patch(corrupted)
        print(f'  Original size: {len(original)} bytes (was {len(corrupted)} bytes)')

        print(f'\n=== Step 2: Re-patch (正确注入) ===')
        fixed = inject_dylib_correct(original, '@executable_path/KMEngine.dylib')
        print(f'  Fixed size: {len(fixed)} bytes')

        # 写回
        with open(exe_path, 'wb') as f:
            f.write(fixed)

        # 验证
        print(f'\n=== Verification ===')
        _, ncmds, sizeofcmds, cmds = parse_macho(fixed)
        print(f'  ncmds={ncmds}, sizeofcmds={sizeofcmds}')

        # 检查 segment bounds
        ok = True
        for cmd in cmds:
            if cmd['cmd'] == LC_SEGMENT_64:
                segname = cmd['segname']
                lc = cmd['raw']
                fileoff = struct.unpack_from(f'<Q', lc, 40)[0]
                filesize = struct.unpack_from(f'<Q', lc, 48)[0]
                if filesize > 0 and fileoff + filesize > len(fixed):
                    print(f'  [CORRUPT] {segname}: fileoff=0x{fileoff:X} + filesize=0x{filesize:X} > {len(fixed)}')
                    ok = False
                elif filesize > 0:
                    print(f'  [OK] {segname}: file 0x{fileoff:X}+0x{filesize:X}')
            elif cmd['cmd'] == LC_LOAD_WEAK_DYLIB:
                print(f'  [OK] WEAK_DYLIB: {cmd.get("dylib_name", "?")}')

        if ok:
            print(f'\n  Binary is VALID!')

        # 重新打包
        print(f'\nRepackaging: {out_path}')
        grandparent = os.path.dirname(os.path.dirname(app_dir))
        with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(grandparent):
                for fn in files:
                    if fn.endswith('.corrupted_backup'):
                        continue
                    full_path = os.path.join(root, fn)
                    arcname = os.path.relpath(full_path, grandparent)
                    zf.write(full_path, arcname)

        # 清理备份
        os.remove(backup_path)

        print(f'\n{"="*60}')
        print(f'Done: {out_path}')
        print(f'{"="*60}')
        print(f'\nNOTE: KMEngine.dylib 尚未编译，IPA 中可以加载但 KM 引擎不生效。')
        print(f'用 GitHub Actions 或 Mac 编译 dylib 后运行:')
        print(f'  python3 make_ipa.py --ipa {out_path} --dylib KMEngine.dylib --out 最终版.ipa')

    finally:
        shutil.rmtree(tmpdir)


if __name__ == '__main__':
    main()
