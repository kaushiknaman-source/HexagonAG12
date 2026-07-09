# Agent 11 — Vercel deployment

This is the same Agent 11 (same UI, same features) restructured to deploy as
a single Vercel Function, instead of a normal always-on Flask server. If
you're not deploying to Vercel, use the other build — this one trades a bit
of architecture for Vercel-compatibility, and it's worth knowing what
changed and why before you point a public link at it.

## Deploy

```bash
npm i -g vercel     # if you don't have the CLI yet
cd agent11-vercel
vercel
```

Then, in the Vercel dashboard for the project, add one environment variable:

```
ANTHROPIC_API_KEY = sk-ant-...
```

Redeploy after adding it (or `vercel --prod` again) so the function picks it up.
That's it — Vercel auto-detects the Flask app from `app.py` at the project
root, installs `requirements.txt`, and serves everything in `public/` as
static assets on its CDN.

Optional, only if you'll use "Post now": add the relevant platform's own
credentials as more environment variables (`TWITTER_API_KEY`,
`LINKEDIN_ACCESS_TOKEN`, etc. — see `publishers/*.py` docstrings for the
exact names each one needs).

## What's different from the standard version, and why

Vercel Functions are **serverless**: your code doesn't run as one continuous
program, it runs fresh, per request, with no guaranteed persistent
filesystem and no background process in between calls. That's a real
architectural constraint, not a Vercel limitation to work around — so rather
than paper over it, three things were deliberately redesigned:

**1. Brand guidelines aren't saved on the server.**
Upload your guidelines file and Agent 11 extracts and returns the
guidelines as JSON — the browser holds onto that JSON in memory for the
session and resends it with every "Generate" click. Functionally this looks
identical to you (upload once, it's applied to everything after), but
technically it means a page refresh clears it, same as anything else kept
only in browser memory. If you want it to survive a refresh too, the
straightforward upgrade is `localStorage` (a few lines in `public/app.js`).

**2. Images come back as embedded image data, not links to `/media/...`.**
There's no persistent place on Vercel to keep a generated image around for
a second request to fetch, so every image is base64-encoded directly into
the response and rendered inline. You'll notice this only if you inspect
network requests — visually it's the same.

One real consequence: **Instagram and LinkedIn publishing needs a public
image URL** (they fetch the image themselves, server-side). When the image
came from a reference link or a web search, Agent 11 already has that
public URL and posting works normally. When the image is a locally
generated **branded card** (the guaranteed fallback), there's no public URL
for it — "Post now" will tell you exactly that instead of failing silently.
Twitter is unaffected either way, since it accepts a direct image upload.
If you regularly rely on the branded-card fallback for Instagram/LinkedIn
specifically, the fix is adding an image host (Vercel Blob, S3, Cloudinary
— any of them work) and posting that URL instead; that's a deliberate,
separate decision rather than something this deployment does for you
silently.

**3. Scheduled posting doesn't run.**
"Schedule" in the UI still takes a time, but the backend responds with a
clear message rather than pretending it queued something that will never
fire — there's no persistent worker process in serverless to run it later.
"Post now" is unaffected. If scheduling matters to you, the other build
(a normal long-running server) supports it, or you could later wire this up
to Vercel Cron + a small persistent store (Vercel KV, or any database) —
that's a real feature addition, not a config flag, so it's not included
here.

## A note on plan limits

Vercel Functions time out at **10 seconds on the free Hobby plan**, 60
seconds on Pro (which `vercel.json` in this project requests via
`maxDuration: 60` — that setting is ignored on Hobby). Generating 3 post
variants for multiple platforms, each with its own Claude call and image
lookup, can comfortably take longer than 10 seconds. If requests are timing
out for you, that's almost certainly why — either upgrade to Pro, or
generate one platform at a time.

## Everything else

Same UI, same panels, same generation pipeline, same honest handling of
protected/paywalled reference links as the main build — see that build's
README for the full feature rundown; nothing about the actual product
changed here, only how it's hosted.
