"""The bot conversation, with no network and no database."""
from reliefnet import intake_flow as f

LANDMARKS = {9: ["Dhobi Ghat", "Hanuman Mandir"], 12: ["Shiv Mandir", "Water Tank"], 13: []}


def ctx(reporter_id: str = "", now: float = 1000.0) -> f.Ctx:
    return f.Ctx(landmarks=LANDMARKS, reporter_id=reporter_id, now=now)


def run(d: f.Draft, *events: f.Event, c: f.Ctx | None = None) -> f.Result:
    c = c or ctx()
    r = f.Result(d, [])
    for ev in events:
        r = f.step(r.draft, ev, c)
    return r


def tap(button: str) -> f.Event:
    return f.Event(button=button)


def say(text: str) -> f.Event:
    return f.Event(text=text)


def test_self_report_with_gps_pin_end_to_end():
    r = f.start(ctx())
    assert r.draft.step == "lang"
    r = run(r.draft, tap("lang:en"), tap("whose:self"), f.Event(lat=25.6, lon=85.13))
    assert r.draft.step == "phone" and r.draft.loc_source == "gps"
    assert r.replies[0].ask_contact  # a person asking for themselves can share their contact
    r = run(r.draft, say("+91 98765-43210"), tap("ppl:5"), tap("n:evacuation"), tap("n:food"), tap("n:done"),
            tap("s:elderly"), tap("s:water_entering"), tap("s:done"))
    assert r.draft.step == "confirm"
    assert "98765" in r.replies[0].text  # the person sees the number to catch typos
    r = run(r.draft, tap("ok:send"))
    sub = r.submission
    assert sub and not sub.partial
    assert sub.phone == "9876543210" and sub.phone_kind == "own"
    assert (sub.lat, sub.lon, sub.loc_source) == (25.6, 85.13, "gps")
    assert sub.reporter_kind == "self"
    assert sub.form["people"] == 5 and sub.form["needs"] == ["evacuation", "food"]
    assert "Water entering the house" in sub.text and "5 people" in sub.text
    assert "9876543210" not in sub.text  # never in the text that is embedded and logged


def test_ward_volunteer_skips_whose_and_gives_the_familys_number():
    c = ctx(reporter_id="vol_1")
    r = f.start(c, lang="en")
    assert r.draft.step == "loc" and r.draft.whose == "other"
    assert not r.replies[0].ask_location  # the volunteer attaches the family's pin instead
    r = run(r.draft, tap("loc:manual"), tap("ward:12"), tap("lm:0"), say("blue door"),
            say("98765 43210"), tap("ppl:3"), tap("n:done"), tap("s:done"), tap("ok:send"), c=c)
    sub = r.submission
    assert sub.reporter_kind == "volunteer" and sub.reporter_id == "vol_1"
    assert (sub.ward, sub.landmark, sub.loc_source) == (12, "Shiv Mandir", "manual")
    assert sub.phone == "9876543210" and sub.phone_kind == "own"
    assert "blue door" in sub.text


def test_stranger_reporting_for_someone_is_a_relay_and_is_asked_whose_number():
    r = f.start(ctx(), lang="en")
    r = run(r.draft, tap("whose:other"), tap("loc:manual"), tap("ward:9"), tap("lm:none"), tap("skip"),
            say("9123456780"))
    assert r.draft.step == "phone_kind"
    r = run(r.draft, tap("pk:contact"), tap("ppl:2"), tap("n:done"), tap("s:done"), tap("ok:send"))
    assert r.submission.reporter_kind == "relay" and r.submission.phone_kind == "contact"


def test_family_without_a_phone_gives_a_contact_number_only():
    r = f.start(ctx(reporter_id="v"), lang="en")
    r = run(r.draft, tap("skip"), tap("phone:none"), say("9123456780"), c=ctx(reporter_id="v"))
    assert r.draft.no_phone and r.draft.alt_phone == "9123456780" and r.draft.phone == ""
    assert r.draft.step == "people"
    sub = f.build(r.draft, ctx(reporter_id="v"))
    assert sub.phone == "" and sub.phone_kind == "" and sub.alt_phone == "9123456780"


