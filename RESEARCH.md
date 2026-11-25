# Phase 0 - Research notes

Status: first pass. Items marked (verify) need a check against the source repo before we rely on them.

## Existing projects

### Azahar
- Open-source 3DS emulator, a continuation of Citra (after Citra was taken down). Repo: github.com/azahar-emu/azahar.
- Desktop (Windows, macOS, Linux) and Android. Not an iOS app.
- Licence: sources disagree. Packagers list GPL-2.0-only or GPLv2+ (with ISCL for some parts), while a third-party directory says GPL-3.0. (verify against the LICENSE file in the repo before reusing any code.)
- Implication: any code we copy from Azahar brings GPL obligations into this repo. A GPL-compatible licence for this project would be needed, and that is a decision to make before Phase 2.

### Folium
- Paid, App Store, iPhone and iPad only. Described by third-party sources as the first commercial 3DS emulator on iOS.
- Confirms there is demand for 3DS on iOS, and that a native-feeling option exists, though it is a closed product.

### RetroArch / libretro core
- An Azahar libretro core exists and is packaged for desktop. A third-party listing says RetroArch can run it on iOS and tvOS. (verify: availability and status on iOS, and whether it is sideloadable.)
- This is the most practical 3DS-on-iPhone option today, and it is not a native port.

### Other
- Panda3DS (open-source 3DS emulator, reported as stronger on iOS-style targets). Not checked yet. (verify: licence, iOS support.)
- Citra (original). Taken down; forks are the maintained line.

## What this means for the plan
1. Do not copy code from Azahar into this repo until the licence question is settled. Reading it for design ideas is fine. Document any design reuse in this file.
2. The iOS 3DS space already has an emulator (Folium) and a RetroArch core. Our project's value is the native-execution approach, not a new emulator, so the README should say so clearly.
3. The hardest item remains the PICA200 GPU to Metal translation (Phase 4). Before Phase 2, look at how Azahar's GPU backend is structured, as a reference only.

## Open items for Phase 0
- Confirm the Azahar licence from the LICENSE file.
- Check Panda3DS licence and iOS status.
- Confirm the RetroArch iOS path (sideloading, status).
- Decide the project licence (GPL-compatible if any Azahar code is reused).
