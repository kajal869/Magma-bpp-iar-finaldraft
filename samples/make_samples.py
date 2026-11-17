"""Create the fictional demo inputs (closing slip + quote) used by the demo case and the tests.

    python samples/make_samples.py            # writes samples/demo_closing_slip.xlsx and samples/demo_quote.xlsx

All names, identifiers and amounts are made up.
"""
import datetime
import sys
from pathlib import Path

import openpyxl

HERE = Path(__file__).resolve().parent

NAME = "ACME PRECISION PRODUCTS PRIVATE LIMITED"
ADDRESS = "PLOT 10, EXAMPLE INDUSTRIAL AREA, BENGALURU 560001 KARNATAKA"
GSTIN = "29ABCDE1234F1Z5"


def make_slip(path, name=NAME, gstin=GSTIN, start=datetime.datetime(2026, 4, 1), end=datetime.datetime(2027, 3, 31), premium=29689):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Closing Slip"
    ws["A1"] = "Business Protect Policy Closing Slip"
    cells = {
        "A4": "Office Name/Code", "B4": "BENGALURU / 900001", "C4": "Sales Manager (Employee Name/Code)", "D4": "SAMPLE MANAGER / G00000",
        "A6": "Channel (Dropdown)", "B6": "Agency", "C6": "Business Type (Dropdown)", "D6": "New Business",
        "A8": "If Renewal (Expiring Policy No.)", "C8": "GC Policy/Product Name (Dropdown)", "D8": "Business Protect Policy (Laghu Udyam) (Commercial)",
        "A10": "Name of the Insured", "B10": name,
        "A11": "Insured's Communication Address", "B11": ADDRESS,
        "A12": "GST No.", "B12": gstin,
        "A16": "Policy Start Date", "B16": start, "C16": "Policy End Date", "D16": end,
        "A18": "Intermediary Name/Code", "B18": "SAMPLE BROKING SERVICES PRIVATE LIMITED/BRC0000000", "C18": "Intermediary Commission %", "D18": 0.2,
        "A20": "Terrorism Cover Opted (Dropdown)", "B20": "No",
        "A24": "100% Premium Amount (INR)\nIncluding GST", "B24": premium,
        "A31": "Whether Magma is Leader/ Follower (Dropdown)", "B31": "Leader", "C31": "Our Share", "D31": 1,
        "A33": "Our Share Premium (INR)\nIncluding GST", "B33": premium,
        "A57": "Top Location Details", "A58": "Policy Name", "B58": "Business Protect Policy (Laghu Udyam) (Commercial)",
        "A60": "Product Code", "B60": 9987, "A62": "UIN Number", "B62": "IRDAN149CP0001V01202122",
        "A66": "Location Address (with Pin Code)", "B66": ADDRESS, "A68": "Occupancy", "B68": "Workshop and office",
    }
    for k, v in cells.items():
        ws[k] = v
    wb.save(path)


def make_quote(path, name=NAME):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Quote"
    rows = [
        ["MAGMA GENERAL INSURANCE LTD"], ["BUSINESS PROTECT POLICY (LAGHU UDYAM) QUOTATION"], [],
        [1, "Name of Insured", name], [2, "Correspondence Address", ADDRESS], [3, "Policy Period", "Premium Receipt Date to 12 Months"],
        [4, "Risk Location", ADDRESS], [5, "Type of occupation", "LIGHT ENGINEERING WORKSHOP"], [6, "Financial interest", "SAMPLE BANK LIMITED"], [],
        [None, "Description", None, "Sum insured", "Premium rate", "Premium"],
        ["I", "Fire"], [None, "Building", None, 60000000], [None, "Contents", None, 20000000], [None, "Total Sum Insured", None, 80000000],
        [None, "STFI + EQ", None, 80000000, 0.3, 24000],
        ["II", "Burglary and House Breaking", "First loss basis - 100%", 10000000, 0.1, 1000],
        ["IV", "Money insurance", "Estimated Annual Turnover", 600000, 0.1, 60],
        [None, "Cash in Till / Counter", None, 300000, 0.17, 50],
        [None, "Cash in safe / strong room", None, 300000, 0.17, 50],
        [None, "TOTAL", None, None, None, 25160], [None, "GST", None, None, 0.18, 4528.8], [None, "Total premium with GST", None, None, None, 29688.8],
    ]
    for r in rows:
        ws.append(r)
    wb.save(path)


if __name__ == "__main__":
    make_slip(HERE / "demo_closing_slip.xlsx")
    make_quote(HERE / "demo_quote.xlsx")
    print("wrote", HERE / "demo_closing_slip.xlsx", "and", HERE / "demo_quote.xlsx")
    sys.exit(0)
