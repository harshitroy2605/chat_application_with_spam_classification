import sqlite3
import secrets
import hashlib
from getpass import getpass

def hash_password(password, salt):
	return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200000).hex()



name = input("Name: ").strip()
email = input("Email: ").strip().lower()
password = getpass("Password: ")

if name == "" or email == "" or password == "":
	print("All fields are required")
	raise SystemExit(1)

salt = secrets.token_bytes(16)


conn = sqlite3.connect("users.db")
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS Users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, salt TEXT NOT NULL, password TEXT NOT NULL)")
try:
	cur.execute("INSERT INTO Users (name, email, salt, password) VALUES (?, ?, ?, ?)", (name, email, salt.hex(), hash_password(password, salt)))
	conn.commit()
	print("User", email, "added")
except sqlite3.IntegrityError:
	print("A user with this email already exists")
conn.close()