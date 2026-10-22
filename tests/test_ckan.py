import pytest
import responses

from curtailmit.ckan import (
    CkanApiError,
    CkanResource,
    get_resources,
    group_monthly_resources,
    package_search,
    package_show,
    pick_best_resource,
)

BASE_URL = "https://example-ckan.test/api/3/action"


@responses.activate
def test_package_show_success():
    responses.add(
        responses.GET,
        f"{BASE_URL}/package_show",
        json={"success": True, "result": {"id": "pkg1", "resources": []}},
        status=200,
    )
    result = package_show(BASE_URL, "pkg1")
    assert result["id"] == "pkg1"


@responses.activate
def test_package_show_http_error_raises():
    responses.add(responses.GET, f"{BASE_URL}/package_show", status=500)
    with pytest.raises(CkanApiError):
        package_show(BASE_URL, "pkg1")


@responses.activate
def test_package_show_api_failure_raises():
    responses.add(
        responses.GET,
        f"{BASE_URL}/package_show",
        json={"success": False, "error": {"message": "Not found"}},
        status=200,
    )
    with pytest.raises(CkanApiError):
        package_show(BASE_URL, "missing")


@responses.activate
def test_package_search_returns_results():
    responses.add(
        responses.GET,
        f"{BASE_URL}/package_search",
        json={"success": True, "result": {"count": 1, "results": [{"id": "pkg1"}]}},
        status=200,
    )
    results = package_search(BASE_URL, "query")
    assert results == [{"id": "pkg1"}]


def test_get_resources_parses_typed_list():
    pkg = {
        "resources": [
            {"id": "r1", "name": "File-2024-01", "format": "csv", "url": "http://x/1.csv"},
            {"id": "r2", "name": "File-2024-01", "format": "PARQUET", "url": "http://x/1.parquet"},
        ]
    }
    resources = get_resources(pkg)
    assert len(resources) == 2
    assert resources[1].format == "PARQUET"


def test_pick_best_resource_prefers_parquet():
    resources = [
        CkanResource(id="1", name="a", format="CSV", url="u1"),
        CkanResource(id="2", name="a", format="PARQUET", url="u2"),
        CkanResource(id="3", name="a", format="XLSX", url="u3"),
    ]
    best = pick_best_resource(resources)
    assert best.format == "PARQUET"


def test_pick_best_resource_falls_back_to_csv():
    resources = [
        CkanResource(id="1", name="a", format="XLSX", url="u1"),
        CkanResource(id="2", name="a", format="CSV", url="u2"),
    ]
    best = pick_best_resource(resources)
    assert best.format == "CSV"


def test_pick_best_resource_returns_none_if_no_match():
    resources = [CkanResource(id="1", name="a", format="PDF", url="u1")]
    assert pick_best_resource(resources) is None


def test_group_monthly_resources_groups_correctly():
    resources = [
        CkanResource(id="1", name="Restricoes_coff_eolicas-2024-01", format="CSV", url="u1"),
        CkanResource(id="2", name="Restricoes_coff_eolicas-2024-01", format="PARQUET", url="u2"),
        CkanResource(id="3", name="Restricoes_coff_eolicas-2024-02", format="CSV", url="u3"),
        CkanResource(id="4", name="Dicionario de Dados", format="PDF", url="u4"),
    ]
    grouped = group_monthly_resources(resources)
    assert set(grouped.keys()) == {(2024, 1), (2024, 2)}
    assert len(grouped[(2024, 1)]) == 2