"""
Statement parsers for various UK bank and credit-card CSV formats.

Supports:
  • Generic CSV    – any CSV with Date, Description and Amount columns
  • Barclays       – Date, Description, Amount (negative = debit)
  • HSBC           – Date, Description, Debit, Credit
  • Monzo          – Transaction ID, Date, …, Amount, Currency, …, Name, …
  • Starling       – Date, Counter Party, Reference, Type, Amount (GBP), Balance (GBP)
  • Amex (UK)      – Date, Description, Amount
  • Lloyds / Halifax – Transaction Date, Transaction Type, Sort Code, Account Number,
                       Transaction Description, Debit Amount, Credit Amount, Balance
  • Revolut        – Type, Product, Started Date, Completed Date, Description,
                       Amount, Fee, Currency, State, Balance

The parsers normalise every statement into a standard DataFrame with columns:
    date  |  description  |  amount  |  source_file

`amount` is always a *positive* number representing money spent (debits only).
Credits / refunds are filtered out.
"""

from __future__ import annotations

import io
import re
from datetime import datetime
from typing import BinaryIO

import pandas as pd


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _to_date(series: pd.Series) -> pd.Series:
    """Try a few common UK date formats."""
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%d/%m/%y", "%m/%d/%Y"):
        try:
            return pd.to_datetime(series, format=fmt, dayfirst=True)
        except (ValueError, TypeError):
            continue
    # fallback: let pandas infer
    return pd.to_datetime(series, dayfirst=True, format="mixed")


