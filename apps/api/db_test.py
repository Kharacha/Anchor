import os
from dotenv import load_dotenv
from urllib.parse import urlparse
import psycopg

load_dotenv(override=True)

url = os.getenv("DATABASE_URL")
u = urlparse(url)

print("HOST =", u.hostname)
print("USER =", u.username)
print("DB   =", u.path)

with psycopg.connect(url) as conn:
    with conn.cursor() as cur:
        cur.execute("select current_user, inet_server_addr(), version();")
        print(cur.fetchone())
print("CONNECTED OK")
