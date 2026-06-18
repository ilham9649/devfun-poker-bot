"""
Poker Profiler — opponent profiling module for DevFun poker bot.

Collects real-time observations of opponents during hands, builds
statistical profiles, and generates natural-language summaries
for use in Gemini player prompts.

Profiles are stored in ~/opponent_profiles.json and updated after
each hand event we observe."""

import json
import os
import time
from datetime import datetime, timezone
from collections import defaultdict
from typing import Optional

WORKSPACE = os.path.dirname(os.path.abspath(__file__))
PROFILES_FILE = os.path.join(WORKSPACE, "..", "opponent_profiles.json")


# ── Data Structures ─────────────────────────────────────

class OpponentObservation:
    """One observed action by an opponent."""
    def __init__(self, agent_id, agent_name, street, action_category,
                 pot_before, pot_after, call_amount, stack_before,
                 board_texture="", is_preflop=True):
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.street = street          # "Preflop", "Flop", "Turn", "River"
        self.action_category = action_category  # "fold", "call", "bet", "raise", "check", "all-in"
        self.pot_before = pot_before
        self.pot_after = pot_after
        self.call_amount = call_amount
        self.stack_before = stack_before
        self.board_texture = board_texture
        self.is_preflop = is_preflop
        self.timestamp = time.time()


