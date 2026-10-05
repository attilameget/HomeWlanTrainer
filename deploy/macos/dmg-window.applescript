-- Finder layout for the steadyGrind drag-and-drop disk image.
-- Icon positions match deploy/macos/dmg-background.png (680×560).
on run argv
	set diskName to item 1 of argv
	set mountDir to item 2 of argv
	set appName to item 3 of argv
	set appsName to item 4 of argv
	set readmeName to item 5 of argv

	set theXOrigin to 200
	set theYOrigin to 120
	set theWidth to 680
	set theHeight to 560

	tell application "Finder"
		tell disk (diskName as string)
			open
			set theBottomRightX to (theXOrigin + theWidth)
			set theBottomRightY to (theYOrigin + theHeight)
			set dsStore to quoted form of (mountDir & "/.DS_Store")

			tell container window
				set current view to icon view
				set toolbar visible to false
				set statusbar visible to false
				set the bounds to {theXOrigin, theYOrigin, theBottomRightX, theBottomRightY}
				-- Park hidden files (.background, .DS_Store) off the visible window.
				set position of every item to {theBottomRightX + 100, 100}
			end tell

			set opts to the icon view options of container window
			tell opts
				set icon size to 128
				set text size to 13
				set arrangement to not arranged
			end tell
			set background picture of opts to file ".background:background.png"

			set position of item appName to {170, 180}
			set position of item appsName to {510, 180}
			set position of item readmeName to {340, 445}
			try
				set extension hidden of item appName to true
			end try

			close
			open
			delay 1

			tell container window
				set statusbar visible to false
				set the bounds to {theXOrigin, theYOrigin, theBottomRightX - 10, theBottomRightY - 10}
			end tell
		end tell

		delay 1

		tell disk (diskName as string)
			tell container window
				set statusbar visible to false
				set the bounds to {theXOrigin, theYOrigin, theBottomRightX, theBottomRightY}
			end tell
		end tell

		delay 3

		set waitTime to 0
		repeat
			delay 1
			set waitTime to waitTime + 1
			if (do shell script "[ -f " & dsStore & " ]; echo $?") = "0" then exit repeat
			if waitTime > 20 then error "Timed out waiting for .DS_Store"
		end repeat
	end tell
end run
