# Architecture (draft)

    user dump -> loader -> CPU layer -> OS services -> GPU layer (Metal)
                                  \                        /
                                   ----- iOS app shell ----

- loader/: container and section parsing.
- cpu/: ARM11 execution (interpreter or AOT recompiler), decided in Phase 2.
- os/: reimplementation of 3DS system services.
- gpu/: PICA200 command decoding, shader translation, Metal backend.
- tools/: build scripts (IPA generation). Not yet written.
- tests/: loader and CPU tests using only synthetic data.

Nothing in this tree is implemented yet. Directories are placeholders.
