#!/usr/bin/env python
# coding: utf-8

# In[1]:


import requests
import pandas as pd
import numpy as np


# In[2]:


import os
import logging
from datetime import datetime
from pathlib import Path


# In[3]:


# Logging setup


# In[4]:


LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

log_filename = LOG_DIR / f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s — %(levelname)s — %(message)s",
    handlers=[
        logging.FileHandler(log_filename),    # writes to file
        logging.StreamHandler()               # also prints to console
    ]
)

logger = logging.getLogger("NaijaWatch")


# In[5]:


## Extract Exchange Rate API


# In[6]:


def extract_exchange_rate() -> pd.DataFrame:

    FALLBACK_RATE = 1580.0
    API_URL = "https://open.er-api.com/v6/latest/USD"

    try:
        response = requests.get(API_URL, timeout=10)
        response.raise_for_status()           # raises HTTPError for 4xx / 5xx
        data = response.json()
        rate = data["rates"]["NGN"]
        source = "live API"

    except (requests.RequestException, KeyError) as err:
        logger.warning(f"Exchange rate API failed ({err}). Using fallback: {FALLBACK_RATE}")
        rate = FALLBACK_RATE
        source = "fallback"

    df = pd.DataFrame({
        "date": [pd.Timestamp.today().normalize()],
        "exchange_rate_ngn": [rate],
        "source": [source]
    })

    logger.info(f"Exchange rate extracted: 1 USD = {rate:,.2f} NGN ({source})")
    return df
df_fx = extract_exchange_rate()
df_fx.head()    


# In[7]:


# World Bank Inflation


# In[8]:


def extract_worldbank_inflation() -> pd.DataFrame:

    API_URL = (
        "https://api.worldbank.org/v2/country/NGA/indicator/"
        "FP.CPI.TOTL.ZG?format=json&per_page=30"
    )

    try:
        response = requests.get(API_URL, timeout=10)
        response.raise_for_status()
        records = response.json()[1]           # index [0] is metadata, [1] is data

        df = pd.DataFrame(records)[["date", "value"]].dropna(subset=["value"])
        df.columns = ["year", "inflation_rate_annual"]
        df["year"] = df["year"].astype(int)
        df = df.sort_values("year").reset_index(drop=True)

        logger.info(f"World Bank CPI data extracted: {len(df)} annual records "
                    f"({df['year'].min()}–{df['year'].max()})")
        return df

    except Exception as err:
        logger.error(f"World Bank API failed: {err}. Returning empty DataFrame.")
        return pd.DataFrame(columns=["year", "inflation_rate_annual"])
df_inflation = extract_worldbank_inflation()
df_inflation.head()


# In[9]:


## Food Prices (CSV)


# In[10]:


def extract_food_prices(filepath: str = "wfp_food_prices_nga.csv") -> pd.DataFrame:

    try:
        df = pd.read_csv(filepath, low_memory=False)
        logger.info(f"Food prices loaded: {len(df):,} rows from '{filepath}'")
        return df

    except FileNotFoundError:
        logger.error(
            f"Food price CSV not found at '{filepath}'.\n"
            "Download it from: https://data.humdata.org/dataset/wfp-food-prices-for-nigeria\n"
            "Save as 'wfp_food_prices_nga.csv' in the project root."
        )
        raise
df_food = extract_food_prices()
df_food.head()


# In[11]:


## Transform dataset


# In[12]:


def clean_food_data(df: pd.DataFrame) -> pd.DataFrame:

    COLUMN_MAP = {
        "cmname":    "commodity",
        "mkt_name":  "market",
        "adm1_name": "state",
        "mp_price":  "price",
        "cur_name":  "currency",
        "pt_name":   "price_type",
    }

    # Only rename columns that actually exist in this version of the CSV
    rename = {k: v for k, v in COLUMN_MAP.items() if k in df.columns}
    df = df.rename(columns=rename)

    # Parse date — WFP uses ISO 8601 format (YYYY-MM-DD)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    # Drop rows where we cannot analyse (missing key fields)
    before = len(df)
    df = df.dropna(subset=["commodity", "price", "date"])
    df = df[df["price"] > 0]
    dropped = before - len(df)
    if dropped:
        logger.warning(f"Dropped {dropped:,} rows with null/zero values during cleaning")

    # Clean text fields
    for col in ["commodity", "market", "state", "currency", "price_type"]:
        if col in df.columns:
            df[col] = df[col].str.strip()

    logger.info(f"Food data cleaned: {len(df):,} valid rows remain")
    return df
df_food = clean_food_data(df_food)    


# In[13]:


## Aggregate Properly


# In[14]:


