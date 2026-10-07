# Running for the first time

# clone the repo
```bash
git clone https://github.com/abarg12/DeadlockTracker.git
cd DeadlockTracker
```

# start up a python virtual environment
```bash
python3 -m venv .venv
source .venv/bin/activate
```

# install dependencies
```bash
pip install -r requirements.txt
```

# create the database tables (requires Postgres installed and running)
<sub> see the end of this doc for instructions on PostgreSQL install and running </sub>
```bash
createdb my_database
psql -d my_database -f sql/schema.sql
```

# create your own secrets file and fill in real credentials
```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

## the app connects to Postgres over TCP, which requires a password, so set one for your Postgres role if it doesn't have one yet (you'll be prompted to type it):
```bash
psql -d postgres -c '\password'
```

Then edit `.streamlit/secrets.toml` with your own values:

| Key | Value | How to find it |
|---|---|---|
| `host` | `localhost` | Postgres is running on your own machine |
| `port` | `5432` | The default. Check with `psql -d postgres -c 'SHOW port'` |
| `database` | `my_database` | The name you passed to `createdb`. List them with `psql -d postgres -c '\l'` |
| `username` | your Postgres role | Usually your OS username. List roles with `psql -d postgres -c '\du'` |
| `password` | the password you just set | |

<sub> `.streamlit/secrets.toml` is in `.gitignore`, so your password is never committed </sub>

# run the app
<sub> by default the app is hosted at localhost:8501 </sub>
```bash
streamlit run app.py
```

---

## Running the App
<sub>After completing the setup steps above once, this is all you need each time.</sub>

1. Make sure Postgres is running:

   | OS | Command |
   |---|---|
   | macOS | `brew services start postgresql@17` |
   | Ubuntu / Debian | `sudo systemctl start postgresql` |
   | Windows | Usually starts automatically. If not, start the postgresql service from the Services app. |

2. Activate the virtual environment:

```bash
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

3. Start the app:

```bash
   streamlit run app.py
```

   The app opens at http://localhost:8501. Press `Ctrl+C` in the terminal to stop it.

### After pulling new changes

If `requirements.txt` changed, reinstall dependencies before running:

```bash
pip install -r requirements.txt
```

--- 

## installing and running PostgreSQL instructions
**macOS (Homebrew)**
```bash
brew install postgresql@17
brew services start postgresql@17
echo 'export PATH="$(brew --prefix postgresql@17)/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

**Ubuntu / Debian**
```bash
sudo apt update
sudo apt install postgresql
sudo systemctl start postgresql
```

---

### Troubleshooting

**`role "<your_username>" does not exist`** (Linux)

Postgres on Linux only creates the `postgres` admin role by default. Either
prefix commands with `sudo -u postgres`, or create a role for yourself once:

```bash
sudo -u postgres createuser --superuser $USER
sudo -u postgres createdb $USER
```

**`password authentication failed for user "..."`**

The `username` or `password` in `.streamlit/secrets.toml` doesn't match your
Postgres role. If the user shown is `your_username`, the file still has the
placeholder values. See the secrets file step above.