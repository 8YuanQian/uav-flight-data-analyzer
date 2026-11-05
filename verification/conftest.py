import pytest
from src.auth.data_scope import use_data_user


@pytest.fixture(autouse=True)
def data_user():
    with use_data_user(1):
        yield
