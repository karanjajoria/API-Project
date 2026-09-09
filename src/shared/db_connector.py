import sqlite3 as sql

class database():
    def __init__(self, address:str):
        self.address = address
        self.connector = sql.connect(self.address)

    def connect_to_db(database: str | None=None):
        try:
            if any(database):
                connector = sql.connect(database)
                
            else:
                return "[ERROR] Please provide database" 
        except Exception as e:
            return f"[ERROR] An error occured while connecting to database: {e}"