def _normalise(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """Return only the four expected columns, dropping NaNs."""
    df = df[["date", "description", "amount"]].copy()
    df["source_file"] = source
    df.dropna(subset=["date", "amount"], inplace=True)
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").abs()
    df = df[df["amount"] > 0]
    df.reset_index(drop=True, inplace=True)
    return df


# ---------------------------------------------------------------------------
# Format-specific parsers
# ---------------------------------------------------------------------------

def _parse_monzo(df_raw: pd.DataFrame, source: str) -> pd.DataFrame | None:
    cols = [c.lower().strip() for c in df_raw.columns]
    if "transaction id" not in cols:
        return None
    df_raw.columns = cols
    df = pd.DataFrame()
    df["date"] = _to_date(df_raw["date"])
    df["description"] = df_raw.get("name", df_raw.get("description", ""))
    # Monzo amounts are negative for debits
    raw_amount = pd.to_numeric(df_raw["amount"], errors="coerce")
    df["amount"] = raw_amount
    # keep only debits (negative amounts in Monzo)
    df = df[df["amount"] < 0].copy()
    df["amount"] = df["amount"].abs()
    return _normalise(df, source)


def _parse_starling(df_raw: pd.DataFrame, source: str) -> pd.DataFrame | None:
    cols = [c.lower().strip() for c in df_raw.columns]
    if "counter party" not in cols and "counterparty" not in cols:
        return None
    df_raw.columns = cols
    cp_col = "counter party" if "counter party" in cols else "counterparty"
    amt_col = [c for c in cols if "amount" in c and "gbp" in c]
    if not amt_col:
        amt_col = [c for c in cols if "amount" in c]
    amt_col = amt_col[0] if amt_col else "amount"
    df = pd.DataFrame()
    df["date"] = _to_date(df_raw["date"])
    ref = df_raw.get("reference", pd.Series([""] * len(df_raw)))
    df["description"] = df_raw[cp_col].astype(str) + " " + ref.astype(str)
    raw_amount = pd.to_numeric(df_raw[amt_col].astype(str).str.replace(",", ""), errors="coerce")
    df["amount"] = raw_amount
    df = df[df["amount"] < 0].copy()
    df["amount"] = df["amount"].abs()
    return _normalise(df, source)


def _parse_revolut(df_raw: pd.DataFrame, source: str) -> pd.DataFrame | None:
    cols = [c.lower().strip() for c in df_raw.columns]
    if "completed date" not in cols and "started date" not in cols:
        return None
    df_raw.columns = cols
    date_col = "completed date" if "completed date" in cols else "started date"
    df = pd.DataFrame()
    df["date"] = _to_date(df_raw[date_col])
    df["description"] = df_raw["description"]
    raw_amount = pd.to_numeric(df_raw["amount"].astype(str).str.replace(",", ""), errors="coerce")
    df["amount"] = raw_amount
    df = df[df["amount"] < 0].copy()
    df["amount"] = df["amount"].abs()
    return _normalise(df, source)


def _parse_lloyds(df_raw: pd.DataFrame, source: str) -> pd.DataFrame | None:
    cols = [c.lower().strip() for c in df_raw.columns]
    if "transaction description" not in cols or "debit amount" not in cols:
        return None
    df_raw.columns = cols
    df = pd.DataFrame()
    df["date"] = _to_date(df_raw["transaction date"])
    df["description"] = df_raw["transaction description"]
    df["amount"] = pd.to_numeric(
        df_raw["debit amount"].astype(str).str.replace(",", ""), errors="coerce"
    )
    df = df[df["amount"] > 0]
    return _normalise(df, source)


def _parse_hsbc(df_raw: pd.DataFrame, source: str) -> pd.DataFrame | None:
    cols = [c.lower().strip() for c in df_raw.columns]
    if "debit" not in cols or "credit" not in cols:
        return None
    df_raw.columns = cols
    desc_col = "description" if "description" in cols else cols[1]
    df = pd.DataFrame()
    df["date"] = _to_date(df_raw["date"])
    df["description"] = df_raw[desc_col]
    df["amount"] = pd.to_numeric(
        df_raw["debit"].astype(str).str.replace(",", ""), errors="coerce"
    )
    df = df[df["amount"] > 0]
    return _normalise(df, source)


def _parse_amex_detailed(df_raw: pd.DataFrame, source: str) -> pd.DataFrame | None:
    """Amex UK CSV with Transaction Date, Billing Amount, Merchant, Debit or Credit."""
    cols = [c.lower().strip() for c in df_raw.columns]
    if "billing amount" not in cols or "merchant" not in cols or "debit or credit" not in cols:
        return None
    df_raw.columns = cols
    # Find the date column
    date_col = "transaction date" if "transaction date" in cols else "posting date"
    # Keep only debits (DBIT)
    df_debits = df_raw[df_raw["debit or credit"].str.upper() == "DBIT"].copy()
    if df_debits.empty:
        return None
    df = pd.DataFrame()
    df["date"] = _to_date(df_debits[date_col])
    df["description"] = df_debits["merchant"].astype(str).str.strip()
    df["amount"] = pd.to_numeric(
        df_debits["billing amount"].astype(str).str.replace(",", ""), errors="coerce"
    )
    df = df[df["amount"] > 0]
    return _normalise(df, source)


def _parse_amex(df_raw: pd.DataFrame, source: str) -> pd.DataFrame | None:
    cols = [c.lower().strip() for c in df_raw.columns]
    if "amount" in cols and "description" in cols and len(cols) <= 6:
        df_raw.columns = cols
        df = pd.DataFrame()
        df["date"] = _to_date(df_raw["date"])
        df["description"] = df_raw["description"]
        df["amount"] = pd.to_numeric(
            df_raw["amount"].astype(str).str.replace(",", ""), errors="coerce"
        )
        # Amex: positive = charge, negative = credit/refund
        df = df[df["amount"] > 0]
        return _normalise(df, source)
    return None


# ---------------------------------------------------------------------------
# Generic / fallback parser
# ---------------------------------------------------------------------------

def _parse_generic(df_raw: pd.DataFrame, source: str) -> pd.DataFrame:
    """Best-effort parser: look for date-like, description-like and amount-like columns."""
    cols = [c.lower().strip() for c in df_raw.columns]
    df_raw.columns = cols

    # Find date column
    date_col = None
    for candidate in ("date", "transaction date", "trans date", "posted date", "value date"):
        if candidate in cols:
            date_col = candidate
            break
    if date_col is None:
        for c in cols:
            if "date" in c:
                date_col = c
                break
    if date_col is None:
        date_col = cols[0]

    # Find description column
    desc_col = None
    for candidate in ("description", "transaction description", "narrative",
                       "details", "memo", "name", "payee", "merchant"):
        if candidate in cols:
            desc_col = candidate
            break
    if desc_col is None:
        for c in cols:
            if "desc" in c or "narr" in c or "detail" in c or "memo" in c:
                desc_col = c
                break
    if desc_col is None:
        desc_col = cols[1] if len(cols) > 1 else cols[0]

    # Find amount column
    amt_col = None
    for candidate in ("amount", "debit", "debit amount", "value", "transaction amount"):
        if candidate in cols:
            amt_col = candidate
            break
    if amt_col is None:
        for c in cols:
            if "amount" in c or "debit" in c or "value" in c:
                amt_col = c
                break
    if amt_col is None:
        amt_col = cols[-1]

    df = pd.DataFrame()
    df["date"] = _to_date(df_raw[date_col])
    df["description"] = df_raw[desc_col].astype(str)
    raw_amount = pd.to_numeric(
        df_raw[amt_col].astype(str).str.replace(",", "").str.replace("£", ""), errors="coerce"
    )
    df["amount"] = raw_amount.abs()
    return _normalise(df, source)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

PARSERS = [
    _parse_amex_detailed,
    _parse_monzo,
    _parse_starling,
    _parse_revolut,
    _parse_lloyds,
    _parse_hsbc,
    _parse_amex,
]


def parse_statement(file: BinaryIO, filename: str) -> pd.DataFrame:
    """
    Read a CSV (or Excel) statement file and return a normalised DataFrame.

    Tries bank-specific parsers first; falls back to the generic parser.
    """
    filename_lower = filename.lower()

    if filename_lower.endswith((".xlsx", ".xls")):
        df_raw = pd.read_excel(file)
    else:
        content = file.read()
        # Try common encodings
        for enc in ("utf-8", "latin-1", "cp1252"):
            try:
                text = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = content.decode("utf-8", errors="replace")

        # Skip leading blank / header lines that some banks add
        lines = text.strip().splitlines()
        start = 0
        for i, line in enumerate(lines):
            if "," in line and len(line.split(",")) >= 3:
                start = i
                break
        cleaned = "\n".join(lines[start:])
        df_raw = pd.read_csv(io.StringIO(cleaned), on_bad_lines="skip")

    if df_raw.empty:
        return pd.DataFrame(columns=["date", "description", "amount", "source_file"])

    # Try specialised parsers in order
    for parser_fn in PARSERS:
        result = parser_fn(df_raw, filename)
        if result is not None and not result.empty:
            return result

    # Fallback
    return _parse_generic(df_raw, filename)


def parse_multiple(files: list[tuple[BinaryIO, str]]) -> pd.DataFrame:
    """Parse several statement files and concatenate into one DataFrame."""
    frames = []
    for fobj, fname in files:
        frames.append(parse_statement(fobj, fname))
    if not frames:
        return pd.DataFrame(columns=["date", "description", "amount", "source_file"])
    return pd.concat(frames, ignore_index=True)
