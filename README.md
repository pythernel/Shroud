# 🔻 Shroud

![Version](https://img.shields.io/badge/version-1.0.0-red)
![Platform](https://img.shields.io/badge/platform-Windows-blue)
![Language](https://img.shields.io/badge/language-C%20%7C%20ASM-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)
![Status](https://img.shields.io/badge/status-stable-brightgreen)

> **Windows PE crypter with section encryption, polymorphic loader stub, and anti-analysis features.**

---

## Features

- **Section Encryption** — Encrypts `.text` and `.rdata` sections with AES-256-CBC; decrypted at runtime by the loader stub
- **Polymorphic Loader Stub** — Each build produces a functionally identical but bytewise-unique stub; signature-based detection is无效
- **Anti-Analysis** — Sandbox detection, debugger detection (`NtGlobalFlag`, `IsDebuggerPresent`, `PEB.BeingDebugged`), and hardware breakpoint checks
- **Import Table Reconstruction** — Original IAT is rebuilt in-memory after decryption; no residual import hints left on disk
- **Entry-Point Obfuscation** — Original OEP is hidden behind a junk-ridden trampoline; real entry is resolved via a scrambled jump table
- **Overlay Preservation** — Any data appended to the original PE (config, resources) is carried through the encryption process
- **Minimal Size Overhead** — Average overhead of ~8 KB over the original PE

---

## How It Works

```
┌──────────────┐     ┌───────────────┐     ┌────────────────┐
│  Original PE  │────▶│  Shroud Pack  │────▶│  Crypted PE    │
│  (plaintext)  │     │               │     │  (encrypted)   │
└──────────────┘     └───────────────┘     └────────────────┘
                           │
                     ┌─────▼─────┐
                     │  Loader   │
                     │  Stub     │
                     │ (appended)│
                     └───────────┘
```

1. **Pre-scan** — The original PE is parsed; sections, imports, relocations, and TLS callbacks are mapped
2. **Encryption** — Target sections are encrypted with AES-256-CBC using a per-build random key and IV
3. **Stub Generation** — A polymorphic loader stub is assembled; junk instructions, variable register allocation, and garbage control-flow blocks are inserted
4. **Stitching** — The stub is prepended as the new entry point; the encrypted PE body is appended as a custom overlay section
5. **Execution** — At runtime the stub:
   - Performs anti-analysis checks (sandbox, debugger, breakpoints)
   - Decrypts the PE sections in-place
   - Rebuilds the IAT via `LdrLoadDll` / `GetProcAddress` resolution
   - Applies relocations if the preferred base address is unavailable
   - Transfers control to the original OEP

---

## Usage

```batch
Shroud.exe -i payload.exe -o shrouded.exe
```

### Options

| Flag           | Description                                    | Default          |
|----------------|------------------------------------------------|------------------|
| `-i, --input`  | Path to the input PE file                      | *required*       |
| `-o, --output` | Path for the output crypted PE                 | `<input>_crypted`|
| `-k, --key`    | AES key file (32 bytes); auto-generated if omitted | random        |
| `--no-anti`    | Disable anti-analysis checks in the loader     | enabled          |
| `--iterations` | PBKDF2 iterations for key derivation           | 10000            |
| `-v, --verbose`| Verbose output                                 | off              |

### Examples

**Encrypt with default settings:**
```batch
Shroud.exe -i beacon.exe -o beacon_shrouded.exe
```

**Encrypt with a user-supplied key:**
```batch
Shroud.exe -i beacon.exe -o beacon_shrouded.exe -k mykey.bin
```

**Encrypt without anti-analysis checks:**
```batch
Shroud.exe -i beacon.exe --no-anti
```

---

## Requirements

- **OS:** Windows 7 / Server 2008 R2 or later (x64)
- **Compiler:** MSVC 2019+ or MinGW-w64 (GCC 10+)
- **Dependencies:** None (statically linked; Win32 API only)
- **Build tools:** CMake ≥ 3.15, NASM (for polymorphic stub assembly)

### Build

```batch
mkdir build && cd build
cmake .. -G "Visual Studio 17 2022"
cmake --build . --config Release
```

---

## Output Format

A crypted PE produced by Shroud has the following structure:

| Offset            | Content                              |
|-------------------|--------------------------------------|
| 0x0000            | DOS header (MZ)                      |
| 0x0040            | PE header + sections (shim)          |
| ...               | Loader stub section (`.shrd0`)       |
| ...               | Original PE headers & imports (encrypted) |
| ...               | Original `.text` (encrypted)         |
| ...               | Original `.rdata` (encrypted)        |
| ...               | Overlay (encrypted original overlay) |

The entry point points into `.shrd0` where the polymorphic loader begins execution.

---

## Advanced Usage

### Custom Stub Template

Place a custom assembly template at `templates/stub.asm` and rebuild:

```batch
Shroud.exe -i payload.exe --stub templates/my_stub.asm
```

### Stub Patching

Use `--patch-config` to inject runtime configuration values into the stub:

```batch
Shroud.exe -i payload.exe --patch-config config.json
```

---

## Notes & Disclaimer

- **For authorized testing only.** Shroud is designed for red-team engagements, penetration tests, and malware-analysis research on systems you own or have explicit written permission to test.
- The author is not responsible for any misuse of this tool.
- Windows Defender and other AV products may flag the output heuristically; use in isolated lab environments for development and testing.
- Shroud does **not** modify the original PE's functionality — it only protects it from static analysis and complicates dynamic analysis for all but the most determined reverser.
