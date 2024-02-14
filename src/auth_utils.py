import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader

from src.logger import root_logger
from src.paths import paths


app_logger = root_logger.getChild("auth_utils")


def generate_password_hash(password: str) -> str:
    """Generate a password hash.

    Args:
        password (str): The password to hash.

    Returns:
        str: The password hash.
    """
    return stauth.Hasher([password]).generate()[0]


def create_user(username: str, name: str, email: str, password: str, ispreauthorized: bool = True) -> bool:
    app_logger.info(f"Creating user {username}")
    password_hash = generate_password_hash(password)

    yaml_path = paths.LOGIN_CONFIG_PATH

    if not yaml_path.exists():
        app_logger.info("Creating login config file")
        yaml_path.parent.mkdir(parents=True, exist_ok=True)
        yaml_path.touch()

        config = {
            "credentials": {"usernames": {}},
            "cookie": {"expiry_days": 0, "key": "ekam-cookie_key", "name": "ekam-cookie"},
            "preauthorized": {"emails": []},
        }
        with open(yaml_path, "w") as file:
            yaml.dump(config, file, default_flow_style=False)

    with open(yaml_path) as file:
        config = yaml.load(file, Loader=SafeLoader)

    config["credentials"]["usernames"][username] = {  # type: ignore
        "email": email,
        "name": name,
        "password": password_hash,
    }

    if ispreauthorized:
        if email not in config["preauthorized"]["emails"]:  # type: ignore
            app_logger.error(f"Annotator {username} is not preauthorized")
            return False

    with open(yaml_path, "w") as file:
        yaml.dump(config, file)

    return True


def delete_user(username: str) -> bool:
    with open(paths.LOGIN_CONFIG_PATH) as file:
        config = yaml.load(file, Loader=SafeLoader)

    try:
        # delete the annotator from the login config
        del config["credentials"]["usernames"][username]
        with open(paths.LOGIN_CONFIG_PATH, "w") as file:
            yaml.dump(config, file, default_flow_style=False)
        return True
    except KeyError:
        app_logger.error(f"Annotator {username} does not exist")
        return False


def list_users() -> list:
    with open(paths.LOGIN_CONFIG_PATH) as file:
        config = yaml.load(file, Loader=SafeLoader)
    return list(config["credentials"]["usernames"].keys())  # type: ignore
