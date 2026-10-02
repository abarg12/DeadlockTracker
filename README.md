# clone the repo
```bash
git clone https://github.com/your_username/my_app.git
cd my_app
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

# create your own secrets file and fill in real credentials
```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

# create the database tables (requires Postgres installed and running)
# see the end of this doc for instructions on PostgreSQL install and running
```bash
createdb my_database
psql -d my_database -f sql/schema.sql
```

# run the app
### by default the app is hosted at localhost:8501
```bash
streamlit run app.py
```



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