#!/usr/bin/env python3
"""
Mach-O dylib 注入工具 — 向 arm64 二进制添加 LC_LOAD_DYLIB 命令

原理:
  1. 解析 Mach-O header + load commands
  2. 在最后一个 LC_LOAD_DYLIB 后面插入新的 dylib 引用
  3. 将所有受影响段的 fileoff 下调
  4. 更新 ncmds / sizeofcmds
  5. 写出新 binary

注意: 本工具不处理代码签名 (TrollStore 不需要签名)
"""

import struct
import sys
import os
import shutil

# ============================================================
# Mach-O 常量
# ============================================================
MH_MAGIC_64 = 0xFEEDFACF
MH_CIGAM_64 = 0xCFFAEDFE

LC_SEGMENT_64        = 0x19
LC_SYMTAB            = 0x02
LC_DYSYMTAB          = 0x0B
LC_LOAD_DYLIB        = 0x0C
LC_ID_DYLIB          = 0x0D
LC_LOAD_WEAK_DYLIB   = 0x18 | 0x80000000
LC_REEXPORT_DYLIB    = 0x1F | 0x80000000
LC_DYLD_INFO_ONLY    = 0x22 | 0x80000000
LC_FUNCTION_STARTS   = 0x26
LC_DATA_IN_CODE      = 0x29
LC_CODE_SIGNATURE    = 0x1D
LC_UUID              = 0x1B
LC_VERSION_MIN_IPHONEOS = 0x25
LC_SOURCE_VERSION    = 0x2A
LC_BUILD_VERSION     = 0x32


# ============================================================
# Mach-O 结构解析
# ============================================================

def read_macho(data: bytes):
    """解析 Mach-O 64-bit"""
    magic = struct.unpack_from('<I', data, 0)[0]

    if magic == MH_MAGIC_64:
        endian = '<'
    elif magic == MH_CIGAM_64:
        endian = '>'
    else:
        raise ValueError(f"不是 64-bit Mach-O (magic=0x{magic:08X})。可能是 fat binary。")

    # 头部 32 字节
    cputype, cpusubtype, filetype, ncmds, sizeofcmds, flags, reserved = \
        struct.unpack_from(f'{endian}IIIIIII', data, 4)

    print(f"  CPU: 0x{cputype:08X}  FileType: {filetype}  ncmds: {ncmds}  sizeofcmds: {sizeofcmds}")

    if cputype != 0x0100000C:  # CPU_TYPE_ARM64
        print(f"  [WARN]  不是 arm64! CPU type = 0x{cputype:08X}")

    # 解析 load commands
    lc_start = 32  # sizeof mach_header_64
    offset = lc_start
    commands = []

    for i in range(ncmds):
        cmd, cmdsize = struct.unpack_from(f'{endian}II', data, offset)

        cmd_data = data[offset:offset + cmdsize]
        cmd_info = {
            'index': i,
            'cmd': cmd,
            'cmdsize': cmdsize,
            'offset': offset,
            'data': cmd_data,
        }

        # 解析已知的 command 字段
        if cmd == LC_SEGMENT_64:
            segname = cmd_data[8:24].rstrip(b'\x00').decode('ascii', errors='replace')
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from(
                f'{endian}QQQQ', cmd_data, 24)
            cmd_info['segname'] = segname
            cmd_info['fileoff'] = fileoff
            cmd_info['filesize'] = filesize
            cmd_info['vmaddr'] = vmaddr

        elif cmd in (LC_LOAD_DYLIB, LC_LOAD_WEAK_DYLIB, LC_REEXPORT_DYLIB):
            name_offset = struct.unpack_from(f'{endian}I', cmd_data, 8)[0]
            name = cmd_data[name_offset:].split(b'\x00')[0].decode('ascii', errors='replace')
            cmd_info['dylib_name'] = name

        elif cmd == LC_SYMTAB:
            symoff, nsyms, stroff, strsize = struct.unpack_from(f'{endian}IIII', cmd_data, 8)
            cmd_info['symoff'] = symoff
            cmd_info['stroff'] = stroff

        elif cmd == LC_DYSYMTAB:
            cmd_info['has_offsets'] = True  # 有很多 offset 字段

        elif cmd == LC_DYLD_INFO_ONLY:
            cmd_info['has_offsets'] = True

        elif cmd == LC_FUNCTION_STARTS:
            dataoff = struct.unpack_from(f'{endian}I', cmd_data, 8)[0]
            cmd_info['dataoff'] = dataoff

        elif cmd == LC_DATA_IN_CODE:
            dataoff = struct.unpack_from(f'{endian}I', cmd_data, 8)[0]
            cmd_info['dataoff'] = dataoff

        elif cmd == LC_CODE_SIGNATURE:
            dataoff = struct.unpack_from(f'{endian}I', cmd_data, 8)[0]
            cmd_info['dataoff'] = dataoff

        commands.append(cmd_info)
        offset += cmdsize

    return endian, ncmds, sizeofcmds, commands, lc_start


