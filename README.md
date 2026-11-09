# Secure Chat: Two-Factor Authentication + ML Spam Detection

A peer-to-peer desktop chat application written in Python. Users log in with a password **and** a one-time code sent to their email, and every message they receive is checked by a machine learning model that flags spam in real time.

- **Two-factor login**: salted PBKDF2-SHA256 password hashing (200,000 iterations) plus a 6-digit email OTP that expires in 5 minutes and allows 3 attempts
- **Spam detection**: Multinomial Naive Bayes trained on 5,169 SMS messages, with 96.1% accuracy and 97% spam recall on held-out test data
- **Chat**: direct socket connection between two computers (or two windows on one computer), with spam shown in red along with its spam probability

## How it works

```
Register -> Login (email + password) -> OTP emailed -> Enter OTP -> Chat
                                                                     |
                                       every received message -> spam model -> red (spam) / blue (normal)
```

### 1. Registration and login

- Users register from the login screen with a name, email and password (minimum 6 characters).
- Passwords are never stored. Each user gets a random 16-byte salt, and the password is run through `PBKDF2-HMAC-SHA256` 200,000 times. Only the salt and the resulting hash are saved in `users.db` (SQLite).
- At login, the typed password is hashed with the same salt and compared using `secrets.compare_digest`, which takes the same time regardless of where the two values differ.
- A wrong email and a wrong password both show the same error, so the screen does not reveal which emails are registered.

### 2. Two-factor authentication (OTP)

- After a correct password, a 6-digit code is generated with Python's `secrets` module (a cryptographically secure random source).
- The code is emailed through Gmail SMTP over SSL (port 465) using a Google App Password.
- The code is valid for **5 minutes** and allows **3 attempts**. A Resend button issues a fresh code.
- The email is sent on a background thread so the window never freezes.

### 3. Spam detection (machine learning)

The model is trained each time the program starts (about 1 second) from `spam.csv`.

| Step | What happens |
| --- | --- |
| Load | `spam.csv` (5,572 labelled SMS) is read; only the label and text columns are kept |
| Clean | 403 duplicate messages are removed, leaving 5,169 (4,516 ham, 653 spam) |
| Vectorise | `CountVectorizer` builds an 8,672-word vocabulary and turns each message into word counts (bag of words) |
| Train and test | 90% of messages train the model; the other 10% (517 messages it never saw) measure accuracy |
| Retrain | The final model is retrained on all 5,169 messages before use |
| Score | Each incoming chat message gets a spam probability from 0 to 1 using `predict_proba` |
| Display | 50% or more is shown in red as `Friend [SPAM 82%] : ...`; anything lower is shown in blue |

**Why Naive Bayes:** it applies Bayes' theorem to word frequencies. For each word it learns how often that word appears in spam compared with normal messages. Words like *claim* and *prize* never appear in normal messages in the dataset, while *home* appears 156 times in normal messages and only twice in spam. It trains almost instantly, works well with word counts, and is a standard baseline for text classification.

**Class prior tuning:** the dataset is 87% normal messages, so by default the model starts every message heavily biased toward "normal", and short spam messages were missed. The model uses `MultinomialNB(fit_prior=False)` so both classes start at 50/50. This raised detection on short messages (for example, "spam ticket" went from 40% to 82%) at the cost of more false alarms.

| Setting | Test accuracy | Spam caught (of 74) | Normal messages wrongly flagged (of 443) |
| --- | --- | --- | --- |
| `fit_prior=True` (default) | 98.1% | 71 | 7 |
| `fit_prior=False` (used) | 96.1% | 72 | 18 |

### 4. Chat networking

- Each running copy is both a server and a client: it **listens** on one port and **sends** to the friend's port.
- Messages are sent over TCP, each ending with a newline, and read line by line so messages never merge or split.
- Received messages go into a thread-safe queue. The window checks the queue every 100 ms, scores each message with the spam model and displays it. Tkinter windows must only be updated from the main thread.
- A send lock makes sure only one message is sent at a time. If the friend is offline, the app shows "Not delivered" and reconnects automatically on the next message.

