"""The help-request conversation, the same on every channel.

Telegram and WhatsApp only translate: they turn a tap, a typed line or a shared
location into an `Event`, call `step()`, and show the `Reply` objects that come
back. Nothing here touches the network or the database, so the whole flow is
tested without either.

Two rules shape the design:
- Nobody is blocked. Every step has Skip, free text is always accepted (it is
  kept as the description), and a draft that is abandoned half way can still be
  sent (`is_stale` + `build(partial=True)`).
- The phone number is for matching households, so it is kept apart from who
  reported it (`reporter_kind`) and from numbers that are only for contact."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any

from . import phone as phones
from .domain import NEEDS as DOMAIN_NEEDS

NEEDS = ["evacuation", "rescue", "food", "water", "medicine", "baby_food", "blankets", "shelter"]
SITUATION = ["elderly", "children", "medical", "water_entering", "trapped", "life_risk"]
PEOPLE_BUTTONS = [1, 2, 3, 4, 5]
MAX_PEOPLE = 500
STALE_AFTER_S = 600

# ----------------------------------------------------------------------------- texts
TEXT: dict[str, dict[str, str]] = {
    "lang": {"en": "Choose your language / भाषा चुनें", "hi": "भाषा चुनें / Choose your language"},
    "whose": {"en": "Who needs help?", "hi": "किसे मदद चाहिए?"},
    "whose_self": {"en": "Me / my family", "hi": "मुझे / मेरे परिवार को"},
    "whose_other": {"en": "Someone else", "hi": "किसी और को"},
    "loc_self": {
        "en": "Please share your location. Tap the button below.",
        "hi": "कृपया अपनी लोकेशन भेजें। नीचे दिया बटन दबाएँ।",
    },
    "loc_other": {
        "en": "Send the family's location: attach, then Location, then pick their spot on the map. Or choose it yourself.",
        "hi": "परिवार की लोकेशन भेजें: अटैच, फिर लोकेशन, फिर नक्शे पर उनकी जगह चुनें। या खुद चुनें।",
    },
    "loc_manual": {"en": "Choose ward and landmark", "hi": "वार्ड और पहचान-स्थल चुनें"},
    "ward": {"en": "Which ward?", "hi": "कौन सा वार्ड?"},
    "ward_n": {"en": "Ward {n}", "hi": "वार्ड {n}"},
    "landmark": {"en": "Nearest landmark?", "hi": "सबसे नज़दीकी पहचान-स्थल?"},
    "landmark_none": {"en": "None of these", "hi": "इनमें से कोई नहीं"},
    "detail": {
        "en": "Any detail to find the house? For example: blue door, third house behind the temple. Or tap Skip.",
        "hi": "घर ढूँढने के लिए कोई जानकारी? जैसे: नीला दरवाज़ा, मंदिर के पीछे तीसरा घर। या छोड़ें दबाएँ।",
    },
    "phone_self": {
        "en": "What is your mobile number? Teams can call you.",
        "hi": "आपका मोबाइल नंबर क्या है? टीम आपसे बात कर सकेगी।",
    },
    "phone_other": {"en": "What is the family's own mobile number?", "hi": "परिवार का अपना मोबाइल नंबर क्या है?"},
    "phone_none": {"en": "No phone / lost phone", "hi": "फ़ोन नहीं है / खो गया"},
    "phone_invalid": {
        "en": "That is not a 10-digit mobile number. Please type it again, for example 98765 43210.",
        "hi": "यह 10 अंकों का मोबाइल नंबर नहीं है। कृपया दोबारा लिखें, जैसे 98765 43210।",
    },
    "phone_alt": {
        "en": "Is there another number that can reach them, such as a neighbour or relative?",
        "hi": "क्या उन तक पहुँचने का कोई और नंबर है, जैसे पड़ोसी या रिश्तेदार का?",
    },
    "phone_kind": {"en": "Whose number is this?", "hi": "यह नंबर किसका है?"},
    "pk_own": {"en": "The family's own", "hi": "परिवार का अपना"},
    "pk_contact": {"en": "Neighbour / relative", "hi": "पड़ोसी / रिश्तेदार"},
    "people": {"en": "How many people need help?", "hi": "कितने लोगों को मदद चाहिए?"},
    "people_more": {"en": "6 or more", "hi": "6 या ज़्यादा"},
    "people_exact": {"en": "Type the number of people.", "hi": "लोगों की संख्या लिखें।"},
    "needs": {
        "en": "What do they need? Tap everything that applies, then Done.",
        "hi": "क्या चाहिए? जो ज़रूरी हो सब दबाएँ, फिर हो गया दबाएँ।",
    },
    "situation": {
        "en": "Is any of this true? Tap everything that applies, then Done.",
        "hi": "क्या इनमें से कुछ है? जो लागू हो सब दबाएँ, फिर हो गया दबाएँ।",
    },
    "done_btn": {"en": "Done", "hi": "हो गया"},
    "skip": {"en": "Skip", "hi": "छोड़ें"},
    "confirm": {"en": "Please check:\n{summary}\n\nSend this request?", "hi": "कृपया जाँचें:\n{summary}\n\nक्या यह अनुरोध भेजें?"},
    "send": {"en": "Send", "hi": "भेजें"},
    "restart": {"en": "Start over", "hi": "फिर से शुरू करें"},
    "resume_q": {
        "en": "You already have a form in progress. Continue it, or start a new one?",
        "hi": "आपका एक फ़ॉर्म चल रहा है। इसे जारी रखें, या नया शुरू करें?",
    },
    "resume_continue": {"en": "Continue", "hi": "जारी रखें"},
    "resume_new": {"en": "Start new", "hi": "नया शुरू करें"},
    "noted": {"en": "Noted.", "hi": "लिख लिया।"},
    "sent": {
        "en": "Received. Your reference is {ref}. Relief teams are being coordinated. If something changes, send /start.",
        "hi": "मिल गया। आपका संदर्भ नंबर {ref} है। राहत टीमें भेजी जा रही हैं। कुछ बदले तो /start भेजें।",
    },
    "auto_sent": {
        "en": "You stopped answering, so we sent what you had entered. Reference {ref}. Send /start to add more.",
        "hi": "आपका जवाब नहीं मिला, इसलिए जितनी जानकारी थी वह भेज दी गई। संदर्भ नंबर {ref}। और जोड़ने के लिए /start भेजें।",
    },
    "cancelled": {"en": "Cancelled. Send /start to begin again.", "hi": "रद्द किया। फिर शुरू करने के लिए /start भेजें।"},
    "sum_people": {"en": "People", "hi": "लोग"},
    "sum_needs": {"en": "Needs", "hi": "ज़रूरत"},
    "sum_where": {"en": "Place", "hi": "जगह"},
    "sum_phone": {"en": "Phone", "hi": "फ़ोन"},
    "sum_notes": {"en": "Notes", "hi": "टिप्पणी"},
    "pin_shared": {"en": "location shared", "hi": "लोकेशन भेजी गई"},
    "share_location": {"en": "📍 Share my location", "hi": "📍 मेरी लोकेशन भेजें"},
    "share_contact": {"en": "📱 Share my number", "hi": "📱 मेरा नंबर भेजें"},
}
NEED_LABEL = {
    "evacuation": {"en": "Evacuation (boat)", "hi": "निकासी (नाव)"},
    "rescue": {"en": "Rescue", "hi": "बचाव"},
    "food": {"en": "Food", "hi": "खाना"},
    "water": {"en": "Drinking water", "hi": "पीने का पानी"},
    "medicine": {"en": "Medicine", "hi": "दवाई"},
    "baby_food": {"en": "Baby food / milk", "hi": "बच्चों का दूध / खाना"},
    "blankets": {"en": "Blankets", "hi": "कंबल"},
    "shelter": {"en": "Shelter", "hi": "आश्रय"},
}
SITUATION_LABEL = {
    "elderly": {"en": "Elderly person", "hi": "बुज़ुर्ग"},
    "children": {"en": "Children", "hi": "बच्चे"},
    "medical": {"en": "Sick or disabled", "hi": "बीमार या विकलांग"},
    "water_entering": {"en": "Water entering the house", "hi": "घर में पानी आ रहा है"},
    "trapped": {"en": "Trapped", "hi": "फँसे हुए हैं"},
    "life_risk": {"en": "Life in danger", "hi": "जान को ख़तरा"},
}


def t(key: str, lang: str, **kw: Any) -> str:
    row = TEXT[key]
    return (row.get(lang) or row["en"]).format(**kw)


def _label(table: dict[str, dict[str, str]], key: str, lang: str) -> str:
    return table[key].get(lang) or table[key]["en"]


# ----------------------------------------------------------------------------- types
@dataclass
class Button:
    id: str
    label: str
    selected: bool = False


@dataclass
class Reply:
    text: str
    buttons: list[Button] = field(default_factory=list)
    ask_location: bool = False  # channel shows a "share my location" button
    ask_contact: bool = False  # channel shows a "share my phone number" button
    multi: bool = False  # buttons are toggles, with a Done button at the end


@dataclass
class Event:
    """What the user did: tapped a button, typed text, or shared a location or contact."""

    text: str = ""
    button: str = ""
    lat: float | None = None
    lon: float | None = None
    contact_phone: str = ""


@dataclass
class Ctx:
    landmarks: dict[int, list[str]]  # ward number -> landmark names, from the gazetteer
    reporter_id: str = ""  # a linked volunteer's id; empty for the public
    now: float = 0.0


@dataclass
class Draft:
    step: str = "lang"
    lang: str = ""
    whose: str = ""  # "self" | "other"
    lat: float | None = None
    lon: float | None = None
    loc_source: str = ""  # "gps" | "manual" | "text"
    ward: int = 0
    landmark: str = ""
    detail: str = ""
    phone: str = ""
    phone_kind: str = ""  # "own" | "contact"
    phone_unverified: str = ""
    phone_tries: int = 0
    no_phone: bool = False
    alt_phone: str = ""
    people: int = 0
    needs: list[str] = field(default_factory=list)
    situation: list[str] = field(default_factory=list)
    description: str = ""
    resume_step: str = ""  # where to go back to when "Continue" is chosen at the resume prompt
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Draft":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Submission:
    """A finished (or partial) report, ready for `field_ops.ingest_message`."""

    text: str  # readable English summary; never contains the phone number
    form: dict[str, Any]
    phone: str
    phone_kind: str
    alt_phone: str
    lat: float | None
    lon: float | None
    loc_source: str
    ward: int
    landmark: str
    reporter_kind: str  # "self" | "volunteer" | "relay"
    reporter_id: str
    lang: str
    partial: bool = False


@dataclass
class Result:
    draft: Draft
    replies: list[Reply]
    submission: Submission | None = None


# ----------------------------------------------------------------------------- rendering
def _skip(lang: str) -> Button:
    return Button("skip", t("skip", lang))


def _summary(d: Draft) -> str:
    lang, lines = d.lang, []
    if d.people:
        lines.append(f"{t('sum_people', lang)}: {d.people}")
    chosen = [_label(NEED_LABEL, n, lang) for n in d.needs] + [_label(SITUATION_LABEL, s, lang) for s in d.situation]
    if chosen:
        lines.append(f"{t('sum_needs', lang)}: {', '.join(chosen)}")
    where = []
    if d.ward:
        where.append(t("ward_n", lang, n=d.ward))
    if d.landmark:
        where.append(d.landmark)
    if d.lat is not None:
        where.append(t("pin_shared", lang))
    if d.detail:
        where.append(d.detail)
    if where:
        lines.append(f"{t('sum_where', lang)}: {', '.join(where)}")
    if d.phone:
        lines.append(f"{t('sum_phone', lang)}: {d.phone}")
    if d.description:
        lines.append(f"{t('sum_notes', lang)}: {d.description}")
    return "\n".join(lines) or "-"


def render(d: Draft, ctx: Ctx, note: str = "") -> list[Reply]:
    """The question for the draft's current step."""
    lang = d.lang or "en"
    prefix = f"{t(note, lang)}\n\n" if note else ""
    s = d.step

    if s == "lang":
        return [Reply(prefix + t("lang", "en"), [Button("lang:en", "English"), Button("lang:hi", "हिन्दी")])]
    if s == "whose":
        return [Reply(prefix + t("whose", lang), [Button("whose:self", t("whose_self", lang)),
                                                   Button("whose:other", t("whose_other", lang))])]
    if s == "loc":
        key = "loc_self" if d.whose == "self" else "loc_other"
        return [Reply(prefix + t(key, lang), [Button("loc:manual", t("loc_manual", lang)), _skip(lang)],
                      ask_location=d.whose == "self")]
    if s == "ward":
        buttons = [Button(f"ward:{n}", t("ward_n", lang, n=n)) for n in sorted(ctx.landmarks)]
        return [Reply(prefix + t("ward", lang), buttons + [_skip(lang)])]
    if s == "landmark":
        names = ctx.landmarks.get(d.ward, [])
        buttons = [Button(f"lm:{i}", n) for i, n in enumerate(names)]
        return [Reply(prefix + t("landmark", lang), buttons + [Button("lm:none", t("landmark_none", lang))])]
    if s == "detail":
        return [Reply(prefix + t("detail", lang), [_skip(lang)])]
    if s == "phone":
        key = "phone_self" if d.whose == "self" else "phone_other"
        return [Reply(prefix + t(key, lang), [Button("phone:none", t("phone_none", lang)), _skip(lang)],
                      ask_contact=d.whose == "self")]
    if s == "phone_kind":
        return [Reply(prefix + t("phone_kind", lang), [Button("pk:own", t("pk_own", lang)),
                                                        Button("pk:contact", t("pk_contact", lang))])]
    if s == "phone_alt":
        return [Reply(prefix + t("phone_alt", lang), [_skip(lang)])]
    if s == "people":
        buttons = [Button(f"ppl:{n}", str(n)) for n in PEOPLE_BUTTONS] + [Button("ppl:more", t("people_more", lang))]
        return [Reply(prefix + t("people", lang), buttons + [_skip(lang)])]
    if s == "people_exact":
        return [Reply(prefix + t("people_exact", lang), [_skip(lang)])]
    if s == "needs":
        buttons = [Button(f"n:{n}", _label(NEED_LABEL, n, lang), n in d.needs) for n in NEEDS]
        return [Reply(prefix + t("needs", lang), buttons + [Button("n:done", t("done_btn", lang))], multi=True)]
    if s == "situation":
        buttons = [Button(f"s:{x}", _label(SITUATION_LABEL, x, lang), x in d.situation) for x in SITUATION]
        return [Reply(prefix + t("situation", lang), buttons + [Button("s:done", t("done_btn", lang))], multi=True)]
    if s == "confirm":
        return [Reply(prefix + t("confirm", lang, summary=_summary(d)),
                      [Button("ok:send", t("send", lang)), Button("ok:restart", t("restart", lang))])]
    if s == "resume":
        return [Reply(t("resume_q", lang), [Button("resume:continue", t("resume_continue", lang)),
                                             Button("resume:new", t("resume_new", lang))])]
    if s == "cancelled":
        return [Reply(t("cancelled", lang))]
    return []


