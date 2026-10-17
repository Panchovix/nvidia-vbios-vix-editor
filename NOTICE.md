# Notice

NVIDIA VBIOS Vix Editor. Copyright (C) 2026 panchovix.

This program is free software: you can redistribute it and/or modify it under the
terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later version.
It is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
PURPOSE. The full license text is in `LICENSE`.

## NVIDIA format references

No NVIDIA source file is included. These NVIDIA publications were used only as
references for data layouts:

- Field locations for the recognized power, rail and VFE tables follow the
  NVIDIA-authored nvgpu `bios.h` structure definitions (MIT)
  (`https://github.com/OE4T/linux-nvgpu/blob/patches-rel-36/drivers/gpu/nvgpu/include/nvgpu/bios.h`),
  as cited in `src/nvidia_vbios/rom/tables.py`.
- The BIT pointer and token structure follows NVIDIA's BIOS Information Table
  specification
  (`https://nvidia.github.io/open-gpu-doc/BIOS-Information-Table/BIOS-Information-Table.html`).
- The PCI device to architecture table in `src/nvidia_vbios/families.py` lists IDs and
  product names from the supported GPU table of NVIDIA's open GPU kernel modules
  (`https://github.com/NVIDIA/open-gpu-kernel-modules/blob/615.71.09/README.md`). Its
  `EDITOR_ONLY` entry (10de:2501) comes from the PCI ID Repository (pci.ids).

NVIDIA and GeForce are trademarks of NVIDIA Corporation. This project is not
affiliated with or endorsed by NVIDIA.

## Acknowledgements

Thanks to @pantsoftime (overclock.net), whose original GB202 VBIOS editor and
`vbios_override` work this project builds on.

## What is not included

This repository contains no ROM, firmware, driver, kernel module or installer. The
tests generate small synthetic images.
