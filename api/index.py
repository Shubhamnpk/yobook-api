from pathlib import Path
import importlib.util


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "api.py"

spec = importlib.util.spec_from_file_location("yobook_api_app", APP_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

app = module.app
