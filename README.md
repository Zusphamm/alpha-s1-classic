# S1 Classic (park+kyle)

Cross-sectional alpha ensemble for crypto USDT-M perpetual futures.

## Performance (backtest 500d, top-100 QV)

| Metric | Value |
|--------|-------|
| Sharpe | 2.53 |
| Max DD | -33.3% |
| Win Rate | 60.7% |
| Return | +150.5% |

## Factors

| Factor | Transform | Direction |
|--------|-----------|-----------|
| parkinson_vol30 | chg20 | - |
| parkinson_vol30 | z120 | - |
| kyle_lambda | z60 | + |

## Setup

```bash
pip install ccxt pandas numpy python-dotenv
cp .env.example .env
python run_trader.py
```
