# 🐋 Leviathan v8 — Multi-Pair Scalping Engine

Bot di scalping crypto su Kraken con gestione multi-pair, trailing stop, stop-loss e controllo completo via Telegram.

## Novità rispetto a v7

| Funzionalità | Descrizione |
|---|---|
| **Multi-pair simultanei** | Una posizione aperta per pair in parallelo (es. BTC/EUR + ETH/EUR contemporaneamente) |
| **Stop-loss automatico** | Ordine limite quando il prezzo scende sotto `entry * (1 - stop_loss_pct)` |
| **Trailing stop** | Segue il prezzo verso l'alto; scatta se scende di `trailing_distance_pct` dal picco. Attivo solo dopo che il prezzo supera il target. |
| **Trailing + SL convivono** | Ogni posizione ha entrambi attivi; vince la prima condizione che si verifica |
| **Telegram esteso** | 10 comandi inclusi /posizioni, /patrimonio, /chiudi, /chiuditutto, /stats, /config |
| **Statistiche dettagliate** | Trade totali, profitto lordo, perdite, netto, media/trade, contatore stop-loss |

## Ciclo di vita di una posizione

```
PENDING  →  ordine BUY aperto (non ancora filled)
   ↓ filled
OPEN     →  BUY eseguito, monitora target / trailing / stop-loss
   ↓ condizione scatta
CLOSING  →  ordine SELL limite aperto
   ↓ filled
[rimossa dal dict positions]
```

## Setup

### Variabili d'ambiente

```
KRAKEN_API_KEY=...
KRAKEN_API_SECRET=...
TELEGRAM_TOKEN=...
TELEGRAM_CHAT_ID=...
REDIS_URL=...          # opzionale, consigliato su Render
```

### Installazione e avvio

```bash
pip install -r requirements.txt
python bot.py
```

## Configurazione (config.yaml)

```yaml
pairs:
  - BTC/EUR
  - ETH/EUR

trading:
  order_size_eur: 5             # EUR per trade
  fee_rate: 0.0016              # Kraken Maker fee (0.16%)
  min_profit_buffer: 0.002      # 0.2% sopra break-even come target fisso
  entry_discount: 0.002         # sconto entry rispetto al last price
  order_ttl_seconds: 120        # TTL ordine BUY non filled
  stop_loss_pct: 0.01           # chiudi se prezzo scende dell'1% sotto entry
  trailing_enabled: true        # attiva trailing stop
  trailing_distance_pct: 0.003  # trailing scatta se prezzo scende 0.3% dal picco

runtime:
  sleep_seconds: 20
```

### Note sui parametri

- **`stop_loss_pct: 0.01`** con `order_size_eur: 5` → perdita max ~0.05€ per trade
- **`trailing_distance_pct`**: più è piccolo, più è aggressivo (cattura profitti prima). Valori consigliati: 0.002–0.005
- Il trailing stop scatta **solo se il prezzo ha già superato il target** — non brucia posizioni in profitto basso
- Per aggiungere più pair basta aggiungere voci sotto `pairs:` (es. `- XRP/EUR`)

## Comandi Telegram

| Comando | Descrizione |
|---|---|
| `/status` | Stato bot, posizioni aperte, statistiche |
| `/posizioni` | Lista dettagliata posizioni con entry, target, stop, P&L non realizzato |
| `/patrimonio` | EUR liberi + valore crypto in EUR + equity totale |
| `/chiudi BTC/EUR` | Chiude forzatamente una posizione specifica |
| `/chiuditutto` | Chiude tutte le posizioni aperte |
| `/stats` | Trade totali, profitto lordo, perdite, netto, media/trade, stop-loss |
| `/config` | Parametri attivi di config.yaml |
| `/pause` | Mette in pausa (non cancella ordini aperti) |
| `/resume` | Riprende l'operatività |
| `/help` | Lista comandi |

## Render deployment

1. Crea un **Background Worker** su Render
2. Aggiungi le env vars
3. (Consigliato) Aggiungi il Redis add-on → copia `REDIS_URL`
4. Start command: `python bot.py`

> **Avvertenza**: il trading automatico comporta rischi di perdita del capitale. Testa sempre con `order_size_eur: 5` o meno prima di aumentare gli importi.
