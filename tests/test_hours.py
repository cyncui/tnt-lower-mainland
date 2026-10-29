from tnt.hours import DAYS, parse_hours


def every_day(open_, close):
    return {d: [open_, close] for d in DAYS}


def test_en_dash_between_days():
    # Seen on tntsupermarket.com: en dash between days, hyphen between times.
    r = parse_hours("Monday – Sunday 9:00 am - 10:00 pm")
    assert r.hours == every_day("09:00", "22:00")
    assert r.notes == []


def test_grand_opening_time_is_not_the_opening_hour():
    r = parse_hours("Grand Opening: Oct 8 9am / Store Hours: Mon - Sun, 8am-11pm")
    assert r.hours == every_day("08:00", "23:00")
    assert r.notes == ["Grand Opening: Oct 8 9am"]


def test_split_week():
    r = parse_hours("Mon - Fri 9am - 9pm, Sat - Sun 10am - 8pm")
    assert r.hours["fri"] == ["09:00", "21:00"]
    assert r.hours["sat"] == ["10:00", "20:00"]


def test_noon_and_midnight():
    r = parse_hours("Daily 12pm - 12am")
    assert r.hours["mon"] == ["12:00", "24:00"]


def test_close_after_midnight_goes_past_24():
    r = parse_hours("Fri 9am - 1am")
    assert r.hours == {"fri": ["09:00", "25:00"]}


def test_week_wraparound():
    r = parse_hours("Sat - Mon 10am - 6pm")
    assert set(r.hours) == {"sat", "sun", "mon"}


def test_unparseable_is_kept_as_note_not_guessed():
    r = parse_hours("Temporarily closed")
    assert r.hours == {}
    assert r.notes == ["unparsed: Temporarily closed"]
