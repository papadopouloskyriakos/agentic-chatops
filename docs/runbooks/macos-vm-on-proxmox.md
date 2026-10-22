# macOS VM on Proxmox (nlmacos01 recipe)

Built 2026-09-27 for **nlmacos01** (VMID VMID_REDACTED, macOS Tahoe 26.7) on **nlpve04** (AMD EPYC 9334,
no GPU). YouTrack IFRNLLEI01PRD-2896 · infra MR !608 · memory `nlmacos01_hackintosh_build_inflight_20260927`.
Apple's licence permits macOS only on Apple hardware — this is a lab decision by the operator.

## What works (copy this, do not re-derive)

| Item | Value |
|---|---|
| OpenCore | **KVM-Opencore v21** EFI (`OpenCoreEFIFolder-v21.zip`, OpenCore REL-100), config as shipped + `boot-args keepsyms=1 -v`, `Misc.Boot.Timeout` 10 |
| SMBIOS | **MacPro7,1** (Tahoe dropped iMacPro1,1/iMac19,1 — Recovery only offers Tahoe for a supported model) |
| `args:` | `-device isa-applesmc,osk="<OSK from OSX-KVM OpenCore-Boot.sh>" -smbios type=2 -device qemu-xhci -device usb-kbd -device usb-tablet -global nec-usb-xhci.msi=off -global ICH9-LPC.acpi-pci-hotplug-with-bridge-support=off -cpu Haswell-noTSX,vendor=GenuineIntel,+invtsc,+hypervisor,kvm=on,vmware-cpuid-freq=on` |
| PVE conf | q35, OVMF `efidisk0 …,efitype=4m,pre-enrolled-keys=0` (Secure Boot OFF), `vga: vmware`, `virtio0 …,cache=unsafe,discard=on`, `net0: vmxnet3,bridge=vmbr0,tag=10`, `balloon: 0`, no `cpu:` line (the `-cpu` in args must be last) |
| Recovery image | `fetch-macOS-v2.py --action download --os-type latest --board-id Mac-CFF7D910A743CAAF` (Apple product 140-93589 = 26.x). ⚠ `--shortname tahoe` fetched the `default` product (082-33203 = Sequoia 15.4.1) |
| Host prereqs | `options kvm ignore_msrs=1` (already on pve04), `zfs_arc_max` low enough that a balloon-0 guest fits (**8 GiB on pve04**) |

## Build steps (all from nl-claude01 → root on the PVE host)

1. **Media on the host** (`/root/macos-build`): `apt install dmg2img unzip`; fetch `BaseSystem.dmg` (see table) and verify it by hashing the chunks with the script's `verify_chunklist()` (its own `verify_image()` fails headless on a terminal ioctl); `dmg2img -s BaseSystem.dmg BaseSystem.img`; unzip the KVM-Opencore EFI, edit `EFI/OC/config.plist` with `plistlib` (SMBIOS, Timeout, boot-args), write it into a 384 MB OpenCore image (`qemu-img convert -O raw` OSX-KVM's `OpenCore.qcow2`, `losetup -fP`, mount `p1`, replace `EFI/`).
2. **VM**: `qm create <vmid> …` per the table, `qm importdisk` the OpenCore raw and `BaseSystem.img`, attach as `ide0`/`ide2` with `cache=unsafe`, `--boot order=ide0`, set `--args`.
3. **RAM gate**: `free -g` on the host with ARC counted separately; the guest WILL touch all of its RAM (macOS caches aggressively) and ARC does not shrink fast enough to prevent an OOM kill.
4. **Install**: start, pick *macOS Base System* in the picker (Timeout 0 in the v21 config = waits for Enter; `qm sendkey <vmid> right`/`ret` from the host), Disk Utility → erase the virtio disk APFS `Macintosh HD` → Reinstall macOS → the picker shows *macOS Installer* while installing and *Macintosh HD* when done. Console screendumps: `pvesh create /nodes/<host>/qemu/<vmid>/monitor --command "screendump /root/x.ppm"` (convert PPM→PNG locally to read it).
5. **Standalone boot**: clean shutdown, mount the macOS disk's ESP (`/dev/zvol/rpool/data/vm-<vmid>-disk-1-part1`) and the OpenCore image's `part1`, `cp -r EFI` across, set `Misc.Boot.Timeout` 10, `qm set --delete ide0 --delete ide2`, `--boot order=virtio0`. Keep the OpenCore disk as an `unused` rescue boot disk; delete the installer disks.
6. **Register**: FreeIPA A+PTR (`scripts/ipa.sh dnsrecord-add … --a-create-reverse`), NetBox VM/interface/IP (REST), append the VMID to the host's node-pinned vzdump job (`pvesh set /cluster/backup/<job> --vmid "<old list>,<vmid>"`), commit the conf byte-identical to `pve/<host>/qemu/<vmid>.conf` (the deploy job skips; ⚠ it is blind to merge commits anyway).

