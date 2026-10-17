"""Phone parsing: no database needed."""
import pytest

from reliefnet import phone


@pytest.mark.parametrize(
    "raw",
    ["9876543210", "+91 98765 43210", "+91-98765-43210", "09876543210", "919876543210", "(98765) 43210",
     "98765.43210", "९८७६५ ४३२१०", " 98765 43210 "],
)
def test_valid_numbers_normalise_to_ten_digits(raw):
    assert phone.normalize(raw) == "9876543210"


@pytest.mark.parametrize(
    "raw", ["", None, "12345", "98765432", "5876543210", "98765432101", "call me", "98765x3210", "+1 415 555 2671"]
)
def test_invalid_numbers_are_rejected(raw):
    assert phone.normalize(raw) is None


def test_same_ignores_formatting_and_rejects_invalid():
    assert phone.same("+91 98765 43210", "09876543210")
    assert not phone.same("9876543210", "9876543211")
    assert not phone.same("", "")
    assert not phone.same("123", "123")


def test_mask_hides_the_middle():
    assert phone.mask("9876543210") == "98xxxxxx10"
    assert phone.mask("") == "" and phone.mask(None) == ""
