from fastapi import FastAPI, Request
from src.shared.helper import email_verifier

app = FastAPI()

# New user
@app.post("/newuser")
def new_user(requsts: Request):
    

# Roles
@app.get("/roles")
def get_roles():

# username
@app.get("/username")

#password
@app.get("/password"):