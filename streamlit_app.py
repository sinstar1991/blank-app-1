#!/usr/bin/env python3
"""
Poker RTA CLI – Texas Hold'em Hand Evaluator + Empfehlungen

Funktionen:
- Bewertung der aktuellen Handstärke (High Card bis Straight Flush)
- Unterstützung für 2 Hole Cards + 0–5 Boardkarten (Preflop bis River)
- Einfache, aber sinnvolle Handlungsempfehlungen (Fold / Call / Bet / Raise)
- Berücksichtigung von Position, Stack in BB und Potgröße

Nutzung (Beispiele):
python poker_rta.py --hole As Ks --board Ah Td 2c --position BTN --stack 100 --pot 12
python poker_rta.py --hole 4s 6s --board 6s 6c 4d --position BB --stack 100 --pot 15
"""

import argparse
from dataclasses import dataclass
from typing import List, Literal, Tuple

from treys import Card, Evaluator  # [web:54][web:65]


# ---------- Datamodelle ----------

Street = Literal["preflop", "flop", "turn", "river"]

POSITION_ORDER = ["UTG", "UTG1", "UTG2", "MP", "CO", "BTN", "SB", "BB"]


@dataclass
class HandEvaluation:
    street: Street
    hand_class: str
    score: int
    pct_rank: float
    description: str


@dataclass
class Recommendation:
    label: str
    action: str
    explanation: str


# ---------- Hilfsfunktionen ----------


def normalize_card_str(card_str: str) -> str:
    """
    Wandelt Eingaben wie 'Ah', 'AS', 'assherz' in treys‑Format wie 'Ah' um.
    Erlaubte Ranks: 2-9,T,J,Q,K,A; Suits: c, d, h, s.
    """
    s = card_str.strip().lower()

    # deutsche Eingaben (ass herz, herz ass, etc.) sehr grob normalisieren
    replacements = {
        "ass": "a",
        "herz": "h",
        "herz": "h",
        "kreuz": "c",
        "karo": "d",
        "pik": "s",
    }
    for k, v in replacements.items():
        s = s.replace(k, v)

    rank_map = {
        "2": "2",
        "3": "3",
        "4": "4",
        "5": "5",
        "6": "6",
        "7": "7",
        "8": "8",
        "9": "9",
        "10": "T",
        "t": "T",
        "j": "J",
        "q": "Q",
        "k": "K",
        "a": "A",
    }

    suit_map = {
        "c": "c",  # Kreuz / Clubs
        "d": "d",  # Karo / Diamonds
        "h": "h",  # Herz / Hearts
        "s": "s",  # Pik / Spades
    }

    # einfache Formen wie "Ah", "as" etc.
    if len(s) == 2:
        rank_chr = rank_map.get(s[0])
        suit_chr = suit_map.get(s[1])
        if not rank_chr or not suit_chr:
            raise ValueError(f"Ungültige Karte: {card_str}")
        return rank_chr + suit_chr

    # "10h" etc.
    if s.startswith("10") and len(s) == 3:
        rank_chr = "T"
        suit_chr = suit_map.get(s[2])
        if not suit_chr:
            raise ValueError(f"Ungültige Karte: {card_str}")
        return rank_chr + suit_chr

    raise ValueError(f"Ungültige Karte: {card_str}")


def parse_cards(cards: List[str]) -> List[int]:
    """Konvertiert String‑Karten in treys‑Card‑Integer.[web:54][web:65]"""
    return [Card.new(normalize_card_str(c)) for c in cards]


def detect_street(board_cards: int) -> Street:
    if board_cards == 0:
        return "preflop"
    if board_cards == 3:
        return "flop"
    if board_cards == 4:
        return "turn"
    if board_cards == 5:
        return "river"
    raise ValueError("Board muss 0, 3, 4 oder 5 Karten enthalten (Preflop/Flop/Turn/River).")


