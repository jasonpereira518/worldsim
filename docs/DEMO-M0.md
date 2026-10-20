# Demo script — Milestone 0

Takes about five minutes. Internet is needed for basemap tiles.

## 1. Start

```bash
cd apps/web && npm install && npm run dev
```

Open http://localhost:3000. You should see: top bar (logo, "Mock engine · M0" badge, simulated date), a white monochrome world map with a layer-pill group top-left, a timeline docked at the bottom, and the chat panel on the right with four example prompts.

## 2. Run the outbreak scenario

Click **"A novel H5N1 variant begins human-to-human transmission in Vietnam"** (or type it).

- The chat shows an **Interpretation** card: event type `outbreak`, origin Hanoi, start 2026-10-20, 180-day horizon, mechanisms, and assumption chips. Hover a chip: each shows its origin (`data` / `model` / `mock` / `user`) and confidence.
- Within a couple of seconds dots start changing: hollow (unaware) → light gray (aware) → mid gray (reacting) → solid black (affected) → ring (recovered). Thin lines with moving dashes show where exposure jumped between cities.
- Speech bubbles appear at affected places. **Hover a bubble** to see "Why": the state change and the metric before → after. Click one to open the persona drawer.
- The timeline fills with tick marks for notable moments ("Reaches Thailand", "10% of represented population affected"). The chat lists them as the playhead passes.
- Progress shows "Simulating day N of 180" while the server streams; playback runs independently at 1×. Try **4×** or **16×**.

## 3. Explore

- **Zoom in** on Southeast Asia. Clusters split into city segments; population totals are conserved (cluster labels show millions of people). Click a cluster to expand it.
- **Click a dot**: the drawer shows the persona, people represented, demographics, trait bars, a state-history step chart, memory (dated status changes), and everything it said.
- **Voices tab**: every bubble so far, filterable by country, persona type, and sentiment. Click one to fly there.
- **Scrub** the timeline or use ← / → keys; **Space** toggles play. Click **Legend** in the layer pills for the encoding.
- **Dark mode**: top-right toggle. Map, UI, and bubbles invert; still no color anywhere.
- At the end of the timeline the **Summary** card appears: headline, metrics with confidence, and an honest note that this is a single mock run with no intervals.

## 4. Follow-ups and commands

In the chat:

- `zoom into Brazil` — flies the map.
- `why did Thailand get hit` — answers from the event log of this run.
- `/assumptions`, `/sources`, `/reset`; `/compare` and `/export` explain they arrive in Milestone 4.
- Type a new event to start a new run; `Restart` re-runs the current prompt (same seed → identical result).

## 5. Other scenarios

- `Apple launches a $499 AR headset globally next month` — global seeding at hubs, `adopted` / `opposed` states, start date 2026-11-20, 7-day steps.
- `The EU imposes a 40% tariff on Chinese EVs` — policy; the rate feeds the price metric.
- `A magnitude 8.1 quake hits Istanbul` — stays regional (reach cap).
- `A massive earthquake strikes` — the one allowed clarifying question ("Where does this start?"); answer `Tokyo`.

## 6. Checks

```bash
cd apps/web && npm test && npm run build
```

Tests cover: grayscale-only map style in both themes, population conservation of the persona generator, engine determinism and monotone status progression, parser on the reference prompts, and bubble collision layout.
