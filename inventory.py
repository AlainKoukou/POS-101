from database import get_connection

def list_items():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM items")

    items = cursor.fetchall()

    conn.close()
    return items
