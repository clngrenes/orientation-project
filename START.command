#!/bin/bash
# ORIENTATION — Start Server
# Doppelklick auf diese Datei startet alles automatisch

cd "$(dirname "$0")"

# Alte Prozesse stoppen
pkill -f "node server.js" 2>/dev/null
pkill -f "ssh.*localhost.run" 2>/dev/null
sleep 1

# Server starten
node server.js > /tmp/orientation-server.log 2>&1 &

# Tunnel starten via Cloudflare (kein Login, kein Passwort, kein Blockieren)
cloudflared tunnel --url http://localhost:3000 > /tmp/cf-tunnel.log 2>&1 &

# Warte auf URL
echo "Starte ORIENTATION..."
for i in {1..20}; do
  URL=$(grep -o "https://[a-z0-9-]*\.trycloudflare\.com" /tmp/cf-tunnel.log 2>/dev/null | head -1)
  if [ -n "$URL" ]; then break; fi
  sleep 1
done

if [ -z "$URL" ]; then
  echo "Tunnel fehlgeschlagen. Prüfe /tmp/cf-tunnel.log"
  read -p "Enter zum Schließen..."; exit 1
fi

clear
echo ""
echo "  ██████╗ ██████╗ ██╗███████╗███╗   ██╗████████╗ █████╗ ████████╗██╗ ██████╗ ███╗   ██╗"
echo "  ██╔══██╗██╔══██╗██║██╔════╝████╗  ██║╚══██╔══╝██╔══██╗╚══██╔══╝██║██╔═══██╗████╗  ██║"
echo "  ██║  ██║██████╔╝██║█████╗  ██╔██╗ ██║   ██║   ███████║   ██║   ██║██║   ██║██╔██╗ ██║"
echo "  ██║  ██║██╔══██╗██║██╔══╝  ██║╚██╗██║   ██║   ██╔══██║   ██║   ██║██║   ██║██║╚██╗██║"
echo "  ██████╔╝██║  ██║██║███████╗██║ ╚████║   ██║   ██║  ██║   ██║   ██║╚██████╔╝██║ ╚████║"
echo "  ╚═════╝ ╚═╝  ╚═╝╚═╝╚══════╝╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝   ╚═╝   ╚═╝ ╚═════╝ ╚═╝  ╚═══╝"
echo ""
echo "  ========================================================================"
echo "  LINKS — diese sind immer gleich!"
echo "  ========================================================================"
echo ""
echo "  Laptop Dashboard : $URL/dashboard"
echo ""
echo "  iPhone VORNE     : $URL/front"
echo "  iPhone HINTEN    : $URL/back"
echo ""
echo "  ========================================================================"
echo "  Dieses Fenster offen lassen! Zum Beenden: Ctrl+C"
echo "  ========================================================================"
echo ""

# Dashboard im Browser öffnen
open "$URL/dashboard"

trap "pkill -f 'node server.js'; pkill -f cloudflared; echo 'Gestoppt.'; exit" INT
tail -f /tmp/orientation-server.log
