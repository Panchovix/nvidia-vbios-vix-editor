# Volta (experimental)

Volta GPUs (GV100: Tesla V100 PCIe 16GB/32GB, Tesla V100S PCIe 32GB, Tesla V100 SXM2 16GB/32GB, Tesla V100 FHHL 16GB, and NVIDIA TITAN V) are recognized by the editor **experimentally**.

Edited images carry unsigned modifications and must be loaded through a runtime firmware override method (such as [NVIDIA Linux VBIOS Vix Loader](https://github.com/Panchovix/nvidia-linux-vbios-vix-loader) or [NVIDIA Windows VBIOS Vix Loader](https://github.com/Panchovix/nvidia-windows-vbios-vix-loader)). **Never flash an edited image using standard nvflash.**

## What the editor does

- **Board power ceiling**: `power_max_w` can be inspected and edited on Volta's 30/27/36 power policy table variant.
  - Tesla V100 PCIe (16GB/32GB): stock 250 W ceiling can be raised up to higher wattages (e.g., 300 W to match SXM2 limits under appropriate liquid cooling).
  - Tesla V100 SXM2 (16GB/32GB): stock 300 W ceiling.
  - Tesla V100S PCIe (32GB): stock 250 W ceiling.
  - TITAN V: stock 250 W ceiling.
- **HBM2 target frequency (`hbm2_target_mhz`)**:
  - Exposed in the **Clocks** section of the GUI and CLI (`--set hbm2_target_mhz=1107` or `877`, or via **Import from ROM…**).
  - Edits the P0 HBM2 clock profile in `BIT P+0x00` (Entry 3, Sub-entry 1) between stock Tesla V100 **877 MHz** (900 GB/s) and Tesla V100S **1,107 MHz** (1,134 GB/s).
- **Read-only Memory inspection**:
  - `nvbios memory card.rom`: inspects Volta's HBM2 (Type 0x6) configuration tables, clock bands, and timing sets.
  - Demonstrates that the Tesla V100 32GB PCIe and Tesla V100S 32GB PCIe share byte-identical memory timing tables (`P+08`, SHA256 `8b992d98e4e01f707deac43dcb17b66518b882fd6c7a88486889df3a3d68858b`) and identical Band 3 profiles (800–1,199 MHz).
- **Additive Checksum Repair**:
  - Recalculates and repairs zero-sum additive checksums on all executable images (`0x00` legacy, `0x03` EFI, `0xE0` NPDS data images).
  - Traverses Volta's unique dual `0x70` NPDS tail images (ISBN digest image followed by the terminal certificate image flagged `last`).

## Image Structure and Loader Compatibility

Volta ROM dumps carry a multi-image chain:
1. `0x00`: Legacy x86 BIOS image (starts at 0x0, typically 64 KiB, additive checksum = 0).
2. `0x03`: UEFI / EFI GOP driver image (starts at 0x10000, typically 79.5 KiB, additive checksum = 0).
3. `0xE0`: Primary NPDS table image (starts at 0x24000, 114.5 KiB, additive checksum = 0, contains BIT tokens, power policies, and clock programming tables).
4. `0x70`: ISBN digest image (starts at 0x40a00, 4.5 KiB).
5. `0x70`: Terminal certificate image (starts at 0x41c00, 67.5 KiB, marked `last`).

Total ROM image size is approximately 330.5 KiB (338,432 bytes), well within the 512 KiB buffer boundary read by runtime loaders.

## Hardware Safety & Responsibility

Modifying power limits and clocks beyond factory specifications carries risk of thermal stress or hardware damage. Ensure adequate cooling (such as full-cover waterblocks) before operating at elevated power limits. You use this software entirely at your own risk.
