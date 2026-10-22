# Deadlock Tracker

A Streamlit dashboard of Deadlock hero, item and player statistics, backed by PostgreSQL and fed automatically from the [Deadlock API](https://api.deadlock-api.com/docs).

- [First-time setup](#first-time-setup)
- [Running the app](#running-the-app)
- [Running the benchmarks](#running-the-benchmarks)
- [Troubleshooting](#troubleshooting)

---

## First-time setup

### 1. Install and start PostgreSQL

**macOS (Homebrew)**
```bash
brew install postgresql@16
brew services start postgresql@16
echo 'export PATH="$(brew --prefix postgresql@16)/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

**Ubuntu / Debian**
```bash
sudo apt update
sudo apt install postgresql-16
sudo systemctl start postgresql
```

<sub> the app creates its own database and tables on first launch, so there's nothing else to set up in Postgres </sub>

### 2. Clone the repo and install dependencies

```bash
git clone https://github.com/abarg12/DeadlockTracker.git
cd DeadlockTracker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Create your secrets file

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

The app connects to Postgres over TCP, which requires a password. If your Postgres role doesn't have one yet, set it (you'll be prompted to type it):
```bash
psql -d postgres -c '\password'
```

Then edit `.streamlit/secrets.toml` with your own values:

| Key | Value | How to find it |
|---|---|---|
| `host` | `localhost` | Postgres is running on your own machine |
| `port` | `5432` | The default. Check with `psql -d postgres -c 'SHOW port'` |
| `database` | any name, e.g. `deadlock` | The app creates this database on first launch if it doesn't exist |
| `username` | your Postgres role | Usually your OS username. List roles with `psql -d postgres -c '\du'` |
| `password` | the password you just set | |

<sub> `.streamlit/secrets.toml` is in `.gitignore`, so your password is never committed </sub>

---

## Running the app

1. Make sure Postgres is running:

   | OS | Command |
   |---|---|
   | macOS | `brew services start postgresql@16` |
   | Ubuntu / Debian | `sudo systemctl start postgresql` |
   | Windows | Usually starts automatically. If not, start the postgresql service from the Services app. |

2. Activate the virtual environment and start the app:

```bash
source .venv/bin/activate        # Windows: .venv\Scripts\activate
streamlit run app.py
```

   The app opens at http://localhost:8501. Press `Ctrl+C` in the terminal to stop it.

### How the data stays current

While the app is running it keeps its own data current, with no manual loading:

- **First launch:** it creates the database and tables, then loads a sample of the past week's matches from the Deadlock API's public data lake. This takes about 7 minutes (about 1 GB is read, but only the sample is stored). The pages are usable within a minute: they load the newest days first, show a progress bar, and update on their own as data arrives.
- **Every 15 minutes:** it adds the sampled matches from the data lake's newest hourly files, then drops data older than a week, so storage stays around 600 MB.
- **Player names:** Steam display names come from the data lake's daily profile snapshot (only the account ID and name columns, cached in `data/lake_cache/`, about 75 MB), so the Player history page can search by name.
- **After time off:** the next launch catches up from where it left off, or reloads the past week if it was off for more than a couple of days.

To ingest without the app running (for example from cron), use `python -m ingest.live --once`.

### Optional settings

Add these to `.streamlit/secrets.toml` to change the defaults:

```toml
[ingest]
sample_percent = 3      # share of public matches to keep (3% is about 19,000 matches and 600 MB per week)
keep_days = 7           # rolling window
interval_minutes = 15   # how often to check for new data
```

### Pages and their queries

The pages run the same SQL files in `sql/queries/` that the benchmarks measure:

| Page | Query |
|---|---|
| Overview | `daily_summary.sql` (matches per day and average duration) |
| Heroes | `hero_win_rates_mv.sql` (reads the `hero_daily_stats` materialized view) |
| Items | `item_win_rates_mv.sql` (reads the `item_daily_stats` materialized view) |
| Player history | `player_match_history.sql` (a player's 20 most recent matches) |

---

## Running the benchmarks

The ablation study measures query latency for each optimization on its own and combined, at several dataset sizes.

1. Create a separate database, so the benchmark doesn't wipe the app's data. It rebuilds both schemas at the start of every run:

```bash
createdb deadlock_bench
```

2. Download a week of matches once. Every configuration and dataset size then uses exactly the same data:

```bash
python -m ingest.fetch --matches 50000 --days 7
```

3. Run the study:

```bash
python -m bench.run --database deadlock_bench --sizes 10000,25000,50000 --repeats 5
```

   For each size, it loads the same matches into both schemas and runs every query in `sql/queries/` under five configurations:

   | Config | Schema | Indexes | Materialized views |
   |---|---|---|---|
   | `baseline` | baseline | | |
   | `baseline+indexes` | baseline | ✓ | |
   | `partitioned` | optimized | | |
   | `partitioned+indexes` | optimized | ✓ | |
   | `full` | optimized | ✓ | ✓ (runs the `*_mv` queries) |

   Each query gets one unrecorded warm-up run, then `--repeats` runs of `EXPLAIN (ANALYZE, BUFFERS)`. Smaller datasets are subsets of larger ones.

4. Read the results in `results/<timestamp>/`:

   | File | Contents |
   |---|---|
   | `latency.csv` | one row per measured run: execution and planning time, buffer hits/reads, temp (disk spill) blocks, slowest plan node |
   | `setup.csv` | load, index build and view build times, and disk size per config |
   | `correctness.csv` | whether every configuration returned identical rows, and each `*_mv` query matched its raw version |
   | `plans/` | every query plan as JSON, for per-node bottleneck analysis |
   | `metadata.json` | PostgreSQL version and settings, query parameters, git commit |

---

## Troubleshooting

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
placeholder values. See [Create your secrets file](#3-create-your-secrets-file).