## Traps (each cost real time on 2026-09-27)

- ⛔ **AMD_Vanilla kernel patches**: under KVM the guest sees an Intel CPU; the patches hang XNU at `EXITBS:START`. Never add them.
- ⛔ OSX-KVM's shipped `OpenCore.qcow2`/`EFI/` are out of sync with its `config.plist` (kexts referenced but absent) and its picker (ScanPolicy 0) lists its own ESP as "EFI" first — a timeout boots OpenCore into itself ("Already started", black screen). Use KVM-Opencore v21.
- ⛔ **Host OOM**: 16 GiB balloon-0 guest + 16 GiB ARC on a 125 GiB host with 214 GiB committed = the guest is killed mid-install while ARC still holds 14.7 GiB. Cap ARC first.
- ⛔ **Screen Sharing / Remote Management kills WindowServer** on this GPU-less VM (SIGABRT loop in `CompositorSW → CA::OGL push_surface`). GUI only via the Proxmox noVNC console; headless SSH is fine. Set `pmset -a displaysleep 0 sleep 0 disksleep 0` (a slept display = black framebuffer). Also: Setup Assistant may hang on the "Update Mac Automatically" pane — `qm reset` is safe once the account exists.
- Apple ID: skip on a generated serial (iMessage activation can lock the ID); sign in inside Xcode only.
- Recovery offers the newest macOS *for the SMBIOS model*, not for the image: iMacPro1,1 → "Reinstall Sequoia" even from a Tahoe-capable image.
- A rejected long `ssh host 'a; b; c'` tool call has usually already run part-way (see `feedback_rejected_tool_calls_may_have_already_run`).

## Intel-only realities for a dev/CI guest (found by the meshsat-ios session, 2026-09-27)

- ⛔ **Homebrew refuses to install on Intel macOS 26** ("only supported on Apple Silicon processors"). Use the
  upstream universal/x86_64 binaries instead (swiftlint, xcodegen, `gitlab-runner-darwin-amd64` → `/usr/local/bin`)
  and build Ruby with ruby-build once a compiler exists.
- ⛔ The `Xcode_26.4.xip` most Macs download is the **arm64-only "Xcode for Apple silicon"** build (2.3 GB,
  `LSRequiresNativeExecution`, "Bad CPU type in executable" on the VM). An Intel guest needs **"Xcode 26.4 (17E192)
  Universal"** (~4 GB) from developer.apple.com/download/all — an Apple ID download the operator does themselves;
  `xcodes` only lists the Apple-silicon variant. Command Line Tools for Intel may still come via `softwareupdate`.
- gitlab-runner registered as `meshsat-macos-vm` (id 16, project 71, tags `macos,macos-vm`, shell executor,
  concurrent 1) and left PAUSED until the benchmark proves the simulator path (MESHSAT-1332 / MESHSAT-1370).

## Access

`ssh -i ~/.ssh/one_key operator@10.0.181.X`; sudo = the operator's login password (never stored). Console: Proxmox noVNC on nlpve04. Rollback: `qm stop && qm destroy <vmid> --purge`, `scripts/ipa.sh dnsrecord-del`, delete the NetBox VM.
