# 360-imma-gan-hard

## HUSH EMULATOR launcher (PCSX2 engine)
Custom frontend that runs games through the installed [PCSX2](https://pcsx2.net) engine (GPLv3, not bundled).
Install PCSX2 and supply your own BIOS dump and game backups, then run: `python -m launcher.app`

## iPhone build: HUSH EMULATOR v5.0.0 (Play! core)
`ios/hush-emulator.patch` turns the iOS app of [Play!](https://github.com/jpd002/Play-) (BSD-2) into HUSH EMULATOR 5.0.0:
- carbon/neon theme, new icon, launch screen and placeholder art, new bundle id `com.hush.emulator`
- adaptive rounded poster grid with live search, A-Z / Recent / Favorites scopes (long-press a cover to favorite)
- vector-drawn DualShock-style pad with an ergonomic layout (d-pad/face diamond at the edges, inset sticks, pill shoulders, L3/SELECT/START/R3 row)
- themed Settings screen with a Small/Medium/Large pad-size selector

On a Mac with Xcode:
1. `git clone --recursive https://github.com/jpd002/Play-.git && cd Play- && git apply <this repo>/ios/hush-emulator.patch`
2. Follow Play!'s iOS build steps (`installer_ios/`, CMake `-G Xcode -DCMAKE_TOOLCHAIN_FILE=deps/Dependencies/cmake-ios/ios.cmake`).
3. Download the `HushEmulator-5.0.0.ipa` artifact from the Actions run and sign/install it with ESign (the IPA is unsigned; ESign signs it with your certificate). JIT is still required for speed.

### JIT with StikDebug
Install [StikDebug](https://github.com/StikDebug/StikDebug) with its pairing file and LocalDevVPN running. Tapping a game without JIT then offers **Enable with StikDebug**: Hush Emulator opens `stikdebug://enable-jit?bundle-id=...&pid=...`, waits for the debugger to attach, and starts the game. Requirements: sign the IPA in ESign with a **development** certificate (the app needs `get-task-allow`), and use iOS 17.4+. On iOS 26 devices with TXM, StikDebug's JIT needs an app-side breakpoint protocol that Play!'s JIT doesn't implement, so JIT may not work there.

The Play! core emulates the BIOS (HLE), so no BIOS file is required to run games. Play!'s BSD-2 license is saved as `ios/Play-LICENSE.txt`; ship it with any copy you distribute.

Icon: `ios/icon/make_icon.py` generates the Hush Emulator icon (`hush-icon-1024.png` plus the 180px `icon@2x.png` baked into the patch). Re-run it with Pillow to tweak the design.