def done_reply(lang: str, ref: str) -> Reply:
    """What the adapter says after it has saved the message and has a reference."""
    return Reply(t("sent", lang or "en", ref=ref))


# ----------------------------------------------------------------------------- flow
def _after_lang(d: Draft) -> str:
    return "loc" if d.whose else "whose"


def start(ctx: Ctx, lang: str = "") -> Result:
    """Begin a new draft. A linked volunteer is always reporting for someone else."""
    d = Draft(lang=lang, whose="other" if ctx.reporter_id else "", updated_at=ctx.now)
    d.step = _after_lang(d) if lang else "lang"
    return Result(d, render(d, ctx))


def _digits_in(text: str) -> int:
    return sum(ch.isdigit() for ch in text)


def _take_pin(d: Draft, ev: Event) -> bool:
    if ev.lat is None or ev.lon is None:
        return False
    d.lat, d.lon, d.loc_source = ev.lat, ev.lon, "gps"
    d.step = "phone"
    return True


def _toggle(items: list[str], key: str) -> None:
    if key in items:
        items.remove(key)
    else:
        items.append(key)


def _h_lang(d: Draft, ev: Event, ctx: Ctx) -> tuple[bool, str]:
    pick = {"lang:en": "en", "lang:hi": "hi"}.get(ev.button)
    low = ev.text.strip().lower()
    # Not "hi" or "en": "hi" is how people say hello.
    if not pick and low == "english":
        pick = "en"
    if not pick and low in ("hindi", "हिन्दी", "हिंदी"):
        pick = "hi"
    if not pick:
        return False, ""
    d.lang, d.step = pick, _after_lang(d)
    return True, ""


