#!/usr/bin/env python3
"""
Shroud — Windows PE Crypter
Encrypts PE sections and appends a polymorphic loader stub.
"""
import struct
import os
import sys
import random
import hashlib
from datetime import datetime

IMAGE_DOS_SIGNATURE = 0x5A4D
IMAGE_NT_SIGNATURE = 0x00004550

STUB_TEMPLATE = '''; Shroud Loader Stub
; Generated: {timestamp}
; Target: {target}

    .486
    .model flat, stdcall
    option casemap:none

include windows.inc
include kernel32.inc
include user32.inc

includelib kernel32.lib
includelib user32.lib

.data
    msg db "Shroud Loader v1.0", 0
    msg2 db "Loaded: {hash}", 0

.code
start:
    invoke GetModuleHandle, NULL
    invoke LoadLibrary, addr msg
    invoke MessageBox, NULL, addr msg2, addr msg, MB_OK
    invoke ExitProcess, 0
end start
'''


class ShroudCrypto:
    def __init__(self):
        self.key = os.urandom(32)
        self.iv = os.urandom(16)

    def xor_encrypt(self, data: bytes) -> bytes:
        result = bytearray()
        for i, b in enumerate(data):
            result.append(b ^ self.key[i % len(self.key)])
        return bytes(result)

    def mask_data(self, data: bytes) -> bytes:
        key = random.randint(0, 255)
        result = bytearray([key])
        for b in data:
            result.append(b ^ key)
            key = (key + 1) & 0xFF
        return bytes(result)


class PEHeaders:
    def __init__(self, data: bytes):
        self.data = data
        self.dos = {}
        self.nt = {}
        self.file_hdr = {}
        self.opt_hdr = {}
        self.sections = []
        self._parse()

    def _r16(self, off):
        return struct.unpack("<H", self.data[off:off + 2])[0]

    def _r32(self, off):
        return struct.unpack("<I", self.data[off:off + 4])[0]

    def _parse(self):
        if self._r16(0) != IMAGE_DOS_SIGNATURE:
            raise ValueError("Invalid DOS header")
        self.dos["e_magic"] = self._r16(0)
        nt_off = self._r32(0x3C)
        self.nt["offset"] = nt_off
        if self._r32(nt_off) != IMAGE_NT_SIGNATURE:
            raise ValueError("Invalid NT headers")
        fo = nt_off + 4
        self.file_hdr["machine"] = self._r16(fo)
        self.file_hdr["num_sections"] = self._r16(fo + 2)
        self.file_hdr["size_opt_hdr"] = self._r16(fo + 16)
        oo = fo + 20
        magic = self._r16(oo)
        self.opt_hdr["magic"] = "PE32" if magic == 0x10B else "PE32+" if magic == 0x20B else f"0x{magic:04X}"
        self.opt_hdr["entry"] = self._r32(oo + 16)
        self.opt_hdr["image_base"] = self._r32(oo + 28) if magic == 0x10B else struct.unpack("<Q", self.data[oo + 24:oo + 32])[0]
        self.opt_hdr["section_align"] = self._r32(oo + 32) if magic == 0x10B else self._r32(oo + 32)
        self.opt_hdr["size_image"] = self._r32(oo + 56) if magic == 0x10B else self._r32(oo + 56)
        data_dir_count = self._r32(oo + 92) if magic == 0x10B else self._r32(oo + 108)
        sec_off = oo + (96 if magic == 0x10B else 112)
        sec_off = (oo + self.file_hdr["size_opt_hdr"])

        for i in range(self.file_hdr["num_sections"]):
            soff = sec_off + i * 40
            if soff + 40 > len(self.data):
                break
            name = self.data[soff:soff + 8].rstrip(b"\\x00").decode("ascii", errors="replace")
            self.sections.append({
                "name": name,
                "vaddr": self._r32(soff + 12),
                "vsize": self._r32(soff + 8),
                "raw_addr": self._r32(soff + 20),
                "raw_size": self._r32(soff + 16),
                "char": self._r32(soff + 36),
            })


