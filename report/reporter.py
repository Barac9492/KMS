"""Report generation — terminal pretty-print + HTML with Plotly."""

import os
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from config import REPORT_DIR
from kms_logger import logger


def generate_html_report(
    portfolio_values: pd.Series,
    trades: list[dict],
    metrics: dict,
    params: dict,
    benchmark_values: pd.Series | None = None,
    grid_results: list[dict] | None = None,
):
    """Generate interactive HTML backtest report with Plotly charts."""
    os.makedirs(REPORT_DIR, exist_ok=True)
    output_path = os.path.join(REPORT_DIR, "backtest_result.html")

    figs = []

    # ── 1. Cumulative Return Chart ────────────────────────────────────────────
    fig1 = go.Figure()
    pv_normalized = portfolio_values / portfolio_values.iloc[0]
    fig1.add_trace(go.Scatter(
        x=pv_normalized.index, y=pv_normalized.values,
        name="KMS Strategy", line=dict(color="royalblue", width=2),
    ))

    if benchmark_values is not None and not benchmark_values.empty:
        # Align benchmark to same date range
        bm = benchmark_values.reindex(pv_normalized.index, method="ffill").dropna()
        if not bm.empty:
            bm_normalized = bm / bm.iloc[0]
            fig1.add_trace(go.Scatter(
                x=bm_normalized.index, y=bm_normalized.values,
                name="KOSPI 200", line=dict(color="gray", width=1, dash="dash"),
            ))

    fig1.update_layout(
        title="Cumulative Return", xaxis_title="Date", yaxis_title="Growth of 1 KRW",
        template="plotly_white", height=400,
    )
    figs.append(fig1)

    # ── 2. MDD Chart ─────────────────────────────────────────────────────────
    cummax = portfolio_values.cummax()
    drawdown = (portfolio_values - cummax) / cummax

    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        x=drawdown.index, y=drawdown.values,
        fill="tozeroy", name="Drawdown",
        line=dict(color="crimson", width=1),
    ))
    fig2.update_layout(
        title="Maximum Drawdown", xaxis_title="Date", yaxis_title="Drawdown %",
        template="plotly_white", height=300,
    )
    figs.append(fig2)

    # ── 3. Yearly Returns Bar Chart ──────────────────────────────────────────
    if len(portfolio_values) > 1:
        yearly = portfolio_values.resample("YE").last()
        yearly_returns = yearly.pct_change().dropna()
        if not yearly_returns.empty:
            fig3 = go.Figure()
            colors = ["green" if r > 0 else "crimson" for r in yearly_returns.values]
            fig3.add_trace(go.Bar(
                x=yearly_returns.index.year, y=yearly_returns.values,
                marker_color=colors, name="Yearly Return",
            ))
            fig3.update_layout(
                title="Yearly Returns", xaxis_title="Year", yaxis_title="Return",
                yaxis_tickformat=".1%", template="plotly_white", height=300,
            )
            figs.append(fig3)

    # ── 4. Trade Table ───────────────────────────────────────────────────────
    trade_html = _trades_table_html(trades)

    # ── 5. Grid Search Heatmap (if available) ────────────────────────────────
    heatmap_html = ""
    if grid_results and len(grid_results) > 1:
        heatmap_html = _grid_heatmap_html(grid_results)

    # ── Assemble HTML ────────────────────────────────────────────────────────
    metrics_html = _metrics_html(metrics, params)
    chart_divs = "\n".join(fig.to_html(full_html=False, include_plotlyjs=False) for fig in figs)

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>KMS Backtest Report</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               max-width: 1200px; margin: 0 auto; padding: 20px; background: #f8f9fa; }}
        h1 {{ color: #1a1a2e; }}
        .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                    gap: 12px; margin: 20px 0; }}
        .metric-card {{ background: white; padding: 16px; border-radius: 8px;
                        box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        .metric-value {{ font-size: 24px; font-weight: bold; color: #1a1a2e; }}
        .metric-label {{ font-size: 13px; color: #666; margin-top: 4px; }}
        table {{ border-collapse: collapse; width: 100%; background: white;
                 border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #eee; font-size: 13px; }}
        th {{ background: #1a1a2e; color: white; }}
        .positive {{ color: #22c55e; }}
        .negative {{ color: #ef4444; }}
        .params {{ background: white; padding: 16px; border-radius: 8px; margin: 20px 0;
                   box-shadow: 0 1px 3px rgba(0,0,0,0.1); font-size: 13px; }}
        .table-wrap {{ overflow-x: auto; }}
        @media (max-width: 600px) {{
            .metrics {{ grid-template-columns: repeat(2, 1fr); }}
        }}
    </style>
</head>
<body>
    <h1>KMS Backtest Report</h1>
    {metrics_html}
    <div class="params"><b>Parameters:</b> {_params_str(params)}</div>
    {chart_divs}
    <h2>Trade History</h2>
    <div class="table-wrap">{trade_html}</div>
    {heatmap_html}
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info("  HTML report saved: %s", output_path)


def _metrics_html(metrics: dict, params: dict) -> str:
    cards = [
        ("Total Return", f"{metrics.get('total_return', 0):.1%}"),
        ("CAGR", f"{metrics.get('cagr', 0):.1%}"),
        ("MDD", f"{metrics.get('mdd', 0):.1%}"),
        ("Sharpe", f"{metrics.get('sharpe', 0):.2f}"),
        ("Trades", f"{metrics.get('num_trades', 0)}"),
        ("Win Rate", f"{metrics.get('win_rate', 0):.1%}"),
        ("Avg Return", f"{metrics.get('avg_return_per_trade', 0):.1%}"),
        ("Avg Hold", f"{metrics.get('avg_hold_days', 0):.0f} days"),
    ]
    if "benchmark_return" in metrics:
        cards.append(("Benchmark", f"{metrics['benchmark_return']:.1%}"))
        cards.append(("Excess", f"{metrics['excess_return']:.1%}"))

    html = '<div class="metrics">'
    for label, value in cards:
        html += f'<div class="metric-card"><div class="metric-value">{value}</div>'
        html += f'<div class="metric-label">{label}</div></div>'
    html += '</div>'
    return html


def _trades_table_html(trades: list[dict]) -> str:
    if not trades:
        return ('<div class="metric-card" style="text-align:center;color:#999">'
                '<div class="metric-value">0</div>'
                '<div class="metric-label">No trades generated — thresholds may be too strict</div>'
                '</div>')

    html = "<table><tr><th>Theme</th><th>ETF</th><th>Entry</th><th>Exit</th>"
    html += "<th>Return</th><th>Entry Phase</th><th>Exit Reason</th></tr>"

    for t in trades:
        ret = t.get("return_pct", 0)
        cls = "positive" if ret > 0 else "negative"
        entry_phase = t.get("entry_phase", "-")
        html += f"<tr><td>{t['theme']}</td><td>{t['etf_name']}</td>"
        html += f"<td>{t['entry_date']}</td><td>{t.get('exit_date', '-')}</td>"
        html += f'<td class="{cls}">{ret:+.1%}</td>'
        html += f"<td>{entry_phase}</td>"
        html += f"<td>{t.get('exit_reason', '-')}</td></tr>"

    html += "</table>"
    return html


def _grid_heatmap_html(grid_results: list[dict]) -> str:
    """Simple table of top grid search results."""
    html = "<h2>Top Grid Search Results</h2><table>"
    html += "<tr><th>Rank</th><th>Train CAGR</th><th>Train Sharpe</th>"
    html += "<th>Test CAGR</th><th>Test Sharpe</th><th>Key Params</th></tr>"

    for i, r in enumerate(grid_results[:10]):
        tm = r["train_metrics"]
        ttm = r["test_metrics"]
        p = r["params"]
        param_str = (f"vol={p.get('vol_threshold')}, search={p.get('search_threshold')}, "
                     f"sl={p.get('stop_loss')}, hold={p.get('max_hold_weeks')}w")
        html += f"<tr><td>{i+1}</td>"
        html += f"<td>{tm.get('cagr', 0):.1%}</td><td>{tm.get('sharpe', 0):.2f}</td>"
        html += f"<td>{ttm.get('cagr', 0):.1%}</td><td>{ttm.get('sharpe', 0):.2f}</td>"
        html += f"<td style='font-size:11px'>{param_str}</td></tr>"

    html += "</table>"
    return html


def _params_str(params: dict) -> str:
    keys = ["vol_threshold", "search_threshold", "stop_loss", "max_hold_weeks",
            "search_lookback_weeks", "ma_period", "position_size", "max_positions"]
    return " | ".join(f"{k}={params.get(k)}" for k in keys if k in params)