def _h_whose(d: Draft, ev: Event, ctx: Ctx) -> tuple[bool, str]:
    if ev.button in ("whose:self", "whose:other"):
        d.whose, d.step = ev.button.split(":")[1], "loc"
        return True, ""
    return False, ""


def _h_loc(d: Draft, ev: Event, ctx: Ctx) -> tuple[bool, str]:
    if _take_pin(d, ev):
        return True, ""
    if ev.button == "loc:manual":
        d.step = "ward"
        return True, ""
    if ev.button == "skip":
        d.step = "phone"
        return True, ""
    if ev.text.strip():  # "near the temple, ward 12": keep it, Intake will place it
        d.detail, d.loc_source, d.step = ev.text.strip()[:300], "text", "phone"
        return True, ""
    return False, ""


def _h_ward(d: Draft, ev: Event, ctx: Ctx) -> tuple[bool, str]:
    if _take_pin(d, ev):
        return True, ""
    pick = None
    if ev.button.startswith("ward:"):
        pick = int(ev.button.split(":")[1])
    elif ev.text.strip().isdigit():
        pick = int(ev.text.strip())
    if ev.button == "skip":
        d.step = "detail"
        return True, ""
    if pick in ctx.landmarks:
        d.ward, d.loc_source = pick, d.loc_source or "manual"
        d.step = "landmark" if ctx.landmarks[pick] else "detail"
        return True, ""
    return False, ""


