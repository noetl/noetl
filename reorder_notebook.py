#!/usr/bin/env python3
import json

# Read notebook
with open('tests/fixtures/notebooks/regression_dashboard.ipynb', 'r') as f:
    nb = json.load(f)

cells = nb['cells']

# Current order analysis - cells are backwards!
# Correct logical order should be:
ordered_cells = [
    cells[0],   # 1. Title
    cells[21],  # 2. Setup header  
    cells[20],  # 3. Setup code
    cells[19],  # 4. DB utilities header
    cells[18],  # 5. DB utilities code
    cells[17],  # 6. Execute test header
    cells[16],  # 7. Execute test code
    cells[15],  # 8. Monitoring header
    cells[14],  # 9. Monitoring code
    cells[13],  # 10. Analysis header
    cells[12],  # 11. Analysis code
    cells[1],   # 12. Validation header
    cells[11],  # 13. Validation code
    cells[10],  # 14. Error detection header
    cells[9],   # 15. Error detection code
    cells[8],   # 16. Visualizations header
    cells[7],   # 17. Visualizations code
    cells[6],   # 18. Historical header
    cells[5],   # 19. Historical code
    cells[4],   # 20. Export header
    cells[22],  # 21. Export code (correct version)
    cells[23],  # 22. Cleanup header
    cells[24],  # 23. Cleanup code
    cells[25],  # 24. Summary
]

nb['cells'] = ordered_cells

# Write back
with open('tests/fixtures/notebooks/regression_dashboard.ipynb', 'w') as f:
    json.dump(nb, f, indent=1)

print("✓ Notebook reordered successfully")
print(f"Total cells: {len(ordered_cells)}")
print("\nFirst 10 cells:")
for i, cell in enumerate(ordered_cells[:10], 1):
    first_line = cell['source'][0][:60] if cell['source'] else ''
    print(f"{i:2d}. {cell['cell_type']:8s} | {first_line}")
