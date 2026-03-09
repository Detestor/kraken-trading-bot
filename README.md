# KrakenBotVPS v2
Questa versione aggiunge:
- `/status`
- `/lasttrades`
- `runtime/state.json`
- `runtime/trades.csv`
- rilevamento posizione corretto con free/total + open orders
- fix sui falsi "posizione chiusa"

## Render
Compatibile con Render Background Worker.
Dopo l'update fai:
1. commit su GitHub
2. Render -> Manual Deploy -> Deploy latest commit

## Telegram
Comandi:
- `/status`
- `/lasttrades`
- `/ping`
- `/help`
