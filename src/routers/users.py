from fastapi import FastAPI, Request
from src.shared.helper import email_verifier

app = FastAPI()

# New user
@app.post("/newuser")
def new_user(requsts: Request):
    return 0

# Roles
@app.get("/roles")
def get_roles():
    return 0

# username
@app.get("/username")
def get_username():
    return 0

#password
@app.get("/password")
def get_password():
    return 0