def aggregate_food_prices(df: pd.DataFrame) -> pd.DataFrame:

    # Floor date to month start for consistent grouping
    df = df.copy()
    df["date"] = df["date"].dt.to_period("M").dt.to_timestamp()

    df_agg = (
        df.groupby(["commodity", "date"], as_index=False)["price"]
        .mean()
        .rename(columns={"price": "real_price_ngn"})
        .sort_values(["commodity", "date"])
        .reset_index(drop=True)
    )

    n_commodities = df_agg["commodity"].nunique()
    date_range = f"{df_agg['date'].min().date()} -> {df_agg['date'].max().date()}"
    logger.info(
        f"Aggregated to {len(df_agg):,} monthly records | "
        f"{n_commodities} commodities | {date_range}"
    )
    return df_agg
df_agg = aggregate_food_prices(df_food)
df_agg.head()


# In[15]:


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:

    df = df.copy().sort_values(["commodity", "date"]).reset_index(drop=True)

    grp = df.groupby("commodity")["real_price_ngn"]

    # Month-over-month change
    df["mom_change_pct"] = grp.pct_change(1) * 100

    # Year-over-year change
    df["yoy_change_pct"] = grp.pct_change(12) * 100

    # Rolling average
    df["rolling_3m_avg"] = (
        grp.transform(lambda x: x.rolling(3, min_periods=2).mean())
    )
    # Inflation severity classification
    def classify_severity(yoy: float) -> str | None:
        """Assign a severity label based on YoY inflation band."""
        if pd.isna(yoy):
            return None
        elif yoy > 30:
            return "Critical"
        elif yoy > 15:
            return "High"
        elif yoy > 5:
            return "Moderate"
        else:
            return "Low"

    df["inflation_severity"] = df["yoy_change_pct"].apply(classify_severity)

    logger.info(
        "Feature engineering complete — new columns: "
        "mom_change_pct, yoy_change_pct, rolling_3m_avg, inflation_severity"
    )
    return df
df_final = engineer_features(df_agg)
df_final.tail()    


# In[16]:


## Generate Synthetic Household Basket


# In[17]:


def build_affordability_layer(
    df: pd.DataFrame,
    low_income_ngn: float = 70_000,
    mid_income_ngn: float = 150_000
) -> pd.DataFrame:

    BASKET = {
        "Rice (imported)": 5,
        "Maize":           3,
        "Beans (niebe)":   2,
        "Tomatoes":        4,
        "Oil (palm)":      1,
    }

    basket_df = df[df["commodity"].isin(BASKET)].copy()
    basket_df["quantity"] = basket_df["commodity"].map(BASKET)
    basket_df["item_spend"] = basket_df["real_price_ngn"] * basket_df["quantity"]

    monthly_basket = (
        basket_df.groupby("date", as_index=False)["item_spend"]
        .sum()
        .rename(columns={"item_spend": "basket_cost_ngn"})
    )

    # Affordability index: % of monthly wage consumed by basket
    monthly_basket["affordability_low_pct"] = (
        monthly_basket["basket_cost_ngn"] / low_income_ngn * 100
    ).round(2)
    monthly_basket["affordability_mid_pct"] = (
        monthly_basket["basket_cost_ngn"] / mid_income_ngn * 100
    ).round(2)

    crisis_months = (monthly_basket["affordability_low_pct"] > 60).sum()
    logger.info(
        f"Affordability layer built | "
        f"{crisis_months} months where low-income basket > 60% of NMW"
    )
    return monthly_basket
df_basket = build_affordability_layer(df_final)
df_basket.head()


# In[18]:


# Validation Layer


# In[19]:


def validate_data(df: pd.DataFrame, name: str = "dataset") -> bool:

    passed = True

    # Check 1: Not empty
    if df.empty:
        logger.error(f"VALIDATION FAILED [{name}]: DataFrame is empty!")
        return False

    logger.info(f"Validating '{name}': shape {df.shape}")

    # Check 2: Null values
    null_counts = df.isnull().sum()
    null_cols = null_counts[null_counts > 0]
    if not null_cols.empty:
        logger.warning(f"[{name}] Columns with nulls:\n{null_cols.to_string()}")
    else:
        logger.info(f"[{name}] OK No null values in key columns")

    # Check 3: Negative prices (if 'real_price_ngn' exists)
    if "real_price_ngn" in df.columns:
        negatives = (df["real_price_ngn"] < 0).sum()
        if negatives:
            logger.error(f"[{name}] FAILED: {negatives} negative prices found!")
            passed = False
        else:
            logger.info(f"[{name}] OK All prices > 0")

    # Check 4: Duplicate rows
    dupes = df.duplicated().sum()
    if dupes:
        logger.warning(f"[{name}] {dupes} duplicate rows found")
    else:
        logger.info(f"[{name}] OK No duplicate rows")

    logger.info(f"Validation for '{name}': {'PASSED' if passed else 'FAILED'}")
    return passed


# In[20]:


## LOAD LAYER


# In[21]:


