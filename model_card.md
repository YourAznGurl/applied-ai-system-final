# Model Card: VibeFinder AI

**Author:** Ena Tarumi | **Z-number:** Z23664744 | Florida Atlantic University, Project 4: Applied AI System

## Overview
VibeFinder AI is an extension of my Module 3 Music Recommender. It lets a person describe a listening situation in plain English, retrieves notes from custom documents, converts the request into genre, mood and energy (using Gemini when a key is available, or offline rules otherwise), ranks songs with my original scorer, and explains the picks in a checked, specialized style. It is a learning project with an 18-song catalog, not a production recommender.

## Limitations and Biases
- **Tiny catalog:** with only 18 songs, the same songs keep reappearing (for example Gym Hero and Storm Runner show up for several different requests), and some genres have only one song.
- **Hand-labeled data:** genre and mood labels in `songs.csv` were assigned by hand, so the "truth" the system matches against reflects one person's judgment.
- **My own assumptions are baked into the notes:** the guide maps situations to music (gym means rock, studying means lofi, rainy day means folk). That is a stereotype, and it will not fit everyone.
- **Conflicting requests:** for "sad rainy day, I want something moody" the offline system picked folk (from the notes) and mood "moody" (from the request words), a combination no song in the catalog has. It still answered with confidence 1.0, so the confidence score does not detect this kind of mismatch.
- **Keyword retrieval:** it misses synonyms and rephrasings that are not in my notes.
- **Confidence is a heuristic, not a calibrated probability.**
- **The "AI mode: Gemini" label only means a key was present**, not that the Gemini call succeeded (see "What Surprised Me").
- **Gemini output can vary between runs**, while the offline mode is deterministic.
- **English only.**

## Misuse and Prevention
The app is low-risk, since it only recommends songs from a fixed list. The main misuse risks are prompt-injection attempts against the Gemini mode and leaking the API key. I added an input guardrail that blocks known manipulation phrases (the injection test case is blocked), a length limit, and `.env` in `.gitignore` so the key is never committed. Limits: the phrase list only catches wording I thought of, so a cleverly worded attack could pass it. The catalog check and the self-check do limit the damage, because the model can only choose from real genres and moods, and its explanation is verified against the songs actually recommended.

## What Surprised Me While Testing
- **My status label was misleading.** My first Gemini run printed "AI mode: Gemini" with a correct-looking answer, but the explanation was identical to the offline template. The log showed that every Gemini call had failed with a certificate error (`CERTIFICATE_VERIFY_FAILED`) and the agent had silently fallen back to offline rules. The fallback worked as designed, but I only noticed by reading `logs/app.log`. After I fixed the certificates, the log showed the Gemini calls succeeding.
- **A test failed with Gemini and not offline.** For "sad rainy day, I want something moody", Gemini chose mood `sad` and my test expected `moody` (7 of 8 passed). The request contains both words, and my catalog has `folk/sad` and `synthwave/moody`, so either answer is defensible. The offline rules pick the longest mood word that appears ("moody"), while Gemini weighed the whole sentence. I left the test as it was, because it shows that a test expecting one exact answer from an AI model is brittle on ambiguous requests.
- **Gibberish still gets songs.** For "asdf qwerty zxcv" the system returned five songs, with confidence 0.0 and no notes matched. It was honest about not understanding, but it did not refuse. A better design would ask a follow-up question below a confidence threshold.
- **Retrieval changed the winner less than I expected.** The top song changed in only one of four queries. The main effect of the notes was getting mood and energy right and raising confidence.
- **My first notes did not match the real catalog**, which I only noticed after listing the genres and moods in `songs.csv`.

## Collaboration with AI
I used an AI assistant (Claude) to plan the project, write most of the code, and help debug setup, git and certificate problems. I ran every command myself and pasted the real output back, so the README evidence comes from my own runs.

- **A suggestion I accepted:** making Gemini optional, with an offline rules mode as the default for tests. It made the project reproducible without an API key, and it let me test the agent and the guardrails the same way every time. It also paid off when Gemini failed, because the app kept working.
- **A suggestion I changed:** the first draft of the knowledge notes assumed only a few genres and moods. After I listed what is actually in my `songs.csv` (15 genres and 13 moods), I had the notes rewritten to match, and I checked the evaluation cases against the real catalog.
- **Something I verified instead of trusting:** the Gemini mode looked successful on screen while the calls were failing. I found the real cause in the log file, applied the certificate fix, and re-checked the log before writing it up.

## Baseline vs Specialized Output
Specialized "DJ" style vs plain baseline, measured on the 5 valid evaluation requests.

Offline mode (templates):
```
style    avg words  titles mentioned   format ok
plain         36.0             100%        0/5
dj            27.0             100%        5/5
```
Gemini mode:
```
style    avg words  titles mentioned   format ok
plain         48.2              84%        0/5
dj            26.8             100%        5/5
```
For "calm music to study for my exam tonight":

- **Plain (baseline, offline):** "Recommended: Focus Flow by LoRoom; Library Rain by Paper Lanterns; Midnight Coding by LoRoom; Coffee Shop Stories by Slow Stereo; Spacewalk Thoughts by Orbit Bloom. These match genre lofi and mood focused with low energy."
- **DJ (specialized, Gemini):** "DJ VibeFinder here: time to ace that test! Focus Flow keeps your mind sharp, while Library Rain and Midnight Coding block out distractions. Coffee Shop Stories adds a gentle rhythm, and Spacewalk Thoughts offers deep ambient calm for ultimate focus. Next up: pure success"

With Gemini, the DJ style was shorter on average (26.8 vs 48.2 words), mentioned every recommended title (100% vs 84% for plain), and followed the required format 5 out of 5 times (0 out of 5 for plain). So the specialized prompt measurably made the output more grounded and more consistent. This is one run on 5 requests, so it is a small sample, and Gemini output can vary between runs. In offline mode both styles are templates, so that table shows the format constraints more than model behavior.

## Future Improvements
- Refuse or ask a follow-up question when confidence is below a threshold.
- Show clearly in the output whether the Gemini call actually succeeded or fell back.
- Add many more songs and use embeddings so retrieval understands synonyms.
- Add user feedback (thumbs up or down) to tune the scoring weights.
