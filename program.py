import os
import socket
import sqlite3
import smtplib
import secrets
import hashlib
import threading
import queue
import time
import argparse
import textwrap
from email.message import EmailMessage
from tkinter import *
from tkinter import messagebox as popup

import pandas as pd
from dotenv import load_dotenv
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.model_selection import train_test_split
from sklearn.naive_bayes import MultinomialNB


load_dotenv()

parser = argparse.ArgumentParser()
parser.add_argument("--listen-port", type=int, default=int(os.getenv("LISTEN_PORT", "3050")))
parser.add_argument("--peer-host", default=os.getenv("PEER_HOST", "127.0.0.1"))
parser.add_argument("--peer-port", type=int, default=int(os.getenv("PEER_PORT", "4050")))
args = parser.parse_args()

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
OTP_VALID_SECONDS = 300
MAX_OTP_ATTEMPTS = 3


# ---------------------------- spam model ----------------------------

dataframe = pd.read_csv("spam.csv", encoding="latin-1", usecols=["v1", "v2"])
dataframe = dataframe.drop_duplicates()

cv = CountVectorizer()
x = cv.fit_transform(dataframe["v2"])
y = dataframe["v1"]

x_train, x_test, y_train, y_test = train_test_split(x, y, test_size=0.1, random_state=42)

#model = MultinomialNB()

model = MultinomialNB(fit_prior=False)


model.fit(x_train, y_train)
print("spam model accuracy:", round(model.score(x_test, y_test) * 100, 2), "%")
model.fit(x, y)

def spam_score(text):
	spam_index = list(model.classes_).index("spam")
	return model.predict_proba(cv.transform([text]))[0][spam_index]


# ---------------------------- database ----------------------------

def hash_password(password, salt):
	return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200000).hex()


def open_db():
	conn = sqlite3.connect("users.db")
	conn.execute("CREATE TABLE IF NOT EXISTS Users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, salt TEXT NOT NULL, password TEXT NOT NULL)")
	return conn


def add_user(name, email, password):
	salt = secrets.token_bytes(16)
	conn = open_db()
	try:
		conn.execute("INSERT INTO Users (name, email, salt, password) VALUES (?, ?, ?, ?)", (name, email, salt.hex(), hash_password(password, salt)))
		conn.commit()
		return True
	except sqlite3.IntegrityError:
		return False
	finally:
		conn.close()


def check_user(email, password):
	conn = open_db()
	cur = conn.cursor()
	cur.execute("SELECT name, salt, password FROM Users WHERE email=?", (email,))
	row = cur.fetchone()
	conn.close()
	if row is None:
		return None
	name, salt, stored = row
	if secrets.compare_digest(hash_password(password, bytes.fromhex(salt)), stored):
		return name
	return None


# ---------------------------- email otp ----------------------------

def send_otp(recipient, otp):
	if SMTP_USER == "" or SMTP_PASSWORD == "":
		print("SMTP not configured in .env, OTP for", recipient, "is", otp)
		return

	email = EmailMessage()
	email["From"] = SMTP_USER
	email["To"] = recipient
	email["Subject"] = "Your login OTP"
	email.set_content("Your OTP is " + otp + ". It is valid for 5 minutes.")

	if SMTP_PORT == 465:
		with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20) as smtp:
			smtp.login(SMTP_USER, SMTP_PASSWORD)
			smtp.send_message(email)
	else:
		with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as smtp:
			smtp.starttls()
			smtp.login(SMTP_USER, SMTP_PASSWORD)
			smtp.send_message(email)


# ---------------------------- application ----------------------------

