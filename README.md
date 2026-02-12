# Polymarket Bot - Bitcoin Up or Down Tracker

🤖 En terminal-basert bot som sporer priser, ordrebøker og aktivitet for Bitcoin prediction markets på Polymarket.

## Funksjoner

- 📊 **Sanntidspriser** - Viser nåværende bid/ask priser for UP og DOWN tokens
- 📈 **Ordrebøker** - Viser de beste bids og asks for begge sider
- 🔄 **Live oppdateringer** - Oppdaterer hvert sekund
- 🎨 **Fargerikt interface** - Lett å lese terminal UI med ANSI farger

## Installasjon

1. Installer Python 3.9 eller nyere

2. Installer avhengigheter:
```bash
pip install -r requirements.txt
```

## Bruk

Kjør boten:
```bash
python polymarket_bot.py
```

For å endre market, rediger `event_slug` variabelen i `main()` funksjonen:
```python
event_slug = "btc-updown-15m-1769755500"  # Endre denne
```

Du finner event slug i URL-en på Polymarket, f.eks.:
- `https://polymarket.com/event/btc-updown-15m-1769755500` → `btc-updown-15m-1769755500`

## API-er brukt

- **Gamma API** (`gamma-api.polymarket.com`) - For å hente markedsdata og event info
- **CLOB API** (`clob.polymarket.com`) - For ordrebøker og trades

## Demo Mode

Hvis boten ikke finner gyldige token IDs, vil den kjøre i demo-modus med simulert data.
Dette er nyttig for å teste interface-et.

## Skjermbilde

```
  ────────────────────────────────────────────────────────────
  🤖 POLYMARKET BOT - Bitcoin Up or Down
  Market: btc-updown-15m-1769755500
  Window: 22:30 - 22:45 UTC  |  Time: 22:37:59 UTC
  Status: ✓ Connected & Streaming  |  Updates: 6967
  ────────────────────────────────────────────────────────────
  💰 CURRENT MARKET PRICES 💰
            UP                          DOWN
          10.5%                        89.5%
       Bid: 10.0¢                  Bid: 89.0¢
       Ask: 11.0¢                  Ask: 90.0¢
            Total:
            100.0¢
  ────────────────────────────────────────────────────────────
    UP Token Orderbook              DOWN Token Orderbook
  Bid $  Size    Ask $  Size    Bid $  Size    Ask $  Size
  0.010  1067    0.990  1079    0.010  10793   0.990  1067
  0.020  3407    0.980  2761    0.020  2761    0.980  3407
  0.030  883.4   0.970  730.4   0.030  730.4   0.970  883.4
  ────────────────────────────────────────────────────────────
```

## Stopp

Trykk `Ctrl+C` for å stoppe boten.

## Deploy til Render

Repoet inneholder nå en ferdig [render.yaml](render.yaml) som konfigurerer en Python-webtjeneste:

1. Push endringene til GitHub og velg **New ➜ Blueprint** i Render-dashbordet (eller bruk `render blueprint launch`).
2. Pek til repoet og branch `main`. Render leser `render.yaml`, kjører `pip install -r requirements.txt` og starter `python web_bot_multi.py`.
3. Eventuelle miljøvariabler kan justeres i Render etter opprettelsen (for eksempel `STARTING_BALANCE` eller `PER_MARKET_BUDGET`).

`web_bot_multi.py` lytter automatisk på porten som Render eksponerer via `PORT`, så ingen ekstra konfigurasjon er nødvendig.

## Lisens

MIT
