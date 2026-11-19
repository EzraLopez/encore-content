# Encore Content

Remote content for the Encore festival app. This repo is the publishing
side of Encore's remote-configuration system: the apps fetch the config on
launch, cache the last good payload on-device, and fall back to their
bundled copy when a fetch fails or returns something malformed — a bad
payload never clobbers good data. **Content changes need no app release.**

Two config versions live side by side:

- **`v2/config.json`** — the current config (festivals + standalone shows,
  wrapped in a versioned envelope). Current app builds read this.
- **`v1/festivals.json`** — the original festivals-only format. It stays
  live and unchanged for older app builds that pin v1. Do not edit `v1/`
  when publishing anymore; publish to v2 (and leave v1 as-is).

## v2 publishing workflow

Every publish follows the same steps:

1. Edit `v2/config.json` — add or change a festival, a lineup, set times,
   a map, or a show (formats below).
2. **Bump `meta.version` by exactly 1** and set `meta.publishedAt` to the
   current UTC time (ISO 8601, e.g. `2026-11-09T03:04:58Z`). The apps use
   `meta.version` as the change trigger for update notifications, so a
   content edit without a version bump will be picked up silently at best.
3. Run the validator — it must pass before you push:

   ```sh
   python3 tools/validate_config.py
   ```

4. Commit and push. Changes go live within minutes
   (raw.githubusercontent.com caches briefly). Apps pick the new config up
   on their next fetch — on launch, on pull-to-refresh, or on a background
   refresh — with no app update.

### Announced lineups (names before set times)

Most festivals announce artists weeks or months before set times. Put
them in the festival's optional `lineup` array; leave `days` empty
until times are published:

```json
"lineup": [
  { "id": "dreamstate-socal-2026-armin-van-buuren", "artist": "Armin van Buuren",
    "day": "2026-11-20", "stage": "Dream" },
  { "id": "dreamstate-socal-2026-alpha-9", "artist": "Alpha 9" }
]
```

- `day` (YYYY-MM-DD, within the festival) and `stage` are optional:
  include them only when the festival has said them.
- **Ids are permanent.** Use `<festival-id>-<artist-slug>`. When set times
  come out, move each artist into `days` as a set **with the same id**
  and remove it from `lineup`; a favourite made from the lineup then
  becomes a timed favourite, with a reminder, on the next refresh. (The
  apps also match by artist name if an id changes, but don't rely on it.)
- An artist playing twice gets `-2` on the second set's id.
- Apps since iOS build 61 / Android 49 show the lineup on About, let
  people favourite it, and notify followers "Lineup announced", then
  "Set times are out". Older builds ignore the field.

### v2 envelope

```json
{
  "meta": { "version": 3, "publishedAt": "2026-11-09T03:04:58Z" },
  "festivals": [ /* festival objects, same shape as v1 */ ],
  "shows": [ /* standalone show objects */ ]
}
```

### Adding a festival (v2)

Append an object to the `festivals` array in `v2/config.json`:

```json
{
  "id": "my-fest-2027",
  "name": "My Fest",
  "tagline": "One line description",
  "location": "City, State",
  "venue": "Venue Name",
  "websiteUrl": "https://example.com",
  "instagramUrl": "https://instagram.com/myfest",
  "accentColor": "#FE005E",
  "startDate": "2027-06-04",
  "endDate": "2027-06-06",
  "timezone": "America/Chicago",
  "mapImageUrl": "https://raw.githubusercontent.com/EzraLopez/encore-content/main/v1/maps/my-fest.png",
  "days": [
    {
      "date": "2027-06-04",
      "stages": [
        {
          "name": "Main Stage",
          "sets": [
            { "id": "mf-2027-06-04-main-1", "artist": "Some Artist", "start": "20:00", "end": "21:30" }
          ]
        }
      ]
    }
  ]
}
```

Notes:

- `id` must be unique and stable — favorites and RSVPs are keyed off it.
  Set ids must be unique too, for the same reason.
- `timezone` is required (IANA name, e.g. `America/Chicago`): reminders,
  the Now tab, and schedule times are computed in the festival's timezone.
- `days` may be `[]` for a TBA lineup; the app hides the lineup UI. When a
  lineup later lands (days go from `[]` to non-empty), followers get an
  update notification.
- `mapImageUrl` may be omitted or `null`; the app shows its placeholder map.
- `mapImageUrls` lists several maps in order (grounds, a stage, the
  afterparty, parking…), and `mapNames` names each one, same order and
  same count: `"mapNames": ["Festival grounds", "Parking & rideshare"]`.
  The Maps tab has a dropdown with those names (from iOS 203 / Android
  162; older builds say "Map 2 of 6"). Keep `mapImageUrl` as the first map
  for the oldest builds.
- `requestedAs` (optional) lists the names people asked for this festival
  by in the apps ("Request a festival"), when they differ from its own
  name: `"requestedAs": ["fs fest"]`. A phone that asked for one of them
  is notified, on that phone only, when the festival appears here. The
  festival's own name already answers a request for it (the year and
  anything after a dash are ignored), so this is only for other spellings.