class App(Tk):
	def __init__(self):
		super().__init__()
		self.title("Secure Chat")
		self.resizable(False, False)
		self.protocol("WM_DELETE_WINDOW", self.close_app)
		self.user_name = ""
		self.user_email = ""
		self.otp = ""
		self.otp_time = 0
		self.otp_attempts = 0
		self.incoming = queue.Queue()
		self.send_socket = None
		self.listen_socket = None
		self.send_lock = threading.Lock()
		self.login_page()

	def clear(self):
		for widget in self.winfo_children():
			widget.destroy()

	# ---------- login page ----------

	def login_page(self):
		self.clear()
		self.geometry("400x400")
		self.config(bg="white")

		Label(self, text="Login", font=("Arial", 26, "bold"), bg="white").place(x=150, y=40)

		Label(self, text="Email", font=("Arial", 11), bg="white").place(x=60, y=120)
		self.email_entry = Entry(self, font=("calibre", 10, "normal"), border=2)
		self.email_entry.place(x=60, y=145, width=280)

		Label(self, text="Password", font=("Arial", 11), bg="white").place(x=60, y=190)
		self.password_entry = Entry(self, font=("calibre", 10, "normal"), show="*", border=2)
		self.password_entry.place(x=60, y=215, width=280)
		self.password_entry.bind("<Return>", lambda event: self.login())

		self.login_button = Button(self, text="Login", command=self.login)
		self.login_button.place(x=80, y=270, width=110)
		Button(self, text="Register", command=self.register_page).place(x=210, y=270, width=110)

		self.status = Label(self, text="", fg="red", bg="white")
		self.status.place(x=60, y=320)
		self.email_entry.focus()

	# ---------- register page ----------

	def register_page(self):
		self.clear()
		self.geometry("400x480")

		Label(self, text="Register", font=("Arial", 26, "bold"), bg="white").place(x=130, y=30)

		Label(self, text="Name", font=("Arial", 11), bg="white").place(x=60, y=100)
		self.name_entry = Entry(self, font=("calibre", 10, "normal"), border=2)
		self.name_entry.place(x=60, y=125, width=280)

		Label(self, text="Email", font=("Arial", 11), bg="white").place(x=60, y=165)
		self.email_entry = Entry(self, font=("calibre", 10, "normal"), border=2)
		self.email_entry.place(x=60, y=190, width=280)

		Label(self, text="Password", font=("Arial", 11), bg="white").place(x=60, y=230)
		self.password_entry = Entry(self, font=("calibre", 10, "normal"), show="*", border=2)
		self.password_entry.place(x=60, y=255, width=280)

		Label(self, text="Confirm Password", font=("Arial", 11), bg="white").place(x=60, y=295)
		self.confirm_entry = Entry(self, font=("calibre", 10, "normal"), show="*", border=2)
		self.confirm_entry.place(x=60, y=320, width=280)
		self.confirm_entry.bind("<Return>", lambda event: self.register())

		Button(self, text="Create Account", command=self.register).place(x=70, y=370, width=125)
		Button(self, text="Back", command=self.login_page).place(x=205, y=370, width=125)

		self.status = Label(self, text="", fg="red", bg="white")
		self.status.place(x=60, y=420)
		self.name_entry.focus()

	def register(self):
		name = self.name_entry.get().strip()
		email = self.email_entry.get().strip().lower()
		password = self.password_entry.get()
		if name == "" or email == "" or password == "":
			self.status.config(text="All fields are required")
			return
		if "@" not in email or "." not in email.split("@")[-1]:
			self.status.config(text="Enter a valid email")
			return
		if len(password) < 6:
			self.status.config(text="Password must be at least 6 characters")
			return
		if password != self.confirm_entry.get():
			self.status.config(text="Passwords do not match")
			return
		if not add_user(name, email, password):
			self.status.config(text="This email is already registered")
			return
		popup.showinfo("Registered", "Account created, you can login now")
		self.login_page()

	def login(self):
		email = self.email_entry.get().strip().lower()
		password = self.password_entry.get()
		if email == "" or password == "":
			self.status.config(text="Enter email and password")
			return
		name = check_user(email, password)
		if name is None:
			self.status.config(text="Invalid email or password")
			return
		self.user_name = name
		self.user_email = email
		self.login_button.config(state=DISABLED)
		self.status.config(text="Sending OTP...", fg="black")
		self.new_otp()

	def new_otp(self):
		self.otp = str(secrets.randbelow(900000) + 100000)
		self.otp_time = time.time()
		self.otp_attempts = 0
		threading.Thread(target=self.otp_worker, daemon=True).start()

	def otp_worker(self):
		try:
			send_otp(self.user_email, self.otp)
			self.after(0, self.otp_page)
		except Exception as error:
			self.after(0, lambda: self.otp_failed(error))

	def otp_failed(self, error):
		popup.showerror("Email error", "Could not send OTP:\n" + str(error))
		self.login_page()

	# ---------- otp page ----------

	def otp_page(self):
		self.clear()
		self.geometry("400x300")

		Label(self, text="Verify OTP", font=("Arial", 22, "bold"), bg="white").place(x=120, y=30)
		Label(self, text="A 6 digit code was sent to\n" + self.user_email, bg="white").place(x=60, y=85)

		self.otp_entry = Entry(self, font=("calibre", 14, "normal"), border=2, justify=CENTER)
		self.otp_entry.place(x=125, y=140, width=150)
		self.otp_entry.bind("<Return>", lambda event: self.verify_otp())
		self.otp_entry.focus()

		Button(self, text="Verify", command=self.verify_otp).place(x=85, y=190, width=100)
		self.resend_button = Button(self, text="Resend", command=self.resend_otp)
		self.resend_button.place(x=215, y=190, width=100)

		self.status = Label(self, text="", fg="red", bg="white")
		self.status.place(x=60, y=240)

	def verify_otp(self):
		if time.time() - self.otp_time > OTP_VALID_SECONDS:
			self.status.config(text="OTP expired, click Resend")
			return
		if self.otp_attempts >= MAX_OTP_ATTEMPTS:
			self.status.config(text="Too many attempts, click Resend")
			return
		self.otp_attempts += 1
		if secrets.compare_digest(self.otp_entry.get().strip(), self.otp):
			self.otp = ""
			self.chat_page()
		else:
			left = MAX_OTP_ATTEMPTS - self.otp_attempts
			self.status.config(text="Incorrect OTP, " + str(left) + " attempts left")

	def resend_otp(self):
		self.resend_button.config(state=DISABLED)
		self.status.config(text="Sending new OTP...", fg="black")
		self.new_otp()

	# ---------- chat page ----------

	def chat_page(self):
		self.clear()
		self.geometry("300x500")
		self.title("Secure Chat - " + self.user_name)

		self.start_image = PhotoImage(file="start.png")
		self.start_button = Button(self, image=self.start_image, command=self.start_chat, borderwidth=0, bg="white")
		self.start_button.place(x=90, y=10)

		self.chat_list = Listbox(self)
		self.chat_list.place(x=10, y=80, width=280, height=350)

		self.message_entry = Entry(self, font=("calibre", 10, "normal"), border=2)
		self.message_entry.place(x=10, y=444, width=240)
		self.message_entry.bind("<Return>", lambda event: self.send_message())

		self.send_image = PhotoImage(file="send.png")
		Button(self, image=self.send_image, command=self.send_message, borderwidth=0, bg="white").place(x=260, y=440)

		self.show("Logged in as " + self.user_name, "gray")
		self.show("Press Start Chat to go online", "gray")
		self.after(100, self.check_incoming)

	def show(self, text, color="black"):
		for part in textwrap.wrap(text, 36) or [""]:
			self.chat_list.insert(END, part)
			self.chat_list.itemconfig(END, fg=color)
		self.chat_list.see(END)

	def start_chat(self):
		try:
			self.listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
			self.listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
			self.listen_socket.bind(("", args.listen_port))
			self.listen_socket.listen(5)
		except OSError as error:
			self.listen_socket = None
			popup.showerror("Chat error", "Cannot listen on port " + str(args.listen_port) + ":\n" + str(error))
			return
		self.start_button.config(state=DISABLED)
		self.show("Online on port " + str(args.listen_port), "gray")
		threading.Thread(target=self.receive_loop, daemon=True).start()

	def receive_loop(self):
		while True:
			try:
				client, address = self.listen_socket.accept()
			except OSError:
				return
			threading.Thread(target=self.client_loop, args=(client,), daemon=True).start()

	def client_loop(self, client):
		try:
			with client:
				for line in client.makefile("r", encoding="utf-8", errors="replace"):
					text = line.rstrip("\n")
					if text != "":
						self.incoming.put(text)
		except OSError:
			pass

	def check_incoming(self):
		while not self.incoming.empty():
			text = self.incoming.get()
			score = spam_score(text)
			if score >= 0.5:
				self.show("Friend [SPAM " + str(round(score * 100)) + "%] : " + text, "red")
			else:
				self.show("Friend : " + text, "blue")
		self.after(100, self.check_incoming)

	def send_message(self):
		text = self.message_entry.get().strip()
		if text == "":
			return
		self.message_entry.delete(0, END)
		self.show("You : " + text)
		threading.Thread(target=self.send_worker, args=(text,), daemon=True).start()

	def send_worker(self, text):
		with self.send_lock:
			try:
				if self.send_socket is None:
					self.send_socket = socket.create_connection((args.peer_host, args.peer_port), timeout=5)
				self.send_socket.sendall((text + "\n").encode("utf-8"))
			except OSError:
				if self.send_socket is not None:
					self.send_socket.close()
				self.send_socket = None
				self.after(0, lambda: self.show("Not delivered, friend is offline", "gray"))

	def close_app(self):
		for sock in (self.send_socket, self.listen_socket):
			if sock is not None:
				try:
					sock.close()
				except OSError:
					pass
		self.destroy()


if __name__ == "__main__":
	window = App()
	window.mainloop()