class Shroud:
    def __init__(self, input_path: str, output_path: str = None):
        self.input = input_path
        self.output = output_path or input_path.replace(".exe", "_shrouded.exe")
        self.crypto = ShroudCrypto()

    def process(self):
        if not os.path.exists(self.input):
            raise FileNotFoundError(f"Input not found: {self.input}")

        with open(self.input, "rb") as f:
            data = bytearray(f.read())

        try:
            pe = PEHeaders(bytes(data))
        except ValueError as e:
            raise ValueError(f"Invalid PE: {e}")

        target_hash = hashlib.sha256(data).hexdigest()[:16]

        code_sections = [s for s in pe.sections if s["char"] & 0x20]
        encrypted_count = 0

        for sec in code_sections:
            if sec["raw_addr"] == 0 or sec["raw_size"] == 0:
                continue
            start = sec["raw_addr"]
            end = start + min(sec["raw_size"], sec["vsize"])
            if end > len(data):
                end = len(data)

            section_data = bytes(data[start:end])
            if section_data:
                enc = self.crypto.xor_encrypt(section_data)
                data[start:start + len(enc)] = enc
                encrypted_count += 1

        stub = STUB_TEMPLATE.format(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            target=os.path.basename(self.input),
            hash=target_hash
        )

        loader_stub = self.crypto.mask_data(stub.encode())

        shrouded_section = struct.pack("<II", 0xDEAD, 0xBEEF)
        shrouded_section += struct.pack("<I", len(loader_stub))
        shrouded_section += loader_stub
        ibase = pe.opt_hdr.get("image_base", 0x400000)
        if ibase > 0xFFFFFFFF:
            ibase = 0x400000
        shrouded_section += ibase.to_bytes(4, "little")
        entry = pe.opt_hdr.get("entry", 0)
        shrouded_section += entry.to_bytes(4, "little")
        shrouded_section += self.crypto.key

        marker = b"SHROUD1.0"
        data.extend(marker)
        data.extend(shrouded_section)

        with open(self.output, "wb") as f:
            f.write(data)

        entry = pe.opt_hdr.get("entry", 0)
        ibase = pe.opt_hdr.get("image_base", 0x400000)
        info = {
            "input": self.input,
            "output": self.output,
            "input_size": len(data) - len(shrouded_section) - len(marker) - 8,
            "output_size": len(data),
            "sections_total": len(pe.sections),
            "sections_encrypted": encrypted_count,
            "entry_point": hex(entry),
            "image_base": hex(ibase),
            "target_hash": target_hash,
            "loader_size": len(loader_stub),
            "key_hex": self.crypto.key.hex()[:16] + "...",
        }
        return info


def format_report(info: dict) -> str:
    lines = []
    lines.append("=" * 60)
    lines.append(f"  Shroud — PE Crypter")
    lines.append("=" * 60)
    lines.append(f"  Input:      {info['input']}")
    lines.append(f"  Output:     {info['output']}")
    lines.append(f"  Size:       {info['input_size']:,} -> {info['output_size']:,} bytes")
    lines.append(f"  Sections:   {info['sections_encrypted']}/{info['sections_total']} encrypted")
    lines.append(f"  Entry:      {info['entry_point']}")
    lines.append(f"  ImageBase:  {info['image_base']}")
    lines.append(f"  Hash:       {info['target_hash']}")
    lines.append(f"  Loader:     {info['loader_size']} bytes")
    lines.append(f"  Key:        {info['key_hex']}")
    lines.append("=" * 60)
    return "\n".join(lines)


def main():
    import argparse
    p = argparse.ArgumentParser(description="Shroud PE Crypter")
    p.add_argument("input", help="Path to PE file")
    p.add_argument("-o", "--output", help="Output path")
    p.add_argument("-v", "--verbose", action="store_true", help="Show details")
    args = p.parse_args()

    if not os.path.exists(args.input):
        print(f"[-] File not found: {args.input}")
        sys.exit(1)

    s = Shroud(args.input, args.output)
    try:
        info = s.process()
        print(format_report(info))
        print(f"[+] Output written to: {info['output']}")
    except Exception as e:
        print(f"[-] Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
