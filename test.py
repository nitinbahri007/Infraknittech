# test.py
from db import get_db_connection

def test_db_connection():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        print("✅ DB Connected Successfully")

        # Simple test query
        cursor.execute("SELECT NOW();")
        result = cursor.fetchone()

        print("🕒 DB Time:", result[0])

        cursor.close()
        conn.close()
        print("✅ Test Completed Successfully")

    except Exception as e:
        print("❌ DB Test Failed")
        print("Error:", str(e))


if __name__ == "__main__":
    print("===== DB TEST START =====")
    test_db_connection()
    print("===== DB TEST END =====")