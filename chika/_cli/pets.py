"""Animated terminal pet companions.

Each profile picks a pet — its ASCII frames render in the CLI status panel
and an SVG version shows in the frontend. The pet has 4 states:

- ``idle``     — between turns
- ``working``  — engine is mid-turn / a tool is running
- ``celebrate``— after a successful workflow_done
- ``sad``      — after an error event

Frames are short multi-line strings. The renderer cycles through frames once
per ~700ms while the pet is in a non-idle state. Idle pets just show one
frame so the terminal isn't constantly flickering.

Pets are intentionally tiny (4-5 lines, ≤24 cols) so they fit in a side
column or status panel without dominating the screen.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Pet:
    id: str
    name: str
    description: str
    accent: str  # rich-color spec for the pet box border
    # State → list of frames. Each frame is a multi-line string. The first
    # frame is shown in idle state; non-idle states cycle.
    frames: dict[str, list[str]] = field(default_factory=dict)
    emoji: str = ""  # used by the frontend SVG fallback
    # Random one-liners the pet says — the renderer picks one when entering
    # the matching state. ``personality`` is its overall vibe in prose for
    # the frontend's pet card.
    personality: str = ""
    quotes: dict[str, list[str]] = field(default_factory=dict)

    def frame_for(self, state: str, tick: int) -> str:
        seq = self.frames.get(state) or self.frames.get("idle") or [""]
        return seq[tick % len(seq)]

    def quote(self, kind: str) -> str:
        opts = self.quotes.get(kind) or []
        if not opts:
            return ""
        # Deterministic pick: tied to pet id + kind so the same pet gives the
        # same line in tests, but rotates per kind so it doesn't repeat.
        idx = (hash(self.id) ^ hash(kind)) % len(opts)
        return opts[idx]


# ── Pet library ────────────────────────────────────────────────────────────
#
# Frames are deliberately ASCII-first so they render in any terminal. Add
# new pets by appending to PETS. Keep them ≤5 lines and ≤24 columns wide.

PETS: dict[str, Pet] = {}


def _register(pet: Pet) -> None:
    PETS[pet.id] = pet


_register(Pet(
    id="cat",
    name="Mochi the Cat",
    description="A sleepy tabby. Blinks slowly while you think.",
    accent="#e0b35c",
    emoji="🐱",
    personality="aloof, ironic, thinks it's smarter than you (might be right)",
    quotes={
        "greet":     ["mrrp.", "you again.", "*stretches*"],
        "working":   ["fine, fine, on it.", "this is beneath me but okay.", "*types in your lap*"],
        "celebrate": ["told you.", "purr.", "you may pet me now."],
        "sad":       ["that wasn't my fault.", "*sulks*", "maybe try turning it off and on."],
        "idle":      ["…", "*tail flicks*", "i was sleeping, you know."],
    },
    frames={
        # Compact 4-frame idle blink — fits in any side-panel width and
        # works on terminals that don't support full-width characters.
        # The fancy ts-animal cat lives on as ``cat-fancy``.
        "idle": [
            r"""
   /\_/\
  ( o.o )
   > ^ <
  /     \
 (___|___)""".strip("\n"),
            r"""
   /\_/\
  ( o.o )
   > ^ <
  /     \
 (___|___)""".strip("\n"),
            r"""
   /\_/\
  ( -.- )
   > ^ <
  /     \
 (___|___)""".strip("\n"),
            r"""
   /\_/\
  ( o.o )
   > ^ <
  /     \
 (___|___)""".strip("\n"),
        ],
        # 4-frame typing cycle: paws bat left, right, left, right.
        "working": [
            r"""
   /\_/\
  ( ^.^ )
  /|> ^ <
 (_|_____)
   ' '""".strip("\n"),
            r"""
   /\_/\
  ( ^.^ )
   > ^ <|\
  /_____|_)
     ' '""".strip("\n"),
            r"""
   /\_/\
  ( ^.^ )
  /|> ^ <
 (_|_____)
   ' '""".strip("\n"),
            r"""
   /\_/\
  ( ^.^ )
   > ^ <|\
  /_____|_)
     ' '""".strip("\n"),
        ],
        # Celebrate: eyes-up + sparkles on either side.
        "celebrate": [
            r"""
 *  /\_/\  *
   ( ^o^ )
    > w <
   /     \
  (___|___)""".strip("\n"),
            r"""
 . *\_/\* .
   ( ^o^ )
    > w <
   /     \
  (___|___)""".strip("\n"),
        ],
        # Sad: drooping ears + teary eyes.
        "sad": [
            r"""
   v\_/v
  ( T_T )
   > _ <
  /     \
 (___|___)""".strip("\n"),
        ],
    },
))

_register(Pet(
    id="dog",
    name="Biscuit the Dog",
    description="A loyal mutt. Wags its tail when tools fire.",
    accent="#3dd68c",
    emoji="🐶",
    personality="enthusiastic, loyal, will fetch literally anything",
    quotes={
        "greet":     ["heya!", "you're back!!", "tail-wag intensifies"],
        "working":   ["on it!!", "yes yes yes!", "fetching!"],
        "celebrate": ["DID GOOD!", "*zoomies*", "treat please?"],
        "sad":       ["i tried...", "*ears droop*", "it was the cat's fault."],
        "idle":      ["*good boy*", "ready when you are!", "should we go for walk?"],
    },
    frames={
        # Idle: tail flick alternates between two positions for a slow wag.
        "idle": [
            r"""
   / \__
  (    @\___
   /         O
  /   (_____/
  ~~~~~~~""".strip("\n"),
            r"""
   / \__
  (    @\___
   /         O
  /   (_____/
   ~~~~~~~""".strip("\n"),
        ],
        # Working: aggressive tail wag — 4 distinct positions.
        "working": [
            r"""
   / \__
  (    @\___
   /         O    ~~
  /   (_____/   ~~
   ' ' ' '""".strip("\n"),
            r"""
   / \__
  (    @\___
   /         O  ~~
  /   (_____/    ~~
   ' ' ' '""".strip("\n"),
            r"""
   / \__
  (    @\___
   /         O    ~~
  /   (_____/  ~~
   ' ' ' '""".strip("\n"),
            r"""
   / \__
  (    @\___
   /         O  ~~
  /   (_____/    ~~
   ' ' ' '""".strip("\n"),
        ],
        # Celebrate: sparkles + bright eyes + visible smile.
        "celebrate": [
            r"""
 *  / \__   *
  (    ^\___
   /         ^
  /   (_____/
   ' ' ' '""".strip("\n"),
            r"""
   / \__
  (    ^\___
   /         ^
  /   (_____/
 *  ' ' ' '   *""".strip("\n"),
        ],
        # Sad: ears flat, eyes squint shut.
        "sad": [
            r"""
   / \__
  (   _,\___
   /         _
  /   (_____/
   . . . .""".strip("\n"),
        ],
    },
))

_register(Pet(
    id="owl",
    name="Pip the Owl",
    description="A studious owl. Nods when it learns something.",
    accent="#9d7fff",
    emoji="🦉",
    personality="bookish, precise, occasionally pedantic",
    quotes={
        "greet":     ["hoot.", "interesting query.", "*adjusts tiny glasses*"],
        "working":   ["citing sources…", "consulting the archives…", "cross-referencing…"],
        "celebrate": ["q.e.d.", "elegant.", "noted in the ledger."],
        "sad":       ["the data was insufficient.", "an unusual hypothesis.", "we shall iterate."],
        "idle":      ["pondering.", "*thoughtful blink*", "ready for inquiry."],
    },
    frames={
        # Idle: head tilts side to side, occasional blink.
        "idle": [
            r"""
   ,___,
   (O,O)
   /   \
  ( | | )
   "-"-"
   ^   ^""".strip("\n"),
            r"""
    ,___,
    (O,O)
    /   \
   ( | | )
    "-"-"
    ^   ^""".strip("\n"),
            r"""
   ,___,
   (-,-)
   /   \
  ( | | )
   "-"-"
   ^   ^""".strip("\n"),
            r"""
   ,___,
   (O,O)
   /   \
  ( | | )
   "-"-"
   ^   ^""".strip("\n"),
        ],
        # Working: head pivots left then right while a wing flutters.
        "working": [
            r"""
   ,___,
  ~(O,O)
   /   \
  ( | | )
   "-"-"
   ^   ^""".strip("\n"),
            r"""
   ,___,
   (O,O)~
   /   \
  ( | | )
   "-"-"
   ^   ^""".strip("\n"),
            r"""
   ,___,
  ~(O,O)
   /   \
  ( | | )
   "-"-"
   ^   ^""".strip("\n"),
            r"""
   ,___,
   (O,O)~
   /   \
  ( | | )
   "-"-"
   ^   ^""".strip("\n"),
        ],
        # Celebrate: wings spread + bright eyes.
        "celebrate": [
            r"""
   ,___,
  *(^,^)*
  /\___/\
 (  | |  )
   "-"-"
   ^   ^""".strip("\n"),
            r"""
   ,___,
  *(^o^)*
   \___/
  ( | | )
   "-"-"
   ^   ^""".strip("\n"),
        ],
        # Sad: head down, eyes downcast.
        "sad": [
            r"""
   ,___,
   (._.)
   /   \
  ( . . )
   "-"-"
   ^   ^""".strip("\n"),
        ],
    },
))

_register(Pet(
    id="robot",
    name="Bolt the Robot",
    description="A blocky helper bot. Antenna spins while it thinks.",
    accent="#7c70ff",
    emoji="🤖",
    personality="precise, deadpan, optimised for compliance",
    quotes={
        "greet":     ["greetings, operator.", "boot sequence complete.", "ready to compute."],
        "working":   ["processing…", "executing subroutine…", "stack frame in flight."],
        "celebrate": ["task: complete.", "exit code 0.", "objective met."],
        "sad":       ["error: handled.", "non-zero exit. retrying logic.", "diagnostic: ungood."],
        "idle":      ["…", "awaiting input.", "fans nominal."],
    },
    frames={
        "idle": [
            r"""
   |
 [o_o]
 /| |\
  | |""".strip("\n"),
            r"""
   |
 [-_-]
 /| |\
  | |""".strip("\n"),
        ],
        "working": [
            r"""
   /
 [o_o]
 /|*|\
  | |""".strip("\n"),
            r"""
   -
 [o_o]
 /|*|\
  | |""".strip("\n"),
            r"""
   \
 [o_o]
 /|*|\
  | |""".strip("\n"),
        ],
        "celebrate": [
            r"""
   *
 [^_^]
 /|!|\
  | |""".strip("\n"),
        ],
        "sad": [
            r"""
   |
 [x_x]
 /| |\
  | |""".strip("\n"),
        ],
    },
))

_register(Pet(
    id="penguin",
    name="Tux the Penguin",
    description="A formal-looking little fellow.",
    accent="#5cc8e0",
    emoji="🐧",
    personality="polite, slightly old-fashioned, runs Linux",
    quotes={
        "greet":     ["evening.", "shall we?", "*formal bow*"],
        "working":   ["one moment please.", "compiling.", "investigating."],
        "celebrate": ["splendid.", "indeed.", "rather pleased."],
        "sad":       ["regrettable.", "the assumptions were wrong.", "let us regroup."],
        "idle":      ["awaiting orders.", "*shuffles*", "tea?"],
    },
    frames={
        "idle": [
            r"""
   ___
  (o_o)
 <(   )>
   ^ ^""".strip("\n"),
            r"""
   ___
  (-_-)
 <(   )>
   ^ ^""".strip("\n"),
        ],
        "working": [
            r"""
   ___
  (o_o)
 <( . )>
   ^ ^""".strip("\n"),
            r"""
   ___
  (o_o)
 <(  .)>
   ^ ^""".strip("\n"),
        ],
        "celebrate": [
            r"""
   ___
  (^_^)
 <( ^ )>
   ^ ^""".strip("\n"),
        ],
        "sad": [
            r"""
   ___
  (T_T)
 <(   )>
   ^ ^""".strip("\n"),
        ],
    },
))

_register(Pet(
    id="dragon",
    name="Ember the Dragon",
    description="A pocket-sized dragon. Breathes pixel-fire when busy.",
    accent="#e05c5c",
    emoji="🐉",
    personality="dramatic, hoards code, refuses to admit it's small",
    quotes={
        "greet":     ["RAWR.", "behold.", "*flame flicker*"],
        "working":   ["FORGING.", "*breathes fire*", "mighty work approaches!"],
        "celebrate": ["VICTORY.", "the prophecy is fulfilled.", "the hoard grows."],
        "sad":       ["a setback. mere mortals understand.", "the flame dims.", "*pouts*"],
        "idle":      ["*coiled around your code*", "pondering schemes.", "smoke curls."],
    },
    frames={
        "idle": [
            r"""
   /\_/\
  ( o.o )_
   /vvv\ \
  (_____)""".strip("\n"),
        ],
        "working": [
            r"""
   /\_/\
  ( o.o )~~ ~
   /vvv\
  (_____)""".strip("\n"),
            r"""
   /\_/\
  ( o.o )~ ~
   /vvv\
  (_____)""".strip("\n"),
        ],
        "celebrate": [
            r"""
   /\_/\
  ( ^.^ )*
   /vvv\
  (_____)""".strip("\n"),
        ],
        "sad": [
            r"""
   /\_/\
  ( -.- )
   /vvv\
  (_____)""".strip("\n"),
        ],
    },
))

_register(Pet(
    id="ghost",
    name="Boo the Ghost",
    description="A friendly spook. Floats gently up and down.",
    accent="#bababa",
    emoji="👻",
    personality="dreamy, vaguely 1990s, haunts your unit tests",
    quotes={
        "greet":     ["boo.", "*phases in*", "hi friend."],
        "working":   ["mmm vibes.", "channeling…", "*floats*"],
        "celebrate": ["✨ done ✨", "the omens were good.", "vibes restored."],
        "sad":       ["spooky failure.", "*sighs ectoplasmically*", "the void has it."],
        "idle":      ["*drifts*", "you have unread spirits.", "🍂"],
    },
    frames={
        "idle": [
            r"""
  .-.
 (o o)
 |~~ |
 ^^^^^""".strip("\n"),
            r"""

  .-.
 (o o)
 |~~ |
 ^^^^^""".strip("\n"),
        ],
        "working": [
            r"""
  .-.
 (o o) ~
 |~  ~|
 ^^^^^""".strip("\n"),
            r"""
  .-.
 (o o)~
 |~ ~ |
 ^^^^^""".strip("\n"),
        ],
        "celebrate": [
            r"""
  .-.
 (^_^)
 |yay |
 ^^^^^""".strip("\n"),
        ],
        "sad": [
            r"""
  .-.
 (._.)
 |~~ |
 ^^^^^""".strip("\n"),
        ],
    },
))


# ── Imported from ts-animal (MIT, https://github.com/ts-animal/ts-animal) ──
#
# These four pets bring richer, multi-frame animations using full-width /
# kaomoji artwork — recommended on terminals + GUIs that handle Unicode
# cleanly. The plain-ASCII pets above (cat / dog / owl / robot / penguin /
# dragon / ghost) stay around as the universal-compatibility roster.
#
# Source: github.com/ts-animal/ts-animal/tree/main/src/zoo
# License: MIT (see ts-animal LICENSE; redistribution + modification allowed
# with attribution). Frames lifted character-for-character so the CLI and
# frontend render the same artwork as the upstream package.

_register(Pet(
    id="bear",
    name="Mochi the Bear",
    description=(
        "A drowsy little bear. Snores softly between turns and curls up to "
        "wait for the next task."
    ),
    accent="#caa472",
    emoji="🐻",
    personality="gentle, sleepy, dreams of honey and dataframes",
    quotes={
        "greet":     ["*yawns*", "hngh.", "i was almost asleep."],
        "working":   ["working on it… mid-yawn.", "moving slowly.", "okie."],
        "celebrate": ["nice.", "treat?", "*soft happy*"],
        "sad":       ["nap helps.", "tomorrow it works.", "*sigh*"],
        "idle":      ["zzz.", "*curled up*", "do not disturb (much)."],
    },
    frames={
        # 7-frame breathing-sleep loop — the "z"s drift up and out of frame.
        "idle": [
            "︎ ⌒__⌒     \n(  ᵕﻌᵕ)z  \n૮　 ❍ ა   \nヽ＿_つ_つ   ",
            "︎ ⌒__⌒     \n(  ᵕﻌᵕ)zz \n૮　 ❍ ა   \nヽ＿_つ_つ   ",
            "︎ ⌒__⌒   z \n(  ᵕﻌᵕ)zz \n૮　 ❍ ა   \nヽ＿_つ_つ   ",
            "︎ ⌒__⌒   zz\n(  ᵕﻌᵕ)zz \n૮　 ❍ ა   \nヽ＿_つ_つ   ",
            "︎ ⌒__⌒   zz\n(  ᵕﻌᵕ) z \n૮　 ❍ ა   \nヽ＿_つ_つ   ",
            "︎ ⌒__⌒   zz\n(  ᵕﻌᵕ)   \n૮　 ❍ ა   \nヽ＿_つ_つ   ",
            "︎ ⌒__⌒    z\n(  ᵕﻌᵕ)   \n૮　 ❍ ა   \nヽ＿_つ_つ   ",
        ],
        "working": [
            "︎ ⌒__⌒     \n(  ᵕﻌᵕ).  \n૮　 ❍ ა   \nヽ＿_つ_つ   ",
            "︎ ⌒__⌒     \n(  ᵕﻌᵕ).. \n૮　 ❍ ა   \nヽ＿_つ_つ   ",
            "︎ ⌒__⌒     \n(  ᵕﻌᵕ)...\n૮　 ❍ ა   \nヽ＿_つ_つ   ",
        ],
        "celebrate": [
            "︎ ⌒__⌒  *  \n(  ◕ﻌ◕)♪ \n૮　 ❍ ა   \nヽ＿_つ_つ   ",
        ],
        "sad": [
            "︎ ⌒__⌒     \n(  •ﻌ•)   \n૮　 ❍ ა   \nヽ＿_つ_つ   ",
        ],
    },
))


_register(Pet(
    id="sheep",
    name="Pog the Sheep",
    description=(
        "A gently combustible sheep. Wool slightly on fire whenever real "
        "work is happening."
    ),
    accent="#e07a5f",
    emoji="🐑",
    personality="dramatic, theatrical, finds every task a Big Deal",
    quotes={
        "greet":     ["bAAA!", "*shimmer*", "we ride."],
        "working":   ["FIRED UP.", "applying maximum effort.", "🔥 going."],
        "celebrate": ["BAAAAAA!!", "fire of victory.", "*flaming bow*"],
        "sad":       ["the flame is out.", "regroup.", "kindling needed."],
        "idle":      ["softly smoldering.", "preheating.", "good vibes only."],
    },
    frames={
        "idle": [
            "╭◜◝◜◝╮ \n꒰•ω• Ꮚ ꒱ \n╰◟◞ ͜ ◟◞╯ ",
        ],
        # Working: the 🔥 darts left → right → left.
        "working": [
            "╭◜🔥◝◜◝╮ \n꒰•ω• Ꮚ ꒱ \n╰◟◞ ͜ ◟◞╯ ",
            "╭◜◝🔥◜◝╮ \n꒰•ω• Ꮚ ꒱ \n╰◟◞ ͜ ◟◞╯ ",
            "╭◜◝◜🔥◝╮ \n꒰•ω• Ꮚ ꒱ \n╰◟◞ ͜ ◟◞╯ ",
            "╭◜◝◜◝🔥╮ \n꒰•ω• Ꮚ ꒱ \n╰◟◞ ͜ ◟◞╯ ",
        ],
        "celebrate": [
            "╭◜🔥◝◜🔥╮ \n꒰•ᴗ• Ꮚ ꒱✨\n╰◟◞ ͜ ◟◞╯ ",
        ],
        "sad": [
            "╭◜  ◝◜  ╮ \n꒰•︿• Ꮚ ꒱ \n╰◟◞ ͜ ◟◞╯ ",
        ],
    },
))


_register(Pet(
    id="bunny",
    name="Riot the Bunny",
    description=(
        "A short-tempered rabbit. Tiny but throws an outsized tantrum when "
        "things break."
    ),
    accent="#e05c5c",
    emoji="🐰",
    personality="furious, principled, refuses to apologise",
    quotes={
        "greet":     ["nh.", "(crosses arms)", "ok let's go."],
        "working":   ["fine.", "FINE.", "*aggressive typing*"],
        "celebrate": ["told you so.", "(briefly smug)", "we live."],
        "sad":       ["💢💢💢", "EVERYTHING.", "this is exactly what i predicted."],
        "idle":      ["calm.", "(suspiciously calm)", "do not test me."],
    },
    frames={
        "idle": [
            "  (\\ /)  \n  `• •´  \n  (=ᴥ=)  ",
            "  (\\ /)  \n  `ᵕ ᵕ´  \n  (=ᴥ=)  ",
            "  (\\ /)  \n  `• •´  \n  (=ᴥ=)  ",
            "  (\\(\\   \n  `• •´  \n  (=ᴥ=)  ",
        ],
        "working": [
            "   (| |)   \n  ( •̀ᴥ•́ )  \n  ૮     ა  \n   _   _   ",
            "   (| |)   \n  ( •̀ᴥ•́ )  \n  ૮     ა  \n   _   0   ",
            "   (| |)   \n  ( •̀ᴥ•́ )  \n  ૮     ა  \n   _   _   ",
        ],
        "celebrate": [
            "   (| |)✨ \n  ( ᴗ ᴗ )  \n  ૮     ა  \n   _   _   ",
        ],
        "sad": [
            "   (| |) 💢\n💢( •̀ᴥ•́ )💢\n  ૮     ა  \n   _   _   ",
        ],
    },
))


_register(Pet(
    id="cat-fancy",
    name="Niko the Fancy Cat",
    description=(
        "Imported from ts-animal — large, detailed kaomoji-style cat. "
        "Best on roomy terminals and the desktop frontend."
    ),
    accent="#e0b35c",
    emoji="🐱",
    personality="elegant, precise, has refined opinions about everything",
    quotes={
        "greet":     ["nyaa.", "(perfect tail flick)", "we begin."],
        "working":   ["*types daintily*", "noted.", "underway."],
        "celebrate": ["resolved.", "splendid.", "*purr*"],
        "sad":       ["regrettable.", "we shall iterate.", "*tail droops*"],
        "idle":      ["…", "*observes*", "patience is a virtue."],
    },
    frames={
        "idle": [
            "　　　　　 ,-､　　　 　 　 　　　..-､\n"
            "　　　　 ./:::::＼　　　　 　 　 ／:::::ヽ\n"
            "　　　　/:::::::::::;ゝ--──-- ､._/:::::::::ヽ\n"
            "　　　 /,.-‐''\"′ 　　　　　　　　 ＼::::::::|\n"
            "　　／　 　　　　　　　　　　  　　ヽ､::::|\n"
            "　/　　　　  ●　　　 　   　 　 　 　 ヽ::|\n"
            " l　　　､､､　　 　 　 　 　 　 　 ●　　   　 l\n"
            ".|　　　 　　 　(､_人__丿　 　､､､　    　|\n"
            " l　　　　　　　　　._　　　　　　  　   l\n"
            "　 ､　　　　 　　　　 　 　 　　 　  　 /\n"
            "　　　`ｰ ､__　　　 　 　 　　　 　 .／\n"
            "　　　　　　/`'''ｰ‐‐──‐‐‐┬--- ／",
            "　　　 　　 ,-､　　　 　 　 　　　..-､\n"
            "　　　　 ./:::::＼　　　　 　 　 ／:::::ヽ\n"
            "　　　 　/:::::::::::;ゝ--──-- ､._/::::::::ヽ\n"
            "　　　 /,.-‐''\"′ 　　　　　　　　 ＼::::::::|\n"
            "　　／　 　　　　　　　　　　   　　ヽ､::::::|\n"
            "　/　　　　  ●　　　 　   　 　 　 　 ヽ:::|\n"
            " l　　　､､､　　 　 　 　 　 　 ●　　   　 l\n"
            "| 　　　 　　　　(､_人__丿　 　､､､　    　|\n"
            " l　　　　　　　　　._　　　　　  　   　 l\n"
            "　` ､　　　　　　　　 　 　 　　 　  　 /\n"
            "　　　`ｰ ､__　　　 　 　 　　　 　 .／\n"
            "　　　　　　/`'''ｰ‐‐──‐‐‐''-- ／",
            "　　　  　　 ,-､　　　 　 　 　　　..-､\n"
            "　　　　 ./:::::＼　　　　 　 　 ／:::::ヽ\n"
            "　 　　/::::::::::::;ゝ--──-- ､._/:::::ヽ\n"
            "　　　 /,.-‐''\"′ 　　　　　　　　 ＼::::::::|\n"
            "　　／　 　　　　　　　　　　  　　  ヽ､:::::|\n"
            "　/　　　　  -　　　 　   　 　 　 　 ヽ::|\n"
            "l　　　､､､　　  　 　 　 　 　 -　　   　 l\n"
            ".|　　　 　　　　(､_人__丿　 　､､､　    　|\n"
            " l　　　　　　　　　._　　　　　　  　    l\n"
            "　` ､　　　　　　　　 　 　 　　 　  　 /\n"
            "　　　`ｰ ､__　　　 　 　 　　　 　 .／\n"
            "　　　　　　/`'''ｰ‐‐──‐‐‐┬--- ／",
            "　　　　　 ,-､　　　 　 　 　　　..-､\n"
            "　　　　 ./:::::＼　　　　 　 　 ／:::::ヽ\n"
            "　　　　/::::::::::::;ゝ--──-- ､._/:::::::ヽ\n"
            "　　　 /,.-‐''\"′ 　　　　　　　　 ＼::::::::|\n"
            "　　／　 　　　　　　　　　　  　　ヽ､::::::|\n"
            "　/　　　　  ●　　　 　   　 　 　 　 ヽ::|\n"
            " l　　　､､､　　 　 　 　 　 　 ●　　   　 l\n"
            ".|　　　 　　 　(､_人__丿　 　､､､　    　|\n"
            " l 　　　　　　　　　._　　　　　　  　   l\n"
            "　` ､　　　　　　　　 　 　 　　 　  　 /\n"
            "　　　`ｰ ､__　　　 　 　 　　　 　 .／\n"
            "　　　　　　/`'''ｰ‐‐──‐‐'''-- ／",
        ],
        # For working / celebrate / sad we reuse the smaller cat artwork —
        # the upstream ts-animal package only ships idle frames for cat.
        "working":   PETS["cat"].frames["working"],
        "celebrate": PETS["cat"].frames["celebrate"],
        "sad":       PETS["cat"].frames["sad"],
    },
))


DEFAULT_PET_ID = "cat"


def get(pet_id: str | None) -> Pet:
    """Resolve a pet id to a Pet, falling back to the default if unknown."""
    if pet_id and pet_id in PETS:
        return PETS[pet_id]
    return PETS[DEFAULT_PET_ID]


def all_pets() -> list[dict]:
    """Return a JSON-friendly catalogue for the API + frontend.

    Each pet ships its full ASCII frame table now so the frontend
    PetCompanion can render the SAME artwork the CLI does — keeping the
    two surfaces in lockstep. Previously the frontend only got an
    emoji/preview which made the desktop pet look much weaker than its
    CLI counterpart.
    """
    out: list[dict] = []
    for p in PETS.values():
        out.append({
            "id":          p.id,
            "name":        p.name,
            "description": p.description,
            "accent":      p.accent,
            "emoji":       p.emoji,
            "personality": p.personality,
            "preview":     p.frame_for("idle", 0),
            "frames":      {state: list(seq) for state, seq in p.frames.items()},
            "quotes":      {kind: list(opts) for kind, opts in p.quotes.items()},
        })
    return out


def get_pet_frames(pet_id: str | None) -> dict[str, list[str]]:
    """Return ``{state: [frames]}`` for a single pet — used by the
    frontend's pet companion endpoint."""
    pet = get(pet_id)
    return {state: list(seq) for state, seq in pet.frames.items()}