def _h_landmark(d: Draft, ev: Event, ctx: Ctx) -> tuple[bool, str]:
    if _take_pin(d, ev):
        return True, ""
    names = ctx.landmarks.get(d.ward, [])
    if ev.button.startswith("lm:") and ev.button != "lm:none":
        i = int(ev.button.split(":")[1])
        if 0 <= i < len(names):
            d.landmark, d.step = names[i], "detail"
            return True, ""
    if ev.button in ("lm:none", "skip"):
        d.step = "detail"
        return True, ""
    low = ev.text.strip().casefold()
    for n in names:
        if low and low == n.casefold():
            d.landmark, d.step = n, "detail"
            return True, ""
    return False, ""


def _h_detail(d: Draft, ev: Event, ctx: Ctx) -> tuple[bool, str]:
    if _take_pin(d, ev):
        return True, ""
    if ev.button == "skip":
        d.step = "phone"
        return True, ""
    if ev.text.strip():
        d.detail, d.step = ev.text.strip()[:300], "phone"
        return True, ""
    return False, ""


def _after_phone(d: Draft, ctx: Ctx) -> str:
    # A stranger reporting for a family could be giving their own number:
    # ask whose it is. A linked volunteer is trusted to give the family's.
    return "phone_kind" if d.whose == "other" and not ctx.reporter_id else "people"


