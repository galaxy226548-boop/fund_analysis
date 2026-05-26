from __future__ import annotations

import argparse
import json
import os
import warnings
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import numpy as np
import pandas as pd
from scipy.optimize import minimize

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager


WINDOW_WEEKS = 52
STEP_WEEKS = 4
MIN_FUND_WEEKS = 104
MIN_R2 = 0.7


@dataclass(frozen=True)
class RBSAConfig:
    root: Path
    growth_path: Path
    value_path: Path
    gc007_path: Path
    fund_nav_path: Path
    output_dir: Path
    window_weeks: int = WINDOW_WEEKS
    step_weeks: int = STEP_WEEKS
    min_fund_weeks: int = MIN_FUND_WEEKS
    min_r2: float = MIN_R2


def find_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_index_path(root: Path, filename: str) -> Path:
    candidates = [
        root / "D_analysis" / "input " / filename,
        root / "D_analysis" / "input" / filename,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    matches = list((root / "D_analysis").glob(f"input*/{filename}"))
    if matches:
        return matches[0]
    raise FileNotFoundError(f"Cannot find {filename} under D_analysis/input*")


def parse_args() -> RBSAConfig:
    parser = argparse.ArgumentParser(description="滚动 RBSA 风格踩对/踩错分析")
    parser.add_argument("--root", type=Path, default=find_project_root(), help="项目根目录")
    parser.add_argument("--growth-path", type=Path, default=None, help="国证成长指数 xlsx")
    parser.add_argument("--value-path", type=Path, default=None, help="国证价值指数 xlsx")
    parser.add_argument("--gc007-path", type=Path, default=None, help="GC007 xlsx")
    parser.add_argument("--fund-nav-path", type=Path, default=None, help="基金净值宽表 xlsx")
    parser.add_argument("--output-dir", type=Path, default=None, help="输出目录")
    parser.add_argument("--window-weeks", type=int, default=WINDOW_WEEKS)
    parser.add_argument("--step-weeks", type=int, default=STEP_WEEKS)
    parser.add_argument("--min-fund-weeks", type=int, default=MIN_FUND_WEEKS)
    parser.add_argument("--min-r2", type=float, default=MIN_R2)
    args = parser.parse_args()

    root = args.root.resolve()
    return RBSAConfig(
        root=root,
        growth_path=(args.growth_path or resolve_index_path(root, "growth_index.xlsx")).resolve(),
        value_path=(args.value_path or resolve_index_path(root, "value_index.xlsx")).resolve(),
        gc007_path=(args.gc007_path or root / "A_data" / "input" / "GC007_加权平均.xlsx").resolve(),
        fund_nav_path=(
            args.fund_nav_path
            or root / "A_data" / "prepared_data" / "主动权益型基金净值变化.xlsx"
        ).resolve(),
        output_dir=(args.output_dir or root / "D_analysis" / "output" / "RBSA").resolve(),
        window_weeks=args.window_weeks,
        step_weeks=args.step_weeks,
        min_fund_weeks=args.min_fund_weeks,
        min_r2=args.min_r2,
    )


def read_index_weekly_return(path: Path, name: str) -> pd.Series:
    df = pd.read_excel(path, usecols=["date", "close"])
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    close = (
        df.dropna(subset=["date", "close"])
        .assign(close=lambda x: pd.to_numeric(x["close"], errors="coerce"))
        .dropna(subset=["close"])
        .drop_duplicates(subset=["date"], keep="last")
        .sort_values("date")
        .set_index("date")["close"]
    )
    weekly_close = close.resample("W-FRI").last().dropna()
    weekly_return = weekly_close.pct_change()
    weekly_return.name = name
    return weekly_return


def read_gc007_weekly_cash(path: Path) -> pd.Series:
    df = pd.read_excel(path, sheet_name=0, usecols=["指标名称", "GC007:加权平均"])
    df["date"] = pd.to_datetime(df["指标名称"], errors="coerce")
    df["gc007"] = pd.to_numeric(df["GC007:加权平均"], errors="coerce")
    daily = (
        df.dropna(subset=["date", "gc007"])
        .drop_duplicates(subset=["date"], keep="last")
        .sort_values("date")
        .set_index("date")["gc007"]
    )
    weekly_cash = daily.resample("W-FRI").last().dropna() / 100.0 / 52.0
    weekly_cash.name = "cash"
    return weekly_cash


def normalize_nav_date(col: object) -> pd.Timestamp:
    if isinstance(col, pd.Timestamp):
        return col.normalize()
    if hasattr(col, "date") and not isinstance(col, str):
        return pd.Timestamp(col).normalize()
    text = str(col).strip()
    if text.endswith(".0") and text[:4].isdigit():
        text = text[:-2]
    if "." in text and ":" in text:
        text = text.rsplit(".", 1)[0]
    return pd.to_datetime(text).normalize()


def first_non_null(values: pd.Series) -> float:
    valid = values.dropna()
    return valid.iloc[0] if len(valid) else np.nan


def read_fund_weekly_returns(path: Path, min_fund_weeks: int) -> pd.DataFrame:
    raw = pd.read_excel(path, sheet_name=0)
    if raw.empty:
        raise ValueError(f"Fund NAV file is empty: {path}")

    fund_col = raw.columns[0]
    raw[fund_col] = raw[fund_col].astype(str).str.strip()
    raw = raw[raw[fund_col].notna() & (raw[fund_col] != "")]
    raw = raw.drop_duplicates(subset=[fund_col], keep="last").set_index(fund_col)
    raw.index.name = "fund_code"

    date_index = pd.Index([normalize_nav_date(col) for col in raw.columns], name="date")
    nav = raw.apply(pd.to_numeric, errors="coerce").replace(0, np.nan).T
    nav.index = date_index
    nav = nav.groupby(level=0).agg(first_non_null).sort_index()

    returns = nav.pct_change(fill_method=None)
    valid_counts = returns.notna().sum(axis=0)
    returns = returns.loc[:, valid_counts >= min_fund_weeks]
    return returns


def align_returns(
    growth: pd.Series,
    value: pd.Series,
    cash: pd.Series,
    fund_returns: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    factors = pd.concat([growth, value, cash], axis=1, sort=True).dropna()
    factors.columns = ["growth", "value", "cash"]
    common_index = factors.index.intersection(fund_returns.index).sort_values()
    factors = factors.loc[common_index]
    fund_returns = fund_returns.loc[common_index]
    return factors, fund_returns


def rebalance_dates(index: pd.DatetimeIndex) -> set[pd.Timestamp]:
    dates: set[pd.Timestamp] = set()
    for year in sorted(set(index.year)):
        for month in (6, 12):
            month_dates = index[(index.year == year) & (index.month == month)]
            if len(month_dates):
                dates.add(month_dates.max())
    return dates


def compute_static_5050(factors: pd.DataFrame) -> pd.Series:
    weights = np.array([0.5, 0.5], dtype=float)
    resets = rebalance_dates(factors.index)
    returns = []
    for date, row in factors[["growth", "value"]].iterrows():
        if date in resets:
            weights = np.array([0.5, 0.5], dtype=float)
        asset_returns = row.to_numpy(dtype=float)
        portfolio_return = float(np.dot(weights, asset_returns))
        returns.append(portfolio_return)
        values = weights * (1.0 + asset_returns)
        total = values.sum()
        weights = values / total if total != 0 else np.array([0.5, 0.5], dtype=float)
    return pd.Series(returns, index=factors.index, name="benchmark_5050")


def solve_rbsa(y: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, float]:
    def objective(w: np.ndarray) -> float:
        residual = y - x @ w
        return float(np.dot(residual, residual))

    constraints = [{"type": "ineq", "fun": lambda w: 1.0 - np.sum(w)}]
    bounds = [(0.0, 1.0), (0.0, 1.0), (0.0, 1.0)]
    result = minimize(
        objective,
        x0=np.array([0.45, 0.45, 0.10]),
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 300, "ftol": 1e-12, "disp": False},
    )
    if not result.success:
        result = minimize(
            objective,
            x0=np.array([1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0]),
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"maxiter": 600, "ftol": 1e-12, "disp": False},
        )
    w = np.clip(result.x, 0.0, 1.0)
    if w.sum() > 1.0:
        w = w / w.sum()

    y_hat = x @ w
    ss_res = float(np.sum((y - y_hat) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
    return w, r2


def run_rolling_rbsa(
    factors: pd.DataFrame,
    fund_returns: pd.DataFrame,
    window_weeks: int,
    step_weeks: int,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    n = len(factors)
    for end_pos in range(window_weeks - 1, n, step_weeks):
        start_pos = end_pos - window_weeks + 1
        window_index = factors.index[start_pos : end_pos + 1]
        x_all = factors.iloc[start_pos : end_pos + 1][["growth", "value", "cash"]]
        estimate_date = factors.index[end_pos]

        fund_window = fund_returns.iloc[start_pos : end_pos + 1]
        eligible = fund_window.columns[fund_window.notna().sum(axis=0) >= window_weeks]
        for fund_code in eligible:
            y = fund_window[fund_code]
            mask = y.notna() & x_all.notna().all(axis=1)
            if int(mask.sum()) < window_weeks:
                continue
            weights, r2 = solve_rbsa(y.loc[mask].to_numpy(dtype=float), x_all.loc[mask].to_numpy(dtype=float))
            rows.append(
                {
                    "estimate_date": estimate_date,
                    "window_start": window_index[0],
                    "window_end": estimate_date,
                    "fund_code": fund_code,
                    "w_growth": weights[0],
                    "w_value": weights[1],
                    "w_cash": weights[2],
                    "weight_sum": weights.sum(),
                    "r2": r2,
                    "valid": bool(pd.notna(r2) and r2 >= MIN_R2),
                    "net_growth_exposure": weights[0] - weights[1],
                }
            )

        if (end_pos - (window_weeks - 1)) % (step_weeks * 20) == 0:
            print(f"RBSA progress: {estimate_date.date()} ({end_pos + 1}/{n})")

    return pd.DataFrame(rows)


def cumulative_return(
    returns: pd.Series | pd.DataFrame,
    min_count: int | None = None,
) -> float | pd.Series:
    min_count = min_count or len(returns)
    return (1.0 + returns).prod(min_count=min_count) - 1.0


def assign_groups(valid_exposures: pd.DataFrame) -> tuple[list[str], list[str]]:
    sorted_df = valid_exposures.sort_values("net_growth_exposure", ascending=False)
    n = len(sorted_df)
    group_size = n // 3
    if group_size == 0:
        return [], []
    growth_group = sorted_df.head(group_size)["fund_code"].astype(str).tolist()
    value_group = sorted_df.tail(group_size)["fund_code"].astype(str).tolist()
    return growth_group, value_group


def build_period_group_returns(
    exposures: pd.DataFrame,
    factors: pd.DataFrame,
    fund_returns: pd.DataFrame,
    benchmark_returns: pd.Series,
    min_r2: float,
    step_weeks: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    fund_rows: list[dict[str, object]] = []
    index = factors.index
    position = {date: i for i, date in enumerate(index)}

    for estimate_date, group in exposures.groupby("estimate_date", sort=True):
        if estimate_date not in position:
            continue
        start = position[estimate_date] + 1
        end = start + step_weeks
        if end > len(index):
            continue
        period_index = index[start:end]

        valid = group[group["r2"] >= min_r2].copy()
        growth_group, value_group = assign_groups(valid)
        if not growth_group or not value_group:
            continue

        growth_style_return = cumulative_return(factors.loc[period_index, "growth"], min_count=step_weeks)
        value_style_return = cumulative_return(factors.loc[period_index, "value"], min_count=step_weeks)
        dominant_style = "成长" if growth_style_return > value_style_return else "价值"

        growth_group_return = cumulative_return(
            fund_returns.loc[period_index, growth_group],
            min_count=step_weeks,
        ).mean()
        value_group_return = cumulative_return(
            fund_returns.loc[period_index, value_group],
            min_count=step_weeks,
        ).mean()
        benchmark_return = cumulative_return(benchmark_returns.loc[period_index], min_count=step_weeks)

        if dominant_style == "成长":
            correct_return = growth_group_return
            wrong_return = value_group_return
            correct_group = "成长偏向组"
            wrong_group = "价值偏向组"
            correct_funds = growth_group
            wrong_funds = value_group
        else:
            correct_return = value_group_return
            wrong_return = growth_group_return
            correct_group = "价值偏向组"
            wrong_group = "成长偏向组"
            correct_funds = value_group
            wrong_funds = growth_group

        rows.append(
            {
                "estimate_date": estimate_date,
                "forward_start": period_index[0],
                "forward_end": period_index[-1],
                "year": period_index[-1].year,
                "valid_fund_count": len(valid),
                "growth_group_count": len(growth_group),
                "value_group_count": len(value_group),
                "dominant_style": dominant_style,
                "growth_style_return": growth_style_return,
                "value_style_return": value_style_return,
                "growth_group_return": growth_group_return,
                "value_group_return": value_group_return,
                "correct_group": correct_group,
                "wrong_group": wrong_group,
                "correct_group_return": correct_return,
                "wrong_group_return": wrong_return,
                "return_diff": correct_return - wrong_return,
                "benchmark_5050_return": benchmark_return,
                "benchmark_minus_wrong": benchmark_return - wrong_return,
            }
        )

        for bucket, fund_codes in (("correct", correct_funds), ("wrong", wrong_funds)):
            returns = cumulative_return(
                fund_returns.loc[period_index, fund_codes],
                min_count=step_weeks,
            )
            for fund_code, fund_return in returns.items():
                fund_rows.append(
                    {
                        "estimate_date": estimate_date,
                        "forward_start": period_index[0],
                        "forward_end": period_index[-1],
                        "year": period_index[-1].year,
                        "fund_code": fund_code,
                        "bucket": bucket,
                        "fund_forward_return": fund_return,
                        "benchmark_5050_return": benchmark_return,
                        "excess_vs_5050": fund_return - benchmark_return,
                    }
                )
    return pd.DataFrame(rows), pd.DataFrame(fund_rows)


def build_annual_stats(period_returns: pd.DataFrame, step_weeks: int) -> pd.DataFrame:
    if period_returns.empty:
        return pd.DataFrame()

    def annual_period_return(returns: pd.Series) -> float:
        returns = returns.dropna()
        if returns.empty:
            return np.nan
        return (1.0 + returns).prod() - 1.0

    annual = (
        period_returns.groupby("year", as_index=False)
        .agg(
            correct_group_return=("correct_group_return", "mean"),
            wrong_group_return=("wrong_group_return", "mean"),
            return_diff=("return_diff", "mean"),
            benchmark_5050_return=("benchmark_5050_return", "mean"),
            benchmark_minus_wrong=("benchmark_minus_wrong", "mean"),
            period_count=("return_diff", "count"),
        )
        .sort_values("year")
    )
    annual_returns = (
        period_returns.groupby("year")
        .agg(
            correct_group_annual_return=("correct_group_return", annual_period_return),
            wrong_group_annual_return=("wrong_group_return", annual_period_return),
            benchmark_5050_annual_return=("benchmark_5050_return", annual_period_return),
        )
        .reset_index()
    )
    annual = annual.merge(annual_returns, on="year", how="left")
    return annual


def build_stable_fund_stats(
    fund_period_returns: pd.DataFrame,
    min_selected_count: int = 10,
    min_correct_rate: float = 0.6,
) -> tuple[pd.DataFrame, set[str]]:
    if fund_period_returns.empty:
        return pd.DataFrame(), set()

    stats = (
        fund_period_returns.groupby("fund_code")
        .agg(
            selected_count=("bucket", "count"),
            correct_count=("bucket", lambda x: int((x == "correct").sum())),
            wrong_count=("bucket", lambda x: int((x == "wrong").sum())),
            avg_forward_return=("fund_forward_return", "mean"),
            avg_excess_vs_5050=("excess_vs_5050", "mean"),
            win_rate_vs_5050=("excess_vs_5050", lambda x: float((x > 0).mean())),
        )
        .reset_index()
    )
    stats["correct_rate"] = stats["correct_count"] / stats["selected_count"]
    stats = stats.sort_values(
        ["correct_count", "correct_rate", "avg_excess_vs_5050"],
        ascending=[False, False, False],
    )
    stable = stats[
        (stats["selected_count"] >= min_selected_count)
        & (stats["correct_rate"] >= min_correct_rate)
        & (stats["avg_excess_vs_5050"] > 0)
    ]
    stats["is_stable"] = stats["fund_code"].astype(str).isin(set(stable["fund_code"].astype(str)))
    return stats, set(stable["fund_code"].astype(str))


def build_summary(
    exposures: pd.DataFrame,
    period_returns: pd.DataFrame,
    factors: pd.DataFrame,
    fund_returns: pd.DataFrame,
    min_r2: float,
) -> pd.DataFrame:
    metrics = {
        "factor_start": factors.index.min().date().isoformat(),
        "factor_end": factors.index.max().date().isoformat(),
        "weekly_observations": len(factors),
        "fund_count_after_104w_filter": fund_returns.shape[1],
        "rbsa_rows": len(exposures),
        "rbsa_valid_rows_r2_ge_threshold": int((exposures["r2"] >= min_r2).sum())
        if not exposures.empty
        else 0,
        "period_count": len(period_returns),
        "full_sample_correct_avg_return": period_returns["correct_group_return"].mean()
        if not period_returns.empty
        else np.nan,
        "full_sample_wrong_avg_return": period_returns["wrong_group_return"].mean()
        if not period_returns.empty
        else np.nan,
        "full_sample_avg_return_diff": period_returns["return_diff"].mean()
        if not period_returns.empty
        else np.nan,
        "full_sample_benchmark_minus_wrong": period_returns["benchmark_minus_wrong"].mean()
        if not period_returns.empty
        else np.nan,
    }
    return pd.DataFrame({"metric": list(metrics.keys()), "value": list(metrics.values())})


def configure_chinese_font() -> None:
    preferred = ["STHeiti", "Arial Unicode MS", "PingFang SC", "Heiti SC", "Songti SC"]
    available = {font.name for font in font_manager.fontManager.ttflist}
    for name in preferred:
        if name in available:
            plt.rcParams["font.sans-serif"] = [name]
            break
    else:
        font_paths = [
            "/System/Library/Fonts/STHeiti Medium.ttc",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        ]
        for font_path in font_paths:
            if Path(font_path).exists():
                font_manager.fontManager.addfont(font_path)
                plt.rcParams["font.sans-serif"] = [font_manager.FontProperties(fname=font_path).get_name()]
                break
    plt.rcParams["axes.unicode_minus"] = False


def plot_annual_return_diff(annual: pd.DataFrame, output_path: Path) -> None:
    configure_chinese_font()
    fig, ax = plt.subplots(figsize=(11, 6), dpi=160)
    x = np.arange(len(annual))
    ax.bar(x, annual["return_diff"] * 100, width=0.62, label="方向正确组 - 方向错误组", color="#2F7D6D")
    ax.plot(
        x,
        annual["benchmark_minus_wrong"] * 100,
        marker="o",
        linewidth=2,
        color="#B45F3C",
        label="50/50静态组合 - 方向错误组",
    )
    ax.axhline(0, color="#333333", linewidth=0.9)
    ax.set_xticks(x)
    ax.set_xticklabels(annual["year"].astype(str))
    ax.set_ylabel("收益差（%）")
    ax.set_xlabel("年份")
    ax.set_title("分年度方向判断收益差")
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)


def plot_cumulative_comparison(
    period_returns: pd.DataFrame,
    output_path: Path,
    stable_period_returns: pd.Series | None = None,
) -> None:
    configure_chinese_font()
    curves = period_returns.set_index("forward_end")[
        ["correct_group_return", "wrong_group_return", "benchmark_5050_return"]
    ].sort_index()
    if stable_period_returns is not None and not stable_period_returns.dropna().empty:
        curves["stable_correct_fund_return"] = stable_period_returns.reindex(curves.index).fillna(0.0)
    nav = (1.0 + curves).cumprod()
    nav.columns = [
        "方向正确组",
        "方向错误组",
        "50/50静态组合",
        *(
            ["稳定上榜基金"]
            if "stable_correct_fund_return" in curves.columns
            else []
        ),
    ]

    fig, ax = plt.subplots(figsize=(12, 6.5), dpi=160)
    colors = ["#2F7D6D", "#8C4A64", "#3C6E9F", "#C08A2A"]
    for col, color in zip(nav.columns, colors, strict=False):
        ax.plot(nav.index, nav[col], linewidth=2, label=col, color=color)
    ax.axhline(1, color="#333333", linewidth=0.8, alpha=0.6)
    ax.set_ylabel("累计净值")
    ax.set_xlabel("日期")
    ax.set_title("方向正确组、方向错误组、50/50静态组合与稳定上榜基金累计收益对比")
    ax.grid(axis="both", linestyle="--", alpha=0.3)
    ax.legend()
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)


def plot_annual_return_lines(annual: pd.DataFrame, output_path: Path) -> None:
    configure_chinese_font()
    fig, ax = plt.subplots(figsize=(12, 6.5), dpi=160)
    x = annual["year"].astype(int)
    series = [
        ("correct_group_annual_return", "方向正确组", "#2F7D6D"),
        ("wrong_group_annual_return", "方向错误组", "#8C4A64"),
        ("benchmark_5050_annual_return", "50/50静态组合", "#3C6E9F"),
    ]
    for col, label, color in series:
        ax.plot(x, annual[col] * 100, marker="o", linewidth=2.2, label=label, color=color)

    ax.axhline(0, color="#333333", linewidth=0.9)
    ax.set_xticks(x)
    ax.set_xticklabels(x.astype(str), rotation=0)
    ax.set_ylabel("年度收益率（%）")
    ax.set_xlabel("年份")
    ax.set_title("分年度收益率对比")
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)


def build_stable_period_returns(
    fund_period_returns: pd.DataFrame,
    stable_funds: set[str],
) -> pd.Series:
    if not stable_funds or fund_period_returns.empty:
        return pd.Series(dtype=float)
    stable_period_returns = (
        fund_period_returns[
            (fund_period_returns["bucket"] == "correct")
            & (fund_period_returns["fund_code"].astype(str).isin(stable_funds))
        ]
        .groupby("forward_end")["fund_forward_return"]
        .mean()
        .sort_index()
    )
    stable_period_returns.index = pd.to_datetime(stable_period_returns.index)
    stable_period_returns.name = "stable_outperform_return"
    return stable_period_returns


def annual_compounded_returns(period_returns: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    data = period_returns.copy()
    data["forward_end"] = pd.to_datetime(data["forward_end"])
    data["year"] = data["forward_end"].dt.year
    rows = []
    for year, group in data.groupby("year", sort=True):
        row: dict[str, object] = {"year": year}
        for col in columns:
            row[col] = (1.0 + group[col].dropna()).prod() - 1.0
        rows.append(row)
    return pd.DataFrame(rows)


def plot_annual_stable_return_lines(
    period_returns: pd.DataFrame,
    stable_period_returns: pd.Series,
    output_path: Path,
) -> None:
    if stable_period_returns.dropna().empty:
        return
    stable_annual = (
        stable_period_returns.dropna()
        .groupby(stable_period_returns.dropna().index.year)
        .agg(lambda x: (1.0 + x).prod() - 1.0)
        .rename("stable_outperform_return")
        .reset_index()
    )
    stable_annual.columns = ["year", "stable_outperform_return"]
    annual_base = annual_compounded_returns(
        period_returns,
        ["wrong_group_return", "benchmark_5050_return"],
    )
    annual_compare = stable_annual.merge(annual_base, on="year", how="left").sort_values("year")
    if annual_compare.empty:
        return

    configure_chinese_font()
    fig, ax = plt.subplots(figsize=(12, 6.5), dpi=160)
    x = annual_compare["year"].astype(int)
    series = [
        ("stable_outperform_return", "稳定跑赢组", "#C08A2A"),
        ("wrong_group_return", "方向错误组", "#8C4A64"),
        ("benchmark_5050_return", "50/50静态组合", "#3C6E9F"),
    ]
    for col, label, color in series:
        ax.plot(x, annual_compare[col] * 100, marker="o", linewidth=2.2, label=label, color=color)

    ax.axhline(0, color="#333333", linewidth=0.9)
    ax.set_xticks(x)
    ax.set_xticklabels(x.astype(str), rotation=0)
    ax.set_ylabel("年度收益率（%）")
    ax.set_xlabel("年份")
    ax.set_title("稳定跑赢组、方向错误组与50/50静态组合分年度收益率对比")
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)


def plot_cumulative_stable_vs_wrong_5050(
    period_returns: pd.DataFrame,
    stable_period_returns: pd.Series,
    output_path: Path,
) -> None:
    if stable_period_returns.dropna().empty:
        return
    curves = period_returns.copy()
    curves["forward_end"] = pd.to_datetime(curves["forward_end"])
    curves = curves.set_index("forward_end")[["wrong_group_return", "benchmark_5050_return"]].sort_index()
    first_stable_date = stable_period_returns.dropna().index.min()
    curves = curves.loc[curves.index >= first_stable_date]
    curves["stable_outperform_return"] = stable_period_returns.reindex(curves.index).fillna(0.0)
    nav = (1.0 + curves).cumprod()
    nav.columns = ["方向错误组", "50/50静态组合", "稳定上榜基金组"]

    configure_chinese_font()
    fig, ax = plt.subplots(figsize=(12, 6.5), dpi=160)
    colors = ["#8C4A64", "#3C6E9F", "#C08A2A"]
    for col, color in zip(nav.columns, colors, strict=False):
        ax.plot(nav.index, nav[col], linewidth=2.2, label=col, color=color)
    ax.axhline(1, color="#333333", linewidth=0.8, alpha=0.6)
    ax.set_ylabel("累计净值")
    ax.set_xlabel("日期")
    ax.set_title("方向错误组、50/50静态组合与稳定上榜基金组累计收益对比")
    ax.grid(axis="both", linestyle="--", alpha=0.3)
    ax.legend()
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)


