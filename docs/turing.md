# Turing (experimental, not tested on Turing hardware)

English | [Español](turing_es.md)

Turing GPUs (TU102, TU104, TU106, TU116 and TU117: GeForce RTX 20 and GTX 16 series, TITAN RTX, Quadro RTX
and the T series) are recognized by the editor and by both loaders, **experimentally**. No Turing card has
run an edited image yet: nothing below is tested on hardware. If you own one, the test at the end tells us
whether it works.

## What the editor does

- **Board power only**: `power_max_w` (ceiling), `power_default_w` (boot default) and `power_min_w` (floor),
  all marked experimental. Voltage, clock and fan tables use other layouts on Turing and are not decoded: they
  have no field.
- The power table decodes like the Ampere one on the 22 Turing images examined (desktop, laptop, Max-Q,
  Quadro and TITAN, TU102 to TU117). The edit is written to both banks of the image, and the checksum of the
  touched image is repaired. Bounds follow the Ampere rules; they are not hardware-safe limits.
- Turing images carry a **signed list of digests that covers the power table**. The editor cannot update
  it, and whether the driver checks it is unknown. That is the main reason an edit may not apply.
- Saving an edited Turing copy also saves two loader files next to it:
  - `<name>-loader.bin`: the first bank of the copy, unchanged. Load this one first.
  - `<name>-loader-e0end.bin`: the same bank, ending at its last data image. The small image after it, which
    holds the digest list, is dropped, and the last data image gets the last-image flags that Ampere and Ada
    images carry there. From the command line:
    `nvbios normalize edited.rom payload.bin --representation turing-e0-end-v1`.

  Both send 250-355 KB from the legacy image to the GSP firmware, well below the 512 KiB it reads (found by
  static analysis of `gsp_tu10x.bin` 615.78.08, not on hardware). The files are larger, 364-500 KB, because
  they keep the bank prefix before the legacy image (about 162 KiB on most boards), which is not sent. A file
  whose second bank is erased keeps flash bytes after its image chain and would send more than 512 KiB; the
  editor then saves only `<name>-loader-e0end.bin` and says why.

**An override that the driver rejects falls back to the stock VBIOS.** Nothing is written to the card. On
Linux the kernel log says `rejected override at ... using stock VBIOS` when the loader refuses it. When the
GSP firmware refuses the image itself it is expected to fall back silently (static analysis, not tested on
Turing), so check the power limits as well.

## Tester guide

Use a loader release whose README lists Turing; earlier releases refuse Turing GPUs. On Linux, re-run the
setup so the module is rebuilt with the Turing chips.

1. **Before anything**, save the stock power limits: `nvidia-smi -q -d POWER > before.txt`, and save your
   card's ROM (for example `nvflash --save original.rom`, or GPU-Z on Windows).
2. **Unmodified image**: export it without changes, `nvbios normalize original.rom original-loader.bin`, and
   load `original-loader.bin`. Reboot (Linux) or restart the GPU (Windows). The card should work as before,
   and on Linux `journalctl -k -b | grep vbios_override` should show `selected: ... staged for GSP`. This
   shows that the loader takes the file and the card still starts with it, not that GSP uses it: the
   unmodified file holds the same bytes as the card's own VBIOS, so on Windows **Verify** reports a match
   either way. On Windows, also load the unmodified e0-end file
   (`nvbios normalize original.rom original-e0end.bin --representation turing-e0-end-v1`), restart the GPU
   and click **Verify**: that file differs from the card's own VBIOS (two flag bytes, no type-0x70 image), so
   `override-active` means the driver runs it and `override-not-active` means it does not.
3. **Power-limit edit**, the first real test: in the editor, change one power value by a visible amount
   (lowering the floor, `power_min_w`, is the least risky; for example 125 W to 100 W), save the copy, load
   `<name>-loader.bin` and reboot. Run `nvidia-smi -q -d POWER`: does Min (or Max, or Default) Power Limit
   show the new value?
4. **If it does not change**, load `<name>-loader-e0end.bin` (same edit) instead, reboot and check again.
5. To go back, remove the override with the loader (Linux: **Remove override** or `nvbios system disable`;
   Windows: **Remove override**).

**If the card does not start** (no image, `nvidia-smi` fails): on Linux, choose your **normal** entry in the
boot menu, which loads no override, and remove the override from there (see
[If something goes wrong](https://github.com/Panchovix/nvidia-linux-vbios-vix-loader#if-something-goes-wrong));
on Windows, start in Safe Mode and click **Remove override** (see
[If the GPU does not start](https://github.com/Panchovix/nvidia-windows-vbios-vix-loader#if-the-gpu-does-not-start)).
Report that too.

**What to report** (an issue in the editor repository): the GPU model and PCI ID (Linux:
`lspci -nn | grep -i nvidia`; Windows: the loader's GPU list), the VBIOS version
(`nvidia-smi -q | grep -i "VBIOS Version"`), the driver version and the OS; which file you loaded at each step
and the edit; `nvidia-smi -q -d POWER` before and after each step. On Linux also the `vbios_override` line of
the kernel log; on Windows the result of the loader's **Verify**.
