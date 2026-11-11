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
- `accentColor` is the festival's own color as `#RRGGBB`: its cards, its
  glow, its Home countdown card. Take it from the festival's site or logo
  (the highlight color, not a background). The apps darken or lighten it
  where text sits on it, so pick the brand color as it is, not a
  "readable" version of it. Two festivals may share a color only when they
  are the same event (two weekends, read off the `websiteUrl` host); any
  other pair must be far enough apart to tell their cards apart, and the
  validator rejects it otherwise: pick the festival's second color.
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