def _h_phone(d: Draft, ev: Event, ctx: Ctx) -> tuple[bool, str]:
    if ev.button == "phone:none":
        d.no_phone, d.step = True, "phone_alt"
        return True, ""
    if ev.button == "skip":
        d.step = "people"
        return True, ""
    raw = (ev.contact_phone or ev.text).strip()
    if not raw:
        return False, ""
    number = phones.normalize(raw)
    if number:
        d.phone, d.phone_kind = number, "own"
        d.step = _after_phone(d, ctx)
        return True, ""
    if _digits_in(raw) >= 7:  # meant as a number, typed wrong
        d.phone_tries += 1
        if d.phone_tries >= 2:  # do not trap anyone; coordinators see it, matching ignores it
            d.phone_unverified, d.step = raw[:30], "people"
            return True, ""
        return True, "phone_invalid"
    return False, ""  # words, not a number: keep as description


def _h_phone_kind(d: Draft, ev: Event, ctx: Ctx) -> tuple[bool, str]:
    if ev.button in ("pk:own", "pk:contact"):
        d.phone_kind, d.step = ev.button.split(":")[1], "people"
        return True, ""
    return False, ""


def _h_phone_alt(d: Draft, ev: Event, ctx: Ctx) -> tuple[bool, str]:
    if ev.button == "skip":
        d.step = "people"
        return True, ""
    raw = (ev.contact_phone or ev.text).strip()
    number = phones.normalize(raw)
    if number:
        d.alt_phone, d.step = number, "people"
        return True, ""
    if raw and _digits_in(raw) >= 7:
        return True, "phone_invalid"
    return False, ""


