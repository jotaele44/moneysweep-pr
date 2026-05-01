import os
import pytest

if not os.path.exists("sample.dat"):
    pytest.skip("sample.dat not present — skipping SAM tests", allow_module_level=True)

with open("sample.dat") as f:
    lines = f.readlines()

rows = [line.strip().replace("!end","").split("|") for line in lines]

print(len(rows[0]))
