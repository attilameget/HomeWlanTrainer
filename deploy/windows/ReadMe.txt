steadyGrind for Windows 11
==========================

Version: __VERSION__

What this is
------------
steadyGrind runs Garmin Connect workouts on a Wahoo KICKR v6 over Wi-Fi.
This folder is a portable Windows build: no installer required.

Install
-------
1. Unzip steadyGrind-__VERSION__-windows.zip somewhere permanent
   (for example C:\Users\<you>\Apps\steadyGrind).
   Keep the whole steadyGrind folder — steadyGrind.exe needs the
   _internal folder beside it. Do not run the exe from inside the zip.
2. Double-click Start steadyGrind.cmd (or steadyGrind.exe).
3. A tray icon (green circle) appears — on Windows 11 check the ^ chevron
   in the notification area if you do not see it. The steadyGrind window
   opens (Edge WebView2). If WebView2 is missing, your default browser
   opens http://127.0.0.1:8080 instead.
4. Open at Login is on by default for packaged builds (Startup folder).
   Toggle it from the tray menu.
5. Same Wi-Fi as the KICKR. Allow the firewall prompt so a phone can
   open http://<pc-name>:8080 or the LAN IP shown under Copy phone URL.
6. Allow Bluetooth to connect a heart-rate strap (Settings → Heart rate).

If nothing appears
------------------
1. Run Debug steadyGrind.cmd (keeps a console open and prints the exit code).
2. Open http://127.0.0.1:8080 in a browser — if the page loads, the server
   is up and only the tray/window failed; look in the ^ tray overflow.
3. Task Manager → details: is steadyGrind.exe listed?
4. Read the logs below. A failed start also shows a MessageBox after this build.

Tray menu
---------
- Open UI
- Reload
- Copy phone URL
- Open at Login
- Quit

Logs
----
%LOCALAPPDATA%\steadyGrind\Logs\agent.log   (tray agent / startup)
%LOCALAPPDATA%\steadyGrind\Logs\server.log  (workout engine)
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
