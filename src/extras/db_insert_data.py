import sqlite3 as sql

db_name = input("Enter the relative file path of the database:\t")
connector = sql.connect(db_name)


cursor = connector.cursor()
flag = True
while flag:
    query = input("Enter the query to be executed: \t")
    if query.lower() == "exit":
        print("Exisiting the program...")
        flag = False
        break

    try:
        cursor.execute(query)
        if query.lower().startswith("select"):
            print(cursor.fetchall())
    except Exception as e:
        print(f"[ERROR] The query caused an Error: as\n{e}")