class OpponentProfile:
    """Aggregated profile of a single opponent."""
    def __init__(self, agent_id, agent_name=""):
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.first_seen = time.time()
        self.last_seen = time.time()
        
        # Raw action counts
        self.total_actions = 0
        self.actions = {"fold": 0, "check": 0, "call": 0, "bet": 0, "raise": 0, "all-in": 0}
        self.preflop_actions = {"fold": 0, "check": 0, "call": 0, "bet": 0, "raise": 0, "all-in": 0}
        self.postflop_actions = {"fold": 0, "check": 0, "call": 0, "bet": 0, "raise": 0, "all-in": 0}
        
        # Derived stats
        self.hands_observed = 0
        self.chips_won = 0
        self.chips_lost = 0
        self.biggest_pot_won = 0
        
        # Action facing us (when we were in hand)
        self.facing_our_bet = {"fold": 0, "call": 0, "raise": 0}
        self.three_bet_opportunities = 0
        self.three_bet_actual = 0
        self.fold_to_cbet_opportunities = 0
        self.fold_to_cbet_actual = 0
        self.cbet_opportunities = 0  # raised preflop, postflop betting opportunity
        self.cbet_actual = 0
        
        # Stack behavior
        self.stack_at_first_seen = 0
        self.stack_trend = []  # snapshots
        
        # Classification (computed)
        self.style_classification = "unknown"
        self.profile_summary = ""
        self.last_updated = time.time()
    
    def record_action(self, action: str, street: str, pot: int, call_amount: int,
                      stack_before: int, is_preflop: bool, board_texture: str = ""):
        """Record one observed opponent action."""
        self.last_seen = time.time()
        self.total_actions += 1
        
        act = action.lower()
        if act in self.actions:
            self.actions[act] += 1
        
        if is_preflop and act in self.preflop_actions:
            self.preflop_actions[act] += 1
        elif not is_preflop and act in self.postflop_actions:
            self.postflop_actions[act] += 1
        
        if act in ("bet", "raise", "all-in"):
            self.chips_lost += call_amount  # they put money in
        elif act == "call":
            self.chips_lost += call_amount
        # fold doesn't cost extra (already committed blinds)
    
    def record_hand_observed(self):
        self.hands_observed += 1
    
    def record_chip_change(self, delta: int):
        if delta > 0:
            self.chips_won += delta
            self.biggest_pot_won = max(self.biggest_pot_won, delta)
        else:
            self.chips_lost += abs(delta)
    
    def record_facing_our_bet(self, action: str):
        act = action.lower()
        if act in self.facing_our_bet:
            self.facing_our_bet[act] += 1
    
    def record_three_bet(self, did_three_bet: bool):
        self.three_bet_opportunities += 1
        if did_three_bet:
            self.three_bet_actual += 1
    
    def record_fold_to_cbet(self, did_fold: bool):
        self.fold_to_cbet_opportunities += 1
        if did_fold:
            self.fold_to_cbet_actual += 1
    
    def record_cbet(self, did_cbet: bool):
        self.cbet_opportunities += 1
        if did_cbet:
            self.cbet_actual += 1
    
    def compute_stats(self) -> dict:
        """Compute derived statistics from raw counts."""
        total_non_check = self.actions["bet"] + self.actions["raise"] + self.actions["call"] + self.actions["fold"] + self.actions["all-in"]
        vpip_count = self.actions["call"] + self.actions["bet"] + self.actions["raise"] + self.actions["all-in"]
        pfr_count = self.actions["raise"] + self.actions["all-in"]  # simplified
        aggressive_actions = self.actions["bet"] + self.actions["raise"] + self.actions["all-in"]
        passive_actions = self.actions["call"]
        
        vpip = vpip_count / total_non_check if total_non_check > 0 else 0
        pfr = pfr_count / total_non_check if total_non_check > 0 else 0
        af = aggressive_actions / passive_actions if passive_actions > 0 else aggressive_actions
        
        three_bet_pct = self.three_bet_actual / self.three_bet_opportunities if self.three_bet_opportunities > 0 else 0
        fold_to_cbet_pct = self.fold_to_cbet_actual / self.fold_to_cbet_opportunities if self.fold_to_cbet_opportunities > 0 else 0
        cbet_pct = self.cbet_actual / self.cbet_opportunities if self.cbet_opportunities > 0 else 0
        
        return {
            "vpip": round(vpip, 3),
            "pfr": round(pfr, 3),
            "aggression_factor": round(af, 2),
            "three_bet_pct": round(three_bet_pct, 3),
            "fold_to_cbet_pct": round(fold_to_cbet_pct, 3),
            "cbet_pct": round(cbet_pct, 3),
            "hands_observed": self.hands_observed,
            "total_actions": self.total_actions,
            "facing_our_bet": dict(self.facing_our_bet)
        }
    
    def classify_style(self) -> str:
        """Classify opponent playing style."""
        stats = self.compute_stats()
        vpip = stats["vpip"]
        pfr = stats["pfr"]
        af = stats["aggression_factor"]
        
        if self.total_actions < 5:
            return "unknown (insufficient data)"
        
        # LAG: high VPIP, high PFR
        if vpip > 0.35 and pfr > 0.12:
            return "loose-aggressive"
        # TAG: low VPIP, high PFR
        if vpip <= 0.35 and vpip >= 0.15 and pfr > 0.10:
            return "tight-aggressive"
        # Loose-passive: high VPIP, low PFR
        if vpip > 0.35 and pfr <= 0.10:
            return "loose-passive (calling station)"
        # Tight-passive: low VPIP, low PFR
        if vpip < 0.20 and pfr < 0.08:
            return "tight-passive (nit)"
        # Weak-tight
        if vpip < 0.25 and af < 0.5:
            return "weak-tight"
        
        return "unknown"
    
    def generate_summary(self) -> str:
        """Generate natural-language profile summary for AI prompts."""
        stats = self.compute_stats()
        style = self.classify_style()
        
        name = self.agent_name or f"Opponent {self.agent_id[:8]}"
        reliability = "high" if self.total_actions >= 20 else \
                      "medium" if self.total_actions >= 10 else "low"
        
        # Build tendencies
        tendencies = []
        
        if stats["fold_to_cbet_pct"] > 0.50 and stats["fold_to_cbet_pct"] <= 1.0:
            tendencies.append(f"folds to continuation bets {stats['fold_to_cbet_pct']*100:.0f}% of the time")
        
        if stats["cbet_pct"] > 0.60:
            tendencies.append("c-bets frequently when raising preflop")
        
        if stats["three_bet_pct"] > 0.08:
            tendencies.append(f"3-bets {stats['three_bet_pct']*100:.0f}% of opportunities (wide)")
        elif stats["three_bet_pct"] < 0.03:
            tendencies.append("rarely 3-bets (only premium hands)")
        
        if stats["aggression_factor"] > 2.0:
            tendencies.append("very aggressive post-flop")
        elif stats["aggression_factor"] < 0.5:
            tendencies.append("passive post-flop, prefers to call")
        
        # Facing our bets
        fob = stats["facing_our_bet"]
        total_facing = sum(fob.values())
        if total_facing > 3:
            fold_rate = fob.get("fold", 0) / total_facing
            raise_rate = fob.get("raise", 0) / total_facing
            if fold_rate > 0.60:
                tendencies.append("folds to our bets ~{:.0f}%".format(fold_rate*100))
            if raise_rate > 0.30:
                tendencies.append("raises our bets ~{:.0f}%".format(raise_rate*100))
        
        tendency_text = "; ".join(tendencies) if tendencies else "no clear tendencies observed yet"
        
        summary = (
            f"{name}: {style} (reliability: {reliability}). "
            f"VPIP {stats['vpip']*100:.0f}% | PFR {stats['pfr']*100:.0f}% | "
            f"AF {stats['aggression_factor']:.1f}. "
            f"Observed {stats['hands_observed']} hands, {stats['total_actions']} actions. "
            f"Tendencies: {tendency_text}."
        )
        
        return summary
    
    def to_dict(self) -> dict:
        stats = self.compute_stats()
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "first_seen": datetime.fromtimestamp(self.first_seen, tz=timezone.utc).isoformat(),
            "last_seen": datetime.fromtimestamp(self.last_seen, tz=timezone.utc).isoformat(),
            "hands_observed": self.hands_observed,
            "total_actions": self.total_actions,
            "stats": stats,
            "actions_breakdown": dict(self.actions),
            "style_classification": self.classify_style(),
            "profile_summary": self.generate_summary()
        }
    
    @classmethod
    def from_dict(cls, data: dict):
        p = cls(data["agent_id"], data.get("agent_name", ""))
        p.first_seen = datetime.fromisoformat(data["first_seen"]).timestamp()
        p.last_seen = datetime.fromisoformat(data["last_seen"]).timestamp()
        p.hands_observed = data["hands_observed"]
        p.total_actions = data["total_actions"]
        # Restore action counts from stored breakdown
        fb = data.get("actions_breakdown", {})
        for k in p.actions:
            p.actions[k] = fb.get(k, 0)
        return p


