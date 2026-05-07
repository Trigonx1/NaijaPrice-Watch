# NaijaPrice Watch 🇳🇬

> A production-grade data engineering pipeline tracking 22 years of food price inflation in Nigeria and its impact on household affordability.

![Python](https://img.shields.io/badge/Python-Data%20Pipeline-blue)
![Power BI](https://img.shields.io/badge/Power%20BI-Dashboard-yellow)
![ETL](https://img.shields.io/badge/ETL-Processing-green)
![Data Engineering](https://img.shields.io/badge/Data-Engineering-red)

---

## What This Project Does

NaijaPrice Watch is an end-to-end data engineering pipeline that processes **87,325 raw records** from the UN World Food Programme’s Nigeria price monitoring dataset.

It transforms raw market data into analytical insights using a 4-stage ETL pipeline, enriches it with macroeconomic indicators (exchange rates + CPI), and delivers an interactive Power BI dashboard.

### Core Question
> Can a minimum-wage Nigerian household afford basic nutrition?

The analysis shows that in **50 out of 262 months**, food costs exceeded sustainable affordability levels.

---

## Key Findings

| Metric                              | Value                    |
|-------------------------------------|--------------------------|
| Raw rows ingested                  | 87,325                   |
| Clean monthly records              | 5,136                    |
| Commodities tracked                | 43                       |
| Date range                         | Jan 2002 – Apr 2026      |
| Crisis months (>60% NMW)           | 50 months                |
| Months food exceeded income        | 8 months                 |
| Peak basket cost                   | ₦94,675 (Jan 2023)       |
| Peak affordability burden          | 135.2% of NMW            |
| Pipeline runtime                   | 2.3 seconds              |

In January 2023, a basic food basket cost ₦94,675 against a minimum wage of ₦30,000 — meaning food consumed **135% of monthly income**.

---

## Dashboard Preview

![Executive Overview](page1_executive_overview.png.png)
![Affordability Crisis](page2_affordability.png.png)
![Commodity Deep Dive](page3_commodities.png.png)

Power BI file: `shop_watch_final_pp.pbix`

---

## Pipeline Architecture

### 1. Extract
- WFP food price dataset
- Live FX rates API
- World Bank CPI data

### 2. Transform
- Cleaning & deduplication
- Monthly aggregation
- MoM% and YoY% calculations
- Rolling averages
- Inflation severity classification

### 3. Validate
- Schema validation
- No negative prices
- No duplicates
- Missing value audit

### 4. Load
- Power BI-ready datasets
- Structured logs in `/logs`

---

## Top Commodities by Inflation

1. Yam — 218.9%
2. Cowpeas (white) — 173.9%
3. Sorghum (brown) — 160.8%
4. Cowpeas (brown) — 155.4%
5. Maize (yellow) — 152.5%

---

## Worst Crisis Months

- Jan 2023 — ₦94,675 — 135.2% of NMW  
- Dec 2022 — ₦93,530 — 133.6%  
- Nov 2022 — ₦91,934 — 131.3%  
- Oct 2022 — ₦86,149 — 123.1%  
- Sep 2022 — ₦83,674 — 119.5%  

---

## Data Quality Notes

- Structural nulls in early time-series metrics (expected)
- YoY nulls due to first-year lag
- No duplicate records
- All prices validated > 0
- Some regional sparsity in certain commodities

---

## Tech Stack

Python · Pandas · NumPy · REST APIs · PostgreSQL · Power BI · Git

---

## How to Run

```bash
git clone https://github.com/Trigonx1/NaijaPrice-Watch
pip install -r requirements.txt
jupyter notebook final_shop_watch.ipynb