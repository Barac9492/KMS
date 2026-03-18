"""Backtesting engine with lifecycle-aware entry/exit."""

import pandas as pd
from config import TOTAL_COST, DEFAULT_PARAMS, ETF_UNIVERSE
from kms_logger import logger
from signals.volume_signal import pick_best_etf
from signals.lifecycle import (
    detect_phase, get_action, get_stop_loss,
    ACCELERATION, EUPHORIA, PEAK, CRASH, BUY, EXIT, HOLD, WATCH,
)
from data.theme_loader import get_instrument_slippage
from utils import get_latest_price


class Position:
    def __init__(self, theme: str, etf_code: str, etf_name: str,
                 entry_date: str, entry_price: float, shares: int, cost: float,
                 instrument_type: str = "etf"):
        self.theme = theme
        self.etf_code = etf_code
        self.etf_name = etf_name
        self.entry_date = pd.Timestamp(entry_date)
        self.entry_price = entry_price
        self.shares = shares
        self.cost = cost  # total capital allocated (after slippage)
        self.peak_search_ratio = 0.0  # for search peak exit
        self.instrument_type = instrument_type
        self.entry_phase = ""  # phase at entry time


class BacktestEngine:
    def __init__(self, etf_data: dict, params: dict | None = None,
                 initial_capital: float = 10_000_000,
                 search_signal_func=None, trend_data: dict | None = None):
        self.etf_data = etf_data
        self.params = {**DEFAULT_PARAMS, **(params or {})}
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: list[Position] = []
        self.trades: list[dict] = []
        self.portfolio_values = {}
        self.search_signal_func = search_signal_func
        self.trend_data = trend_data or {}

        # Build code-to-theme and code-to-name lookups
        self.code_to_theme = {}
        self.code_to_name = {}
        self.code_to_type = {}
        self.theme_to_codes = {}
        for theme, etfs in ETF_UNIVERSE.items():
            codes = []
            for etf in etfs:
                self.code_to_theme[etf["code"]] = theme
                self.code_to_name[etf["code"]] = etf["name"]
                self.code_to_type[etf["code"]] = etf.get("type", "etf")
                codes.append(etf["code"])
            self.theme_to_codes[theme] = codes

    def _portfolio_value(self, date: str) -> float:
        """Current portfolio value = cash + sum of position market values."""
        value = self.cash
        for pos in self.positions:
            if pos.etf_code in self.etf_data:
                price = get_latest_price(self.etf_data[pos.etf_code], date)
                if price is not None:
                    value += pos.shares * price
        return value

    def _should_exit(self, pos: Position, date: str) -> tuple[bool, str]:
        """Check exit conditions. Returns (should_exit, reason)."""
        current_date = pd.Timestamp(date)

        # Time exit: max_hold_weeks
        hold_days = (current_date - pos.entry_date).days
        if hold_days >= self.params["max_hold_weeks"] * 7:
            return True, "time_exit"

        # Stop loss (phase-aware: tightened during EUPHORIA)
        stop_loss = self.params["stop_loss"]
        if pos.etf_code in self.etf_data:
            current_price = get_latest_price(self.etf_data[pos.etf_code], date)
            if current_price is not None:
                pnl_pct = (current_price / pos.entry_price) - 1

                # Lifecycle phase exit
                if pos.theme in self.trend_data:
                    etf_df = self.etf_data.get(pos.etf_code)
                    phase_result = detect_phase(
                        self.trend_data[pos.theme], date,
                        etf_df=etf_df,
                        lookback_weeks=self.params["search_lookback_weeks"],
                        recent_weeks=self.params["search_recent_weeks"],
                        search_threshold=self.params["search_threshold"],
                    )
                    phase = phase_result["phase"]
                    action = get_action(phase, holding=True)

                    if action == EXIT:
                        return True, f"lifecycle_{phase.lower()}"

                    # Tighten stop during EUPHORIA
                    stop_loss = get_stop_loss(phase, self.params["stop_loss"])

                if pnl_pct <= -stop_loss:
                    return True, "stop_loss"

        # Search peak exit fallback (only if search signal is available, no lifecycle data)
        if self.search_signal_func and pos.theme in self.trend_data:
            search_sig = self.search_signal_func(
                self.trend_data[pos.theme], date,
                lookback_weeks=self.params["search_lookback_weeks"],
                recent_weeks=self.params["search_recent_weeks"],
            )
            if search_sig["ratio"] > 0:
                if search_sig["ratio"] > pos.peak_search_ratio:
                    pos.peak_search_ratio = search_sig["ratio"]
                if pos.peak_search_ratio > 0 and search_sig["ratio"] < pos.peak_search_ratio * 0.7:
                    return True, "search_peak_decline"

        return False, ""

    def _exit_position(self, pos: Position, date: str, reason: str):
        """Close a position, record the trade."""
        if pos.etf_code not in self.etf_data:
            logger.warning("ETF %s not in data for exit", pos.etf_code)
            return
        exit_price = get_latest_price(self.etf_data[pos.etf_code], date)
        if exit_price is None:
            return
        gross_value = pos.shares * exit_price
        exit_cost = gross_value * TOTAL_COST
        net_proceeds = gross_value - exit_cost
        self.cash += net_proceeds

        return_pct = (net_proceeds / pos.cost) - 1

        self.trades.append({
            "theme": pos.theme,
            "etf_code": pos.etf_code,
            "etf_name": pos.etf_name,
            "entry_date": pos.entry_date.strftime("%Y-%m-%d"),
            "exit_date": date,
            "entry_price": pos.entry_price,
            "exit_price": exit_price,
            "shares": pos.shares,
            "return_pct": return_pct,
            "exit_reason": reason,
            "entry_phase": pos.entry_phase,
        })

    def _enter_position(self, theme: str, etf_code: str, date: str, phase: str = ""):
        """Open a new position."""
        if etf_code not in self.etf_data:
            return
        entry_price = get_latest_price(self.etf_data[etf_code], date)
        if entry_price is None:
            return

        portfolio_value = self._portfolio_value(date)
        alloc = portfolio_value * self.params["position_size"]

        # Apply entry cost (stocks have higher slippage)
        inst_type = self.code_to_type.get(etf_code, "etf")
        slippage = 0.005 if inst_type == "stock" else 0.003
        entry_cost = slippage + 0.0023  # slippage + tax
        effective_price = entry_price * (1 + entry_cost)
        shares = int(alloc / effective_price)
        if shares <= 0:
            return

        cost = shares * effective_price
        self.cash -= cost

        pos = Position(
            theme=theme,
            etf_code=etf_code,
            etf_name=self.code_to_name.get(etf_code, etf_code),
            entry_date=date,
            entry_price=entry_price,
            shares=shares,
            cost=cost,
            instrument_type=inst_type,
        )
        pos.entry_phase = phase
        self.positions.append(pos)

    def run(self, start: str, end: str) -> tuple[pd.Series, list[dict]]:
        """Run backtest over the date range.

        Returns:
            (portfolio_values_series, trades_list)
        """
        # Collect all trading dates from ETF data
        all_dates = set()
        for df in self.etf_data.values():
            all_dates.update(df.loc[start:end].index.strftime("%Y-%m-%d"))
        trading_dates = sorted(all_dates)

        if not trading_dates:
            return pd.Series(dtype=float), []

        held_themes = lambda: {pos.theme for pos in self.positions}

        for date in trading_dates:
            # ── 1. EXIT before entry (prevents look-ahead bias in position count) ──
            to_exit = []
            for pos in self.positions:
                should_exit, reason = self._should_exit(pos, date)
                if should_exit:
                    to_exit.append((pos, reason))

            for pos, reason in to_exit:
                self._exit_position(pos, date, reason)
                self.positions.remove(pos)

            # ── 2. ENTRY (lifecycle-aware) ──
            if len(self.positions) < self.params["max_positions"]:
                for theme, codes in self.theme_to_codes.items():
                    if theme in held_themes():
                        continue
                    if len(self.positions) >= self.params["max_positions"]:
                        break

                    # Lifecycle-based entry
                    if theme in self.trend_data:
                        # Use first available ETF for price divergence check
                        etf_df = None
                        for c in codes:
                            if c in self.etf_data:
                                etf_df = self.etf_data[c]
                                break

                        phase_result = detect_phase(
                            self.trend_data[theme], date,
                            etf_df=etf_df,
                            lookback_weeks=self.params["search_lookback_weeks"],
                            recent_weeks=self.params["search_recent_weeks"],
                            search_threshold=self.params["search_threshold"],
                        )
                        action = get_action(phase_result["phase"], holding=False)
                        if action != BUY:
                            continue
                    elif self.search_signal_func:
                        # No trend data — fallback to volume-only
                        pass
                    else:
                        continue

                    # Volume signal — pick best ETF in theme
                    best_code, vol_sig = pick_best_etf(
                        self.etf_data, codes, date,
                        vol_threshold=self.params["vol_threshold"],
                    )
                    if best_code:
                        phase_name = phase_result["phase"] if theme in self.trend_data else ""
                        self._enter_position(theme, best_code, date, phase=phase_name)

            # ── 3. Record portfolio value ──
            self.portfolio_values[date] = self._portfolio_value(date)

        # Close any remaining positions at end
        for pos in list(self.positions):
            self._exit_position(pos, trading_dates[-1], "backtest_end")
            self.positions.remove(pos)
            self.portfolio_values[trading_dates[-1]] = self._portfolio_value(trading_dates[-1])

        pv = pd.Series(self.portfolio_values, name="portfolio_value")
        pv.index = pd.to_datetime(pv.index)
        pv.sort_index(inplace=True)

        return pv, self.trades
