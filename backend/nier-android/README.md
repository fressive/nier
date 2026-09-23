# Android backend support

The default Nier runtime does not install or start a phone-side network
server. It communicates through ADB directly. Rooted touch injection is kept
in the standalone `backend/nier-uinput` executable, which the host invokes in
persistent stdin/stdout session mode.

This module remains available for optional Android/JNI experiments and is not
needed for the default ADB backend. Build it with an Android SDK and Gradle if
you need the JNI uinput library:

```bash
./gradlew :app:assembleDebug
```

For the default flow, build and push the standalone helper instead:

```bash
cmake -S backend/nier-uinput -B /tmp/nier-uinput-android \
  -DCMAKE_TOOLCHAIN_FILE="$ANDROID_NDK/build/cmake/android.toolchain.cmake" \
  -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-26 -DBUILD_TESTING=OFF
cmake --build /tmp/nier-uinput-android --config Release
adb push /tmp/nier-uinput-android/nier-uinput /data/local/tmp/nier-uinput
adb shell su -M -c 'chmod 755 /data/local/tmp/nier-uinput'
```

The optional `WebViewDebugController` is a cooperative non-root integration
for an application that owns the WebView. Call
`WebViewDebugController.enable()` before constructing the first WebView. It
does not inject into arbitrary applications; root-mode injection is provided by
the separate `backend/nier-frida` component.

The module also packages the optional `NierInputMethodService`. Set
`input_text.mode: ime` in the host configuration after installing the APK. The
host sends text through the UID-checked `NierInputCommandProvider` using
`adb shell content call`; it does not require root or a phone-side network
server. Set `input_text.auto_enable: true` only when the session is allowed to
switch the current input method, and leave `restore_previous: true` to return
to the previous IME on close.
