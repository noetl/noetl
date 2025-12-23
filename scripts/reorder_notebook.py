#!/usr/bin/env python3
import json
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(message)s')

# Read notebook
with open('tests/fixtures/notebooks/regression_dashboard.ipynb', 'r') as f:
    nb = json.load(f)

cells = nb['cells']
logger.info(f"Original cell count: {len(cells)}")

# Correct logical order
ordered_cells = [
    cells[0],   # Title
    cells[21],  # Setup header  
    cells[20],  # Setup code
    cells[19],  # DB utilities header
    cells[18],  # DB utilities code
    cells[17],  # Execute test header
    cells[16],  # Execute test code
    cells[15],  # Monitoring header
    cells[14],  # Monitoring code
    cells[13],  # Analysis header
    cells[12],  # Analysis code
    cells[1],   # Validation header
    cells[11],  # Validation code
    cells[10],  # Error detection header
    cells[9],   # Error detection code
    cells[8],   # Visualizations header
    cells[7],   # Visualizations code
    cells[6],   # Historical header
    cells[5],   # Historical code
    cells[4],   # Export header
    cells[22],  # Export code (correct version)
    cells[23],  # Cleanup header
    cells[24],  # Cleanup code
    cells[25],  # Summary
]

nb['cells'] = ordered_cells

# Write back
with open('tests/fixtures/notebooks/regression_dashboard.ipynb', 'w') as f:
    json.dump(nb, f, indent=1)

logger.info("✓ Notebook reordered successfully")
logger.info(f"Total cells: {len(ordered_cells)}")
logger.info("\nFirst 10 cells:")
for i, cell in enumerate(ordered_cells[:10], 1):
    first_line = cell['source'][0][:60] if cell['source'] else ''
    logger.info(f"{i:2d}. {cell['cell_type']:8s} | {first_line}")
