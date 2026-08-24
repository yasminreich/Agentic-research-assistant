# Deploying it so other people can use it

Right now the app runs only on your machine. `python run.py` binds to
`localhost`, which means *you* can reach it and nobody else can — not even
someone on the same wifi. The **code** is public on GitHub; the **running app**
is not.

To give people a link that works, you deploy it once. It then runs on **your**
Anthropic API key, and every question anyone asks is billed to you. So the order
of the steps below matters: the spending cap and the password go in **before**
the URL exists, not after.

Budget about 15 minutes.

---

## 1. Cap your spending first

This is the only hard limit. Everything else in this project is a best-effort
backstop on top of it.

1. Go to [console.anthropic.com](https://console.anthropic.com/) → **Settings**
   → **Limits**.
2. Set a monthly spend limit you would be genuinely comfortable losing — $10–20
   is a sensible starting point.

A single research run costs roughly **$0.15–$1.00**, so a $15 cap is somewhere
between 15 and 100 questions. If the cap is reached, runs stop working until the
next month; nothing overruns.

> Do this before deploying, not after. It takes one minute and it is the
> difference between a bad day and a bad month.

## 2. Decide on a password

`ACCESS_PASSWORD` gates the whole page. Set it unless you genuinely want the
link to be open to anyone who finds it.

- **Set it** if you're sharing with named people — a lab group, a few
  colleagues. Give them the password separately from the link.
- **Leave it blank** only for a demo you're happy for strangers to run on your
  key.

There is no user accounts system here — it is one shared password, and anyone
who has it can spend your money. Treat it accordingly.

## 3. Deploy on Render

Render's free tier is enough. The repo already contains the `Dockerfile` and
`render.yaml` that describe the service, so you do not need to configure a build.

1. Push everything to GitHub if you haven't (`git push`).
2. Sign in at [render.com](https://render.com/) **with GitHub**, and grant it
   access to this repository.
3. **New +** → **Blueprint**.
4. Pick `Agentic-research-assistant`. Render reads `render.yaml` and proposes a
   web service called `research-assistant`.
5. It will ask for the values marked `sync: false` — these are never stored in
   the repo:

   | Variable | What to put |
   |---|---|
   | `ANTHROPIC_API_KEY` | Your key from the Anthropic Console |
   | `ACCESS_PASSWORD` | The password from step 2 (leave blank for an open link) |
   | `OPENALEX_MAILTO` | Optional — your email, for OpenAlex's faster pool |

6. **Apply**. The first build takes a few minutes.

You'll get a URL like `https://research-assistant-xxxx.onrender.com`.

Railway and Fly.io work the same way from the same `Dockerfile`, if you prefer
one of those.

## 4. Check it actually works

Two checks, in order:

```bash
curl https://YOUR-URL.onrender.com/health
# {"status":"ok"}
```

Then open the URL in a browser and run **one real question**. This costs one API
call, and it is worth it — it is the only way to know the key was entered
correctly and the agents can reach Claude.

If the page loads but a run fails with a 503 mentioning `ANTHROPIC_API_KEY`, the
key didn't save. Re-enter it in Render → your service → **Environment**.

## 5. Share the link

Send the URL, and the password separately if you set one.

Tell people what to expect, because two things surprise everyone:

- **A run takes 1–2 minutes.** The page shows a spinner the whole time. It has
  not frozen.
- **The first request after a quiet spell is slow.** See below.

---

## What to warn people about

**Free-tier instances sleep.** After about 15 minutes of no traffic, Render
spins the service down. The next request has to start it again, which takes
30–60 seconds *before* the 1–2 minute run even begins. The page gives up after
3 minutes, so a cold start plus a slow run can time out. Ask them to just try
again — the second attempt is fast.

**Your daily cap still applies.** `MAX_RUNS_PER_DAY` (default 50) is enforced in
the app, but it resets whenever the service restarts, and each worker process
counts separately. It is a speed bump, not a guarantee. The Console limit from
step 1 is the guarantee.

**OpenAlex has its own daily budget.** Paper search is free but metered. A very
heavy day can exhaust it, and runs will then fail with a clear message saying it
resets at midnight UTC. Setting `OPENALEX_MAILTO` gets you into the politer,
faster pool.

---

## Changing things later

**Rotate the API key.** Create a new key in the Anthropic Console, update
`ANTHROPIC_API_KEY` in Render → **Environment**, then revoke the old one. Render
redeploys automatically.

**Change the password.** Same place — update `ACCESS_PASSWORD`. Everyone's saved
password stops working and they'll be asked for the new one.

**Take it down.** Render → your service → **Settings** → **Suspend** stops it
serving without deleting anything, and **Delete** removes it entirely. Either
way, revoke the API key too if you're done: suspending the service does not
invalidate the key.

**Deploy an update.** Push to `main` and Render rebuilds automatically.
