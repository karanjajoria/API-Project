from fastapi import FastAPI, Request
from src.shared.helper import email_verifier
import sqlite3 as sql
# from dtos import User

app = FastAPI()

# New user
# @app.post("/newuser")
# def new_user(user: User):
#     return 0

# # Roles
# @app.get("/roles")
# def get_roles():
#     return 0

# # username
# @app.get("/username")
# def get_username():
#     return 0

# #password
# @app.get("/password")
# def get_password():
#     return 0

# Welcome Page
@app.get("/")
def welcome():
    return {"message": "Welcome to the Passport-DB API"}

# fetch data from User.passport_table
@app.get("/passport/{name}")
def get_passport_data(name:str):
    db = sql.connect("src/Database/user.db")
    cursor = db.cursor()
    cursor.execute(f"Select * from passport_table where name = '{name}'")
    data = cursor.fetchone()
    if data == None:
        return {"Status": "Error", "Message": "No data found for the given name."}
    return {"Status": "OK", 
            "Name": data[0], 
            "DOB": data[1], 
            "Gender": data[2], 
            "Place of issue": data[3], 
            "MRZ": data[6], 
            "Date of Issue": data[4], 
            "Date of Expiry": data[5]
        }