def _h_people(d: Draft, ev: Event, ctx: Ctx) -> tuple[bool, str]:
    if ev.button.startswith("ppl:") and ev.button != "ppl:more":
        d.people, d.step = int(ev.button.split(":")[1]), "needs"
        return True, ""
    if ev.button == "ppl:more":
        d.step = "people_exact"
        return True, ""
    if ev.button == "skip":
        d.step = "needs"
        return True, ""
    if ev.text.strip().isdigit() and 0 < int(ev.text.strip()) <= MAX_PEOPLE:
        d.people, d.step = int(ev.text.strip()), "needs"
        return True, ""
    return False, ""


def _h_people_exact(d: Draft, ev: Event, ctx: Ctx) -> tuple[bool, str]:
    if ev.button == "skip":
        d.step = "needs"
        return True, ""
    if ev.text.strip().isdigit() and 0 < int(ev.text.strip()) <= MAX_PEOPLE:
        d.people, d.step = int(ev.text.strip()), "needs"
        return True, ""
    return False, ""


def _h_needs(d: Draft, ev: Event, ctx: Ctx) -> tuple[bool, str]:
    if ev.button.startswith("n:") and ev.button != "n:done":
        key = ev.button[2:]
        if key in NEEDS:
            _toggle(d.needs, key)
            return True, ""
    if ev.button in ("n:done", "skip"):
        d.step = "situation"
        return True, ""
    return False, ""


def _h_situation(d: Draft, ev: Event, ctx: Ctx) -> tuple[bool, str]:
    if ev.button.startswith("s:") and ev.button != "s:done":
        key = ev.button[2:]
        if key in SITUATION:
            _toggle(d.situation, key)
            return True, ""
    if ev.button in ("s:done", "skip"):
        d.step = "confirm"
        return True, ""
    return False, ""