- `accentColor` is the festival's own color as `#RRGGBB`: its cards, its
  glow, its Home countdown card. Take it from the festival's site or logo
  (the highlight color, not a background). The apps darken or lighten it
  where text sits on it, so pick the brand color as it is, not a
  "readable" version of it. The brand color wins even when another festival's
  is similar (Nov 15, 2026): two festivals may both be blue. The
  validator refuses only the same color on two different events (a
  copy-paste slip); two weekends of one event, read off the `websiteUrl`
  host, share theirs. Read the color off the festival's logo, such as its
  Instagram avatar; leave it out when the logo is black and white or a
  photo.
  Optional. Without it the app uses the color it ships for that id, or one
  derived from the id. Changing only a color notifies nobody. Builds
  before iOS 34 / Android 26 ignore the field.
- Dates are `YYYY-MM-DD`, set times are 24h `HH:MM`. An overnight set ends
  after midnight (`"start": "23:30", "end": "01:00"`); `start` may not
  equal `end`.

### Adding a standalone show (v2)

Append an object to the `shows` array in `v2/config.json`. Remote shows
are editorial content shown to every install (they appear in Home, Search,
and Now like festivals); they are separate from shows a user adds for
themselves in the app.

```json
{
  "id": "svdden-death-brooklyn-2026",
  "artist": "SVDDEN DEATH",
  "support": ["Support Act"],
  "venue": "The Brooklyn Monarch",
  "city": "New York, NY",
  "start": "2026-11-28T23:00:00",
  "timezone": "America/New_York"
}
```

`id`, `artist`, `venue`, `city`, `start` (ISO local datetime in the show's
timezone), and `timezone` are required; `support` is optional.

### An afterparty (a second part of the night)

A festival night that continues somewhere else under the same name (an
official afterparty, often a separate ticket) goes beside the day's
`stages`, not inside them:

```json
{ "date": "2026-11-20",
  "stages": [ /* the festival's own stages */ ],
  "afterparty": {
    "name": "Official Afterparty",
    "note": "Separate ticket · aboard the Queen Mary",
    "stages": [ { "name": "Grand", "sets": [ /* ... */ ] } ]
  } }
```

- It belongs to the day whose night it follows: Friday's afterparty, on
  Saturday from midnight to 6 AM, is in Friday's day with times
  `00:00` to `06:00`.
- Apps from iOS build 153 / Android 119 show a Festival / Afterparty
  switch on that day's Schedule and My Sets; hearts, reminders and
  clashes work across both. Older builds ignore the field, which is why
  it is not just more stages: they would draw one grid to 6 AM.
