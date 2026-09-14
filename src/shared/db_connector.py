import sqlite3 as sql

class database():
    def __init__(self, address:str):
        self.address = address
        try:
            self.connector = sql.connect(self.address)
        except sql.Error as e:
            print(f"Error connecting to database: {e}")

    def execute_query(self,query:str | None=None):
        if query == None:
            print("Nothing was passed in the database.execute_query function.")

        try:
            cursor = self.connector.cursor()
            cursor.execute(query)
            if query.lower().startswith("select"):
                return cursor.fetchall()
            return f"{query} executed successfully"
        
        except Exception as e:     
            print(f"[ERROR] An error occured while working with database.execute_query as {e}")

    def fetch_data(self,query:str | None=None):
        if query == None:
            print("Nothing was passed in the database.fetch_data")
        try:
            cursor = self.connector.cursor()
            if not query.lower().startswith("select"):
                return 0

            cursor.execute(query)
            query_data = cursor.fetchall()

            return query_data

        except Exception as e:
            raise e 

LATEST_CAPTURE = {
    "available": False,
    "timestamp": None,
    "token": None,
    "frame_path": None,
    "face_crop_path": None,
    "icao_crop_path": None,
    "frame_base64": None,
    "face_crop_base64": None,
    "icao_crop_base64": None,
}

Token = "Tokens"
Passport = "Passports"
Camera = "Camera"

class Database:
    def __init__(self, db:str, data = LATEST_CAPTURE):
        self.data = LATEST_CAPTURE
        self.db = sql.connect(db)
        self.cursor = self.db.cursor()

    def execute_query(self):
        try:
            passport = Passport
            token = Token
            camera = Camera

            data = self.cursor.execute(f"SELECT * FROM {token}")
            data = data.fetchall()
            serial_number = data[-1][0]

            self.cursor.execute(f"Insert into {token} values ({serial_number + 1},'{self.data.get('token')}')")

        except Exception as e:
            return f"An error has occured {e}"