def test_bad_phone_gets_one_retry_then_is_kept_as_unverified_without_blocking():
    r = f.start(ctx(), lang="en")
    r = run(r.draft, tap("whose:self"), tap("skip"), say("98765 4321"))
    assert r.draft.step == "phone" and "10-digit" in r.replies[0].text
    r = run(r.draft, say("98765 4321"))
    assert r.draft.step == "people"
    assert r.draft.phone == "" and r.draft.phone_unverified == "98765 4321"


def test_words_at_the_phone_step_are_kept_as_description_not_counted_as_a_bad_number():
    r = f.start(ctx(), lang="en")
    r = run(r.draft, tap("whose:self"), tap("skip"), say("we are on the roof"))
    assert r.draft.step == "phone" and r.draft.phone_tries == 0
    assert r.draft.description == "we are on the roof" and r.replies[0].text.startswith("Noted.")


def test_free_text_at_the_location_step_is_accepted_as_the_location():
    r = f.start(ctx(), lang="en")
    r = run(r.draft, tap("whose:self"), say("near the temple ward 12"))
    assert r.draft.step == "phone" and r.draft.loc_source == "text"
    assert "near the temple ward 12" in f.build(r.draft, ctx()).text


def test_a_pin_is_accepted_at_any_location_step():
    r = f.start(ctx(), lang="en")
    r = run(r.draft, tap("whose:other"), tap("loc:manual"), tap("ward:12"), f.Event(lat=25.5, lon=85.1))
    assert r.draft.step == "phone" and r.draft.loc_source == "gps"


def test_typed_ward_and_landmark_name_are_understood():
    r = f.start(ctx(), lang="en")
    r = run(r.draft, tap("whose:self"), tap("loc:manual"), say("12"), say("shiv mandir"))
    assert (r.draft.ward, r.draft.landmark, r.draft.step) == (12, "Shiv Mandir", "detail")


def test_a_ward_with_many_landmarks_shows_few_buttons_but_accepts_any_typed_name():
    many = {12: [f"Place {i}" for i in range(30)]}
    c = f.Ctx(landmarks=many, now=1000.0)
    r = f.start(c, lang="en")
    r = run(r.draft, tap("whose:self"), tap("loc:manual"), tap("ward:12"), c=c)
    buttons = [b.id for b in r.replies[0].buttons]
    assert buttons == [f"lm:{i}" for i in range(f.LANDMARK_BUTTONS)] + ["lm:none"]
    r = run(r.draft, say("place 25"), c=c)
    assert (r.draft.landmark, r.draft.step) == ("Place 25", "detail")


def test_ward_without_landmarks_goes_straight_to_details():
    r = f.start(ctx(), lang="en")
    r = run(r.draft, tap("whose:self"), tap("loc:manual"), tap("ward:13"))
    assert r.draft.step == "detail"


def test_toggles_select_and_unselect_and_more_than_five_people_asks_for_a_number():
    r = f.start(ctx(), lang="en")
    r = run(r.draft, tap("whose:self"), tap("skip"), tap("skip"), tap("ppl:more"))
    assert r.draft.step == "people_exact"
    r = run(r.draft, say("12"), tap("n:food"), tap("n:water"), tap("n:food"))
    assert r.draft.people == 12 and r.draft.needs == ["water"]
    assert [b.selected for b in r.replies[0].buttons if b.id == "n:water"] == [True]
    assert [b.selected for b in r.replies[0].buttons if b.id == "n:food"] == [False]


def test_restart_keeps_language_and_reporter_but_clears_answers():
    c = ctx(reporter_id="v")
    r = f.start(c, lang="hi")
    r = run(r.draft, tap("skip"), tap("skip"), tap("ppl:2"), tap("n:done"), tap("s:done"), tap("ok:restart"), c=c)
    assert r.draft.lang == "hi" and r.draft.whose == "other" and r.draft.people == 0 and r.draft.step == "loc"


