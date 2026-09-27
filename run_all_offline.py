"""Run lessons 01-15 offline with the 'test' model. Verifies nothing crashes.

Excluded (inherently live): 00_* smokes (OmniRoute / AI Gateway) and
16_acp_matrix (drives real CLI harnesses). 12_telemetry exports spans to
Phoenix if it's up, else logs export errors and still exits 0.
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent

env = {**os.environ, "PYDANTIC_AI_MODEL": "test", "PYDANTIC_AI_NO_BANNER": "1"}
failed: list[str] = []
files = [f for f in sorted(HERE.glob("0[1-9]*.py")) + sorted(HERE.glob("1*.py"))
         if f.name != "16_acp_matrix.py"]
for f in files:
    print(f"\n===== {f.name} =====")
    p = subprocess.run([sys.executable, str(f)], cwd=HERE, env=env,
                       capture_output=True, text=True)
    print(p.stdout[-3000:] if len(p.stdout) > 3000 else p.stdout, end="")
    if p.returncode != 0:
        failed.append(f.name)
        print(p.stderr[-2000:])
print("\nAll examples ran OK (offline, test model)." if not failed
      else f"\nFAILED: {failed}")