def export_for_powerbi(
    df_main: pd.DataFrame,
    df_basket: pd.DataFrame,
    df_inflation: pd.DataFrame,
    output_dir: str = "outputs"
) -> dict[str, str]:

    out = Path(output_dir)
    out.mkdir(exist_ok=True)

    paths = {
        "food_prices":      str(out / "powerbi_food_prices.csv"),
        "basket":           str(out / "powerbi_basket.csv"),
        "inflation_annual": str(out / "powerbi_inflation_wb.csv"),
    }

    df_main.to_csv(paths["food_prices"], index=False)
    df_basket.to_csv(paths["basket"], index=False)
    df_inflation.to_csv(paths["inflation_annual"], index=False)

    for label, path in paths.items():
        size_kb = Path(path).stat().st_size / 1024
        logger.info(f"Exported [{label}] -> {path} ({size_kb:.1f} KB)")

    return paths


# In[22]:


paths = export_for_powerbi(df_final, df_basket, df_inflation)

print(paths)


# In[23]:


#Analysis


# In[24]:


def answer_business_questions(df: pd.DataFrame, basket: pd.DataFrame) -> None:
    """
    Print answers to the 10 core business questions from the project brief.
    """
    SEP = "─" * 70
    print(f"\n{SEP}")
    print(" NAIJAPRICEWATCH — ANALYTICAL FINDINGS")
    print(f"{SEP}")

    # BQ1: Top YoY inflating commodities
    print("\n BQ1 | Which commodities have risen fastest (YoY)?")
    top_yoy = (
        df.groupby("commodity")["yoy_change_pct"]
        .mean()
        .dropna()
        .sort_values(ascending=False)
        .head(10)
    )
    print(top_yoy.round(1).to_string())

    # BQ3: Monthly inflation spikes
    print("\n BQ3 | When did food prices spike the most (MoM)?")
    spikes = (
        df.groupby("date")["mom_change_pct"]
        .mean()
        .sort_values(ascending=False)
        .head(5)
    )
    print(spikes.round(2).to_string())

    # BQ4: Affordability crisis months
    print("\n BQ4 | How many months did low-income basket exceed 60% of NMW?")
    crisis = basket[basket["affordability_low_pct"] > 60]
    print(f"  → {len(crisis)} months ({len(crisis)/len(basket)*100:.1f}% of data period)")
    if not crisis.empty:
        latest = crisis.sort_values("date").tail(3)[["date", "basket_cost_ngn", "affordability_low_pct"]]
        print("  → Most recent crisis months:")
        print(latest.to_string(index=False))

    # BQ5: Severity distribution
    print("\n BQ5 | Inflation severity breakdown (all commodities, all periods)")
    sev = df["inflation_severity"].value_counts()
    total = sev.sum()
    for label, count in sev.items():
        print(f"  {label:<12}: {count:>5,}  ({count/total*100:.1f}%)")

    # BQ7: Most price-volatile commodities
    print("\n BQ7 | Which commodities are most price-volatile (MoM std dev)?")
    vol = (
        df.groupby("commodity")["mom_change_pct"]
        .std()
        .sort_values(ascending=False)
        .head(10)
    )
    print(vol.round(2).to_string())

    print(f"\n{SEP}\n")


# In[26]:


# Main orchestrator


# In[27]:


def run_pipeline(food_csv_path: str = "wfp_food_prices_nga.csv") -> None:
    """
    Full pipeline orchestrator — Extract → Transform → Validate → Load.
    """
    start_time = datetime.now()
    logger.info("=" * 60)
    logger.info("NaijaPrice Watch pipeline STARTED")
    logger.info("=" * 60)

    # ── EXTRACT ───────────────────────────────────────────────────────────────
    logger.info("[1/4] EXTRACT")
    df_fx          = extract_exchange_rate()
    df_wb          = extract_worldbank_inflation()
    df_food_raw    = extract_food_prices(food_csv_path)

    # ── TRANSFORM ─────────────────────────────────────────────────────────────
    logger.info("[2/4] TRANSFORM")
    df_food_clean  = clean_food_data(df_food_raw)
    df_food_agg    = aggregate_food_prices(df_food_clean)
    df_food_final  = engineer_features(df_food_agg)
    df_basket      = build_affordability_layer(df_food_final)

    # ── VALIDATE ──────────────────────────────────────────────────────────────
    logger.info("[3/4] VALIDATE")
    validate_data(df_food_final, name="food_prices")
    validate_data(df_basket,     name="basket")

    # ── LOAD ──────────────────────────────────────────────────────────────────
    logger.info("[4/4] LOAD")
    paths = export_for_powerbi(df_food_final, df_basket, df_wb)

    # ── ANALYSIS ──────────────────────────────────────────────────────────────
    answer_business_questions(df_food_final, df_basket)

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info(f"Pipeline COMPLETED in {elapsed:.1f} seconds")
    logger.info(f"Log saved to: {log_filename}")
    for label, path in paths.items():
        logger.info(f"Output [{label}]: {path}")


if __name__ == "__main__":
    run_pipeline(food_csv_path="wfp_food_prices_nga.csv")


# In[ ]:




