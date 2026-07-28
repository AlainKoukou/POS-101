import sqlite3

def get_connection():
    conn = sqlite3.connect("pos.db")
    return conn
