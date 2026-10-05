steadyGrind — quick start
=========================

Install
-------
1. Drag "steadyGrind" into Applications (or Desktop).
2. Eject this disk image.

First launch (Gatekeeper)
-------------------------
The app is not notarized with Apple. On first open:

  • Right-click (or Control-click) "steadyGrind"
  • Choose Open
  • Confirm Open in the dialog

Later launches can use a normal double-click.

Use
---
1. Double-click steadyGrind — a menu-bar item (● SG) appears and the
   steadyGrind window opens (no browser toolbar). Open at Login is enabled
   by default and does not open that window until you choose Open UI.
2. Allow Local Network access if macOS asks (needed to find the KICKR).
   Allow Bluetooth if you connect a heart-rate strap (Garmin HRM-Pro or similar).
3. Mac and KICKR must be on the same Wi‑Fi.
4. Settings → Garmin Connect → log in to fetch today's bike workout.
5. Optional: Plan → paste an Anthropic API key for Claude plan sketches
   (console.anthropic.com). Leave empty to use the on-host rules planner.
6. Menu bar: Open UI · Copy phone URL · Open at Login · Quit.
   Quit stops the server for this session (Open at Login still applies next login).

Logs
----
~/Library/Logs/steadyGrind/server.log

Support
-------
Built from the HomeWlanTrainer / kickr-pi project (v__VERSION__).
