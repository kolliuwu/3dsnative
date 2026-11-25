# Plan

Phases are ordered by risk. Each phase has an exit criterion; do not start the next one until it is met.

## Phase 0 - Research
- Document the ROM/container formats to accept (CCI/.3ds, CIA, ExeFS, RomFS).
- Survey existing open-source 3DS work (Citra/Azahar, Panda3DS, others) for reusable pieces and license compatibility.
- Exit: a short written decision on which components are reused vs. written from scratch.

## Phase 1 - Loader
- Parse the container, extract ExeFS and RomFS, read the ExHeader.
- Exit: a tool that lists sections and the file tree for a known dump.

## Phase 2 - CPU
- Decide between interpreting ARM11 (ARMv6) and recompiling it to ARM64 ahead of time.
- Recompilation is the nxnative-style path and needs an analysis step per binary.
- Exit: a homebrew or test ROM executes its first function on the device.

## Phase 3 - OS services
- Implement the minimum 3DS services needed to boot: filesystem, HID, display, audio, config.
- Exit: a title reaches its first screen.

## Phase 4 - GPU
- Translate PICA200 command streams and shaders to Metal.
- This is the largest risk. Prototype one simple scene before any game-specific work.
- Exit: a textured triangle renders at a playable frame rate on one device.

## Phase 5 - iOS shell and packaging
- App bundle, input mapping, save storage, IPA generation script.
- Exit: a sideloadable IPA built from a user-supplied dump.

## Phase 6 - Per-game profiles
- Per-title fixes keyed by product code / build ID.

## Open questions
- Which parts can legally be shared as source, and which must stay out of the repo?
- Realistic device floor (memory and texture constraints).
- Whether to build on existing emulator code, and under which license.
