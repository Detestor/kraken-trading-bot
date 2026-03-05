# KrakenBotVPS
Bot Kraken SPOT BTC/EUR con regime detector + stop reale + TP software + Telegram.

## VPS (Ubuntu/Debian) — quick start
1) Copia il progetto sul server (es. /root/KrakenBotVPS)
2) `cd /root/KrakenBotVPS`
3) `bash deploy/install_vps.sh`
4) `sudo nano /opt/krakenbot/.env` (copia da .env.example e inserisci chiavi)
5) `sudo systemctl start krakenbot`
6) Log: `journalctl -u krakenbot -f`

## Tools
- `python tools/check_kraken.py`
- `python tools/close_btc_now.py`

## AI management (feature v0)
Al momento l'AI è solo “commentatore”: spiega contesto e segnali su Telegram.
È OFF di default: `AI_MODE=off`.
