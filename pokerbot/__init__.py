"""DevFun Arena Texas Hold'em poker bot.

Package modules:
    pokerbot.quant    — hand evaluation, equity, ICM, push/fold, postflop strategy (fallback engine)
    pokerbot.profiler — opponent profiling: observed stats + natural-language summaries
    pokerbot.player   — Gemini 3.1 Flash Lite decision engine (uses the profiler; falls back to quant)
    pokerbot.bot      — arena API polling loop, decision routing, lifecycle (entry point)
"""

__version__ = "0.1.0"