- Set ids are unique across the catalog as always; prefix them with
  `<festival-id>-afterparty-` so an artist who plays both doesn't collide.
- An extra stage inside the grounds (an art car) is an ordinary stage.

### Map artwork

Put PNGs in `v1/maps/` (shared by both config versions) and reference them
with the raw URL above. Landscape, ~1920px wide works well. Keep files
under ~3 MB.

### The validator

`tools/validate_config.py` (Python 3, standard library only) checks the
envelope (`meta.version` is a positive integer, `meta.publishedAt` parses),
required festival fields, unique festival/set/show ids, IANA timezones,
`YYYY-MM-DD` dates, 24h `HH:MM` set times, that no set has `start == end`,
the required show fields, and that each `accentColor` is `#RRGGBB` and
not a near-copy of another festival's. It prints every problem it finds and exits
non-zero. Run it against another file with
`python3 tools/validate_config.py path/to/config.json`.

## Update notifications and deep links

There is no server and there are no accounts yet, so update notifications
are generated **on-device**: when an app fetches a config whose
`meta.version` is newer than its stored baseline, it diffs the two and
posts local notifications for what changed — a new festival, a lineup
published for a festival the user follows, artists added/removed or set
times changed on a followed festival, a new festival map, changed dates,
or a new remote show.

Every notification (and every set reminder) deep-links into the app:

- `encore://festival/<id>` — the festival's detail page
- `encore://festival/<id>/schedule` — the festival's Schedule tab
  (lineup-change notifications link here)
- `encore://artist/<festivalId>/<artistName>` — the artist page
- `encore://show/<id>` — the show

## v1 (legacy)

Older app builds fetch `v1/festivals.json` on launch, cache it on-device,
and fall back to their bundled copy when offline. The file keeps its
original shape (`{ "festivals": [...] }`, same festival objects as v2) and
stays live for those builds. Breaking schema changes go in a new top-level
folder (`v2/`, `v3/`, …); each app pins the version it understands.

## Artist photos from Apple Music (Nov 13, 2026)

`tools/enrich_artists.py` fills `imageUrl` from Apple Music artist
artwork (MusicKit catalog API, 600x600) for every artist that has an
`appleMusicUrl` and no photo. It needs a MusicKit developer token,
which this repo never holds:

1. developer.apple.com → Certificates, Identifiers & Profiles → Keys →
   "+" → enable MusicKit → download the `.p8` (Ezra keeps it).
2. Sign a developer token from that key (ES256 JWT, `kid` = key id,
   `iss` = team `4DS7X7GGR3`, up to 6 months).
3. Locally: `APPLE_MUSIC_TOKEN=… python3 tools/enrich_artists.py`.
   In the cloud routines: a network secret on the Default environment
   (Bearer, host `api.music.apple.com`, path `/v1/`), so the token
   never reaches a session.

Without a token the pass prints a note and is skipped.

## Request outcomes (Nov 13, 2026)

`requestOutcomes` (optional, top level) tells the apps what the request
research decided for a requested festival it did NOT add, so "Your
requests" (in You, and in Search when the request is searched again)
can say so instead of "we're looking into it". Notes describe what the
research found; they never suggest adding the request as a show:

```json
"requestOutcomes": {
  "portola": {"outcome": "no-dates-yet", "note": "2027 dates aren't out yet · we'll keep checking"},
  "pretty lights": {"outcome": "not-a-festival", "note": "Pretty Lights plays the Fox Theater, Oakland, Nov 19–21"}
}
```

Keys are request keys (lowercase; years, anything after a dash and a
trailing weekend marker dropped), the same matching the apps use.
`outcome` is `no-dates-yet`, `not-a-festival` or `unclear`; `note` is an
optional public line of 2–120 characters. Never put who asked, how many
or from where here: this file is public. When a festival is later added,
remove its outcome (the apps show "Added" from the festival itself).

## Instagram watch (Nov 15, 2026)

