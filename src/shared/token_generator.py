# Test file to check and verify token generation using random function
import random
import math
import sqlite3 as sql

db = sql.connect("src/Database/User.db")
table = "Tokens"

cursor = db.cursor()
cursor.execute(f"Select * from {table}")
data = cursor.fetchall()
serial_number = data[-1][0]

def Generate():
    token = random.randint(100000,999999)
    if token in data:
        Generate()
    cursor.execute(f"Insert into {table} values ({serial_number +1},{token})")
    db.commit()
