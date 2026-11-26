"""Command-line app for VibeFinder AI."""
import argparse

from .agent import VibeAgent, save_trace_markdown, setup_logging


def show(result):
    """Print one result in a readable way."""
    print("\n" + "=" * 60)
    print("Request:", result["query"])
    if not result["valid"]:
        print("Blocked by guardrail:", result["message"])
        return
    p = result["prefs"]
    print(f"Understood as: genre={p['genre']}, mood={p['mood']}, energy={p['energy']:.2f}")
    mode = "Gemini" if result["llm_used"] else "offline rules"
    print(f"Confidence: {result['confidence']} | AI mode: {mode} | Scorer: {result['engine']}")
    print("Notes used:", ", ".join(result["notes_used"]) or "none")
    print("\nTop picks:")
    for i, r in enumerate(result["recs"], 1):
        print(f"  {i}. {r['title']} by {r['artist']} (score {r['score']})")
    print("\n" + result["explanation"])


def main():
    parser = argparse.ArgumentParser(description="VibeFinder AI music recommender")
    parser.add_argument("request", nargs="*", help="the vibe you want, in plain English")
    parser.add_argument("--style", choices=["dj", "plain"], default="dj")
    parser.add_argument("--offline", action="store_true", help="do not use Gemini")
    args = parser.parse_args()

    setup_logging()
    agent = VibeAgent(use_llm=not args.offline, style=args.style)

    if args.request:  # one request given on the command line
        result = agent.run(" ".join(args.request))
        show(result)
        save_trace_markdown(result)
        return

    print("VibeFinder AI - describe a vibe (type 'quit' to stop).")
    while True:
        text = input("\nWhat vibe? > ")
        if text.strip().lower() in {"quit", "exit", "q"}:
            break
        result = agent.run(text)
        show(result)
        save_trace_markdown(result)


if __name__ == "__main__":
    main()