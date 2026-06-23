# UTM Tagging Guide

This is the human- and agent-readable companion to [`utm-spec.yaml`](./utm-spec.yaml).
`utm-spec.yaml` is the machine-readable source of truth that the UTM Helper MCP
tools parse; this guide explains the *why* and shows worked examples per channel.

> **The one rule that matters:** whatever drafts a link, the final URL **must**
> be passed through the `validate_and_normalize` tool and the tool's output is
> what gets published — never a hand-rolled string. Everything below exists to
> make the correct link the path of least resistance.

---

## Why we lock UTMs

Inconsistent UTMs silently corrupt analytics. `utm_medium=paid-social` and
`utm_medium=cpc` describe the same traffic but split into two buckets in GA4, so
no report ever shows the true total. The fix is not discipline (it doesn't
scale); it's making the tool emit the right value by default.

We split the parameters by **how often they change** and **how much damage a
wrong value does**:

| Param | Stakes | Churn | Where it lives | On an unknown value |
|---|---|---|---|---|
| `utm_medium` | **Highest** (GA4 channel grouping) | Lowest | Git enum (closed) | **Hard refuse** — show valid set + suggestion |
| `utm_source` | Low | Low–medium | Git enum (open) | **Emit + nudge** to add it via PR |
| `utm_campaign` | Medium | **Highest** | Google Sheet | Two-phase dedup write (`add_campaign`) |
| `utm_content` | Low | High | Git shape rule | Normalize shape |
| `utm_term` | Low | High | Git shape rule | Normalize shape (paid only) |

`utm_medium` is the product: it is closed, lives in version control, and **never**
moves to a writable store. An unknown medium is almost always an agent typo, so
we stop. An unknown *source* is plausibly a real new platform, so we emit the
link and nudge you to add it.

---

## The parameters

### `utm_source` — where the click comes from
The platform or referrer. **Open enum**: the values below are seeded, but a new
platform is allowed — the tool will emit your link and remind you to add the new
source to `utm-spec.yaml` via PR.

Seeded sources: `reddit`, `linkedin`, `x`, `hackernews`, `newsletter`,
`youtube`, `github`.

### `utm_medium` — the channel type
**Closed enum.** These are the only valid values; anything else is refused.

| Value | Use for |
|---|---|
| `social` | Organic social posts (Reddit, LinkedIn, X, …) |
| `email` | Newsletters, lifecycle/transactional sends |
| `cpc` | Paid search **and** paid social (cost-per-click) |
| `organic` | Organic search |
| `referral` | Links from other sites / partners |
| `affiliate` | Affiliate / partner-attribution links |

Common mistakes the tool will reject: `paid-social` → use `cpc`; `ppc` → `cpc`;
`newsletter` → `email`; `post` → `social`.

### `utm_campaign` — the initiative
Template: **`YYYY-qN_kebab-slug`** — e.g. `2026-q2_agent-launch`.

- `YYYY` four-digit year, `qN` quarter `q1`–`q4`, then `_`, then a kebab slug.
- The `_` between the `YYYY-qN` prefix and the slug is **structural** — it's the
  one underscore that is *not* converted to a hyphen. The slug itself is
  hyphenated.
- Campaigns live in the registry Google Sheet, not in Git. Use `list_campaigns`
  to see existing ones and `add_campaign` to add a new one — it dedup-checks
  against close matches before writing, so reuse an existing campaign rather
  than minting a near-duplicate.

### `utm_content` — distinguishes similar links
Optional, free-form, kebab-case. Use it when two links point to the same
destination from the same campaign and you need to tell them apart:
`header-cta`, `footer-link`, `variant-a`.

### `utm_term` — paid-search keywords
Optional, free-form, kebab-case, **paid-search only** (`utm_medium: cpc`). Leave
it off for everything else: `mcp-server`, `ai-agent-tools`.

---

## Casing & separator rules

Applied to **every** value (see `normalization` in `utm-spec.yaml`):

- Lowercase everything.
- Words within a value are separated by a single hyphen `-`.
- No spaces, ever (spaces → `-`).
- Underscores → `-`, **except** the structural `_` in `utm_campaign`.
- Strip any character outside `[a-z0-9-]`; collapse repeated `-`; trim edge `-`.

Normalization is idempotent: running it twice changes nothing. So you can pass an
already-clean URL through `validate_and_normalize` safely.

---

## Worked examples per channel

All examples tag `https://arcade.dev/` for illustration. In practice the base URL
is whatever you're linking to.

### Reddit (organic social)
A post in r/LocalLLaMA for the Q2 agent launch:

```
https://arcade.dev/?utm_source=reddit&utm_medium=social&utm_campaign=2026-q2_agent-launch&utm_content=localllama-post
```
`source=reddit`, `medium=social`. `content` distinguishes this from other Reddit
links in the same campaign.

### LinkedIn (organic social)
Founder's organic post, testing two CTAs (variant A):

```
https://arcade.dev/?utm_source=linkedin&utm_medium=social&utm_campaign=2026-q2_agent-launch&utm_content=founder-post-variant-a
```

### Blog / website (referral)
A link from a partner's blog back to us:

```
https://arcade.dev/?utm_source=partner-blog&utm_medium=referral&utm_campaign=2026-q2_agent-launch&utm_content=inline-mention
```
`partner-blog` isn't a seeded source — the tool **emits the link and nudges** you
to add it to `utm-spec.yaml` if it's going to recur.

### Newsletter (email)
The header CTA in the June newsletter:

```
https://arcade.dev/?utm_source=newsletter&utm_medium=email&utm_campaign=2026-q2_agent-launch&utm_content=header-cta
```
`source=newsletter`, `medium=email` (not `social`).

### Ad (paid — cpc)
A Google paid-search ad bidding on "mcp server":

```
https://arcade.dev/?utm_source=google&utm_medium=cpc&utm_campaign=2026-q2_agent-launch&utm_content=search-ad&utm_term=mcp-server
```
Paid → `medium=cpc` (covers paid search *and* paid social). `utm_term` carries
the keyword and is used **only** on `cpc` links. `google` is not yet a seeded
source, so the tool emits + nudges.

---

## Failure modes (what the tools do)

- **Unknown `utm_medium`** → hard refuse, no link emitted, shows valid values +
  closest match.
- **Unknown `utm_source`** → emits the normalized link, nudges you to add it.
- **Unknown `utm_campaign`** → not auto-created; use `add_campaign` (two-phase,
  dedup-checked) and then build the link.
- **Spec unreadable / Sheet schema malformed** → tools fail loud and specific and
  refuse to emit a link rather than silently guessing. Contact the admin.

---

## Changing the spec

Edit [`utm-spec.yaml`](./utm-spec.yaml) and open a PR. Adding a `utm_source` or a
new `utm_campaign` convention is routine. Changing the `utm_medium` enum is a
big deal — it reshapes historical analytics — so treat those PRs accordingly.
