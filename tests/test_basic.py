"""
Basic test to ensure pytest runs successfully
"""


def test_basic():
    """A simple test that should always pass"""
    assert True


def test_imports():
    """Test that we can import basic modules"""
    import sys

    assert sys.version_info.major == 3
    assert sys.version_info.minor >= 10
