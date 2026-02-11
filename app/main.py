"""
Expense Tracker - Streamlit App (v2)

Category cards with inline transactions, re-categorize support,
and a clean dashboard — no clicks needed to understand each category.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.categoriser import Categoriser, CategoryConfig, OverrideStore
from app.parsers import parse_statement

# ---------------------------------------------------------------------------
# Page config & custom CSS
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Expense Tracker", page_icon="💷", layout="wide")

st.markdown("""
<style>
    /* tighten spacing */
    .block-container { padding-top: 1.5rem; }
    /* metric cards */
    [data-testid="stMetric"] {
        background: linear-gradient(135deg, #667eea22, #764ba222);
        border-radius: 12px; padding: 14px 18px;
        border: 1px solid #e0e0e0;
    }
    [data-testid="stMetric"] label { font-size: 0.82rem; }
    /* category card */
    .cat-card {
        background: #ffffff; border-radius: 12px;
        border: 1px solid #e8e8e8; padding: 18px 20px;
        margin-bottom: 16px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.04);
    }
    .cat-header {
        display: flex; align-items: center; gap: 10px;
        margin-bottom: 8px;
    }
    .cat-icon { font-size: 1.6rem; }
    .cat-name { font-size: 1.15rem; font-weight: 600; color: #1a1a2e; }
    .cat-amount { font-size: 1.15rem; font-weight: 700; color: #2d3436; margin-left: auto; }
    .cat-meta { font-size: 0.82rem; color: #636e72; margin-bottom: 10px; }
    .cat-bar-bg {
        background: #f0f0f0; border-radius: 6px; height: 8px;
        margin-bottom: 14px; overflow: hidden;
    }
    .cat-bar-fill { height: 100%; border-radius: 6px; }
    /* txn row */
    .txn-row {
        display: flex; align-items: center; gap: 8px;
        padding: 6px 0; border-bottom: 1px solid #f5f5f5;
        font-size: 0.88rem;
    }
    .txn-row:last-child { border-bottom: none; }
    .txn-date { color: #636e72; min-width: 80px; }
    .txn-desc { flex: 1; color: #2d3436; }
    .txn-amt { font-weight: 600; color: #2d3436; min-width: 75px; text-align: right; }
    .txn-big { color: #d63031; }
    /* override badge */
    .override-badge {
        background: #ffeaa7; color: #636e72; font-size: 0.7rem;
        padding: 1px 6px; border-radius: 8px; margin-left: 4px;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Colour palette for categories
# ---------------------------------------------------------------------------
PALETTE = [
    "#667eea", "#764ba2", "#f7971e", "#00b894", "#e17055",
    "#0984e3", "#6c5ce7", "#fdcb6e", "#00cec9", "#d63031",
    "#e84393", "#55efc4",
]

def cat_colour(idx: int) -> str:
    return PALETTE[idx % len(PALETTE)]

# ---------------------------------------------------------------------------
# Initialise categoriser (fresh each run to pick up overrides)
# ---------------------------------------------------------------------------

def get_categoriser() -> Categoriser:
    return Categoriser()

categoriser = get_categoriser()
cfg = categoriser.config

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.sidebar.title("📂 Upload Statements")
st.sidebar.markdown("Upload **CSV** or **Excel** files from your bank or credit card.")

uploaded_files = st.sidebar.file_uploader(
    "Choose files", type=["csv", "xlsx", "xls"],
    accept_multiple_files=True,
    help="Monzo, Starling, Revolut, HSBC, Amex, Lloyds/Halifax, or any generic CSV.",
)

st.sidebar.markdown("---")
st.sidebar.subheader("📅 Date Range")
today = date.today()
default_start = today - timedelta(days=14)
col_from, col_to = st.sidebar.columns(2)
date_from = col_from.date_input("From", value=default_start)
date_to = col_to.date_input("To", value=today)

st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ Settings")
threshold = st.sidebar.number_input(
    "Itemised threshold (£)", min_value=0.0,
    value=float(cfg.itemised_threshold), step=5.0,
    help="Transactions above this amount are highlighted.",
)

# Show override count
overrides = categoriser.overrides.all_overrides()
if overrides:
    st.sidebar.markdown("---")
    st.sidebar.caption(f"🔄 {len(overrides)} merchant override(s) saved")
    if st.sidebar.button("Clear all overrides"):
        import os
        from app.categoriser import OVERRIDES_PATH
        if OVERRIDES_PATH.exists():
            os.remove(OVERRIDES_PATH)
        st.rerun()

# ---------------------------------------------------------------------------
# Title
# ---------------------------------------------------------------------------

st.title("💷 Expense Tracker")

if not uploaded_files:
    st.info(
        "👈 Upload bank or credit-card statements from the sidebar to get started.\n\n"
        "**Supported:** Monzo · Starling · Revolut · HSBC · Amex · Lloyds/Halifax · Generic CSV"
    )
    with st.expander("📋 What should my CSV look like?"):
        st.markdown("""
Your CSV needs at minimum: **Date**, **Description** (or Merchant), and **Amount** columns.

| Date | Description | Amount |
|------|-------------|--------|
| 28/01/2026 | TESCO STORES | 45.30 |
| 27/01/2026 | UBER *TRIP | 12.50 |

The tool also supports Amex-style CSVs with `Transaction Date`, `Billing Amount`, `Merchant`, `Debit or Credit` columns.
        """)
    st.stop()

# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner="Parsing statements…")
def load_data(files_bytes: list[tuple[bytes, str]]) -> pd.DataFrame:
    import io as _io
    frames = []
    for content, name in files_bytes:
        frames.append(parse_statement(_io.BytesIO(content), name))
    if not frames:
        return pd.DataFrame(columns=["date", "description", "amount", "source_file"])
    return pd.concat(frames, ignore_index=True)

files_input = [(f.getvalue(), f.name) for f in uploaded_files]
df_all = load_data(files_input)

if df_all.empty:
    st.warning("No transactions could be parsed. Please check the file format.")
    st.stop()

# ---------------------------------------------------------------------------
# Filter by date
# ---------------------------------------------------------------------------

df_all["date"] = pd.to_datetime(df_all["date"])
mask = (df_all["date"].dt.date >= date_from) & (df_all["date"].dt.date <= date_to)
df = df_all.loc[mask].copy()

if df.empty:
    st.warning(f"No transactions between **{date_from:%d %b %Y}** and **{date_to:%d %b %Y}**.")
    st.stop()

# ---------------------------------------------------------------------------
# Categorise
# ---------------------------------------------------------------------------

df["category"] = df["description"].apply(categoriser.categorise)
df = df.sort_values("date", ascending=False).reset_index(drop=True)

total_spend = df["amount"].sum()
n_txns = len(df)
n_days = max((date_to - date_from).days, 1)

# ---------------------------------------------------------------------------
# Metrics row
# ---------------------------------------------------------------------------

st.markdown("---")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Total Spend", f"£{total_spend:,.2f}")
m2.metric("Transactions", f"{n_txns}")
m3.metric("Daily Average", f"£{total_spend / n_days:,.2f}")
m4.metric("Period", f"{n_days} days")

# ---------------------------------------------------------------------------
# Charts row: donut + daily trend
# ---------------------------------------------------------------------------

cat_summary = (
    df.groupby("category")
    .agg(total=("amount", "sum"), count=("amount", "size"))
    .sort_values("total", ascending=False)
    .reset_index()
)
cat_summary["pct"] = (cat_summary["total"] / total_spend * 100).round(1)

st.markdown("---")
chart1, chart2 = st.columns([1, 1.3])

with chart1:
    st.subheader("📊 Category Split")
    fig = px.pie(
        cat_summary, names="category", values="total", hole=0.45,
        color_discrete_sequence=PALETTE,
    )
    fig.update_traces(textposition="inside", textinfo="percent+label", textfont_size=11)
    fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=False, height=380)
    st.plotly_chart(fig, use_container_width=True)

with chart2:
    st.subheader("📈 Daily Trend")
    daily = (
        df.groupby([df["date"].dt.date, "category"])
        .agg(total=("amount", "sum")).reset_index()
    )
    daily.columns = ["date", "category", "total"]
    fig2 = px.bar(
        daily, x="date", y="total", color="category",
        color_discrete_sequence=PALETTE,
        labels={"total": "Amount (£)", "date": "", "category": ""},
    )
    fig2.update_layout(
        barmode="stack", height=380,
        margin=dict(t=10, b=30, l=40, r=10),
        legend=dict(orientation="h", yanchor="bottom", y=-0.25, xanchor="center", x=0.5, font_size=10),
    )
    st.plotly_chart(fig2, use_container_width=True)

# ---------------------------------------------------------------------------
# Category cards — each one shows all its transactions inline
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("🗂️ Spending by Category")
st.caption("Every category with its transactions. Use the dropdown to move a merchant to a different category.")

all_cats = categoriser.all_categories()

for cat_idx, row in cat_summary.iterrows():
    cat_name = row["category"]
    cat_total = row["total"]
    cat_count = int(row["count"])
    cat_pct = row["pct"]
    icon = categoriser.get_icon(cat_name)
    colour = cat_colour(cat_idx)

    df_cat = df[df["category"] == cat_name].copy()

    # Card header via HTML
    st.markdown(f"""
    <div class="cat-card">
        <div class="cat-header">
            <span class="cat-icon">{icon}</span>
            <span class="cat-name">{cat_name}</span>
            <span class="cat-amount">£{cat_total:,.2f}</span>
        </div>
        <div class="cat-meta">{cat_count} transaction{'s' if cat_count != 1 else ''} · {cat_pct}% of total</div>
        <div class="cat-bar-bg">
            <div class="cat-bar-fill" style="width:{cat_pct}%; background:{colour};"></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Transactions table (always visible)
    df_show = df_cat.copy()
    df_show["Date"] = df_show["date"].dt.strftime("%d %b %Y")
    df_show["Description"] = df_show["description"]
    df_show["Amount (£)"] = df_show["amount"].apply(lambda x: f"£{x:,.2f}")

    # Highlight big spends
    big_mask = df_show["amount"] > threshold

    with st.expander(f"View {cat_count} transaction{'s' if cat_count != 1 else ''}", expanded=(cat_count <= 15)):
        # Show transactions
        st.dataframe(
            df_show[["Date", "Description", "Amount (£)"]],
            use_container_width=True, hide_index=True,
        )

        # Re-categorise widget: pick a merchant from this category to move
        unique_merchants = sorted(df_cat["description"].unique())
        if len(unique_merchants) > 0:
            recat_col1, recat_col2, recat_col3 = st.columns([2, 2, 1])
            with recat_col1:
                merchant_to_move = st.selectbox(
                    "Move merchant",
                    options=[""] + unique_merchants,
                    key=f"move_from_{cat_name}",
                    label_visibility="collapsed",
                    placeholder="Select merchant to re-categorise…",
                )
            with recat_col2:
                target_cats = [c for c in all_cats if c != cat_name]
                new_cat = st.selectbox(
                    "To category",
                    options=[""] + target_cats,
                    key=f"move_to_{cat_name}",
                    format_func=lambda c: f"{categoriser.get_icon(c)} {c}" if c else "Select target category…",
                    label_visibility="collapsed",
                )
            with recat_col3:
                if st.button("Move ➜", key=f"move_btn_{cat_name}", use_container_width=True):
                    if merchant_to_move and new_cat:
                        categoriser.recategorise(merchant_to_move, new_cat)
                        st.toast(f"✅ **{merchant_to_move}** → {categoriser.get_icon(new_cat)} {new_cat}")
                        st.rerun()
                    else:
                        st.warning("Select both a merchant and a target category.")

# ---------------------------------------------------------------------------
# Itemised big spends
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader(f"🔍 Itemised Transactions Over £{threshold:,.0f}")

df_big = df[df["amount"] > threshold].copy()
if df_big.empty:
    st.success(f"No transactions exceed £{threshold:,.0f} in this period. 🎉")
else:
    df_big = df_big.sort_values("amount", ascending=False)
    df_big["Date"] = df_big["date"].dt.strftime("%d %b %Y")
    df_big["Category"] = df_big["category"].apply(lambda c: f"{categoriser.get_icon(c)} {c}")
    df_big["Amount (£)"] = df_big["amount"].apply(lambda x: f"£{x:,.2f}")
    st.dataframe(
        df_big[["Date", "Category", "description", "Amount (£)"]].rename(columns={"description": "Description"}),
        use_container_width=True, hide_index=True,
    )
    big_total = df_big["amount"].sum()
    st.caption(
        f"**{len(df_big)}** transactions over £{threshold:,.0f} totalling "
        f"**£{big_total:,.2f}** ({big_total / total_spend * 100:.1f}% of total)"
    )

# ---------------------------------------------------------------------------
# Downloads
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("💾 Download")
dl1, dl2 = st.columns(2)
with dl1:
    st.download_button(
        "📥 Category Summary",
        data=cat_summary[["category", "total", "count", "pct"]].to_csv(index=False),
        file_name=f"expense_summary_{date_from}_{date_to}.csv", mime="text/csv",
    )
with dl2:
    exp = df[["date", "description", "amount", "category", "source_file"]].copy()
    exp["date"] = exp["date"].dt.strftime("%Y-%m-%d")
    st.download_button(
        "📥 All Transactions",
        data=exp.to_csv(index=False),
        file_name=f"expense_transactions_{date_from}_{date_to}.csv", mime="text/csv",
    )

st.markdown("---")
st.caption("💷 Expense Tracker · Categories are keyword-based — edit `config/categories.json` to customise · Re-categorisations are saved to `config/overrides.json`")
