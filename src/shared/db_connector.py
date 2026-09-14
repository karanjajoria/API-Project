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

class Database:
    def __init__(self,db_path:str, table_name:str):
        self.table = table_name
        self.db = sql.connect(db_path)


    def execute(self,db,data:dict):
        '''
        data = {
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
        '''
        cursor = self.db.cursor()
        try:
            cursor.execute(f"INSERT INTO {self.table} VALUES('{data.get("token")}', '{data.get("icao_crop_base64")}')")
        except Exception as e:
            return f"There is an error {e}"