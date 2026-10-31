# Third-party tools and notices

The MIT license at the repository root covers this project's original code and
icons. It does not relicense third-party tools, platform libraries, SDKs or the
artifacts produced by those projects.

## scrcpy and its portable toolchain

- Project: https://github.com/Genymobile/scrcpy
- Pinned build input: official macOS aarch64 portable release v5.0
- Archive: https://github.com/Genymobile/scrcpy/releases/download/v5.0/scrcpy-macos-aarch64-v5.0.tar.gz
- SHA-256: `7cb4e41c859b05b36e89dc9be6c353cc5980c00d7f7f6a763b5b355551b82e9c`
- scrcpy source license: Apache License 2.0, https://github.com/Genymobile/scrcpy/blob/v5.0/LICENSE

The source repository does not include scrcpy, adb, codec libraries or their
server binaries. The Mac build script retrieves the official portable archive
and copies its scrcpy executables, server and adb into a locally built app.
It also preserves the upstream scrcpy LICENSE in that local app. The portable
toolchain contains components with their own licensing obligations. Consult the
upstream release and each component's notices before redistributing a bundled
Mac binary. No precompiled Mac app is distributed by this source repository.

## Android platform and JDK

The Android app uses Android framework APIs and no external application library.
Android SDK tools and a JDK are build prerequisites and are not included in this
repository or the APK. Obtain them from their official publishers under their
respective terms. The APK contains this project's application code and icon,
with a development signing certificate; its private signing key is not public.

## Apple platform

The Mac app uses system AppKit, SwiftUI, CoreAudio, CoreImage and Vision APIs.
Apple SDKs and system frameworks remain subject to Apple's applicable terms and
are not copied into this repository.
