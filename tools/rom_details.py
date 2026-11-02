#!/usr/bin/env python3
"""Generate a ROM Details Markdown file matching TechPowerUp / VBIOS database specification type style.

Extracts:
  - File metadata, size, MD5/SHA1/SHA256 hashes
  - VBIOS version, UEFI support, BIOS build date
  - BIOS Internals (GPU device ID, SKU string, Copyright, Board name, power limits, memory support)
  - Graphics Card Info (Manufacturer, Model, Device ID, Subsystem ID, Interface, Memory Size & Type)
"""
import argparse
import datetime
import hashlib
import os
from pathlib import Path
import re
import sys

# Ensure library can be imported from parent directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from nvidia_vbios.rom import load, inspect_image
from nvidia_vbios.rom.memory import memory_report


def extract_subsystem_id(data):
    """Extract Subsystem Vendor & Device ID from NVGI header (offset 0x0c) or NPDE header."""
    if data[:4] == b'NVGI' and len(data) >= 0x10:
        sub_ven = data[0x0c:0x0e][::-1].hex().upper()
        sub_dev = data[0x0e:0x10][::-1].hex().upper()
        return f"{sub_ven} {sub_dev}"
    
    npde_idx = data.find(b'NPDE')
    if npde_idx != -1 and npde_idx + 0x14 <= len(data):
        sub_ven = data[npde_idx + 0x10:npde_idx + 0x12][::-1].hex().upper()
        sub_dev = data[npde_idx + 0x12:npde_idx + 0x14][::-1].hex().upper()
        return f"{sub_ven} {sub_dev}"
    return None


def extract_build_date(legacy_bytes):
    """Extract BIOS build date from standard PC BIOS option ROM offset +0x38 or nearby header."""
    # Standard PC BIOS date location at +0x38: MM/DD/YY
    date_m = re.search(rb'\d{2}/\d{2}/\d{2}', legacy_bytes[:0x200])
    if date_m:
        raw = date_m.group().decode('latin1')
        try:
            dt = datetime.datetime.strptime(raw, '%m/%d/%y')
            return dt.strftime('%Y-%m-%d 00:00:00')
        except ValueError:
            return raw
    return "Unknown"


def extract_header_strings(legacy_bytes):
    """Extract model/SKU, copyright, and board string from legacy image."""
    sku_m = re.search(rb'(?:G[A-Z0-9]+|AD[0-9]+|TU[0-9]+|GB[0-9]+)\s+PG[^\x00\r\n]+', legacy_bytes)
    sku_str = sku_m.group().decode('latin1', 'ignore').strip() if sku_m else ''

    cp_m = re.search(rb'Copyright \(C\) [^\x00\r\n]+', legacy_bytes)
    cp_str = cp_m.group().decode('latin1', 'ignore').strip() if cp_m else ''

    bd_m = re.search(rb'(?:G[A-Z0-9]+|AD[0-9]+|TU[0-9]+|GB[0-9]+)\s+Board', legacy_bytes)
    bd_str = bd_m.group().decode('latin1', 'ignore').strip() if bd_m else ''

    return sku_str, cp_str, bd_str


