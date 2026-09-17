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
    def __init__(self, db_path: str):
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.cursor = self.db.cursor()
        self.create_tables()

    def create_tables(self):
        """Creates both tables if they don't already exist — safe to call
        every startup; does nothing if they're already there."""
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS Tokens (
                ID INTEGER PRIMARY KEY AUTOINCREMENT,
                Token TEXT UNIQUE NOT NULL
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS Camera (
                Token TEXT NOT NULL,
                "Frame(b64)" TEXT,
                "ICAO(b64)" TEXT,
                Timestamp TEXT,
                FOREIGN KEY (Token) REFERENCES Tokens(Token)
            )
        """)
        self.db.commit()

    def insert_capture(self, data: dict) -> "str | None":
        token = data.get("token")
        if not token:
            return "No token in capture data — nothing to insert."

        try:
            # ID is AUTOINCREMENT — no manual COUNT-based ID computation
            # needed (a row COUNT is also not a safe stand-in for a unique
            # ID once any row is ever deleted, which was a bug in the
            # original draft regardless of the missing-column issue).
            self.cursor.execute("INSERT INTO Tokens (Token) VALUES (?)", (token,))
            self.cursor.execute(
                'INSERT INTO Camera (Token, "Frame(b64)", "ICAO(b64)", Timestamp) VALUES (?, ?, ?, ?)',
                (token, data.get("frame_base64"), data.get("icao_crop_base64"), data.get("timestamp")),
            )
            self.db.commit()
            return None
        except Exception as e:
            self.db.rollback()
            return f"Database insert failed: {e}"

    def close(self):
        try:
            self.db.close()
        except Exception:
            pass