def save_outputs(
    cfg: RBSAConfig,
    exposures: pd.DataFrame,
    period_returns: pd.DataFrame,
    fund_period_returns: pd.DataFrame,
    stable_fund_stats: pd.DataFrame,
    stable_funds: set[str],
    annual: pd.DataFrame,
    summary: pd.DataFrame,
) -> None:
    cfg.output_dir.mkdir(parents=True, exist_ok=True)

    exposures.to_csv(cfg.output_dir / "rbsa_exposures.csv", index=False, encoding="utf-8-sig")
    period_returns.to_csv(cfg.output_dir / "period_group_returns.csv", index=False, encoding="utf-8-sig")
    fund_period_returns.to_csv(cfg.output_dir / "fund_period_returns.csv", index=False, encoding="utf-8-sig")
    stable_fund_stats.to_csv(cfg.output_dir / "stable_fund_stats.csv", index=False, encoding="utf-8-sig")
    annual.to_csv(cfg.output_dir / "annual_return_diff.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(cfg.output_dir / "summary_stats.csv", index=False, encoding="utf-8-sig")

    if not annual.empty:
        plot_annual_return_diff(annual, cfg.output_dir / "annual_return_diff.png")
        plot_annual_return_lines(annual, cfg.output_dir / "annual_return_lines.png")
    if not period_returns.empty:
        stable_period_returns = build_stable_period_returns(fund_period_returns, stable_funds)
        plot_cumulative_comparison(
            period_returns,
            cfg.output_dir / "cumulative_return_comparison.png",
            stable_period_returns=stable_period_returns,
        )
        if not stable_period_returns.empty:
            plot_annual_stable_return_lines(
                period_returns,
                stable_period_returns,
                cfg.output_dir / "annual_return_lines_stable.png",
            )
            plot_cumulative_stable_vs_wrong_5050(
                period_returns,
                stable_period_returns,
                cfg.output_dir / "cumulative_stable_vs_wrong_5050.png",
            )

    metadata = {
        "growth_path": str(cfg.growth_path),
        "value_path": str(cfg.value_path),
        "gc007_path": str(cfg.gc007_path),
        "fund_nav_path": str(cfg.fund_nav_path),
        "output_dir": str(cfg.output_dir),
        "window_weeks": cfg.window_weeks,
        "step_weeks": cfg.step_weeks,
        "min_fund_weeks": cfg.min_fund_weeks,
        "min_r2": cfg.min_r2,
    }
    (cfg.output_dir / "run_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")
    cfg = parse_args()

    print("Reading index and cash data...")
    growth = read_index_weekly_return(cfg.growth_path, "growth")
    value = read_index_weekly_return(cfg.value_path, "value")
    cash = read_gc007_weekly_cash(cfg.gc007_path)

    print("Reading fund NAV data...")
    fund_returns = read_fund_weekly_returns(cfg.fund_nav_path, cfg.min_fund_weeks)
    factors, fund_returns = align_returns(growth, value, cash, fund_returns)
    if factors.empty or fund_returns.empty:
        raise ValueError("No overlapping weekly observations after data alignment.")

    print(f"Aligned weeks: {len(factors)}, funds after filter: {fund_returns.shape[1]}")
    benchmark_returns = compute_static_5050(factors)

    print("Running rolling RBSA...")
    exposures = run_rolling_rbsa(factors, fund_returns, cfg.window_weeks, cfg.step_weeks)
    if exposures.empty:
        raise ValueError("No RBSA exposure rows were produced.")
    exposures["valid"] = exposures["r2"] >= cfg.min_r2

    print("Building style timing statistics...")
    period_returns, fund_period_returns = build_period_group_returns(
        exposures=exposures,
        factors=factors,
        fund_returns=fund_returns,
        benchmark_returns=benchmark_returns,
        min_r2=cfg.min_r2,
        step_weeks=cfg.step_weeks,
    )
    annual = build_annual_stats(period_returns, cfg.step_weeks)
    stable_fund_stats, stable_funds = build_stable_fund_stats(fund_period_returns)
    summary = build_summary(exposures, period_returns, factors, fund_returns, cfg.min_r2)

    print("Saving outputs...")
    save_outputs(
        cfg,
        exposures,
        period_returns,
        fund_period_returns,
        stable_fund_stats,
        stable_funds,
        annual,
        summary,
    )
    print(f"Done. Outputs saved to: {cfg.output_dir}")


if __name__ == "__main__":
    main()