def generate_rom_markdown(rom_path):
    """Parse a .rom file and return a structured markdown string matching TechPowerUp style."""
    rom_path = Path(rom_path).resolve()
    with open(rom_path, 'rb') as f:
        data = f.read()

    img = load(rom_path)
    info = inspect_image(img)
    mem = memory_report(img)

    filename = rom_path.name
    size_kb = f"{round(len(data) / 1024)} KB"
    md5 = hashlib.md5(data).hexdigest()
    sha1 = hashlib.sha1(data).hexdigest()

    version = info.get('versions', ['Unknown'])[0]
    pci_images = info.get('pci_images', [])
    has_uefi = any(p.get('type') == 3 for p in pci_images)

    # Legacy image slice for strings
    legacy_start = pci_images[0]['start'] if pci_images else 0
    legacy_end = pci_images[0]['end'] if pci_images else min(len(data), 65536)
    legacy_bytes = data[legacy_start:legacy_end]

    build_date = extract_build_date(legacy_bytes)
    sku_str, copyright_str, board_str = extract_header_strings(legacy_bytes)

    # Device & Subsystem IDs
    pci_dev_raw = info.get('pci_device', '').upper().replace(':', ' ')
    pci_parts = pci_dev_raw.split()
    gpu_device_id_str = f"0x{pci_parts[0]} 0x{pci_parts[1]}" if len(pci_parts) == 2 else pci_dev_raw
    device_id_str = f"{pci_parts[0]} {pci_parts[1]}" if len(pci_parts) == 2 else pci_dev_raw
    subsystem_str = extract_subsystem_id(data) or "Unknown"

    # Board power limit calculation
    field_map = {f['key']: f for f in info.get('fields', [])}
    p_def = field_map.get('power_default_w', {}).get('current')
    p_max = field_map.get('power_max_w', {}).get('current')
    p_min = field_map.get('power_min_w', {}).get('current')

    power_lines = []
    if p_def is not None:
        power_lines.append(f" * Target: {p_def:.1f} W")
        if p_max is not None:
            power_lines.append(f" * Limit: {p_max:.1f} W")
        if p_min is not None and p_max is not None and p_def > 0:
            adj_min = round(((p_min - p_def) / p_def) * 100)
            adj_max = round(((p_max - p_def) / p_def) * 100)
            power_lines.append(f" * Adj. Range: {adj_min:+d}%, {adj_max:+d}%")

    # Memory support
    configs = mem.get('configurations', {}).get('items', [])
    mem_support = sorted({
        (c.get('type') or 'Unknown', (c.get('vendor') or 'Unknown').replace('SK hynix', 'Hynix'))
        for c in configs if c.get('vendor')
    })

    product_name = info.get('architecture', {}).get('product', 'Unknown')
    # Short model name
    short_model = (product_name.replace('NVIDIA ', '')
                               .replace('-PCIE', '')
                               .replace('-SXM2', '')
                               .replace('-32GB', '')
                               .replace('-16GB', '')
                               .replace('100S', '100s')
                               .strip())

    # Detect memory size and type
    mem_size = ''
    for token, sz in [('32GB', '32768 MB'), ('32768', '32768 MB'),
                      ('16GB', '16384 MB'), ('16384', '16384 MB'),
                      ('24GB', '24576 MB'), ('12GB', '12288 MB'),
                      ('8GB', '8192 MB'), ('6GB', '6144 MB')]:
        if token in product_name:
            mem_size = sz
            break

    mem_type = mem_support[0][0] if mem_support else 'Unknown'

    # Clocks if available
    clocks_lines = []
    gpc_boost = field_map.get('factory_rated_boost_mhz', {}).get('current')
    hbm2_target = field_map.get('hbm2_target_mhz', {}).get('current')
    if gpc_boost:
        clocks_lines.append(f"Boost Clock:\t*{gpc_boost} MHz*")
    if hbm2_target:
        clocks_lines.append(f"Memory Clock:\t*{hbm2_target} MHz*")

    # Assemble Document
    doc = [
        f"# VGA BIOS {product_name} BIOS",
        "",
        "**VBIOS Info**",
        f"Filename:\t{filename}",
        f"VBIOS Version:\t**{version}**",
        f"UEFI Supported:\t{'Yes' if has_uefi else 'No'}",
        f"BIOS Build date:\t{build_date}",
        f"VBIOS Size:\t{size_kb}",
        f"MD5 Hash:\t{md5}",
        f"SHA1 Hash:\t{sha1}",
        "",
        "**BIOS Internals**",
        f"GPU Device Id: **{gpu_device_id_str}**",
    ]

    if sku_str:
        doc.append(sku_str)
    if copyright_str:
        doc.append(copyright_str)
    if board_str:
        doc.append(board_str)
    if power_lines:
        doc.append("Board power limit")
        doc.extend(power_lines)
    if mem_support:
        doc.append("Memory Support")
        for t, v in mem_support:
            doc.append(f" * {t}, {v}")

    doc.extend([
        "",
        "**Graphics Card Info**",
        "Manufacturer:\t*NVIDIA*",
        f"Model:\t*{short_model}*",
        f"Device Id:\t*{device_id_str}*",
        f"Subsystem Id:\t*{subsystem_str}*",
        "Interface:\t*PCI-E*",
    ])

    if mem_size:
        doc.append(f"Memory Size:\t*{mem_size}*")
    doc.extend(clocks_lines)
    if mem_type:
        doc.append(f"Memory Type:\t*{mem_type}*")

    doc.extend([
        "",
        "",
        f'ROM File: "{rom_path}"',
        ""
    ])

    return "\n".join(doc)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("rom", help="Path to NVIDIA VBIOS .rom file")
    parser.add_argument("-o", "--output", help="Optional output markdown path (default: <rom>.md or stdout)")
    parser.add_argument("--stdout", action="store_true", help="Print to stdout even if -o is specified")
    args = parser.parse_args()

    md = generate_rom_markdown(args.rom)

    if args.output:
        out_path = Path(args.output)
        out_path.write_text(md, encoding="utf-8")
        print(f"Wrote details to: {out_path}")
    elif not args.stdout and not sys.stdout.isatty():
        sys.stdout.write(md)
    else:
        out_path = Path(str(args.rom) + ".md")
        out_path.write_text(md, encoding="utf-8")
        print(f"Generated: {out_path}")


if __name__ == "__main__":
    main()

