"""Seed (or remove) load-test accounts directly in a NON-production database.

Creating realistic libraries through the web UI is slow: every "add card"
request reloads the whole library, which is the bottleneck being measured.
This seeds the same data in one transaction instead.

    python loadtest/seed.py --database-url "$STAGING_DATABASE_URL" --run-id r1 --users 10
    k6 run -e BASE_URL=... -e SEEDED=1 -e RUN_ID=r1 -e LOADTEST_USERS=10 loadtest/zunoot.js
    python loadtest/seed.py --database-url "$STAGING_DATABASE_URL" --run-id r1 --delete

Accounts are named loadtest_<run-id>_<n> with the password the k6 script uses,
and each gets SUBJECTS x TOPICS x CARDS cards (default 5 x 4 x 8 = 160).

Safety: refuses to touch a database whose host equals ZUNOOT_PROD_HOST, and
asks for confirmation unless --yes.
"""

import argparse
import os
import sys
from urllib.parse import urlparse

import psycopg2
from werkzeug.security import generate_password_hash

PASSWORD = "loadtest-password-1"   # must match loadtest/zunoot.js


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--users", type=int, default=10)
    ap.add_argument("--subjects", type=int, default=5)
    ap.add_argument("--topics", type=int, default=4)
    ap.add_argument("--cards", type=int, default=8)
    ap.add_argument("--delete", action="store_true", help="remove this run's accounts (cascades)")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()

    if not args.database_url:
        sys.exit("seed: --database-url (or DATABASE_URL) is required")
    host = urlparse(args.database_url).hostname
    prod = os.environ.get("ZUNOOT_PROD_HOST")
    if prod and host == prod:
        sys.exit(f"seed: refusing: {host} is PRODUCTION (ZUNOOT_PROD_HOST). Seed staging instead.")
    if not prod:
        print("seed: warning: ZUNOOT_PROD_HOST is not set, so the production guard is off", file=sys.stderr)
    action = "DELETE" if args.delete else f"CREATE {args.users} accounts in"
    if not args.yes and input(f"{action} loadtest_{args.run_id}_* on {host}? [y/N] ").lower() != "y":
        sys.exit("seed: cancelled")

    conn = psycopg2.connect(args.database_url)
    with conn, conn.cursor() as cur:
        if args.delete:
            cur.execute("delete from students where username like %s", (f"loadtest\\_{args.run_id}\\_%",))
            print(f"seed: deleted {cur.rowcount} accounts (and their data, by cascade)")
            return

        pw_hash = generate_password_hash(PASSWORD)
        for i in range(args.users):
            user = f"loadtest_{args.run_id}_{i}"
            cur.execute("insert into students(username, first_name, last_name, password, email_address, date_joined)"
                        " values (%s, 'Load', 'Test', %s, %s, current_date)",
                        (user, pw_hash, f"{user}@example.invalid"))
            cur.execute("insert into purchases(username, item_id) values (%s, 1), (%s, 13)", (user, user))
            for s in range(args.subjects):
                cur.execute("insert into subjects(subject_name, username, position) values (%s, %s, %s)"
                            " returning subject_id", (f"Load Subject {s}", user, s))
                sid = cur.fetchone()[0]
                for t in range(args.topics):
                    cur.execute("insert into topics(topic_name, subject_id, position) values (%s, %s, %s)"
                                " returning topic_id", (f"Load Topic {t}", sid, t))
                    tid = cur.fetchone()[0]
                    cur.executemany(
                        "insert into flashcards(front, back, topic_id, position) values (%s, %s, %s, %s)",
                        [(f"Question {s}.{t}.{c} ({user})", f"Answer {s}.{t}.{c}", tid, c)
                         for c in range(args.cards)])
        total = args.users * args.subjects * args.topics * args.cards
        print(f"seed: created {args.users} accounts, {total} flashcards (run {args.run_id})")
    conn.close()


if __name__ == "__main__":
    main()
