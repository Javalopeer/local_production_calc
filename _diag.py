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
