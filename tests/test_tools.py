from tools.flights_tools import get_latest_flight_analysis


def test_latest_analysis__not_found():
    data=get_latest_flight_analysis()
    assert data["status"] == "not_found"

def test_latest_flight_error(monkeypatch):
    monkeypatch.setattr(tools.flights_tools,)
    data=get_latest_flight_analysis()