def evaluate_hand(hole: List[str], board: List[str]) -> HandEvaluation:
    """
    Bewertet Hand + Board mit treys‑Evaluator.
    Score: 1 (beste Hand) bis 7462 (schlechteste).[web:54][web:65]
    pct_rank: 0.0 = beste, 1.0 = schlechteste.
    """
    evaluator = Evaluator()
    street = detect_street(len(board))

    board_parsed = parse_cards(board) if board else []
    hole_parsed = parse_cards(hole)

    score = evaluator.evaluate(board_parsed, hole_parsed)
    hand_class = evaluator.class_to_string(evaluator.get_rank_class(score))
    pct_rank = evaluator.get_five_card_rank_percentage(score)  # funktioniert auch für 7‑card eval.[web:57][web:61]

    descr = evaluator.hand_summary(board_parsed, [hole_parsed])
    # summary ist ein mehrzeiliger Text; für CLI kurz halten
    description = hand_class

    return HandEvaluation(
        street=street,
        hand_class=hand_class,
        score=score,
        pct_rank=pct_rank,
        description=description,
    )


# ---------- Empfehlungslogik ----------


def position_factor(position: str) -> float:
    """
    Einfacher Faktor für Positionseinfluss (Late Position besser).
    """
    pos = position.upper()
    if pos not in POSITION_ORDER:
        return 1.0
    idx = POSITION_ORDER.index(pos)
    # UTG (0) = 0.9, ..., BTN (5) = 1.05, SB/BB etwas reduziert
    base = 0.9 + 0.03 * idx
    if pos in ("SB", "BB"):
        base -= 0.05
    return base


def classify_strength(hand_eval: HandEvaluation) -> str:
    """
    Gruppiert hand_class in Kategorien: premium / stark / mittel / schwach.
    """
    name = hand_eval.hand_class.lower()
    pct = hand_eval.pct_rank

    if any(k in name for k in ["straight flush", "four of a kind", "full house"]):
        return "premium"
    if any(k in name for k in ["flush", "straight", "three of a kind"]):
        return "stark"
    if any(k in name for k in ["two pair", "pair"]):
        # sehr schwache Paare können mittel sein, aber hier zusammengefasst
        return "mittel"
    # high card
    if pct > 0.7:
        return "schwach"
    return "mittel"


def recommend_action(
    hand_eval: HandEvaluation,
    position: str,
    stack_bb: float,
    pot_bb: float,
    players: int,
) -> Recommendation:
    """
    Liefert eine einfache Handlungsempfehlung basierend auf
    - Handkategorie (premium/stark/mittel/schwach)
    - Street (preflop/flop/turn/river)
    - Position, Stack, Potgröße, Anzahl Spieler
    """
    pos_factor = position_factor(position)
    strength = classify_strength(hand_eval)

    # einfache "required equity" Heuristik
    multiway_factor = 1.0 + max(players - 2, 0) * 0.03
    required_equity = 0.35 * multiway_factor / pos_factor  # grobe Heuristik

    # echte Equity schätzen aus pct_rank (0 = beste, 1 = schlechteste)
    equity_est = 1.0 - hand_eval.pct_rank

    # Street-spezifische Anpassungen
    street = hand_eval.street
    label = ""
    action = ""
    explanation = ""

    # PRE-FLOP
    if street == "preflop":
        if strength == "premium":
            label = "PREMIUM PRE-FLOP"
            action = "3-bet / 4-bet for Value; niemals folden."
            explanation = "Sehr starke Starthand. Aggressiv für Value spielen, besonders in später Position."
        elif strength == "stark":
            label = "Starke Hand Pre-Flop"
            action = "Open-Raise oder Call vs. 3-bet; selten folden."
            explanation = "Gute Starthand. In früher Position tighter, in später Position aggressiver."
        elif strength == "mittel":
            label = "Grenzhand Pre-Flop"
            action = "Open-Raise in später Position oder Fold in früher Position."
            explanation = "Spielbar, aber positionabhängig. Gegen viel Action eher folden."
        else:
            label = "Trash Hand Pre-Flop"
            action = "Fold."
            explanation = "Schwache Starthand ohne klare Zukunft. Meistens einfach wegwerfen."
        return Recommendation(label, action, explanation)

    # POST-FLOP
    # Equity vs. benötigte Equity
    if equity_est > required_equity + 0.15:
        edge = "große Edge"
        category = "sehr stark"
    elif equity_est > required_equity + 0.05:
        edge = "leichte Edge"
        category = "stark"
    elif equity_est > required_equity - 0.05:
        edge = "knapp"
        category = "grenzwertig"
    else:
        edge = "nachteil"
        category = "schwach"

    if strength == "premium":
        label = f"{street.capitalize()} – Monsterhand"
        action = "Großer Valuebet / Raise (mindestens 2/3 Pot). Niemals folden."
        explanation = (
            f"Deine Hand ist {category} (z.B. {hand_eval.hand_class}). "
            f"Du hast eine {edge} gegenüber typischen Ranges. "
            "Baue den Pot auf und schütze deine Hand gegen Draws."
        )
    elif strength == "stark":
        label = f"{street.capitalize()} – starke Made Hand / guter Draw"
        action = "Bet 1/2–2/3 Pot oder Call gegen moderate Bets."
        explanation = (
            f"Deine Hand ist {category} (z.B. {hand_eval.hand_class}). "
            "Oft bist du vorne, aber große Pots gegen viel Action können gefährlich werden."
        )
    elif strength == "mittel":
        label = f"{street.capitalize()} – mittlere Hand / schwacher Showdown-Wert"
        if equity_est >= required_equity:
            action = "Check/Call kleine Bets oder Thin Valuebet in Position."
            explanation = (
                "Grenzhand: Du hast gerade genug Equity, um weiterzuspielen, "
                "aber du solltest den Pot klein halten."
            )
        else:
            action = "Check/Fold gegen größere Bets."
            explanation = (
                "Gegen typische Ranges und Betgrößen ist deine Hand häufig hinten. "
                "Nur gegen sehr kleine Bets weiter mitgehen."
            )
    else:
        label = f"{street.capitalize()} – schwache Hand / Luft"
        action = "Check/Fold, außer du hast einen klaren Bluff-Spot."
        explanation = (
            "Deine Hand hat kaum Showdown-Wert und wenig Equity. "
            "Nur als Bluff in sehr guten Spots spielbar."
        )

    return Recommendation(label, action, explanation)


