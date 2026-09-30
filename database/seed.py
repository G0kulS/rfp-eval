import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    sys.path.insert(0, str(ROOT))
    storage = importlib.import_module("core.storage")
    config = importlib.import_module("core.config")
    reset = "--reset" in sys.argv[1:]
    storage.prepare_database(reset_criteria=reset)
    print(f"Database ready at {config.database_path()}")
    for row in storage.list_criteria():
        state = "active" if row["active"] else "inactive"
        print(f"{row['id']}. {row['title']} - weight {row['weight']:g}, max {row['max_points']:g}, {state}")


if __name__ == "__main__":
    main()
