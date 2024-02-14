from datetime import datetime
from pathlib import Path


now_str = datetime.strftime(datetime.now(), "%Y-%m-%d_%H-%M-%S")


class Paths:
    PROJECT_ROOT_DIR = Path(__file__).parent.parent
    DATA_DIR: Path = PROJECT_ROOT_DIR / "data"
    VOICES_DIR: Path = DATA_DIR / "voices"
    JOBS_DIR: Path = DATA_DIR / "jobs"

    # create directories if they don't exist
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    VOICES_DIR.mkdir(parents=True, exist_ok=True)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)

    WEB_APP_DATA_DIR: Path = PROJECT_ROOT_DIR / "src" / "web_app" / "data"

    # create directories if they don't exist
    WEB_APP_DATA_DIR.mkdir(parents=True, exist_ok=True)

    # config files
    CONFIGS_DIR: Path = PROJECT_ROOT_DIR / "configs"
    LOGIN_CONFIG_PATH: Path = CONFIGS_DIR / "login_config.yaml"

    PIPELINE_INFO_PATH: Path = PROJECT_ROOT_DIR / "subtitle-pipeline.json"

paths = Paths()