HANDLERS = {
    "lang": _h_lang, "whose": _h_whose, "loc": _h_loc, "ward": _h_ward, "landmark": _h_landmark,
    "detail": _h_detail, "phone": _h_phone, "phone_kind": _h_phone_kind, "phone_alt": _h_phone_alt,
    "people": _h_people, "people_exact": _h_people_exact, "needs": _h_needs, "situation": _h_situation,
}
# Steps where the answer is a tap. Free text there is kept as the description.
KEEPS_TEXT = set(HANDLERS) - {"lang", "whose"} | {"confirm"}


# Greetings and restart commands. Typed in the middle of a form, they ask what to do instead of
# being kept as a note (or silently throwing the answers away).
RESTART_WORDS = {"start", "/start", "restart", "/report", "hi", "hii", "hello", "hey", "namaste",
                 "नमस्ते", "हेलो", "हाय", "शुरू", "शुरू करें"}


def is_restart_word(text: str) -> bool:
    return text.strip().lower().strip(" .!?,") in RESTART_WORDS


def has_progress(d: Draft) -> bool:
    """Is there anything worth keeping? Language and "who" alone are not."""
    return d.step not in ("lang", "whose", "done", "cancelled")


def step(d: Draft, ev: Event, ctx: Ctx) -> Result:
    """Apply one event to a draft. Returns the new draft, what to say, and a Submission when done."""
    d.updated_at = ctx.now
    if ev.button == "cancel" or ev.text.strip().lower() in ("/cancel", "cancel"):
        d.step = "cancelled"
        return Result(d, render(d, ctx))
    if d.step in ("done", "cancelled"):
        return start(ctx, d.lang)

    if d.step == "resume":
        if ev.button == "resume:new":
            return start(ctx, d.lang)
        if ev.button == "resume:continue":
            d.step, d.resume_step = d.resume_step or "loc", ""
        return Result(d, render(d, ctx))
    if ev.text and not ev.button and is_restart_word(ev.text):
        if has_progress(d):
            d.resume_step, d.step = d.step, "resume"
        return Result(d, render(d, ctx))

    if d.step == "confirm":
        if ev.button == "ok:send":
            d.step = "done"
            return Result(d, [], build(d, ctx))
        if ev.button == "ok:restart":
            return start(ctx, d.lang)
    else:
        consumed, note = HANDLERS[d.step](d, ev, ctx)
        if consumed:
            return Result(d, render(d, ctx, note))

    # Not an answer to this step. Keep typed text so nothing the person wrote is lost.
    note = ""
    text = ev.text.strip()
    if text and d.step in KEEPS_TEXT and not text.startswith("/"):
        d.description = (d.description + "; " + text if d.description else text)[:600]
        note = "noted"
    return Result(d, render(d, ctx, note))


# ----------------------------------------------------------------------------- output
def has_enough(d: Draft) -> bool:
    """Enough to act on: a place of some kind, or anything the person wrote."""
    return d.lat is not None or bool(d.ward) or bool(d.detail) or bool(d.description)


def is_stale(d: Draft, now: float, ttl: float = STALE_AFTER_S) -> bool:
    """An abandoned draft that should be sent as it is. Battery dies, signal drops."""
    return d.step not in ("done", "cancelled", "lang") and now - d.updated_at >= ttl and has_enough(d)


def _reporter_kind(d: Draft, ctx: Ctx) -> str:
    if d.whose == "self":
        return "self"
    return "volunteer" if ctx.reporter_id else "relay"


def _compose(d: Draft) -> str:
    parts = ["Help request from the bot."]
    if d.people:
        parts.append(f"{d.people} people.")
    if d.situation:
        parts.append(", ".join(SITUATION_LABEL[s]["en"] for s in d.situation) + ".")
    if d.needs:
        parts.append("Needs: " + ", ".join(NEED_LABEL[n]["en"] for n in d.needs) + ".")
    where = []
    if d.ward:
        where.append(f"ward {d.ward}")
    if d.landmark:
        where.append(f"near {d.landmark}")
    if d.lat is not None:
        where.append("location pin shared")
    if where:
        parts.append(", ".join(where).capitalize() + ".")
    if d.detail:
        parts.append(f"Location details: {d.detail}.")
    if d.description:
        parts.append(f"Notes: {d.description}.")
    return " ".join(parts)  # no phone number: it must not reach the embedding or the logs


