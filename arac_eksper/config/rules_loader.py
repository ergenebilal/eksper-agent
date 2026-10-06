from pathlib import Path
import yaml

RULES_PATH = Path(__file__).parent / "rules.yaml"


def load_rules() -> dict:
    with open(RULES_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["rules"]
