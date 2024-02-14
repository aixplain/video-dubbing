import os
import sys

import streamlit as st
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader


current_file_path = os.path.dirname(os.path.abspath(__file__))
# aapedn 3 parent directories to the path
sys.path.append(os.path.join(current_file_path, "..", "..", ".."))

from dotenv import load_dotenv

from src.auth_utils import create_user, delete_user, list_users
from src.logger import root_logger
from src.paths import paths


BASE_DIR = str(paths.PROJECT_ROOT_DIR.resolve())

# load the .env file
load_dotenv(os.path.join(BASE_DIR, "vars.env"), override=True)
load_dotenv(os.path.join(BASE_DIR, "secrets.env"), override=True)  # THIS SHOULD ALWAYS BE BEFORE aixplain import


# set app name and icon
st.set_page_config(page_title="aiXplain's Automatic Video Dubbing App", page_icon="🎙️", layout="wide")

app_logger = root_logger.getChild("web_app::home")
BACKEND_URL = "http://{}:{}".format(os.environ.get("SERVER_HOST"), os.environ.get("SERVER_PORT"))


config_file_path = paths.LOGIN_CONFIG_PATH
with open(config_file_path) as file:
    config = yaml.load(file, Loader=SafeLoader)

authenticator = stauth.Authenticate(
    config["credentials"], config["cookie"]["name"], config["cookie"]["key"], config["cookie"]["expiry_days"], config["preauthorized"]
)

# sidebar
with st.sidebar:
    name, authentication_status, username = authenticator.login("Login", "main")
    if st.session_state["authentication_status"]:
        authenticator.logout("Logout", "main")
        st.write(f'Welcome *{st.session_state["name"]}*')
        choice = st.selectbox("Select an option", ["Create User", "Delete User"])
        if choice == "Create User":
            try:
                with st.form("Register user"):
                    email = st.text_input("Email")
                    username = st.text_input("Username")
                    name = st.text_input("Name")
                    password = st.text_input("Password", type="password")
                    repeat_password = st.text_input("Repeat password", type="password")
                    submit_button = st.form_submit_button("Add User")

                if submit_button:
                    if password == repeat_password:
                        # create user
                        created = create_user(username, name, email, password, ispreauthorized=True)
                        if not created:
                            st.error("Something went wrong. Please make sure that the user is preauthorized")
                        else:
                            st.success("User created successfully")
                    else:
                        st.error("Passwords do not match")
            except Exception as e:
                st.error(e)
        if choice == "Delete User":
            try:
                users = list_users()
                with st.form("Delete user"):
                    user_selected = st.selectbox("Users", users)
                    submit_button = st.form_submit_button("Delete User")
                if submit_button:
                    # delete user
                    is_deleted = delete_user(user_selected)
                    if not is_deleted:
                        st.error("Something went wrong in deleting the user")
                    else:
                        st.success(f"User {user_selected} deleted successfully")
            except Exception as e:
                st.error(f"Error: {e}")

    elif st.session_state["authentication_status"] is False:
        st.error("Username/password is incorrect")
        try:
            username_forgot_pw, email_forgot_password, random_password = authenticator.forgot_password("Forgot password")
            if username_forgot_pw:
                st.success("New password sent securely")
                with open(config_file_path, "w") as file:
                    yaml.dump(config, file, default_flow_style=False)
                # Random password to be transferred to user securely
            else:
                st.error("Username not found")
        except Exception as e:
            st.error(e)
    elif st.session_state["authentication_status"] is None:
        st.warning("Please enter your username and password")


st.title("Automatic Video Dubbing")
text = """
## Instructions
1. Upload the video file
2. TODO
"""


st.markdown(text)
