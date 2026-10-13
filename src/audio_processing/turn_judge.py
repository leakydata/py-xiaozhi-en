"""Decide when the user has finished speaking, from what they said.

A silence timer cannot tell "I'm looking for my... hammer" from "I'm looking
for my hammer." - both are a pause. The words can: a phrase that stops on
"my", "the", "and" or "um" is not finished, however long the pause, while a
complete sentence ending in a full stop or question mark usually is.

This is the rule the MicroTurn work (Codacus, after DuplexCascade) found mattered
most: their base model waited through a mid-sentence pause 92 times in 474,
and 456 once trained to judge from the words. Here the judgement is a rule
over the transcript rather than a 35B model, so it runs on the client for free
and can be read, tested and tuned.

It is also how a backchannel is told from an interruption while the assistant
is talking: "yeah" or "mm-hm" means carry on, real words mean stop.

Pure Python with no imports from the app, so the benchmark that measures it on
real recordings runs exactly this code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Words a finished thought never ends on: articles, possessives, linking
#: conjunctions and fillers. "I'm looking for my" is unfinished whatever
#: punctuation the recogniser puts after it.
STRONG_INCOMPLETE = frozenset(
    """
    a an the my your his her our their these those every each another
    and but or nor because cause cuz if unless whereas although
    um uh er erm ah uhm
    """.split()
)

#: Words that usually mean more is coming, but can end a sentence:
#: "what else am I gonna do?", "didn't I?", "more than I'm supposed to." -
#: prepositions included, which spoken English strands at the end all the
#: time. Unfinished only when nothing marks the sentence as over.
WEAK_INCOMPLETE = frozenset(
    """
    to of for with without in on at from by about into onto over under
    between through during against toward towards via per than
    this that some any no such what which whose so since then when while as
    like after before until though
    i i'm im i've i'd i'll we we're you you're he she they it's there's
    is are was were be been being am
    have has had do does did can could would should will shall may might must
    gonna wanna gotta going trying want need got get
    very really just maybe kind sort more most less least quite pretty
    not don't didn't can't won't isn't wasn't hmm mm
    """.split()
)

#: "-'s" words that are "... is", and so can end a thought, rather than possessives.
_CONTRACTED_IS = frozenset(
    "it's that's he's she's there's here's what's who's where's how's let's".split()
)

#: Kept for callers that want the whole set.
INCOMPLETE_ENDINGS = STRONG_INCOMPLETE | WEAK_INCOMPLETE

#: What a listener says to show they are following, not to take the floor.
BACKCHANNELS = frozenset(
    """
    yeah yea yep yes yup ok okay right sure mhm mm-hm mmhm uh-huh uhhuh
    hm hmm mm uh-uh huh oh ah cool nice gotcha true exactly totally
    """.split()
)

#: Numbers count as words: "for $40, $50." ends on fifty, not on "for".
_WORD = re.compile(r"[A-Za-z0-9$][A-Za-z0-9'\-$%]*")


@dataclass(frozen=True)
class TurnSettings:
    """How long a silence has to be before the turn is over, by what came before it.

    Defaults are deliberately on the patient side: being cut off is worse than
    waiting a beat longer, and the point of this feature is to stop the former.
    """

    #: After a complete sentence ("...hammer." / "...is it?").
    complete_s: float = 0.7
    #: After something with no clear ending either way.
    neutral_s: float = 1.2
    #: After a phrase that stops on "my", "and", "um" and the like.
    incomplete_s: float = 3.0
    #: Speech needed before an end is even considered, so a cough or a click
    #: at the start does not end the turn.
    min_speech_s: float = 0.4
    #: Real words needed while the assistant is talking before it is treated
    #: as an interruption rather than a backchannel.
    barge_in_words: int = 2
    #: Once someone has talked this long they are telling something, and a
    #: full stop is more often a breath between sentences than the end of it:
    #: a listener says "mm-hm" there and takes the turn on a question or a
    #: longer pause. On the benchmark, 7 of 10 cut-offs were exactly this - a
    #: finished sentence that Nathan went on from.
    long_turn_s: float = 8.0
    #: How long a finished statement is held once the turn is long.
    long_complete_s: float = 1.3


def words_of(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text or "")]


def ending(text: str) -> str:
    """Classify how the transcript so far ends: complete, incomplete or neutral."""
    stripped = (text or "").strip()
    if not stripped:
        return "neutral"
    tokens = words_of(stripped)
    if not tokens:
        return "neutral"
    last = tokens[-1]
    # A strong ending wins over the punctuation. A recogniser will happily put
    # a full stop at a pause - "I'm looking for my." - and that is exactly the
    # case this exists to catch.
    if last in STRONG_INCOMPLETE:
        return "incomplete"
    if stripped.endswith((",", "...", "…", "-", "—", ":", ";")):
        return "incomplete"
    if stripped.endswith((".", "?", "!")):
        return "complete"
    if last in WEAK_INCOMPLETE:
        return "incomplete"
    # With no full stop to say otherwise: "-ly" ("they look distinctly") and a
    # possessive ("that's somebody's") both lean on a word still to come.
    if last.endswith("ly") or (last.endswith("'s") and last not in _CONTRACTED_IS):
        return "incomplete"
    return "neutral"


def _is_question(text: str) -> bool:
    return (text or "").rstrip().endswith("?")


def hold_for(
    text: str, settings: TurnSettings = TurnSettings(), speech_s: float = 0.0
) -> float:
    """How long a silence after this transcript has to last to end the turn."""
    kind = ending(text)
    if kind == "complete":
        if speech_s >= settings.long_turn_s and not _is_question(text):
            return settings.long_complete_s
        return settings.complete_s
    if kind == "incomplete":
        return settings.incomplete_s
    return settings.neutral_s


def turn_over(
    text: str,
    silence_s: float,
    speech_s: float,
    settings: TurnSettings = TurnSettings(),
    *,
    speaking: bool = False,
    vad_silence_s: float | None = None,
) -> bool:
    """Has the user finished?

    text          - what they have said this turn, as transcribed so far
    silence_s     - how long since their last recognised word
    speech_s      - how much speech this turn has held in total
    speaking      - the speech detector hears a voice right now
    vad_silence_s - how long the speech detector has heard none

    Measured on Nathan's recordings (sidecars/turn_bench.py): timing the pause
    from the last word answers fastest, because the speech detector clings to
    "speaking" through room noise. But recognisers drop "uhhh" entirely, so a
    voice the detector can hear still holds the turn open, and after an
    unfinished phrase the more cautious of the two measures is used.
    """
    if speech_s < settings.min_speech_s or speaking:
        return False
    # Speech with no words in it is noise or a mumble so far - nothing to
    # answer yet - so it gets the longest wait.
    if not words_of(text):
        return silence_s >= settings.incomplete_s
    kind = ending(text)
    if kind == "incomplete" and vad_silence_s is not None:
        silence_s = min(silence_s, vad_silence_s)
    return silence_s >= hold_for(text, settings, speech_s)


def is_backchannel(text: str) -> bool:
    """Only listener noises - "yeah", "mm-hm", "right" - and nothing else."""
    tokens = words_of(text)
    return bool(tokens) and all(t in BACKCHANNELS for t in tokens)


def is_interruption(
    text: str,
    assistant_text: str = "",
    settings: TurnSettings = TurnSettings(),
) -> bool:
    """Did the user cut in, as opposed to murmuring along?

    assistant_text is what the assistant is saying right now. Without echo
    cancellation the microphone hears it, so words that are simply the
    assistant's own coming back are not counted as the user's.
    """
    tokens = words_of(text)
    if not tokens or is_backchannel(text):
        return False
    echo = set(words_of(assistant_text))
    own = [t for t in tokens if t not in BACKCHANNELS and t not in echo]
    return len(own) >= settings.barge_in_words


# ---------------------------------------------------------------- backchannels


@dataclass(frozen=True)
class BackchannelSettings:
    """When to murmur "mm-hm" so the user can tell they are being listened to.

    From MicroTurn's dataset rules: only once the user has been talking a
    while, never too often, and only at a clause break - the moments a good
    listener nods. Their trained model placed fillers right about a third of
    the time and, in one run, said "mm-hm" 950 times where 164 were called for,
    so these lean sparse.
    """

    #: The user has to have been talking this long in the turn.
    min_speech_s: float = 3.6
    #: Never closer together than this.
    min_gap_s: float = 6.0
    #: The pause it lands in: long enough to be a pause, short enough that it
    #: reads as a reaction rather than a late afterthought.
    earliest_s: float = 0.45
    latest_s: float = 1.0
    #: And never this close to the moment the turn would end, so "mm-hm" is not
    #: immediately followed by a full answer.
    clear_of_end_s: float = 0.3


def backchannel_due(
    text: str,
    silence_s: float,
    speech_s: float,
    since_last_s: float,
    settings: BackchannelSettings = BackchannelSettings(),
    turn: TurnSettings = TurnSettings(),
    *,
    speaking: bool = False,
) -> bool:
    """Is this pause a good moment for "mm-hm"?

    At a clause break, an open-ended pause, or - once the user has been
    talking a while - the end of a statement. A question always gets an
    answer, not a murmur, as does a finished sentence in a short turn; a
    phrase cut off on "my" or "the" is someone searching for a word, and a
    listener waits quietly there.
    """
    if (
        speaking
        or speech_s < settings.min_speech_s
        or since_last_s < settings.min_gap_s
    ):
        return False
    if not (settings.earliest_s <= silence_s <= settings.latest_s):
        return False
    stripped = (text or "").rstrip()
    clause_break = stripped.endswith((",", ";", ":"))
    kind = ending(stripped)
    # In a long telling, the end of a statement is where a listener nods.
    statement_in_a_story = (
        kind == "complete"
        and speech_s >= turn.long_turn_s
        and not _is_question(stripped)
    )
    if not (clause_break or kind == "neutral" or statement_in_a_story):
        return False
    return silence_s <= hold_for(stripped, turn, speech_s) - settings.clear_of_end_s
