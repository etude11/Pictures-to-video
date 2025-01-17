import os
import psycopg2

db = psycopg2.connect(os.environ["DATABASE_URL"])

cursor = db.cursor()
cursor.execute("SELECT now()")
res = cursor.fetchall()
db.commit()
print(res)