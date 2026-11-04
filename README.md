# Kalshi candlestick recovery archive

Immutable records written by .github/workflows/kalshi-candles.yml.
Schema: cbb_edge/kalshi/candles.py (kalshi-candles-v1).

Every record is `executable=false`, provenance `recovered_candle_not_top_of_book`:
aggregate OHLC candles, NOT top-of-book quotes. Never use as a fill price.