def patch_offsets(cmd_info: dict, shift_amount: int, endian: str):
    """
    将 load command 中的所有文件偏移字段 += shift_amount
    返回修改后的 cmd_data
    """
    cmd = cmd_info['cmd']
    data = bytearray(cmd_info['data'])

    if cmd == LC_SEGMENT_64:
        # fileoff 在 offset 40 (不是 32! 32 是 vmsize)
        fileoff = struct.unpack_from(f'{endian}Q', data, 40)[0]
        filesize = struct.unpack_from(f'{endian}Q', data, 48)[0]
        # fileoff=0 的 segment (__TEXT) 包含 header+LCs，不需要偏移
        # 只偏移那些文件数据在 LC 区域之后的 segment
        if fileoff > 0 and filesize > 0:
            struct.pack_into(f'{endian}Q', data, 40, fileoff + shift_amount)

        # 修正 section 内部的 offset 和 reloff
        nsects = struct.unpack_from(f'{endian}I', data, 64)[0]
        for s in range(nsects):
            sec_off = 72 + s * 80
            # section.offset (uint32 at sec_off+48)
            sec_offset = struct.unpack_from(f'{endian}I', data, sec_off + 48)[0]
            if sec_offset > 0:
                struct.pack_into(f'{endian}I', data, sec_off + 48, sec_offset + shift_amount)
            # section.reloff (uint32 at sec_off+56)
            reloff = struct.unpack_from(f'{endian}I', data, sec_off + 56)[0]
            if reloff > 0:
                struct.pack_into(f'{endian}I', data, sec_off + 56, reloff + shift_amount)

    elif cmd == LC_SYMTAB:
        for field_off in [8, 16]:  # symoff at 8, stroff at 16
            val = struct.unpack_from(f'{endian}I', data, field_off)[0]
            if val > 0:
                struct.pack_into(f'{endian}I', data, field_off, val + shift_amount)

    elif cmd == LC_DYSYMTAB:
        # 这个 command 全是 file offsets (uint32_t, 从 offset 8 开始, 最多 10 个)
        # 每个都是偏移量
        for field_off in range(8, len(data), 4):
            if field_off + 4 <= len(data):
                val = struct.unpack_from(f'{endian}I', data, field_off)[0]
                if val > 0 and val < 10_000_000:  # 合理的文件偏移范围
                    struct.pack_into(f'{endian}I', data, field_off, val + shift_amount)

    elif cmd in (LC_DYLD_INFO_ONLY,):
        for field_off in [8, 12, 16, 20, 24]:  # rebase_off, bind_off, weak_bind_off, lazy_bind_off, export_off
            if field_off + 4 <= len(data):
                val = struct.unpack_from(f'{endian}I', data, field_off)[0]
                if val > 0:
                    struct.pack_into(f'{endian}I', data, field_off, val + shift_amount)

    elif cmd in (LC_FUNCTION_STARTS, LC_DATA_IN_CODE, LC_CODE_SIGNATURE):
        val = struct.unpack_from(f'{endian}I', data, 8)[0]
        if val > 0:
            struct.pack_into(f'{endian}I', data, 8, val + shift_amount)

    return bytes(data)