def test_cancel_works_from_anywhere_and_start_begins_again():
    r = f.start(ctx(), lang="en")
    r = run(r.draft, tap("whose:self"), say("/cancel"))
    assert r.draft.step == "cancelled" and "Cancelled" in r.replies[0].text
    r = run(r.draft, say("/start"))
    assert r.draft.step == "whose" and r.draft.lang == "en"


def test_abandoned_draft_with_a_place_is_stale_and_sendable():
    r = f.start(ctx(now=1000), lang="en")
    r = run(r.draft, tap("whose:self"), f.Event(lat=25.6, lon=85.1), c=ctx(now=1000))
    assert not f.is_stale(r.draft, now=1000 + 60)
    assert f.is_stale(r.draft, now=1000 + f.STALE_AFTER_S + 1)
    sub = f.build(r.draft, ctx(), partial=True)
    assert sub.partial and sub.lat == 25.6


def test_draft_with_nothing_to_act_on_is_never_auto_sent():
    r = f.start(ctx(now=1000), lang="en")
    r = run(r.draft, tap("whose:self"), c=ctx(now=1000))
    assert not f.is_stale(r.draft, now=10_000)


def test_draft_survives_json_roundtrip():
    r = f.start(ctx(), lang="en")
    r = run(r.draft, tap("whose:self"), f.Event(lat=1.5, lon=2.5), say("98765 43210"), tap("n:food"))
    again = f.Draft.from_dict(r.draft.to_dict())
    assert again == r.draft
    assert f.Draft.from_dict({**r.draft.to_dict(), "removed_field": 1}) == r.draft


def test_every_text_has_english_and_hindi():
    for table in (f.TEXT, f.NEED_LABEL, f.SITUATION_LABEL):
        for key, row in table.items():
            assert row.get("en") and row.get("hi"), key
    assert set(f.NEEDS) == set(f.NEED_LABEL) and set(f.SITUATION) == set(f.SITUATION_LABEL)


def test_all_needs_are_ones_the_dispatch_agent_understands():
    from reliefnet.domain import NEEDS

    assert set(f.NEEDS) <= set(NEEDS)


def test_every_screen_renders_in_both_languages_with_short_unique_button_ids():
    c = ctx()
    for lang in ("en", "hi"):
        for s in ("lang", "whose", "loc", "ward", "landmark", "detail", "phone", "phone_kind", "phone_alt",
                  "people", "people_exact", "needs", "situation", "confirm", "resume", "cancelled"):
            d = f.Draft(step=s, lang=lang, whose="self", ward=12)
            for rep in f.render(d, c):
                ids = [b.id for b in rep.buttons]
                assert len(ids) == len(set(ids)), (s, ids)
                assert all(len(i) <= 32 for i in ids), (s, ids)  # Telegram allows 64 bytes, WhatsApp 256
                assert rep.text


# ---- what Intake gets from the form
def test_form_becomes_the_fields_intake_expects():
    form = {"people": 5, "needs": ["food", "medicine"], "situation": ["elderly", "water_entering"],
            "detail": "blue door", "notes": ""}
    d = f.form_to_data(form, ward=12, landmark="Shiv Mandir", text="summary", lang="hi")
    assert d["people"] == 5 and d["elderly"] == 1 and d["children"] == 0
    assert d["water_entering"] and d["urgency"] == "high"
    assert d["needs"] == ["food", "medicine", "evacuation"]  # water entering implies evacuation
    assert (d["ward"], d["landmark"], d["location_text"]) == (12, "Shiv Mandir", "blue door")
    assert d["kind"] == "help_request" and d["language"] == "hi"


def test_life_risk_is_critical_and_nothing_special_is_medium():
    assert f.form_to_data({"situation": ["life_risk"]})["urgency"] == "critical"
    assert f.form_to_data({"situation": []})["urgency"] == "medium"
    assert f.form_to_data({})["people"] == 0  # unknown, not guessed


