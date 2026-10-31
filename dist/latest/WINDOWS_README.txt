steadyGrind for Windows 11
==========================

Version: 1.3.6

What this is
------------
steadyGrind runs Garmin Connect workouts on a Wahoo KICKR v6 over Wi-Fi.
This folder is a portable Windows build: no installer required.

Install
-------
1. Unzip steadyGrind-1.3.6-windows.zip somewhere permanent
   (for example C:\Users\<you>\Apps\steadyGrind).
2. Double-click steadyGrind.exe.
3. A tray icon (green circle) appears. The steadyGrind window opens
   (Edge WebView2). If WebView2 is missing, your default browser opens
   http://127.0.0.1:8080 instead.
4. Open at Login is on by default for packaged builds (Startup folder).
   Toggle it from the tray menu.
5. Same Wi-Fi as the KICKR. Allow the firewall prompt so a phone can
   open http://<pc-name>:8080 or the LAN IP shown under Copy phone URL.
6. Allow Bluetooth to connect a heart-rate strap (Settings → Heart rate).

Tray menu
---------
- Open UI
- Copy phone URL
- Open at Login
- Quit

Logs
----
%LOCALAPPDATA%\steadyGrind\Logs\server.log
(or the platformdirs user log folder for steadyGrind)

Emulator (desk development)
---------------------------
Settings → Trainer mode → Emulator (dev) → Apply mode.
Or set KICKR_TRAINER_MODE=simulated before launching.

Requirements
------------
- Windows 11 (x64)
- Microsoft Edge WebView2 Runtime (usually already installed)
- Same LAN as the KICKR for Real KICKR mode