# ── Profiler Manager ────────────────────────────────────

class Profiler:
    """Manages all opponent profiles."""
    
    def __init__(self, profiles_path: str = PROFILES_FILE):
        self.profiles_path = profiles_path
        self.profiles: dict[str, OpponentProfile] = {}
        self._load()
    
    def _load(self):
        try:
            with open(self.profiles_path) as f:
                data = json.load(f)
            for agent_id, pdata in data.get("profiles", {}).items():
                self.profiles[agent_id] = OpponentProfile.from_dict(pdata)
        except (FileNotFoundError, json.JSONDecodeError):
            self.profiles = {}
    
    def save(self):
        data = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "profile_count": len(self.profiles),
            "profiles": {aid: p.to_dict() for aid, p in self.profiles.items()}
        }
        os.makedirs(os.path.dirname(self.profiles_path) or ".", exist_ok=True)
        with open(self.profiles_path, "w") as f:
            json.dump(data, f, indent=2)
    
    def get_or_create(self, agent_id: str, agent_name: str = "") -> OpponentProfile:
        if agent_id not in self.profiles:
            self.profiles[agent_id] = OpponentProfile(agent_id, agent_name)
        elif agent_name and not self.profiles[agent_id].agent_name:
            self.profiles[agent_id].agent_name = agent_name
        return self.profiles[agent_id]
    
    def observe_action(self, agent_id: str, action: str, street: str, pot: int,
                       call_amount: int, stack_before: int, is_preflop: bool,
                       board_texture: str = "", agent_name: str = ""):
        profile = self.get_or_create(agent_id, agent_name)
        profile.record_action(action, street, pot, call_amount, stack_before, is_preflop, board_texture)
    
    def record_hand_observed(self, agent_id: str):
        if agent_id in self.profiles:
            self.profiles[agent_id].record_hand_observed()
    
    def get_profiles_for_prompt(self, agent_ids: list[str]) -> str:
        """Get formatted profile text for Gemini prompt."""
        if not agent_ids:
            return "No opponent data yet."
        
        parts = []
        # Sort by reliability (most observed first)
        sorted_profiles = sorted(
            [self.profiles[aid] for aid in agent_ids if aid in self.profiles],
            key=lambda p: p.total_actions,
            reverse=True
        )
        
        for profile in sorted_profiles:
            if profile.total_actions > 0:
                parts.append(profile.generate_summary())
            else:
                name = profile.agent_name or f"Opponent {profile.agent_id[:8]}"
                parts.append(f"{name}: no data yet (new opponent).")
        
        return "\n".join(parts)
    
    def get_all_active_profiles(self, min_actions: int = 3) -> list:
        return [p for p in self.profiles.values() if p.total_actions >= min_actions]
    
    def get_table_profiles(self, table_seats: list[dict], our_agent_id: str) -> str:
        """Get profile summaries for all opponents at a table."""
        opponent_ids = []
        for seat in table_seats:
            aid = seat.get("agentId", "")
            if aid and aid != our_agent_id:
                opponent_ids.append(aid)
                # Capture name if available
                aname = seat.get("agentName", "")
                if aname:
                    self.get_or_create(aid, aname)
        
        return self.get_profiles_for_prompt(opponent_ids)
