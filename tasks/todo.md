# KMS Implementation

## P0: Foundation
- [x] config.py
- [x] requirements.txt
- [x] data/fetch_etf.py
- [x] signals/volume_signal.py
- [x] backtest/metrics.py
- [x] backtest/engine.py
- [x] backtest.py

## P1: Search Signal Integration
- [x] data/fetch_trend.py
- [x] signals/search_signal.py
- [x] signals/signal_combiner.py
- [x] Update backtest/engine.py
- [x] run.py

## P2: Reports & Optimization
- [x] report/reporter.py
- [x] Grid search in backtest.py
- [x] Walk-forward validation
- [x] .gitignore

## P3: Mania Lifecycle Detection System
- [x] 1. `themes.yaml` + `data/theme_loader.py` + update `config.py`
- [x] 2. `signals/lifecycle.py` (core algorithm)
- [x] 3. `signals/keyword_scanner.py` (batch scanning)
- [x] 4. Update `backtest/engine.py` (lifecycle-aware entry/exit)
- [x] 5. Update `data/fetch_trend.py` (dynamic theme list)
- [x] 6. Update `run.py` (scanner + lifecycle flow)
- [x] 7. Update `report/reporter.py` (phase info)
- [x] 8. Update `requirements.txt` (add pyyaml)
- [x] 9. Verification

## P4: Production Hardening (CEO+Eng+Design Review)
- [x] 1. git init + .gitignore
- [x] 2. .env migration (already done — config.py uses dotenv)
- [x] 3. kms_logger.py (centralized logging)
- [x] 4. utils.py (get_latest_price utility — DRY fix)
- [x] 5. Granular error handling + pandas deprecation fix
- [x] 6. ETF dedup check in run.py
- [x] 7. Signal accuracy CSV logger
- [x] 8. notify.py (Telegram bot + heartbeat)
- [x] 9. Mobile CSS for HTML report
- [x] 10. Zero-trade display in HTML report
- [x] 11. Unit tests (47 tests — all passing)
- [x] 12. Fill unmapped theme instruments (38/38 themes now have instruments)
- [x] 13. macOS launchd cron (com.kms.weekly.plist)

## Verification (P0-P2)
- [x] `python backtest.py` runs without errors — 150 trades, 52% win rate
- [x] `python run.py` prints signals — volume-only mode (no Naver API keys)
- [x] HTML report generated at `report/backtest_result.html`

## Verification (P3)
- [x] `themes.yaml` loads 38 themes, 23 with instruments
- [x] `signals/lifecycle.py` correctly detects phases (PEAK, CRASH, ACCELERATION)
- [x] `python backtest.py` runs — 303 trades across expanded 23-theme universe
- [x] `python run.py` runs full scanner → lifecycle → action flow
- [x] Trade records include `entry_phase` field
- [x] Reporter shows phase info in trade table
- [x] Backward compatible: volume-only fallback when no trend data

## Verification (P4)
- [x] All imports pass (`python -c "import run; import backtest"`)
- [x] kms_logger.py writes to both console and logs/kms.log
- [x] get_latest_price returns correct values + None for empty
- [x] notify.py returns False gracefully when no Telegram credentials
- [x] launchd plist validates with `plutil -lint`
- [x] Unit tests pass (`pytest tests/` — 47/47 green)
- [x] themes.yaml updated — all 38 themes have instruments
