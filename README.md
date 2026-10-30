# 360-imma-gan-hard

## VOID//DECK launcher (PCSX2 engine)
Custom frontend that runs games through the installed [PCSX2](https://pcsx2.net) engine (GPLv3, not bundled).
Install PCSX2 and supply your own BIOS dump and game backups, then run: `python -m launcher.app`

## iPhone build: VOID DECK v3.2.1 (Play! core)
`ios/void-deck-restyle.patch` turns the iOS app of [Play!](https://github.com/jpd002/Play-) (BSD-2) into VOID DECK 3.2.1:
- carbon/neon theme, new icon, launch screen and placeholder art, new bundle id `com.voiddeck.app`
- adaptive rounded poster grid with live search, A-Z / Recent / Favorites scopes (long-press a cover to favorite)
- vector-drawn DualShock-style pad with an ergonomic layout (d-pad/face diamond at the edges, inset sticks, pill shoulders, L3/SELECT/START/R3 row)
- themed Settings screen with a Small/Medium/Large pad-size selector

On a Mac with Xcode:
1. `git clone --recursive https://github.com/jpd002/Play-.git && cd Play- && git apply <this repo>/ios/void-deck-restyle.patch`
2. Follow Play!'s iOS build steps (`installer_ios/`, CMake `-G Xcode -DCMAKE_TOOLCHAIN_FILE=deps/Dependencies/cmake-ios/ios.cmake`).
3. Sideload (AltStore/SideStore); iOS blocks JIT otherwise.

The Play! core emulates the BIOS (HLE), so no BIOS file is required to run games. Play!'s BSD-2 license is saved as `ios/Play-LICENSE.txt`; ship it with any copy you distribute.
