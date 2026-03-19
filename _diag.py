# ⚠️  WARNING — DESTRUCTIVE SCRIPT ⚠️
# This script permanently DELETES sheets from the shared team Excel file.
# It was used once for a one-off cleanup and should NOT be run again without
# careful review.  Running it again will erase historical data for every
# designer whose sheet is not in the 'keep' list below.
#
# To recover lost data, use OneDrive version history on _TeamProduction.xlsx:
#   Right-click the file in the OneDrive web interface → Version history.

import sys
print("⚠️  WARNING: This script is destructive. It will delete Excel sheets.")
print("Edit the script and remove this guard if you really intend to run it.")
sys.exit(1)

import openpyxl, os

team = r'C:\Users\gerar\Envista\SPARK-GLB-OPS-ICON - Reports\Productions\_TeamProduction.xlsx'
wb = openpyxl.load_workbook(team)
print("Before:", wb.sheetnames)

# Keep only Dashboard and Gerardo
to_remove = [s for s in wb.sheetnames if s not in ('Dashboard', 'Gerardo')]
for s in to_remove:
    del wb[s]
    print(f"Removed sheet: {s}")

wb.save(team)
wb2 = openpyxl.load_workbook(team)
print("After:", wb2.sheetnames)
print("Done.")
