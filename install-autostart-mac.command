#!/bin/bash
# Starts the news tracker quietly every time you log in to your Mac.
DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST="$HOME/Library/LaunchAgents/vn.renews.tracker.plist"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>vn.renews.tracker</string>
<key>ProgramArguments</key><array><string>$(command -v python3)</string><string>$DIR/tracker.py</string><string>background</string></array>
<key>WorkingDirectory</key><string>$DIR</string>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
</dict></plist>
PL
launchctl unload "$PLIST" 2>/dev/null; launchctl load "$PLIST"
echo "Done. The tracker starts at login and is running now: http://localhost:8765"
echo "To undo: launchctl unload $PLIST && rm $PLIST"
