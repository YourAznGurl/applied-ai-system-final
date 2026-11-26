# Model Card: VibeFinder AI

## Overview
VibeFinder AI is an extension of my Module 3 Music Recommender. It lets a person describe a listening situation in plain English, retrieves notes from custom documents, converts the request into genre, mood and energy, ranks songs with my original scorer, and explains the picks in a checked, specialized style. It is a learning project with an 18-song catalog, not a production recommender.

## Limitations and Biases
- **Tiny catalog:** with only 18 songs, the same songs keep reappearing (for example Gym Hero and Storm Runner show up for several different requests), and some genres have only one song.
- **Hand-labeled data:** genre and mood labels in `songs.csv` were assigned by hand, so the "truth" the system matches against reflects one person's judgment.
- **My own assumptions are baked into the notes:** the guide maps situations to music (gym means rock, studying means lofi, rainy day means folk). That is a stereotype, and it will not fit everyone.
- **Conflicting requests:** for "sad rainy day, I want something moody" the system picked folk (from the notes) and mood "moody" (from the request words), a combination no song in the catalog has. It still answered with full confidence 1.0, so the confidence score does not detect this kind of mismatch.
- **Keyword retrieval:** it misses synonyms and rephrasings that are not in my notes.
- **Confidence is a heuristic, not a calibrated probability.**
- **English only.**

## Misuse and Prevention
The app is low-risk, since it only recommends songs from a fixed list. The main misuse risks are prompt-injection attempts against the Gemini mode and leaking the API key. I added an input guardrail that blocks known manipulation phrases (the injection test case is blocked), a length limit, and `.env` in `.gitignore` so the key is never committed. Limits: the phrase list only catches wording I thought of, so a cleverly worded attack could pass it. The catalog check and the self-check do limit the damage, because the model can only choose from real songs and its explanation is verified against them.

## What Surprised Me While Testing
- For the gibberish input, the system still returned five songs. The confidence was 0.0 and no notes matched, so it was honest about not understanding, but it did not refuse. A better design would ask a follow-up question below a confidence threshold.
- Retrieval changed the winning song in only one of four queries. I expected a bigger effect. Its main impact was getting mood and energy right and raising confidence, not changing the ranking.
- My first version of the notes did not match the real catalog, which I only noticed after listing the genres and moods in `songs.csv`.

## Collaboration with AI
I used an AI assistant to plan the project, write most of the code, and debug setup and git problems, and I tested every step myself by running the commands and reading the output.

- **A suggestion I accepted:** making Gemini optional, with an offline rules mode as the default for tests. It made the project reproducible without an API key, and it let me test the agent and the guardrails the same way every time.
- **A suggestion I changed:** the first draft of the knowledge notes assumed only a few genres and moods. After I listed what is actually in my `songs.csv` (15 genres and 13 moods), I had the notes rewritten to match, and I checked the evaluation cases against the real catalog.
- **[EDIT/ADD:** one more honest example in your own words, such as something you did not follow or something that was confusing, if you have one.**]**

## Baseline vs Specialized Output
```
style    avg words  titles mentioned   format ok
plain         36.0             100%        0/5
dj            27.0             100%        5/5
```
For "calm music to study for my exam tonight":

- **Plain (baseline):** "Recommended: Focus Flow by LoRoom; Library Rain by Paper Lanterns; ... These match genre lofi and mood focused with low energy."
- **DJ (specialized):** "DJ VibeFinder here: spinning Focus Flow, Library Rain, Midnight Coding, Coffee Shop Stories and Spacewalk Thoughts for your focused lofi mood at low energy. Next up: focused"

The DJ style is shorter on average (27.0 vs 36.0 words), follows a strict format (5/5 vs 0/5) and mentions every recommended title in both styles. One caveat: this comparison was run in offline mode, where both styles are templates, so it demonstrates the constraints more than model creativity.

## Future Improvements
- Refuse or ask a follow-up question when confidence is below a threshold.
- Add many more songs and use embeddings so retrieval understands synonyms.
- Add user feedback (thumbs up or down) to tune the scoring weights.