def inject_dylib(data: bytes, dylib_path: str) -> bytes:
    """
    向 Mach-O 注入 LC_LOAD_DYLIB 命令
    """
    endian, ncmds, sizeofcmds, commands, lc_start = read_macho(data)

    # ---- 找到插入位置: 最后一个 LC_LOAD_DYLIB 之后 ----
    last_dylib_idx = -1
    for i, cmd in enumerate(commands):
        if cmd['cmd'] == LC_LOAD_DYLIB:
            last_dylib_idx = i

    if last_dylib_idx < 0:
        raise ValueError("找不到 LC_LOAD_DYLIB — 无法确定插入位置")

    insert_after = commands[last_dylib_idx]
    insert_offset = insert_after['offset'] + insert_after['cmdsize']

    print(f"  在 LC_LOAD_DYLIB #{last_dylib_idx} 之后插入 (offset=0x{insert_offset:X})")

    # ---- 构建新的 LC_LOAD_DYLIB command ----
    path_bytes = dylib_path.encode('ascii') + b'\x00'
    # 对齐到 8 字节
    padding_needed = (8 - (len(path_bytes) % 8)) % 8
    path_bytes += b'\x00' * padding_needed

    # dylib_command 结构:
    #   cmd: uint32 = LC_LOAD_DYLIB
    #   cmdsize: uint32 = 24 + len(path_bytes)
    #   dylib.name_offset: uint32 = 24 (相对于 command 开始)
    #   dylib.timestamp: uint32 = 2
    #   dylib.current_version: uint32 = 0x10000
    #   dylib.compatibility_version: uint32 = 0x10000
    cmdsize = 24 + len(path_bytes)

    new_cmd = struct.pack(
        f'{endian}IIIIII',
        LC_LOAD_WEAK_DYLIB,       # cmd — 弱链接: 找不到 dylib 也不会 crash
        cmdsize,                 # cmdsize
        24,                      # name_offset (always 24 for dylib_command)
        2,                       # timestamp
        0x00010000,              # current_version (1.0.0)
        0x00010000,              # compatibility_version (1.0.0)
    ) + path_bytes

    print(f"  新 dylib: {dylib_path} (cmd size={cmdsize})")

    # ---- 构建新 binary ----
    shift_amount = cmdsize

    # 新 header
    new_ncmds = ncmds + 1
    new_sizeofcmds = sizeofcmds + shift_amount

    # 计算旧 header (32B) + old sizeofcmds 之后的偏移（即 segment 数据开始处）
    segment_data_start = lc_start + sizeofcmds

    new_data = bytearray()
    # 新 header
    header = bytearray(data[:32])
    struct.pack_into(f'{endian}I', header, 16, new_ncmds)
    struct.pack_into(f'{endian}I', header, 20, new_sizeofcmds)
    new_data += header

    # Load commands (保持原样 + 修补偏移 + 插入新 command)
    for i, cmd in enumerate(commands):
        new_cmd_data = patch_offsets(cmd, shift_amount, endian)
        new_data += new_cmd_data

        # 在最后一个 dylib 之后插入新 command
        if i == last_dylib_idx:
            new_data += new_cmd

    # Segment 数据 (直接复制，不修改)
    new_data += data[segment_data_start:]

    print(f"  旧大小: {len(data)} bytes → 新大小: {len(new_data)} bytes")
    print(f"  [OK] 注入完成")
    return bytes(new_data)


# ============================================================
# CLI
# ============================================================

def main():
    if len(sys.argv) < 3:
        print("用法: python3 patch_macho.py <macho_file> <dylib_path>")
        print("示例: python3 patch_macho.py Tiaose '@executable_path/KMEngine.dylib'")
        sys.exit(1)

    macho_file = sys.argv[1]
    dylib_path = sys.argv[2]

    # 备份
    backup = macho_file + ".backup"
    shutil.copy2(macho_file, backup)
    print(f"[backup] 已备份: {backup}")

    # 读取
    with open(macho_file, 'rb') as f:
        data = f.read()

    print(f"[parse] 解析 {macho_file} ({len(data)} bytes)")

    # 注入
    new_data = inject_dylib(data, dylib_path)

    # 写回
    with open(macho_file, 'wb') as f:
        f.write(new_data)

    print(f"[done] 完成! {macho_file} 已修改")


if __name__ == '__main__':
    main()