## Project structure

```
.
├── program.py          # the whole application
├── spam.csv            # SMS Spam Collection dataset used to train the model
├── start.png           # Start chat button image
├── send.png            # send button image
├── requirements.txt    # Python dependencies
├── .env.example        # template for your private settings
└── .gitignore
```

`users.db` (user accounts) and `.env` (your email password) are created locally and are **not** uploaded.

## Setup

Requires **Python 3.10 to 3.13** (tested on 3.13). Tkinter is included with the standard Windows and macOS Python installers; on Ubuntu run `sudo apt install python3-tk`.

**1. Clone the repository**

```
git clone https://github.com/<your-username>/<repo-name>.git
cd <repo-name>
```

**2. Create and activate a virtual environment**

Windows:
```
py -3.13 -m venv venv
venv\Scripts\activate
```

macOS / Linux:
```
python3 -m venv venv
source venv/bin/activate
```

**3. Install dependencies**

```
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

**4. Create a Gmail App Password**

1. Turn on 2-Step Verification for the Gmail account that will send OTPs.
2. Go to https://myaccount.google.com/apppasswords and create an app password.
3. Copy the 16-character code (remove the spaces).

**5. Create your `.env` file**

Copy `.env.example` to `.env` and fill in your Gmail address and app password:

```
copy .env.example .env      (Windows)
cp .env.example .env        (macOS / Linux)
```

If `SMTP_USER` or `SMTP_PASSWORD` is left empty, the OTP is printed in the terminal instead of emailed, which is useful for testing.

## Running

**Single computer (two windows):**

Terminal 1:
```
python program.py
```

Terminal 2:
```
python program.py --listen-port 4050 --peer-port 3050
```

Register a user in each window, log in, enter the OTP, then click **Start chat** in both.

Tip: Gmail delivers `yourname+friend@gmail.com` to `yourname@gmail.com`, so one inbox can be used for two test accounts.

**Two computers on the same network:**

Run `python program.py --peer-host <other-computer-IP>` on one and `python program.py --listen-port 4050 --peer-port 3050 --peer-host <other-computer-IP>` on the other. Find the IP with `ipconfig` (Windows) or `ip a` (Linux). Allow Python through the firewall if asked.

**Command-line options** (each overrides the value in `.env`):

| Option | Default | Meaning |
| --- | --- | --- |
| `--listen-port` | 3050 | Port this copy receives messages on |
| `--peer-host` | 127.0.0.1 | Friend's computer address |
| `--peer-port` | 4050 | Port the friend receives on |

## Try these messages

| Message | Result |
| --- | --- |
| hello | normal |
| come home | normal |
| free stuff | SPAM 55% |
| get a free gift | SPAM 98% |
| Congratulations! You have won a FREE holiday. Call now to claim | SPAM 100% |

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `SMTPAuthenticationError` | Use a Gmail App Password, not your normal password |
| "Cannot listen on port 3050" | Another copy is using it; start the second copy with `--listen-port 4050 --peer-port 3050` |
| "Not delivered, friend is offline" | Click Start chat in both windows; check the IP and firewall |
| `FileNotFoundError: spam.csv` | Run the program from inside the project folder |

## Limitations

- The model only knows words from the dataset (UK SMS messages, around 2011 to 2012). Modern spam styles and non-English text are mostly unknown to it.
- Bag-of-words ignores word order and meaning, so "I am not offering a free prize" can look like spam.
- Very short messages carry little signal; for example, "free ticket buy online" scores 18%.
- Chat messages are sent unencrypted over the network, so it is meant for local networks and demonstration.

## Tech stack

Python, Tkinter, scikit-learn, pandas, SQLite, socket, smtplib, hashlib, python-dotenv

## Dataset

[SMS Spam Collection](https://archive.ics.uci.edu/dataset/228/sms+spam+collection) by Tiago A. Almeida and José María Gómez Hidalgo, UCI Machine Learning Repository.