def test_free_text_fills_gaps_but_never_overrides_what_was_tapped():
    base = f.form_to_data({"people": 5, "needs": ["food"], "situation": ["children"]})
    parsed = {"contact_name": "R. Kumar", "medical_condition": "BP", "people": 4, "children": 3,
              "needs": ["medicine", "first_aid", "not_a_need"], "urgency": "critical", "water_entering": True}
    d = f.merge_notes(base, parsed)
    assert d["contact_name"] == "R. Kumar" and d["medical_condition"] == "BP"
    assert d["people"] == 5  # the tapped number is kept when the text says fewer
    assert d["children"] == 3  # a tap says "children", the text says how many
    assert d["needs"] == ["food", "medicine", "first_aid"]
    assert d["urgency"] == "critical" and d["water_entering"]


def test_tapped_urgency_is_not_lowered_by_the_text():
    base = f.form_to_data({"situation": ["trapped"]})
    assert f.merge_notes(base, {"urgency": "low"})["urgency"] == "high"


def test_submission_form_carries_the_free_text_and_is_json_safe():
    import json

    r = f.start(ctx(), lang="en")
    r = run(r.draft, tap("whose:self"), tap("skip"), say("we are on the roof"), tap("skip"), tap("ppl:2"),
            tap("n:done"), tap("s:done"), tap("ok:send"))
    form = r.submission.form
    assert form["notes"] == "we are on the roof"
    json.dumps(form)


# ---- greetings in the middle of a form
def test_greeting_mid_form_asks_to_continue_or_start_new():
    r = f.start(ctx(), lang="en")
    r = run(r.draft, tap("whose:self"), tap("skip"), tap("skip"), say("hi"))
    assert r.draft.step == "resume" and r.draft.description == ""  # not kept as a note
    assert [b.id for b in r.replies[0].buttons] == ["resume:continue", "resume:new"]
    r = run(r.draft, tap("resume:continue"))
    assert r.draft.step == "people" and r.draft.resume_step == ""


def test_choosing_start_new_clears_the_answers_but_keeps_language_and_reporter():
    c = ctx(reporter_id="v")
    r = f.start(c, lang="hi")
    r = run(r.draft, tap("skip"), tap("skip"), tap("ppl:3"), say("Start"), tap("resume:new"), c=c)
    assert r.draft.step == "loc" and r.draft.people == 0 and r.draft.lang == "hi" and r.draft.whose == "other"


def test_slash_start_and_other_greetings_do_the_same():
    for word in ("/start", "Start", "restart", "Hello!", "नमस्ते", "/report"):
        r = f.start(ctx(), lang="en")
        r = run(r.draft, tap("whose:self"), tap("skip"), tap("skip"), say(word))
        assert r.draft.step == "resume", word


def test_other_input_at_the_resume_prompt_repeats_the_question():
    r = f.start(ctx(), lang="en")
    r = run(r.draft, tap("whose:self"), tap("skip"), tap("skip"), say("hi"), say("5 people"), tap("ppl:2"))
    assert r.draft.step == "resume" and r.draft.people == 0 and r.draft.description == ""


def test_greeting_before_any_answers_just_repeats_the_question():
    r = f.start(ctx(), lang="en")
    r = run(r.draft, say("hi"))
    assert r.draft.step == "whose"  # nothing to lose, no prompt
    r = f.start(ctx())
    r = run(r.draft, say("hi"))
    assert r.draft.step == "lang" and r.draft.lang == ""  # "hi" is hello, not Hindi


def test_language_can_still_be_typed_in_words():
    r = f.start(ctx())
    assert run(r.draft, say("हिंदी")).draft.lang == "hi"
    r = f.start(ctx())
    assert run(r.draft, say("English")).draft.lang == "en"


def test_abandoned_resume_prompt_is_still_sent_if_it_has_a_place():
    r = f.start(ctx(now=1000), lang="en")
    r = run(r.draft, tap("whose:self"), f.Event(lat=25.6, lon=85.1), say("hi"), c=ctx(now=1000))
    assert r.draft.step == "resume" and f.is_stale(r.draft, now=1000 + f.STALE_AFTER_S + 1)
