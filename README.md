# 💷 Expense Tracker

A personal expense tracking tool that reads your bank and credit-card
statements (CSV / Excel) and gives you an instant, categorised breakdown of
where your money went — with special attention to the last 2 weeks and
itemised detail for any spend over £30.

---

## ✨ Features

| Feature | Detail |
|---------|--------|
| **Multi-file upload** | Upload bank *and* credit-card CSVs together |
| **Auto-detection** | Recognises Monzo, Starling, Revolut, HSBC, Lloyds/Halifax, Barclays, Amex, or generic CSV |
| **Smart categorisation** | Keyword-based rules split spending into Shopping, Grocery, Dining, Fixed Monthly, Subscriptions, Local Travel, Experiences, and Other |
| **Date filtering** | Defaults to last 14 days; adjustable from the sidebar |
| **Itemised detail** | Any transaction above a configurable threshold (default £30) is shown individually |
| **Donut chart & daily trend** | Visual breakdown of where your money went |
| **Category drilldown** | Pick a category and see every transaction within it |
| **CSV export** | Download the summary or full categorised transaction list |
| **Fully customisable** | Edit `config/categories.json` to add keywords, new categories, or change the threshold |

---

## 🚀 Quick Start

### 1. Install

```bash
cd expense-tracker
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Run

```bash
streamlit run app/main.py
```

Opens in your browser at **http://localhost:8501**.

### 3. Upload your statements

- Export a CSV from your bank's online banking.
- Drag and drop the file(s) into the sidebar uploader.
- Adjust the date range if needed.

### 4. Try with sample data

Upload the files in `sample_data/` to test the tool.

---

## 📁 Project Structure

```
expense-tracker/
├── app/
│   ├── __init__.py
│   ├── categoriser.py    # Keyword-based categorisation engine
│   ├── main.py           # Streamlit web app (entry point)
│   └── parsers.py        # CSV/Excel parsers for multiple bank formats
├── config/
│   └── categories.json   # Category rules, keywords & threshold
├── sample_data/
│   ├── bank_statement_sample.csv
│   └── credit_card_sample.csv
├── requirements.txt
└── README.md
```

---

## ⚙️ Customising Categories

Open `config/categories.json` and:

- **Add keywords** to an existing category to improve matching.
- **Add a new category** by adding a new entry under `"categories"`.
- **Change the itemised threshold** via `"itemised_threshold_gbp"`.

---

## 🏦 Supported Statement Formats

| Bank / Provider | Notes |
|----------------|-------|
| **Monzo** | Auto-detected via `Transaction ID` column |
| **Starling** | Auto-detected via `Counter Party` column |
| **Revolut** | Auto-detected via `Completed Date` column |
| **HSBC** | Auto-detected via `Debit` / `Credit` columns |
| **Lloyds / Halifax** | Auto-detected via `Transaction Description` + `Debit Amount` |
| **Amex UK** | Auto-detected via `Date` + `Description` + `Amount` |
| **Generic** | Any CSV/Excel with Date, Description, and Amount columns |
