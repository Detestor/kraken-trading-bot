# 🐋 Leviathan v7 — Anti-Bleed Scalping Engine

Bot di scalping crypto su Kraken con controllo del rischio integrato.

## Novità rispetto a v6.1

| Fix | Descrizione |
|-----|-------------|
| **#1 Order tracking** | Ogni BUY salva `order_id`. Il bot verifica lo stato ad ogni ciclo. Ordini non filled entro `order_ttl_seconds` vengono cancellati automaticamente. |
| **#2 Sell con target_price** | Il sell limit usa sempre `target_price` (calcolato al momento del buy), non il prezzo spot. Garantisce il margine minimo anche in mercati veloci. |
| **#3 Stato persistente** | Redis se `REDIS_URL` è impostato (Render Redis add-on), fallback su file locale. Lo stato sopravvive ai restart. |
| **#4 Batch ticker** | Una sola chiamata `fetch_tickers()` per tutti i pair, invece di N chiamate separate. Meno rate limiting, ciclo più veloce. |
| **#5 Statistiche** | Contatore `trades_total` e `profit_total` (EUR netto) visibili con `/status`. |

## Setup

### 1. Variabili d'ambiente

```
KRAKEN_API_KEY=...
KRAKEN_API_SECRET=...
TELEGRAM_TOKEN=...
TELEGRAM_CHAT_ID=...
REDIS_URL=...          # opzionale, ma consigliato su Render
```

### 2. Installazione

```bash
pip install -r requirements.txt
```

### 3. Avvio

```bash
python bot.py
```

## Configurazione (config.yaml)

```yaml
pairs:
  - BTC/EUR
  - ETH/EUR

trading:
  order_size_eur: 5        # EUR per trade
  fee_rate: 0.0016         # Kraken Maker fee (0.16%)
  min_profit_buffer: 0.002 # 0.2% sopra il break-even
  spread_multiplier: 1.0   # 1.0 = minimo garantito, >1 = più margine ma fill più lento
  entry_discount: 0.002    # sconto entry rispetto al last price (0.2%)
  order_ttl_seconds: 120   # TTL ordine BUY non filled

runtime:
  sleep_seconds: 20
```

### Parametri chiave

- **`order_ttl_seconds`**: se un ordine BUY non viene eseguito entro questo tempo, viene cancellato e il capitale è libero per un nuovo trade. Default 120s.
- **`spread_multiplier`**: con `1.0` vendi esattamente al break-even + buffer. Con `1.2` aggiungi un 20% di margine extra sul buffer, ma i fill diventano più rari.
- **`entry_discount`**: quanto sotto il prezzo corrente piazzi il BUY. Più alto = fill più raro ma prezzo migliore.

## Comandi Telegram

| Comando | Descrizione |
|---------|-------------|
| `/status` | Stato completo, equity, trades, profitto |
| `/pause` | Mette in pausa il bot (non cancella ordini aperti) |
| `/resume` | Riprende l'operatività |
| `/help` | Lista comandi |

## Note sul rendimento

Con i parametri default (5€/trade, fee 0.16%, buffer 0.2%):
- Profitto netto stimato per trade: ~0.01 EUR
- Ciclo ogni 20 secondi: max ~4.300 cicli/giorno
- **Tetto teorico: ~43 EUR/giorno** (solo se ogni ciclo produce un trade filled)
- In pratica: dipende dalla volatilità e dalla velocità dei fill

> **Avvertenza**: il trading automatico comporta rischi di perdita del capitale. Testa sempre con importi minimi prima di aumentare `order_size_eur`.

## Render deployment

1. Crea un **Web Service** o **Background Worker** su Render
2. Aggiungi le env vars sopra
3. (Consigliato) Aggiungi il **Redis** add-on e copia `REDIS_URL`
4. Start command: `python bot.py`
