"""Task 22: demonstrate N+1 by counting queries at two different row counts.

A claim that something is N+1 is only worth making if the query count grows with
the number of rows. Each test below runs the same endpoint twice — once with a
small number of rows, once with more — and records both counts. A flat count is
not an N+1; a count that tracks the row count is.

Results are written to nplus1_results.json for the report to cite.
"""
import json, os, pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from plane.tests.factories import (
    UserFactory, WorkspaceFactory, WorkspaceMemberFactory,
    ProjectFactory, ProjectMemberFactory,
)

RESULTS = []
OUT = os.environ.get("NPLUS1_OUT", "nplus1_results.json")


def record(name, endpoint, counts, note=""):
    small, large = counts
    RESULTS.append({
        "name": name, "endpoint": endpoint,
        "rows_small": small["rows"], "queries_small": small["queries"],
        "rows_large": large["rows"], "queries_large": large["queries"],
        "delta_queries": large["queries"] - small["queries"],
        "delta_rows": large["rows"] - small["rows"],
        "queries_per_extra_row": round(
            (large["queries"] - small["queries"]) / max(1, large["rows"] - small["rows"]), 2),
        "verdict": "N+1" if (large["queries"] - small["queries"]) >= (large["rows"] - small["rows"]) else "flat",
        "note": note,
    })
    with open(OUT, "w") as f:
        json.dump(RESULTS, f, indent=1)


def _seed(n_projects):
    user = UserFactory()
    ws = WorkspaceFactory(owner=user)
    WorkspaceMemberFactory(workspace=ws, member=user, role=20)
    for _ in range(n_projects):
        p = ProjectFactory(workspace=ws)
        ProjectMemberFactory(project=p, member=user, role=20)
    return user, ws


@pytest.mark.django_db
@pytest.mark.parametrize("label,n_small,n_large", [("projects", 2, 12)])
def test_project_list_scales_with_project_count(api_client, label, n_small, n_large):
    """ProjectListSerializer.get_next_work_item_sequence runs one aggregate per
    project. If that is an N+1, query count rises roughly 1:1 with projects."""
    measured = []
    for n in (n_small, n_large):
        user, ws = _seed(n)
        api_client.force_authenticate(user=user)
        with CaptureQueriesContext(connection) as ctx:
            resp = api_client.get(f"/api/workspaces/{ws.slug}/projects/")
        assert resp.status_code in (200, 401, 403), resp.status_code
        measured.append({"rows": n, "queries": len(ctx.captured_queries),
                         "status": resp.status_code})
    record("project list", "/api/workspaces/<slug>/projects/", measured,
           note="ProjectListSerializer.next_work_item_sequence -> IssueSequence aggregate per row")
    print(f"\n[N+1] project list: {measured[0]['rows']} rows -> {measured[0]['queries']} queries; "
          f"{measured[1]['rows']} rows -> {measured[1]['queries']} queries")