# ---------- CLI ----------


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Poker RTA – Texas Hold'em Handbewertung + Empfehlung (CLI)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--hole",
        nargs=2,
        required=True,
        metavar=("CARD1", "CARD2"),
        help="Deine Hole Cards, z.B. 'As Ks' oder 'Ah Kh'.",
    )
    p.add_argument(
        "--board",
        nargs="*",
        default=[],
        metavar="CARD",
        help="Boardkarten (0, 3, 4 oder 5 Karten), z.B. 'Ah Td 2c'.",
    )
    p.add_argument(
        "--position",
        type=str,
        default="BTN",
        help="Position am Tisch (UTG, UTG1, UTG2, MP, CO, BTN, SB, BB).",
    )
    p.add_argument(
        "--stack",
        type=float,
        default=100.0,
        help="Dein Stack in Big Blinds.",
    )
    p.add_argument(
        "--pot",
        type=float,
        default=10.0,
        help="Aktuelle Potgröße in Big Blinds.",
    )
    p.add_argument(
        "--players",
        type=int,
        default=6,
        help="Anzahl Spieler im Pot (inkl. dir).",
    )
    return p


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    board = args.board
    if len(board) not in (0, 3, 4, 5):
        raise SystemExit("Board muss 0, 3, 4 oder 5 Karten haben (Preflop/Flop/Turn/River).")

    hand_eval = evaluate_hand(args.hole, board)
    rec = recommend_action(
        hand_eval,
        position=args.position,
        stack_bb=args.stack,
        pot_bb=args.pot,
        players=args.players,
    )

    print("=" * 60)
    print(f"Street: {hand_eval.street.upper()}")
    print(f"Hole Cards: {' '.join(args.hole)}")
    print(f"Board: {' '.join(board) if board else '-'}")
    print(f"Position: {args.position.upper()} | Stack: {args.stack:.1f} BB | Pot: {args.pot:.1f} BB")
    print("-" * 60)
    print(f"Handklasse: {hand_eval.hand_class}")
    print(f"Score (1 best, 7462 worst): {hand_eval.score}")
    print(f"Percentile (0=best,1=worst): {hand_eval.pct_rank:.3f}")
    print("-" * 60)
    print(f"Empfehlung: {rec.label}")
    print(f"Aktion:     {rec.action}")
    print(f"Begründung: {rec.explanation}")
    print("=" * 60)


if __name__ == "__main__":
    main()
