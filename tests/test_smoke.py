"""Smoke tests for mibare package."""


def test_smoke() -> None:
    """Test that the package can be imported."""
    import mibare  # noqa: PLC0415

    assert mibare is not None