`tools/watch_instagram.py --file-changes` runs every hour on Ezra's Mac
(LaunchAgent `dev.elopez.katla-instagram-watch`, plist in `tools/`, log
`~/Library/Logs/katla/instagram-watch.log`). For each festival from the
day before it starts through its last day it reads the latest 8 posts of
the festival's Instagram (Meta Business Discovery, through @getkatla;
token in `~/.config/katla/meta-token`, expires 2027-01-15). It reads the
live catalog, remembers the posts it has seen
(`~/.config/katla/instagram-seen.json`), and files each new post whose
caption uses change words (set times, cancel, weather…) as a festival
change report: Firestore `feedback`, kind `change`, platform `watcher`,
with the post's image. The Encore queue keeper turns reports into
proposed catalog changes; on Ezra's Approve it opens a pull request.
Nothing here edits the catalog. Stories can't be read this way; Report
a Change in the apps covers them. It only runs while the Mac is awake.

## Instagram link (Nov 15, 2026)

Every festival has `instagramUrl` (`https://instagram.com/<handle>`): the
About page links it, and the hourly Instagram watch can only follow a
festival that has one. Check a handle before adding it:
`python3 tools/check_instagram.py <handle>…` prints the account's name,
followers and website from Instagram itself (this Mac only: it uses the
watch's token). Editions of one series share a handle. An audit that day
found 44 of 58 festivals without one, Coachella included.

## Subreddit link (Nov 15, 2026)

`redditUrl` on a festival (optional, `https://www.reddit.com/r/<name>/`)
adds a Reddit link beside Website and Instagram in the apps (iOS 129 /
Android 97 and later). Use the festival's own community subreddit, and
only one you have opened and seen is about that festival: Reddit blocks
automated checks, so the validator can only check the link's shape.

**Every festival added to the catalog gets this looked up**, like its
website and Instagram: search for the festival's own subreddit, link it
when it is public, active and about that festival (editions of one
series share one), and leave the field out when there is none. A genre
or city subreddit doesn't count, and a guess is worse than a blank.

## Cancellations and notices (Nov 15, 2026)

Three optional fields on a festival (apps from iOS 121 / Android 91;
older builds ignore them):

```json
"cancelledDays": ["2026-11-15"],
"notice": {
  "id": "seismic-2026-sunday-cancelled",
  "title": "Sunday is cancelled",
  "body": "The grounds are unsafe after heavy rain. Do not travel to the site.",
  "notify": true,
  "linkUrl": "https://www.instagram.com/seismicdanceevent/",
  "linkLabel": "Seismic's announcement",
  "notifyTitle": "🚨 Seismic: Sunday is cancelled 🚨",
  "notifyBody": "Don't travel to the site. Open for what happens next."
}
```

- `cancelledDays`: dates of days that are called off. `cancelled: true`
  calls off the whole festival. **Leave the day and its sets in `days`.**
  The apps show the day marked cancelled and keep people's hearts, and
  send no reminders for it. Deleting the sets makes every build drop
  those hearts.
- `notice`: any message, not only a cancellation (doors moved, a stage
  closed). It shows on Home and at the top of About. With `notify`
  (true unless set false), everyone following the festival gets it once
  as a notification, in these words, the next time their phone
  refreshes the catalog. There is no push, so that can take hours.
- `linkUrl` (https only) puts a link under the message, worded by
  `linkLabel` ("More details" when left out). Point it at the
  festival's own announcement. Apps from iOS 122 / Android 92.
- `notifyTitle` and `notifyBody` are the notification's own words, for
  when it should say what happened and give a reason to open it. Left
  out, the notification is "<festival>: <title>" over `body`.
- Give a new message a new `id`: a phone notifies once per id. Remove
  the notice when it no longer matters.
- A cancellation needs a notice saying why; the validator checks that,
  and that each cancelled day is one of the festival's days.
- Use the festival's own announcement as the source and put its link in
  the commit message.

## Instagram feed watch (Nov 15, 2026)

`tools/watch_instagram.py` reads public feed posts for festivals that
are on, from the day before they start through their last day. It uses
Meta's Business Discovery API (the official route; nothing is scraped)
and prints JSON: each post's permalink, time and caption, or an
explicit failure. It does not edit the catalog and does not publish.
A proposed change still goes to the queue for Ezra.

The Katla Meta app is **Katla Festival Watch**, id `4546099592371580`.
Business Discovery needs a Facebook user token with `instagram_basic`,
`instagram_manage_insights` and `pages_read_engagement`, and the
numeric id of the `@getkatla` Instagram account that makes the query.
Neither is in this repo:

- token: `KATLA_IG_TOKEN`, or `~/.config/katla/meta-token` mode 600
- id: `KATLA_IG_USER_ID`, or `~/.config/katla/ig-user-id`

`python3 tools/watch_instagram.py --dry-run` lists who would be checked
and does not need either. A real run exits non-zero when a due festival
could not be read. Tests: `python3 tests/test_watch_instagram.py`.

Checked the evening of Nov 15, 2026: the Katla Page (id
`1436561812876094`) is linked to `@getkatla` (Instagram user id
`17841479841352396`). A long-lived user token for Katla Festival Watch
is in `~/.config/katla/meta-token` (mode 600). It expires 2027-01-15
03:25 UTC; data access expires 2027-02-14 03:25 UTC. Its scopes are
`instagram_basic`, `instagram_manage_insights`, `pages_read_engagement`
and `pages_show_list`, each limited to that Page or that Instagram
account. `instagram_content_publish` is not on the token.

`python3 tools/watch_instagram.py --date 2026-11-15` returned 8 posts
for `seismic-dance-event-2026` (`@seismicdanceevent`), and the same
check run from launchd did it again (exit 0, 8 posts, newest
`https://www.instagram.com/p/Dfx08Qgy4zn/`). The script reads the token
file itself. It does not see a cloud network secret unless something
sets `KATLA_IG_TOKEN`. `/me/accounts` is empty for this token; the Page
and `@getkatla` answer when requested by id. The app is still
unpublished, standard access only.

On this Mac the check repeats itself. The LaunchAgent
`dev.elopez.katla-instagram-watch` (plist in `tools/`, installed at
`~/Library/LaunchAgents/`) runs the script every hour while the Mac
is awake. It does not start at login and it is not kept alive. Outside
a festival window the run reads the catalog and makes no Instagram
call. Output is appended to `~/Library/Logs/katla/instagram-watch.log`.
No server is involved. A cloud routine is not wired.

## Where a festival is (Nov 19, 2026)

`latitude` and `longitude` (decimal degrees, both or neither) put a festival
on the map tab of profiles. In the cloud routines, or anywhere,
`python3 tools/add_coordinates.py --write` fills in any that are missing by
the festival's `location` (Open-Meteo's free geocoder); the validator warns
about a festival without them. On a Mac, Apple's geocoder by venue is more
precise:
`swiftc -O tools/geocode.swift -o /tmp/geocode`, then feed it
`id<TAB>venue, location` lines on stdin; it prints `id<TAB>lat<TAB>lon`
(`-` when nothing was found: try the location alone). Check the result on a
map before publishing; the geocoder sometimes picks a same-named place
elsewhere (Grant Park, IL for Chicago's Grant Park). Builds without the map
ignore the fields.

## Telling the apps a newer build is out

`meta.iosBuild` / `meta.androidBuild` (with `iosUpdateUrl` /
`androidUpdateUrl`) are the newest builds testers can install. An app on
an older build shows "A newer Encore is ready" on Home. Set them with
`tools/set_app_build.py ios 95` or `tools/set_app_build.py android 70`
once a build has reached the testers (the Friends TestFlight group, Play
internal testing), then commit and push.
