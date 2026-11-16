"""Start the concert queue from its production batch directory."""
import sys
from pathlib import Path

root = Path("/Users/gold/repos/adele")
sys.path.insert(0, str(root))
from workflow.priority_delivery import HERE, locked, schedule
import os

if __name__ == "__main__":
    with locked(HERE / "priority.lock"):
        (HERE / "priority.pid").write_text(str(os.getpid()))
        schedule()
