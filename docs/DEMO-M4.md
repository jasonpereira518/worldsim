# Demo script — Milestone 4 (branching, compare, feeds, export, sharing)

About eight minutes, after one finished run from `docs/DEMO-M2.md` or `docs/DEMO-M3.md`.

## 1. Branch from chat

With the outbreak run loaded, type **What if borders close on day 10?** The reply names the change, and a new run streams with the same seed and the closure applied on day 10. With the launch run, try **Rerun with a 20% lower price**.

## 2. Compare

Type **Compare with the baseline**, or click **Compare with baseline** on the summary card. The overlay shows both runs' key-metric bands (solid for the baseline, dashed for the branch median), every outcome with its 90% interval and the change, and the countries that moved most (above 5 million people). For the price cut, units rise about 20% while revenue barely moves.

## 3. Run history

Open the **Runs** tab. Branches are nested under their baseline, and each row can be reloaded (it replays from its saved seed and configuration) or compared with its parent.

## 4. Live signals

The empty chat lists live USGS earthquakes and WHO Disease Outbreak News items. Rings on the map are USGS earthquakes from the past week, sized by magnitude. Clicking a ring or a list item drafts a scenario prompt in the chat input. When a feed cannot be reached, its last good copy is served and labeled stale.

## 5. Export and share

- **Export** (top bar) or **Full report** opens `/report/<run_id>`. **Print / Save PDF** uses the print stylesheet, and **Download Markdown** saves the same report as `.md`.
- **Share link** copies `/r/<run_id>`, a read-only replay without the chat input.
- Slash commands: `/assumptions`, `/sources`, `/compare`, `/export`, `/share`, `/runs`, `/reset`.
