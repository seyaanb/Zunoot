// Load test for Zunoot's main user flows.
//
//   k6 run -e BASE_URL=https://zunoot-staging.onrender.com loadtest/zunoot.js
//
// What one virtual user (VU) does, repeatedly: a short study session.
//   log in (once) -> library -> a subject -> a topic -> start a review ->
//   rate 3 cards -> end the session, plus now and then the guild page, the
//   shop, the community library or a search.
//
// setup() registers LOADTEST_USERS throwaway accounts (loadtest_<run>_<n>),
// each with a realistic library: SUBJECTS x TOPICS x CARDS (default 5x4x8 =
// 160 cards; production averages ~85 cards/user, heavy users have more).
// teardown() deletes them again, which cascades to all their data.
//
// SAFETY: refuses to run against production (zunoot.onrender.com) unless
// ALLOW_PRODUCTION=yes. Load-testing production creates and deletes real rows
// in the production database and competes with real users. Use staging.
//
// Every request carries an X-Request-ID (k6-<run>-<vu>-<iter>) that the app
// logs, so a slow or failed request in the k6 output can be found in the logs.
//
// Env (all optional except BASE_URL):
//   BASE_URL         target, e.g. https://zunoot-staging.onrender.com
//   PROFILE          smoke | load | stress   (default: load)
//   LOADTEST_USERS   accounts to create (default 10)
//   SUBJECTS, TOPICS, CARDS   library shape per account (default 5, 4, 8)
//   SEEDED           1 = accounts already created by loadtest/seed.py (recommended for staging)
//   HOLD             how long the load profile holds peak rate (default 5m)
//   SUMMARY_FILE     where to write the JSON summary (default loadtest/results/summary-<run>.json)

import http from "k6/http";
import { check, fail, group, sleep } from "k6";
import exec from "k6/execution";

const BASE_URL = (__ENV.BASE_URL || "").replace(/\/$/, "");
const PROFILE = __ENV.PROFILE || "load";
const USERS = parseInt(__ENV.LOADTEST_USERS || "10", 10);
const SUBJECTS = parseInt(__ENV.SUBJECTS || "5", 10);
const TOPICS = parseInt(__ENV.TOPICS || "4", 10);
const CARDS = parseInt(__ENV.CARDS || "8", 10);
const RUN_ID = __ENV.RUN_ID || `${Date.now().toString(36)}`;
const PASSWORD = "loadtest-password-1";
const HOLD = __ENV.HOLD || "5m";
// SEEDED=1: accounts were created by loadtest/seed.py (fast, direct to the
// staging database), so setup only checks they can log in and teardown leaves
// them for `seed.py --delete`.
const SEEDED = __ENV.SEEDED === "1";

if (!BASE_URL) {
  throw new Error("Set BASE_URL, e.g. -e BASE_URL=https://zunoot-staging.onrender.com");
}
if (/(^|\/\/)zunoot\.onrender\.com/.test(BASE_URL) && __ENV.ALLOW_PRODUCTION !== "yes") {
  throw new Error("Refusing to load-test PRODUCTION. Use staging, or set ALLOW_PRODUCTION=yes after agreeing it.");
}

// Profiles. Arrival-rate executors keep the request rate fixed even when the
// app slows down, so a slower app shows up as higher latency instead of
// silently receiving less load (the "coordinated omission" problem).
const PROFILES = {
  // Is everything wired up? 1 VU, a few sessions.
  smoke: {
    smoke: { executor: "shared-iterations", vus: 1, iterations: 3, maxDuration: "2m", tags: { phase: "main" } },
  },
  // Realistic peak for Zunoot (a study evening, several times today's traffic):
  // ramp up, hold 10 sessions/min for 5 minutes, ramp down.
  load: {
    sessions: {
      executor: "ramping-arrival-rate",
      startRate: 1, timeUnit: "1m", preAllocatedVUs: USERS, maxVUs: USERS, tags: { phase: "main" },
      stages: [
        { target: 10, duration: "1m" },
        { target: 10, duration: HOLD },
        { target: 0, duration: "30s" },
      ],
    },
  },
  // Find the knee: keep increasing the session rate until it breaks.
  stress: {
    sessions: {
      executor: "ramping-arrival-rate",
      startRate: 5, timeUnit: "1m", preAllocatedVUs: USERS, maxVUs: USERS, tags: { phase: "main" },
      stages: [
        { target: 30, duration: "2m" },
        { target: 60, duration: "2m" },
        { target: 120, duration: "2m" },
        { target: 0, duration: "30s" },
      ],
    },
  },
};
if (!PROFILES[PROFILE]) throw new Error(`Unknown PROFILE ${PROFILE}; use smoke, load or stress`);

