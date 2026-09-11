from fastapi import FastAPI, Request
from src.shared.helper import email_verifier
import sqlite3 as sql
from src.dtos import passport
# from dtos import User

app = FastAPI()



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

#insert into database
@app.post("/passport")
def insert_into_db(data: passport):
    db = sql.connect("src/Database/user.db")
    cursor = db.cursor()
    query = data.model_dump()
    cursor.execute(f"insert into passport_table values ('{query.get('name')}','{query.get('dob')}','{query.get('gender')}','{query.get('place_of_issue')}','{query.get('date_of_issue')}','{query.get('date_of_expiry')}','{query.get('mrz')}')")
    fetcher = cursor.fetchall()
    db.commit()
    return {"Status": "OK",
            "Method": "POST",
            "Query": query,
            "fetcher":fetcher,
            "Msg": "Data has been added to database"
            }