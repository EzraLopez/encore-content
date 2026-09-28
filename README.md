# Encore Content

Remote content for the Encore festival app. The app fetches
`v1/festivals.json` on launch, caches it on-device, and falls back to its
bundled copy when offline.

## Updating content

Edit `v1/festivals.json`, commit, and push. Changes go live within minutes
(raw.githubusercontent.com caches briefly). No app update needed.

### Adding a festival

Append an object to the `festivals` array:

```json
{
  "id": "my-fest-2027",
  "name": "My Fest",
  "tagline": "One line description",
  "location": "City, State",
  "venue": "Venue Name",
  "websiteUrl": "https://example.com",
  "instagramUrl": "https://instagram.com/myfest",
  "startDate": "2027-06-04",
  "endDate": "2027-06-06",
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
- `days` may be `[]` for a TBA lineup; the app hides the lineup UI.
- `mapImageUrl` may be omitted or `null`; the app shows its placeholder map.
- Dates are `YYYY-MM-DD`, times are 24h `HH:MM`.

### Map artwork

Put PNGs in `v1/maps/` and reference them with the raw URL above.
Landscape, ~1920px wide works well. Keep files under ~3 MB.

## Versioning

Breaking schema changes go in a new top-level folder (`v2/`). The app
pins the version it understands.