def build(d: Draft, ctx: Ctx, partial: bool = False) -> Submission:
    return Submission(
        text=_compose(d),
        form={"people": d.people, "needs": list(d.needs), "situation": list(d.situation),
              "no_phone": d.no_phone, "phone_unverified": d.phone_unverified,
              "detail": d.detail, "notes": d.description},
        phone=d.phone,
        phone_kind=d.phone_kind if d.phone else "",
        alt_phone=d.alt_phone,
        lat=d.lat,
        lon=d.lon,
        loc_source=d.loc_source,
        ward=d.ward,
        landmark=d.landmark,
        reporter_kind=_reporter_kind(d, ctx),
        reporter_id=ctx.reporter_id,
        lang=d.lang,
        partial=partial,
    )


# ----------------------------------------------------------------------------- for Intake
_URGENCY_ORDER = ["low", "medium", "high", "critical"]


def form_to_data(form: dict[str, Any], *, ward: int = 0, landmark: str = "", text: str = "", lang: str = "") -> dict:
    """The fields Intake needs, taken straight from what the person tapped.

    Same shape the language model returns, so the rest of Intake is unchanged.
    The model is only needed for the free text (names, medical detail), which
    Intake merges in afterwards with `merge_notes`."""
    sit = set(form.get("situation") or [])
    needs = [n for n in (form.get("needs") or []) if n in NEEDS]
    if sit & {"trapped", "water_entering"} and "evacuation" not in needs:
        needs.append("evacuation")
    if "life_risk" in sit:
        urgency = "critical"
    elif sit & {"water_entering", "trapped", "elderly", "medical"}:
        urgency = "high"
    else:
        urgency = "medium"
    return {
        "kind": "help_request",
        "contact_name": "",
        "people": int(form.get("people") or 0),
        "elderly": int("elderly" in sit),
        "children": int("children" in sit),
        "pregnant_or_disabled": int("medical" in sit),
        "medical_condition": "sick or disabled person" if "medical" in sit else "",
        "needs": needs,
        "water_entering": "water_entering" in sit,
        "trapped": "trapped" in sit,
        "urgency": urgency,
        "ward": int(ward or 0),
        "landmark": landmark or "",
        "location_text": form.get("detail") or "",
        "road_name": "",
        "road_status": "",
        "summary_en": text,
        "language": lang,
    }


def merge_notes(data: dict, parsed: dict) -> dict:
    """Fill gaps in the tapped answers from what was read out of the free text.

    What the person tapped wins. The text adds a name, medical detail, larger
    counts (a tap says "children", the text says "3 children") and extra needs."""
    out = dict(data)
    if not out["contact_name"]:
        out["contact_name"] = parsed.get("contact_name") or ""
    if not out["medical_condition"]:
        out["medical_condition"] = parsed.get("medical_condition") or ""
    for key in ("people", "elderly", "children", "pregnant_or_disabled"):
        out[key] = max(int(out[key] or 0), int(parsed.get(key) or 0))
    out["needs"] = out["needs"] + [n for n in parsed.get("needs", []) if n in DOMAIN_NEEDS and n not in out["needs"]]
    out["water_entering"] = out["water_entering"] or bool(parsed.get("water_entering"))
    out["trapped"] = out["trapped"] or bool(parsed.get("trapped"))
    pu = parsed.get("urgency") or "low"
    if pu in _URGENCY_ORDER and _URGENCY_ORDER.index(pu) > _URGENCY_ORDER.index(out["urgency"]):
        out["urgency"] = pu
    return out