export const options = {
  scenarios: PROFILES[PROFILE],
  // Keep each VU's session cookie between iterations (k6 resets cookie jars per
  // iteration by default, which would log every VU out after one session).
  noCookiesReset: true,
  setupTimeout: "15m",
  teardownTimeout: "10m",
  // Thresholds mirror the SLOs in docs/SLO.md, so a run "passes" if the SLOs
  // would hold at this load. Setup/teardown requests are excluded.
  thresholds: Object.assign({
    "http_req_failed{phase:main}": ["rate<0.005"],         // availability 99.5%
    "http_req_duration{phase:main}": ["p(95)<1000"],        // latency p95 < 1 s
    "checks{phase:main}": ["rate>0.99"],
    "http_reqs{phase:main}": ["count>0"],                   // so req/s excludes setup traffic
  }, perPage()),
  summaryTrendStats: ["avg", "min", "med", "p(90)", "p(95)", "p(99)", "max"],
  // Per-page breakdown in the end-of-test summary.
  tags: { run: RUN_ID },
};

// k6 only reports a sub-metric (here: latency per page) if it has a threshold,
// so each page gets a deliberately loose, report-only one.
function perPage() {
  const t = {};
  for (const name of ["login", "library", "subject", "topic", "review_start", "review_rate",
                      "review_end", "guild", "shop", "community", "search"]) {
    t[`http_req_duration{name:${name},phase:main}`] = ["p(95)<30000"];
  }
  return t;
}

// --- helpers --------------------------------------------------------------

function rid() {
  const vu = exec.vu.idInTest || 0;
  const it = exec.vu.iterationInScenario || 0;
  return `k6-${RUN_ID}-${vu}-${it}-${Math.floor(Math.random() * 1e6)}`;
}

function params(name, phase) {
  return { headers: { "X-Request-ID": rid() }, tags: { name, phase: phase || "main" }, redirects: 5 };
}

function csrfFrom(res) {
  const m = res.body && res.body.match(/name="csrf_token" value="([^"]+)"/);
  return m ? m[1] : null;
}

// GET a page that contains a form, then POST the form with its CSRF token.
function postForm(getPath, postPath, data, name, phase) {
  const page = http.get(`${BASE_URL}${getPath}`, params(`${name}_form`, phase));
  const token = csrfFrom(page);
  if (!token) return page;
  return http.post(`${BASE_URL}${postPath}`, Object.assign({ csrf_token: token }, data), params(name, phase));
}

let loggedIn = false;

function userName(i) { return `loadtest_${RUN_ID}_${i}`; }
const subjectName = (s) => `Load Subject ${s}`;
const topicName = (t) => `Load Topic ${t}`;

function login(username, phase) {
  const res = postForm("/auth/login", "/auth/login", { username, password: PASSWORD }, "login", phase);
  return check(res, { "logged in": (r) => r.status === 200 && r.url.includes("/library") }, { phase: phase || "main" });
}

// --- setup: accounts with realistic libraries ------------------------------

export function setup() {
  const health = http.get(`${BASE_URL}/healthz`, params("healthz", "setup"));
  if (health.status !== 200) fail(`target unhealthy: /healthz returned ${health.status}`);

  if (SEEDED) {
    http.cookieJar().clear(BASE_URL);
    if (!login(userName(0), "setup")) fail(`SEEDED=1 but ${userName(0)} can't log in: run loadtest/seed.py with RUN_ID=${RUN_ID}`);
    http.get(`${BASE_URL}/auth/logout`, params("logout", "setup"));
    return { users: USERS };
  }

  for (let i = 0; i < USERS; i++) {
    const jar = http.cookieJar();
    jar.clear(BASE_URL);
    const username = userName(i);
    postForm("/auth/register", "/auth/register", {
      username, "first-name": "Load", "last-name": "Test",
      email: `${username}@example.invalid`, password: PASSWORD,
    }, "register", "setup");
    if (!login(username, "setup")) fail(`could not log in as ${username}`);

    for (let s = 0; s < SUBJECTS; s++) {
      postForm("/library/", "/library/", { "new-subject": subjectName(s) }, "add_subject", "setup");
      const sPath = `/library/${encodeURIComponent(subjectName(s))}`;
      for (let t = 0; t < TOPICS; t++) {
        postForm(sPath, sPath, { "new-topic": topicName(t) }, "add_topic", "setup");
        const tPath = `${sPath}/${encodeURIComponent(topicName(t))}`;
        // One form GET, then all cards with the same token (it's per-session).
        const token = csrfFrom(http.get(`${BASE_URL}${tPath}`, params("add_card_form", "setup")));
        for (let c = 0; c < CARDS; c++) {
          http.post(`${BASE_URL}${tPath}`, {
            csrf_token: token,
            "new-flashcard-front": `Question ${s}.${t}.${c} (${username})`,
            "new-flashcard-back": `Answer ${s}.${t}.${c}`,
          }, params("add_card", "setup"));
        }
      }
    }
    http.get(`${BASE_URL}/auth/logout`, params("logout", "setup"));
  }
  return { users: USERS };
}

