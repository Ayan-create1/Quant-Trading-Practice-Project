"""
Load, clean, and plot the daily price data for Assets A-F.

Run from the project folder:
    .venv/bin/python research/load_data.py

Other scripts can reuse the loader:
    from research.load_data import load_all_assets
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # draw straight to an image file (no pop-up window needed)
import matplotlib.pyplot as plt
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"

# Only A-F. Asset_G is a duplicate of Asset_B and is deliberately ignored.
ASSETS = [f"Asset_{letter}" for letter in "ABCDEF"]
PRICE_COLUMNS = ["Open", "High", "Low", "Close"]


def load_asset(name: str) -> pd.DataFrame:
    """Read one CSV and return a clean table indexed by date (oldest first)."""
    df = pd.read_csv(DATA_DIR / f"{name}.csv")

    # Give the close column a simpler name.
    df = df.rename(columns={"Close/Last": "Close"})

    # Prices are stored as text like "$28.43". Remove the "$" and turn them into numbers.
    for col in PRICE_COLUMNS:
        df[col] = df[col].astype(str).str.replace("$", "", regex=False).str.replace(",", "")
        df[col] = pd.to_numeric(df[col], errors="raise")
    df["Volume"] = pd.to_numeric(df["Volume"], errors="raise")

    # Turn the date text into real dates, sort oldest -> newest, and drop any repeated days.
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").drop_duplicates(subset="Date", keep="first")
    df = df.set_index("Date")

    return df[PRICE_COLUMNS + ["Volume"]]


def check_asset(df: pd.DataFrame) -> list[str]:
    """Sanity checks. Returns a list of problems found (empty list = all good)."""
    problems = []
    if df.isna().any().any():
        problems.append(f"missing values: {df.isna().sum().to_dict()}")
    if (df[PRICE_COLUMNS] <= 0).any().any():
        problems.append("some prices are zero or negative")
    # The day's High should be the highest price and Low the lowest.
    bad_high = (df["High"] < df[["Open", "Close", "Low"]].max(axis=1)).sum()
    bad_low = (df["Low"] > df[["Open", "Close", "High"]].min(axis=1)).sum()
    if bad_high or bad_low:
        problems.append(f"{bad_high} days with High too low, {bad_low} days with Low too high")
    return problems


def load_all_assets() -> dict[str, pd.DataFrame]:
    """Load every asset A-F into a dict: {"Asset_A": table, ...}."""
    return {name: load_asset(name) for name in ASSETS}


def plot_prices(data: dict[str, pd.DataFrame], out_path: Path) -> None:
    """One small chart per asset (they have very different price levels)."""
    fig, axes = plt.subplots(3, 2, figsize=(12, 9), sharex=True)
    for ax, (name, df) in zip(axes.flat, data.items()):
        ax.plot(df.index, df["Close"], color="#2a78d6", linewidth=1.5)
        ax.set_title(name, loc="left", fontsize=11, color="#0b0b0b")
        ax.set_ylabel("Close ($)", color="#52514e")
        ax.grid(axis="y", color="#e5e4df", linewidth=0.8)
        ax.tick_params(colors="#52514e", labelsize=9)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        # Shade the 2022-2023 holdout period so we remember not to tune on it.
        ax.axvspan(pd.Timestamp("2022-01-01"), df.index.max(), color="#000000", alpha=0.05, linewidth=0)
    fig.suptitle("Daily closing price, Assets A-F (shaded = 2022-23 holdout)", x=0.01, ha="left", fontsize=13)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120, facecolor="#fcfcfb")
    print(f"\nSaved chart to {out_path}")


if __name__ == "__main__":
    data = load_all_assets()

    print(f"{'Asset':<9} {'Rows':>5}  {'First day':<11} {'Last day':<11} {'First close':>11} {'Last close':>11}  Checks")
    for name, df in data.items():
        problems = check_asset(df)
        status = "OK" if not problems else "; ".join(problems)
        print(
            f"{name:<9} {len(df):>5}  {df.index.min().date()!s:<11} {df.index.max().date()!s:<11} "
            f"{df['Close'].iloc[0]:>11.2f} {df['Close'].iloc[-1]:>11.2f}  {status}"
        )

    # Do all assets trade on the same days? (Important when we combine them later.)
    date_sets = [set(df.index) for df in data.values()]
    common = set.intersection(*date_sets)
    print(f"\nDays shared by all 6 assets: {len(common)}")

    plot_prices(data, PROJECT_DIR / "research" / "prices.png")
