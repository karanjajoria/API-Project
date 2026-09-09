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