// --- the main flow --------------------------------------------------------------

export default function (data) {
  const vu = exec.vu.idInTest;
  const username = userName((vu - 1) % data.users);

  // Each VU keeps its cookie jar between iterations, so it logs in once, like a
  // real user who comes back to an open tab. (Module scope is per-VU in k6.)
  if (!loggedIn) {
    if (!login(username)) return;
    loggedIn = true;
  }

  const s = Math.floor(Math.random() * SUBJECTS);
  const t = Math.floor(Math.random() * TOPICS);
  const sPath = `/library/${encodeURIComponent(subjectName(s))}`;
  const tPath = `${sPath}/${encodeURIComponent(topicName(t))}`;

  group("browse library", () => {
    const lib = http.get(`${BASE_URL}/library/`, params("library"));
    check(lib, { "library 200": (r) => r.status === 200 && r.url.endsWith("/library/") });
    sleep(1 + Math.random() * 2);
    const subj = http.get(`${BASE_URL}${sPath}`, params("subject"));
    check(subj, { "subject 200": (r) => r.status === 200 && r.body.includes(topicName(0)) });
    sleep(1 + Math.random() * 2);
    const top = http.get(`${BASE_URL}${tPath}`, params("topic"));
    check(top, { "topic shows cards": (r) => r.status === 200 && r.body.includes("Question") });
  });

  group("review session", () => {
    const spaced = Math.random() < 0.5 ? "true" : "false";
    let res = postForm("/library/", "/library/review", { "spaced-repetition": spaced }, "review_start");
    // A new account's cards are all due, so a card must be shown.
    check(res, { "review shows a card": (r) => r.status === 200 && r.body.includes("Question") });
    for (let i = 0; i < 3; i++) {
      sleep(2 + Math.random() * 3);   // reading the card
      const token = csrfFrom(res);
      res = http.post(`${BASE_URL}/library/spaced-repetition`,
        { csrf_token: token, option: String(3 + Math.floor(Math.random() * 3)) }, params("review_rate"));
      check(res, { "rating accepted": (r) => r.status === 200 && r.url.endsWith("/library/review") });
    }
    const token = csrfFrom(res);
    res = http.post(`${BASE_URL}/library/end-session`, { csrf_token: token }, params("review_end"));
    check(res, { "session ended": (r) => r.status === 200 && r.url.endsWith("/library/") });
  });

  // Secondary pages, sometimes.
  const roll = Math.random();
  if (roll < 0.15) http.get(`${BASE_URL}/guild/guild`, params("guild"));
  else if (roll < 0.25) http.get(`${BASE_URL}/shop/shop`, params("shop"));
  else if (roll < 0.35) http.get(`${BASE_URL}/community/browse-subjects`, params("community"));
  else if (roll < 0.45) http.get(`${BASE_URL}/library/search?keyword=Question`, params("search"));
  sleep(1);
}

// --- teardown: remove the throwaway accounts -----------------------------------

export function teardown(data) {
  if (SEEDED) {
    console.log(`Seeded accounts kept. Remove them with: python loadtest/seed.py --run-id ${RUN_ID} --delete`);
    return;
  }
  for (let i = 0; i < data.users; i++) {
    http.cookieJar().clear(BASE_URL);
    if (!login(userName(i), "teardown")) continue;
    // POST with CSRF (account deletion is POST-only); cascades to all their data.
    postForm("/library/", "/auth/delete-account", {}, "delete_account", "teardown");
  }
}

// --- summary --------------------------------------------------------------------

export function handleSummary(data) {
  const file = __ENV.SUMMARY_FILE || `loadtest/results/summary-${RUN_ID}.json`;
  const m = data.metrics;
  const main = m["http_req_duration{phase:main}"];
  const reqs = m["http_reqs{phase:main}"] || m.http_reqs;
  const failed = m["http_req_failed{phase:main}"];
  const lines = [
    "",
    `Zunoot load test  run=${RUN_ID}  profile=${PROFILE}  target=${BASE_URL}`,
    `  requests (main phase): ${reqs ? reqs.values.count : "?"}  (${reqs ? reqs.values.rate.toFixed(2) : "?"} req/s)`,
    `  p95 latency:           ${main ? main.values["p(95)"].toFixed(0) : "?"} ms   (SLO < 1000 ms)`,
    `  p50 latency:           ${main ? main.values.med.toFixed(0) : "?"} ms`,
    `  failed requests:       ${failed ? (failed.values.rate * 100).toFixed(2) : "?"}%   (SLO < 0.5%)`,
    `  summary written to:    ${file}`,
    "",
  ];
  return {
    stdout: lines.join("\n"),
    [file]: JSON.stringify(data, null, 2),
  };
}
