# Alpha S1 Classic — Volatility + Liquidity

The original live-proven 3-factor ensemble. First alpha deployed live, generated +$242 in 10 days.

## Strategy

Combines Parkinson volatility (high/low range estimator) with Kyle's lambda (market microstructure). Short high-vol coins and long coins becoming more liquid. Two transforms of parkinson capture both level and momentum of volatility.

## Backtest Performance

| Metric | Value |
|--------|-------|
| Period | 500 days (top-100 QV universe) |
| Sharpe | **2.53** |
| Max Drawdown | **-33.3%** |
| Win Rate | 60.7% |
| Total Return | +150.5% |
| Positions | 30 (equal-weight, daily rebalance) |

## Paper Trade Performance

| Factor | PnL | Days | $/Day |
|--------|-----|------|-------|
| `parkinson|vol30|chg20|-` | $+0.00 | 0 | $+0.000 |
| `parkinson|vol30|z120|-` | $+0.00 | 0 | $+0.000 |
| `kyle|lambda|z60|+` | $+0.00 | 0 | $+0.000 |
| **Total** | **$+0.00** | | |

## Factors (3)

| Factor | Transform | Dir | Description |
|--------|-----------|-----|-------------|
| `parkinson_vol30` | `chg20` | `-` | 20-day change in 30-day Parkinson vol — short rising vol |
| `parkinson_vol30` | `z120` | `-` | 120-day z-score of Parkinson vol — short vol spikes |
| `kyle_lambda` | `z60` | `+` | 60-day z-score of Kyle's lambda — long improving liquidity |

## Signal Construction

```
1. Compute raw factor for all symbols
2. Apply transform (level, change, z-score)
3. Filter to top-100 by quote volume
4. Cross-sectional z-score (demean + normalize)
5. Winsorize at +/-3 sigma
6. Equal-weight top-30 by |signal|
7. Daily rebalance after candle close (00:00 UTC)
```

## Risk Management

| Parameter | Value |
|-----------|-------|
| Free margin | >= 33% |
| Leverage | 5x |
| Funding filter | Skip if \|rate\| > 0.03% |
| Stop loss | -30% from peak |
| Candle check | Only trade after close |

## Setup

```bash
pip install ccxt pandas numpy python-dotenv
cp .env.example .env
# Add Binance Futures API key + secret
python run_trader.py  # dry run first
# Set LIVE_DRY_RUN=0 to go live
```
